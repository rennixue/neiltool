import logging
from asyncio import Semaphore
from typing import Literal

from llama_cloud import AsyncLlamaCloud

from .models.settings import LlamacloudSettings, StrPath

logger = logging.getLogger(__name__)


class Llamacloud:
    def __init__(self, settings: LlamacloudSettings) -> None:
        self._client = AsyncLlamaCloud(api_key=settings.api_key)
        self._semaphore = Semaphore(settings.concurrency)

    async def parse_pages(
        self,
        in_path: StrPath,
        *,
        tier: Literal["fast", "cost_effective"] = "fast",
        max_pages: int = 50,
    ) -> list[str]:
        texts: list[str] = []
        if tier == "fast":
            expand = ["text"]
        else:
            expand = ["text", "markdown"]
        try:
            async with self._semaphore:
                file = await self._client.files.create(file=in_path, purpose="parse")
                try:
                    resp = await self._client.parsing.parse(
                        file_id=file.id,
                        tier=tier,
                        version="latest",
                        expand=expand,
                        page_ranges={"max_pages": max_pages},
                    )
                    if tier == "fast":
                        assert resp.text is not None
                        for page in resp.text.pages:
                            texts.append(page.text)
                    else:
                        assert resp.text is not None
                        assert resp.markdown is not None
                        for page, md_page in zip(resp.text.pages, resp.markdown.pages):
                            if hasattr(md_page, "markdown") and isinstance(md := getattr(md_page, "markdown"), str):
                                texts.append(md)
                            else:
                                logger.warning("llama parse no markdown, use text instead")
                                texts.append(page.text)
                finally:
                    await self._client.files.delete(file_id=file.id)
        except Exception as exc:
            logger.error("LlamaCloud fail to parse '%s': %r", in_path, exc)
        return texts
