import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from .agent import Agent
from .daobi_database import DaobiDatabase
from .models import dtos
from .models.operation import (
    OrderInfo,
    RunIntroOutput,
    RunRegularOutput,
    RunRegularOutputKeypoint,
    RunRegularOutputPage,
    RunRegularOutputQuestion,
    SlideData,
)
from .parse import IParse

logger = logging.getLogger(__name__)


def to_pages(pages: Sequence[dtos.UpdateFileRetPage]) -> list[tuple[int, str]]:
    return [(it.page_no, it.text) for it in pages]


def to_text(pages: Sequence[dtos.UpdateFileRetPage]) -> str:
    return "\n\n".join(it.text for it in pages)


class OrderKwargs(TypedDict):
    univ_name: str
    course_code: str
    course_name: str
    student_name: str
    need: str


class OperationAI:
    def __init__(self, agent: Agent, daobi_database: DaobiDatabase, parse: IParse, tmp_dir: Path) -> None:
        self._agent = agent
        self._daobi_database = daobi_database
        self._parse = parse
        self._base_tmp_dir = tmp_dir
        self._base_tmp_dir.mkdir(parents=True, exist_ok=True)

    async def _make_order_info(self, order_id: int) -> OrderInfo:
        try:
            order_info = await self._daobi_database.fetch_order_info(order_id)
        except Exception as exc:
            logger.error("daobi_database fetch_order_info fail at %s: %r", order_id, exc)
            order_info = OrderInfo.fallback(order_id)
        if order_info is None:
            order_info = OrderInfo.fallback(order_id)
        return order_info

    async def run_intro(
        self, order_id: int, tutor: dtos.UpdateFileRet, syllabus: dtos.UpdateFileRet | None, teacher_msg: str | None
    ) -> RunIntroOutput:
        order_info = await self._make_order_info(order_id)
        need = "\n------\n".join(it for it in order_info.needs.values())
        teacher_msg = teacher_msg or ""
        tutor_text = to_text(tutor.pages)

        tutor_schedule = await self._agent.tutor_schedule(tutor_text)
        if syllabus:
            syllabus_overview = await self._agent.syllabus_overview(syllabus.name, to_text(syllabus.pages))
        else:
            syllabus_overview = ""
        slide_1 = await self._agent.slide_1(
            course_code=order_info.course_code,
            course_name=order_info.course_name,
            need=need,
            teacher_msg=teacher_msg,
            text=tutor_text,
            syllabus_overview=syllabus_overview,
        )
        knowledge = "\n".join(it.model_dump_json() for it in slide_1.knowledges)
        slide_2 = await self._agent.slide_2(
            course_code=order_info.course_code,
            course_name=order_info.course_name,
            need=need,
            teacher_msg=teacher_msg,
            text=tutor_text,
            knowledge=knowledge,
        )
        outline = await self._agent.outline(
            univ_name=order_info.univ_name,
            course_code=order_info.course_code,
            course_name=order_info.course_name,
            student_name=order_info.student_name,
            teacher_msg=teacher_msg,
            tutor_name=tutor.name,
            text=tutor_text,
            tutor_schedule=tutor_schedule,
            syllabus_overview=syllabus_overview,
            knowledge=knowledge,
        )
        return RunIntroOutput(
            slide=SlideData.from_two_schemas(slide_1, slide_2),
            outline=outline,
        )

    async def run_regular(self, order_id: int, tutor: dtos.UpdateFileRet) -> RunRegularOutput:
        order_info = await self._make_order_info(order_id)
        tutor_pages = to_pages(tutor.pages)

        keypoints = await self._agent.keypoints(tutor_pages)
        keypoint_questions = await asyncio.gather(
            *(self._agent.keypoint_question(it.name, it.page_no, tutor_pages) for it in keypoints)
        )
        keypoint_questions = [it for it in keypoint_questions if it is not None]
        page_no_to_idx: dict[int, int] = {}
        output_pages: list[RunRegularOutputPage] = []
        for it in keypoint_questions:
            page_no = it.page_no
            if page_no in page_no_to_idx:
                logger.warning("more than one keypoint on one page")
                continue
            page_no_to_idx[page_no] = len(output_pages)
            output_pages.append(
                RunRegularOutputPage(
                    page_no=page_no,
                    keypoints=[
                        RunRegularOutputKeypoint(
                            name=it.keypoint,
                            questions=[
                                RunRegularOutputQuestion(
                                    stem=it.stem,
                                    options=it.options,
                                    solution=it.solution,
                                    answer=it.answer,
                                )
                            ],
                        )
                    ],
                )
            )
        keypoint_names = [it.keypoint for it in keypoint_questions]
        revision = await self._agent.revision(
            univ_name=order_info.univ_name,
            course_code=order_info.course_code,
            course_name=order_info.course_name,
            student_name=order_info.student_name,
            tutor_name=tutor.name,
            tutor_pages=tutor_pages,
            keypoint_names=keypoint_names,
        )
        return RunRegularOutput(
            pages=output_pages,
            revision=revision,
        )
