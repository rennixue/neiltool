import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from .models.settings import GotenbergSettings, StrPath

logger = logging.getLogger(__name__)


class Gotenberg:
    def __init__(self, settings: GotenbergSettings) -> None:
        if settings.use_auth:
            self._client = AsyncClient(base_url=settings.base_url, auth=(settings.username, settings.password))
        else:
            self._client = AsyncClient(base_url=settings.base_url)

    async def convert(self, in_path: StrPath, out_path: StrPath) -> None:
        with open(in_path, "rb") as fp_in:
            files = {"files": (Path(in_path).name, fp_in)}
            async with self._client.stream("POST", "/forms/libreoffice/convert", files=files, timeout=300) as response:
                with open(out_path, "wb") as fp_out:
                    async for chunk in response.aiter_bytes(65536):
                        fp_out.write(chunk)

    async def convert_bytes(self, name: str, input_: bytes) -> bytes:
        files = {"files": (name, input_)}
        fp_out = BytesIO()
        async with self._client.stream("POST", "/forms/libreoffice/convert", files=files, timeout=300) as response:
            async for chunk in response.aiter_bytes(65536):
                fp_out.write(chunk)
        return fp_out.getvalue()

    async def render_bytes(self, url: str, options: dict[str, Any]) -> bytes:
        form = {"url": url, **options}
        fp_out = BytesIO()
        async with self._client.stream(
            "POST",
            "/forms/chromium/convert/url",
            data=form,
            files={"file": ""},  # multipart/form-data required
            timeout=300,
        ) as response:
            async for chunk in response.aiter_bytes(65536):
                fp_out.write(chunk)
        return fp_out.getvalue()

    async def render_outline(self, url: str) -> bytes:
        options = {
            "paperWidth": "8.5",
            "paperHeight": "11",
            "landscape": True,
            "marginTop": "0.5",
            "marginBottom": "0.5",
            "marginLeft": "0.5",
            "marginRight": "0.5",
            "scale": 1.0,
            # do not use waitForExpression, because it cannot judge whether fonts have been loaded or not
            "waitDelay": "10s",
        }
        try:
            return await self.render_bytes(url, options)
        except Exception as exc:
            logger.error("gotenberg fail to render_outline: %r", exc)
            return b""

    async def render_revision(self, url: str) -> bytes:
        options = {
            "paperWidth": "8.5",
            "paperHeight": "11",
            "landscape": False,
            "marginTop": "0.5",
            "marginBottom": "0.5",
            "marginLeft": "0.5",
            "marginRight": "0.5",
            "scale": 1.0,
            # do not use waitForExpression, because it cannot judge whether fonts have been loaded or not
            "waitDelay": "10s",
        }
        try:
            return await self.render_bytes(url, options)
        except Exception as exc:
            logger.error("gotenberg fail to render_revision: %r", exc)
            return b""
