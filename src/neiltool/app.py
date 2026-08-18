import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .agent import Agent
from .app_utils import InvalidRequest, PydanticJSONResponse, PydanticRoute, extract_path_param, extract_req_body
from .daobi_database import DaobiDatabase
from .database import Database
from .doc2txt import Doc2txt
from .gotenberg import Gotenberg
from .llamacloud import Llamacloud
from .models import dtos
from .models.app import *  # noqa: F403
from .models.settings import AppSettings
from .operation import Operation
from .parse import MoonshotParser

logger = logging.getLogger(__name__)


class AppState(TypedDict):
    daobi_database: DaobiDatabase
    database: Database
    operation: Operation


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[AppState]:
    settings = AppSettings.model_validate({**os.environ})
    agent = Agent(settings.volcengine, "default")
    daobi_database = DaobiDatabase(settings.daobi_database_url)
    database = Database(settings.database_url)
    gotenberg = Gotenberg(settings.gotenberg)
    doc2txt = Doc2txt(gotenberg, settings.doc2txt, settings.tmp_dir / "doc2txt")
    llamacloud = Llamacloud(settings.llamacloud)
    moonshot = MoonshotParser(settings.moonshot)
    operation = Operation(
        agent,
        daobi_database,
        database,
        doc2txt,
        gotenberg,
        llamacloud,
        moonshot,
        str(settings.base_url),
        settings.static_dir,
        str(settings.static_url),
        settings.tmp_dir / "operation",
    )
    state: AppState = {
        "daobi_database": daobi_database,
        "database": database,
        "operation": operation,
    }
    yield state


async def handle_http_exception(request: Request[AppState], exc: HTTPException) -> PydanticJSONResponse:
    return PydanticJSONResponse(WrapResp(code=exc.status_code, msg=exc.detail), status_code=exc.status_code)


async def handle_invalid_request(request: Request[AppState], exc: InvalidRequest) -> PydanticJSONResponse:
    return PydanticJSONResponse(WrapResp(code=422, msg=exc.msg), status_code=422)


async def handle_exception(request: Request[AppState], exc: Exception) -> PydanticJSONResponse:
    return PydanticJSONResponse(WrapResp(code=500, msg="Internal Server Error"), status_code=500)


def create_app() -> Starlette:
    settings = AppSettings.model_validate({**os.environ})
    static_dir = settings.static_dir
    static_dir.mkdir(parents=True, exist_ok=True)
    return Starlette(
        lifespan=lifespan,
        exception_handlers={
            HTTPException: handle_http_exception,
            InvalidRequest: handle_invalid_request,
            Exception: handle_exception,
        },  # pyright: ignore[reportArgumentType]
        middleware=[
            Middleware(CORSMiddleware, allow_origins=["*"]),
        ],
        routes=[
            Route("/doc", get_doc, methods=["GET"]),
            Route("/render", get_render, methods=["GET"]),
            Mount("/assets", StaticFiles(directory="./static/assets")),
            Mount("/static", StaticFiles(directory=static_dir)),
            PydanticRoute("/api/health", get_health, methods=["GET"]),
            PydanticRoute("/api/job", post_job, methods=["POST"]),
            PydanticRoute("/api/job/{job_id}/status", get_job_status, methods=["GET"]),
            PydanticRoute("/api/job/{job_id}/result", get_job_result, methods=["GET"]),
            PydanticRoute("/api/job/{job_id}/classroom", put_job_classroom, methods=["PUT"]),
            PydanticRoute("/api/material/{material_id}", get_or_put_material, methods=["GET", "PUT"]),
            PydanticRoute("/api/question/{question_id}/answer", patch_question_answer, methods=["PATCH"]),
        ],
    )


async def get_doc(request: Request[AppState]) -> HTMLResponse:
    doc_path = Path("./static/doc.html")
    if doc_path.exists():
        bytes_ = doc_path.read_bytes()
    else:
        bytes_ = b""
    return HTMLResponse(bytes_)


async def get_render(request: Request[AppState]) -> HTMLResponse:
    doc_path = Path("./static/index.html")
    if doc_path.exists():
        bytes_ = doc_path.read_bytes()
    else:
        bytes_ = b""
    return HTMLResponse(bytes_)


type _WrapRespRetT = WrapResp | tuple[WrapResp, int]


async def get_health(request: Request[AppState]) -> _WrapRespRetT:
    if all(
        await asyncio.gather(
            request.state["daobi_database"].is_healthy(),
            request.state["database"].is_healthy(),
        )
    ):
        status = "UP"
    else:
        status = "DOWN"
    return WrapResp(data=GetHealthResp(status=status))


async def post_job(request: Request[AppState]) -> _WrapRespRetT:
    req = await extract_req_body(request, PostJobReq)
    dto = await request.state["database"].insert_job(
        req.type,
        req.order_id,
        req.classroom_id,
        files=[
            dtos.InsertJobArgFile(
                type=file.type,
                ident=str(file.ident) if file.ident is not None else None,
                name=file.name,
                url=str(file.url),
            )
            for file in req.files
        ],
    )
    file_ids: list[int] = []
    for orig_file in req.files:
        for it in dto.files:
            if (
                it.type == orig_file.type
                and it.ident == orig_file.ident
                and it.name == orig_file.name
                and it.url == str(orig_file.url)
            ):
                file_ids.append(it.file_id)
                break
    if len(file_ids) != len(req.files):
        logger.warning(f"post_job: {len(file_ids)=} != {len(req.files)=}")
        file_ids = [file.file_id for file in dto.files]
    asyncio.create_task(request.state["operation"].run_job(dto))
    return (
        WrapResp(
            code=202,
            msg="accepted",
            data=PostJobResp(job_id=dto.job_id, status=enums.JobStatus.Pend, file_ids=file_ids),
        ),
        202,
    )


async def get_job_status(request: Request[AppState]) -> _WrapRespRetT:
    job_id = extract_path_param(request, "job_id", int)
    dto = await request.state["database"].select_job_status(job_id)
    if dto is None:
        return WrapResp(code=404, msg="job not found"), 404
    return WrapResp(data=GetJobStatusResp(job_id=dto.job_id, status=dto.status))


async def get_job_result(request: Request[AppState]) -> _WrapRespRetT:
    job_id = extract_path_param(request, "job_id", int)
    dto = await request.state["database"].select_job_result(job_id)
    if dto is None:
        return WrapResp(code=404, msg="job not found"), 404
    if dto.status == enums.JobStatus.Succeed:
        match dto.type:
            case enums.JobType.Intro:
                materials_slide = [it for it in dto.materials if it.type == enums.MaterialType.Slide]
                if len(materials_slide) != 1:
                    logger.error(f"get_job_result: {len(materials_slide)=}")
                    return WrapResp(code=500, msg="wrong data for materials"), 500
                slide = materials_slide[0]
                if slide.tmp_url is None:
                    logger.error("get_job_result: tmp_url for slide is null")
                    return WrapResp(code=500, msg="wrong data for materials"), 500
                materials_outline = [it for it in dto.materials if it.type == enums.MaterialType.Outline]
                if len(materials_outline) != 1:
                    logger.error(f"get_job_result: {len(materials_outline)=}")
                    return WrapResp(code=500, msg="wrong data for materials"), 500
                outline = materials_outline[0]
                if outline.tmp_url is None:
                    logger.error("get_job_result: tmp_url for outline is null")
                    return WrapResp(code=500, msg="wrong data for materials"), 500
                generated = GetJobResultRespIntro(
                    slide=GetJobResultRespMaterial(
                        material_id=slide.material_id,
                        name=slide.name,
                        tmp_url=slide.tmp_url,  # pyright: ignore[reportArgumentType]
                    ),
                    outline=GetJobResultRespMaterial(
                        material_id=outline.material_id,
                        name=outline.name,
                        tmp_url=outline.tmp_url,  # pyright: ignore[reportArgumentType]
                    ),
                )
            case enums.JobType.Regular:
                materials_revision = [it for it in dto.materials if it.type == enums.MaterialType.Revision]
                if len(materials_revision) != 1:
                    logger.error(f"get_job_result: {len(materials_revision)=}")
                    return WrapResp(code=500, msg="wrong data for materials"), 500
                revision = materials_revision[0]
                if revision.tmp_url is None:
                    logger.error("get_job_result: tmp_url for revision is null")
                    return WrapResp(code=500, msg="wrong data for materials"), 500
                pages: list[GetJobResultRespPage] = []
                for page in dto.pages:
                    keypoints: list[GetJobResultRespKeypoint] = []
                    for keypoint in page.keypoints:
                        questions: list[GetJobResultRespQuestionChoice] = []
                        for question in keypoint.questions:
                            # NOTE better not use match between a Literal and a StrEnum member
                            match question.type:
                                case enums.QuestionType.Choice:
                                    if len(question.options) != 4 or question.answer not in ("A", "B", "C", "D"):
                                        logger.warning(f"question {question.question_id} has invalid data")
                                        continue
                                    resp_question = GetJobResultRespQuestionChoice(
                                        question_id=question.question_id,
                                        stem=question.stem,
                                        options=[
                                            f"{label}. {option}" for label, option in zip("ABCD", question.options)
                                        ],
                                        solution=question.solution,
                                        answer=question.answer,
                                    )
                            questions.append(resp_question)
                        if len(questions) != 0:
                            keypoints.append(
                                GetJobResultRespKeypoint(
                                    keypoint_id=keypoint.keypoint_id, name=keypoint.name, questions=questions
                                )
                            )
                    pages.append(GetJobResultRespPage(page_no=page.page_no, keypoints=keypoints))
                generated = GetJobResultRespRegular(
                    revision=GetJobResultRespMaterial(
                        material_id=revision.material_id,
                        name=revision.name,
                        tmp_url=revision.tmp_url,  # pyright: ignore[reportArgumentType]
                    ),
                    pages=pages,
                )
    else:
        generated = None
    return WrapResp(
        data=GetJobResultResp(job_id=dto.job_id, status=dto.status, err_msg=dto.err_msg, generated=generated)
    )


async def put_job_classroom(request: Request[AppState]) -> _WrapRespRetT:
    job_id = extract_path_param(request, "job_id", int)
    req = await extract_req_body(request, PutJobClassroomReq)
    dto = await request.state["database"].update_job_classroom_id(job_id, req.classroom_id)
    if dto is None:
        return WrapResp(code=404, msg="job not found"), 404
    return WrapResp(data=PutJobClassroomResp(job_id=dto.job_id, classroom_id=dto.classroom_id))


async def get_or_put_material(request: Request[AppState]) -> _WrapRespRetT:
    if request.method == "GET":
        return await get_material(request)
    elif request.method == "PUT":
        return await put_material(request)
    else:
        raise HTTPException(405)


async def get_material(request: Request[AppState]) -> _WrapRespRetT:
    material_id = extract_path_param(request, "material_id", int)
    dto = await request.state["database"].select_material(material_id)
    if dto is None:
        return WrapResp(code=404, msg="material not found"), 404
    return WrapResp(
        data=GetMaterialResp(
            material_id=dto.material_id,
            job_id=dto.job_id,
            type=dto.type,
            name=dto.name,
            tmp_url=dto.tmp_url,
            url=dto.url,
            text=dto.text,
        )
    )


async def put_material(request: Request[AppState]) -> _WrapRespRetT:
    material_id = extract_path_param(request, "material_id", int)
    req = await extract_req_body(request, PutMaterialReq)
    dto = await request.state["database"].update_material_url(material_id, str(req.url))
    if dto is None:
        return WrapResp(code=404, msg="material not found"), 404
    return WrapResp(data=PutMaterialResp(material_id=dto.material_id, url=dto.url))


async def patch_question_answer(request: Request[AppState]) -> _WrapRespRetT:
    question_id = extract_path_param(request, "question_id", int)
    req = await extract_req_body(request, PatchQuestionAnswerReq)
    dto = await request.state["database"].update_question_answer(question_id, req.is_correct)
    if dto is None:
        return WrapResp(code=404, msg="question not found"), 404
    return WrapResp(
        data=PatchQuestionAnswerResp(
            question_id=dto.question_id,
            attempt=dto.attempt,
            first_correct=dto.first_correct,
            last_correct=dto.last_correct,
        )
    )
