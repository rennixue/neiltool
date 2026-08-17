import asyncio
import base64
import logging
import random
import time
from asyncio import Semaphore, Task
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import PIL.Image
import pymupdf
from openai import AsyncOpenAI, RateLimitError
from PIL.Image import Image

from .gotenberg import Gotenberg
from .models.settings import AgentSettings, StrPath

logger = logging.getLogger(__name__)


PROMPTS: dict[str, str] = {
    "default": R"""
Output the text content in the image, which is a scanned document page, a presentation slide, or a screenshot.

- Adhere to the original language and content. Do not make any translation or explanation.
- Output as canonical markdown. Add formatting only when necessary.
- Use markdown tables for simple tables, but use HTML tables for complex tables.
- Use LaTeX notations for math symbols or formulas, enclosed in a pair of \( ... \) or \[ ... \] .
- Output <Image description="..."/>  as placeholders for photos, charts, figures, etc. detected in the input image, where a short description of the detected content should be attached as attribute in one sentence.
- Ignore page numbers, headers, footers, and watermarks.
- Ignore badges, icons, and visual decorations with no semantic meanings.
""".strip(),
}


class Vlm:
    def __init__(self, settings: AgentSettings) -> None:
        self._client = AsyncOpenAI(base_url=settings.base_url, api_key=settings.api_key, timeout=120)
        self._model = settings.models["default"]
        self._semaphore = Semaphore(settings.concurrency)

    async def recognize(self, b64img: str, prompt: str) -> str:
        messages: Any = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64img, "detail": "high"}},
                    {"type": "text", "text": PROMPTS[prompt]},
                ],
            }
        ]
        async with self._semaphore:
            attempt = 0
            while True:
                try:
                    chat_completion = await self._client.chat.completions.create(
                        stream=False,
                        model=self._model,
                        messages=messages,
                        temperature=0.0,
                        max_completion_tokens=4096,
                        extra_body={"thinking": {"type": "disabled"}},
                    )
                except RateLimitError as exc:
                    logger.warning("rate limited")
                    attempt += 1
                    if attempt == 2:
                        raise exc
                    await asyncio.sleep(10 * 2**attempt + random.random())
                else:
                    break
        if chat_completion.choices:
            if content := chat_completion.choices[0].message.content:
                return content.strip()
        return ""


class Doc2txtError(Exception):
    pass


class FileUnsupportedError(Doc2txtError):
    pass


class ConversionError(Doc2txtError):
    pass


class RecognitionError(Doc2txtError):
    pass


class LlmError(RecognitionError):
    pass


def resize_image(img: Image, max_side: int) -> Image:
    wd, ht = img.width, img.height
    if wd <= max_side and ht <= max_side:
        return img
    if wd > ht:
        new_wd = max_side
        new_ht = int(max_side / wd * ht)
    else:
        new_ht = max_side
        new_wd = int(max_side / ht * wd)
    new_img = img.resize((new_wd, new_ht))  # type: ignore
    return new_img


def encode_image(img: Image) -> str:
    io = BytesIO()
    img.save(io, "png")
    io.seek(0)
    return base64.b64encode(io.read()).decode()


def pdf_iter_images(path: Path) -> Iterator[Image]:
    with pymupdf.Document(path) as doc:
        for page in doc.pages():  # type: ignore
            page = cast(pymupdf.Page, page)
            pixmap = page.get_pixmap(dpi=150)  # type: ignore
            yield pixmap.pil_image()


class Doc2txt:
    def __init__(self, gotenberg: Gotenberg, settings: AgentSettings, tmp_dir: Path) -> None:
        self._gotenberg = gotenberg
        self._tmp_dir = tmp_dir
        self._vlm = Vlm(settings)
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

    async def parse_pages(
        self,
        path: StrPath,
        prompt: str = "default",
        *,
        max_side: int = 1400,
        max_pages: int = 50,
    ) -> list[str]:
        paths = [Path(path)]
        try:
            ext = paths[-1].suffix.removeprefix(".")
            if ext in ("txt", "md"):
                return [paths[-1].read_text()]
            if ext not in ("pdf", "docx", "doc", "pptx", "ppt", "png", "jpg", "jpeg", "webp"):
                raise FileUnsupportedError(f".{ext} is not supported")
            if ext in ("docx", "doc", "pptx", "ppt"):
                new_path = self._tmp_dir / f"{int(time.time())}-{uuid4().hex[:8]}.pdf"
                try:
                    await self._gotenberg.convert(paths[-1], new_path)
                except Exception as exc:
                    raise ConversionError(repr(exc)) from exc
                paths.append(new_path)
                ext = "pdf"
            if ext == "pdf":
                texts = await self.recognize_pdf(paths[-1], prompt, max_side, max_pages=max_pages)
            elif ext in ("png", "jpg", "jpeg", "webp"):
                texts = [await self.recognize_img(paths[-1], prompt, max_side)]
            else:
                assert False
        except Doc2txtError as exc:
            logger.error("doc2txt error: %r", exc)
            raise
        except Exception as exc:
            logger.error("unexpected error: %r", exc)
            raise
        finally:
            while len(paths) >= 2:
                paths.pop().unlink(missing_ok=True)
        return texts

    async def _call_agent(self, b64img: str, prompt: str) -> str:
        try:
            text = await self._vlm.recognize(b64img, prompt)
        except Exception as exc:
            raise LlmError(repr(exc)) from exc
        return text

    async def recognize_img(self, path: Path, prompt: str, max_side: int) -> str:
        try:
            with PIL.Image.open(path) as image_file:
                b64img = encode_image(resize_image(image_file, max_side))
        except Exception as exc:
            raise RecognitionError(repr(exc)) from exc
        text = await self._call_agent(b64img, prompt)
        return text

    async def recognize_pdf(self, path: Path, prompt: str, max_side: int, max_pages: int) -> list[str]:
        tasks: list[Task[str]] = []
        try:
            for i, image in enumerate(pdf_iter_images(path)):
                if i == max_pages:
                    break
                await asyncio.sleep(0)
                b64img = encode_image(resize_image(image, max_side))
                tasks.append(asyncio.create_task(self._call_agent(b64img, prompt)))
        except Exception as exc:
            raise RecognitionError(repr(exc)) from exc
        texts = await asyncio.gather(*tasks)
        return texts
