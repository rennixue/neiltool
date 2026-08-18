import asyncio
import logging
import shutil
import traceback
import uuid
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import httpx
from pathvalidate import sanitize_filename

from .agent import Agent
from .daobi_database import DaobiDatabase
from .database import Database
from .doc2txt import Doc2txt
from .gotenberg import Gotenberg
from .llamacloud import Llamacloud
from .models import dtos, enums
from .models.operation import OperationError
from .operation_ai import OperationAI
from .parse import IParse
from .pptx_maker import make_pptx_async
from .utils import md2odt_async

logger = logging.getLogger(__name__)


def make_rand_str() -> str:
    return f"{datetime.now().strftime('%y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


class Operation:
    def __init__(
        self,
        agent: Agent,
        daobi_database: DaobiDatabase,
        database: Database,
        doc2txt: Doc2txt,
        gotenberg: Gotenberg,
        llamacloud: Llamacloud,
        parse: IParse,
        base_url: str,
        static_dir: Path,
        static_url: str,
        tmp_dir: Path,
    ) -> None:
        self._database = database
        self._daobi_database = daobi_database
        self._doc2txt = doc2txt
        self._gotenberg = gotenberg
        self._llamacloud = llamacloud
        self._base_url = base_url
        self._static_dir = static_dir
        self._static_dir.mkdir(parents=True, exist_ok=True)
        self._static_url = static_url
        self._base_tmp_dir = tmp_dir
        self._base_tmp_dir.mkdir(parents=True, exist_ok=True)
        self._ai = OperationAI(agent, daobi_database, parse, tmp_dir / "ai")

    async def run_job(self, job: dtos.InsertJobRet) -> None:
        job_id = job.job_id
        logger.info("job %d start", job_id)
        try:
            await asyncio.wait_for(self.run(job), 1800)
        except OperationError as exc:
            logger.error("job %d fail known: %s", job_id, exc.msg)
            err_msg = exc.msg
            priv_msg = repr(exc.data)[:20000] if exc.data else None
        except TimeoutError:
            logger.error("job %d fail timeout", job_id)
            err_msg = "timeout for job run"
            priv_msg = None
        except Exception as exc:
            logger.error("job %d fail unknown: %r", job_id, exc)
            err_msg = "unexpected error during job run"
            priv_msg = repr(exc)[:20000]
            traceback.print_exc()
        else:
            logger.info("job %d ok", job_id)
            err_msg = None
            priv_msg = None
        if err_msg is None:
            await self._database.update_job_succeed(job_id)
        else:
            await self._database.update_job_fail(job_id, err_msg, priv_msg)
        logger.info("job %d finish", job_id)

    async def run(self, job: dtos.InsertJobRet) -> None:
        tmp_dir = self._base_tmp_dir / str(job.job_id)
        tmp_dir.mkdir()
        try:
            parsed_files = await self.make_parsed_files(job.files, tmp_dir)
            match job.type:
                case enums.JobType.Intro:
                    await self.make_intro(job.job_id, job.order_id, parsed_files)
                case enums.JobType.Regular:
                    await self.make_regular(job.job_id, job.order_id, parsed_files)
        finally:
            try:
                tmp_dir.rmdir()
            except OSError:
                logger.warning("tmp dir not empty")
                shutil.rmtree(tmp_dir)

    async def make_parsed_files(
        self, files: Iterable[dtos.InsertJobRetFile], tmp_dir: Path
    ) -> list[dtos.UpdateFileRet]:
        ret_files: list[dtos.UpdateFileRet] = []
        for file in files:
            texts: list[str] = []
            file_id = file.file_id
            try:
                texts = await self._download_and_parse(file, tmp_dir)
            except OperationError as exc:
                logger.error("file %d fail known: %s", file_id, exc.msg)
                err_msg = exc.msg
                priv_msg = repr(exc.data)[:20000] if exc.data else None
            except Exception as exc:
                logger.error("file %d fail unknown: %r", file_id, exc)
                err_msg = "unexpected error during file fetch and parse"
                priv_msg = repr(exc)[:20000]
                traceback.print_exc()
            else:
                logger.info("file %d ok", file_id)
                err_msg = None
                priv_msg = None
            if err_msg is None:
                if texts:
                    dto_file = await self._database.update_file_succeed(file_id, texts)
                    if dto_file is not None:
                        ret_files.append(dto_file)
                else:
                    await self._database.update_file_fail(file_id, "empty pages", None)
            else:
                await self._database.update_file_fail(file_id, err_msg, priv_msg)
        return ret_files

    async def _download_and_parse(self, file: dtos.InsertJobRetFile, tmp_dir: Path) -> list[str]:
        ext = file.name.rpartition(".")[2]
        if ext not in ("pdf", "pptx", "docx"):
            raise OperationError("unsupported file extension")
        download_path = tmp_dir / f"{file.file_id}.{ext}"
        try:
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as httpx_client:
                    async with httpx_client.stream("GET", file.url) as stream:
                        stream.raise_for_status()
                        with open(download_path, "wb") as fp:
                            async for chunk in stream.aiter_bytes(65536):
                                fp.write(chunk)
            except httpx.HTTPError as exc:
                raise OperationError("cannot download", data=repr(exc))
            priv_msg = ""
            try:
                return await self._doc2txt.parse_pages(download_path, "default", max_side=1400, max_pages=100)
            except Exception as exc:
                logger.warning("doc2txt fail for file %s: %r", file.file_id, exc)
                priv_msg += repr(exc) + "\n"
            try:
                return await self._llamacloud.parse_pages(download_path, tier="fast", max_pages=100)
            except Exception as exc:
                logger.warning("llama cloud fail for file %s: %r", file.file_id, exc)
                priv_msg += repr(exc) + "\n"
            raise OperationError("cannot parse", data=priv_msg.rstrip())
        finally:
            download_path.unlink(missing_ok=True)

    async def make_intro(self, job_id: int, order_id: int, files: list[dtos.UpdateFileRet]) -> None:
        tutor_files = [it for it in files if it.type == enums.FileType.Tutor]
        if len(tutor_files) != 1:
            raise OperationError("not 1 tutor file")
        tutor_file = tutor_files[0]
        syllabus_files = [it for it in files if it.type == enums.FileType.Syllabus]
        if len(syllabus_files) == 0:
            syllabus_file = None
        else:
            syllabus_file = syllabus_files[0]
        output = await self._ai.run_intro(order_id, tutor_file, syllabus_file)

        course_code_or_name = (output.slide.course_code or output.slide.course_name)[:50]
        course_code_or_name = sanitize_filename(course_code_or_name)
        slide_text = output.slide.model_dump_json()
        outline_text = output.outline
        prefix = make_rand_str()

        (self._static_dir / f"{prefix}-slide.json").write_text(slide_text)
        slide_pptx = await make_pptx_async(output.slide)
        if slide_pptx is None:
            slide_url = None
        else:
            (self._static_dir / f"{prefix}-slide.pptx").write_bytes(slide_pptx)
            slide_pdf = await self._gotenberg.convert_bytes("slide.pptx", slide_pptx)
            (self._static_dir / f"{prefix}-slide.pdf").write_bytes(slide_pdf)
            slide_url = self._static_url + "/" + f"{prefix}-slide.pdf"
        await self._database.insert_material(
            job_id,
            enums.MaterialType.Slide,
            f"{course_code_or_name} 上课方案与总结.pdf".lstrip(),
            slide_url,
            slide_text,
        )

        (self._static_dir / f"{prefix}-outline.txt").write_text(outline_text)
        outline_odt = await md2odt_async(outline_text, "outline")
        if outline_odt is None:
            outline_url = None
        else:
            (self._static_dir / f"{prefix}-outline.odt").write_bytes(outline_odt)
            outline_pdf = await self._gotenberg.convert_bytes("outline.odt", outline_odt)
            (self._static_dir / f"{prefix}-outline.pdf").write_bytes(outline_pdf)
            outline_url = self._static_url + "/" + f"{prefix}-outline.pdf"
        outline_material_id = await self._database.insert_material(
            job_id,
            enums.MaterialType.Outline,
            f"{course_code_or_name} 知识点大纲.pdf".lstrip(),
            outline_url,
            outline_text,
        )

        outline_pdf_by_html = await self._gotenberg.render_outline(
            self._base_url + f"/render?material_id={outline_material_id}"
        )
        (self._static_dir / f"{prefix}-outline.html.pdf").write_bytes(outline_pdf_by_html)

        if not slide_url or not outline_url:
            raise OperationError("fail to render file", f"slide={bool(slide_url)} outline={bool(outline_url)}")

    async def make_regular(self, job_id: int, order_id: int, files: list[dtos.UpdateFileRet]):
        tutor_files = [it for it in files if it.type == enums.FileType.Tutor]
        if len(tutor_files) != 1:
            raise OperationError("not 1 tutor file")
        tutor_file = tutor_files[0]
        output = await self._ai.run_regular(order_id, tutor_file)

        page_no_to_id = {page.page_no: page.page_id for page in tutor_file.pages}
        dto_keypoints: list[dtos.InsertKeypointArg] = []
        for output_page in output.pages:
            page_id = page_no_to_id.get(output_page.page_no)
            if page_id is None:
                logger.warning("make_regular: invalid page_no")
                continue
            keypoint_no = 0
            for output_keypoint in output_page.keypoints:
                if not output_keypoint.questions:
                    logger.warning("make_regular: keypoint with 0 question")
                    continue
                keypoint_no += 1
                dto_keypoints.append(
                    dtos.InsertKeypointArg(
                        page_id=page_id,
                        keypoint_no=keypoint_no,
                        name=output_keypoint.name.strip(),
                        questions=[
                            dtos.InsertKeypointArgQuestion(
                                question_no=question_no,
                                type=enums.QuestionType.Choice,
                                content=output_question.model_dump_json(),
                            )
                            for question_no, output_question in enumerate(output_keypoint.questions, 1)
                        ],
                    )
                )
        await self._database.insert_keypoints(dto_keypoints)

        orig_name = tutor_file.name.partition(".")[0][:50]
        orig_name = sanitize_filename(orig_name)
        revision_text = output.revision
        prefix = make_rand_str()

        (self._static_dir / f"{prefix}-revision.txt").write_text(revision_text)
        revision_odt = await md2odt_async(revision_text, "revision")
        if revision_odt is None:
            revision_url = None
        else:
            (self._static_dir / f"{prefix}-revision.odt").write_bytes(revision_odt)
            revision_pdf = await self._gotenberg.convert_bytes("revision.odt", revision_odt)
            (self._static_dir / f"{prefix}-revision.pdf").write_bytes(revision_pdf)
            revision_url = self._static_url + "/" + f"{prefix}-revision.pdf"
        revision_material_id = await self._database.insert_material(
            job_id,
            enums.MaterialType.Revision,
            f"{orig_name} 复习资料.pdf".lstrip(),
            revision_url,
            revision_text,
        )

        revision_pdf_by_html = await self._gotenberg.render_revision(
            self._base_url + f"/render?material_id={revision_material_id}"
        )
        (self._static_dir / f"{prefix}-revision.html.pdf").write_bytes(revision_pdf_by_html)

        if not revision_url:
            raise OperationError("fail to render file", f"revision_url={bool(revision_url)}")
