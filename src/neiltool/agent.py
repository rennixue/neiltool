import asyncio
import functools
import logging
import random
from asyncio import Semaphore
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Awaitable, Callable, ParamSpec, TypeVar, cast

from openai import AsyncOpenAI, AsyncStream, RateLimitError
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from .answer import OpenAIAnswer, ThreeStringIO
from .models.operation import *  # noqa: F403
from .models.settings import AgentSettings
from .template import JinjaTemplateManager

logger = logging.getLogger(__name__)


_P = ParamSpec("_P")
_R = TypeVar("_R")


def with_fallback(func: Callable[_P, Awaitable[_R]], fallback: Callable[_P, _R]) -> Callable[_P, Awaitable[_R]]:
    @functools.wraps(func)
    async def inner(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            logger.error("agent %s fail: %r", func.__name__, exc)
            result = fallback(*args, **kwargs)
        return result

    return inner


class BaseAgent:
    def __init__(self, settings: AgentSettings, default_model: str) -> None:
        self._client = AsyncOpenAI(base_url=settings.base_url, api_key=settings.api_key, timeout=60.0)
        self._models = settings.models
        self._default_model = self._models.get(default_model, default_model)
        self._semaphore = Semaphore(settings.concurrency)
        mngr = JinjaTemplateManager(Path(__file__).parent / "prompts", trim_blocks=True, lstrip_blocks=True)
        self._templates = mngr.load_all_templates()

    async def _ask(self, messages: str | list[Any], **kwargs: Any) -> OpenAIAnswer:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        verbose = int(kwargs.pop("verbose", 0))  # may be bool
        if verbose >= 2:
            print("-" * 60)
            print(messages[-1]["content"])
        model: str = kwargs.pop("model", self._default_model)
        model = self._models.get(model, model)
        stream: bool = kwargs.pop("stream", True)
        if stream:
            if stream_options := kwargs.get("stream_options"):
                if "include_usage" not in stream_options:
                    kwargs["stream_options"]["include_usage"] = True
            else:
                kwargs["stream_options"] = {"include_usage": True}
        max_completion_tokens: int = kwargs.pop("max_completion_tokens", 8192)
        kwargs.pop("max_tokens", None)
        temperature: float = kwargs.pop("temperature", 0.1)
        if extra_body := kwargs.get("extra_body"):
            if thinking := extra_body.get("thinking"):
                if thinking["type"] == "enabled" and "reasoning_effort" not in kwargs:
                    kwargs["reasoning_effort"] = "low"
            else:
                kwargs["extra_body"]["thinking"] = {"type": "disabled"}
        else:
            if kwargs.get("reasoning_effort"):
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            else:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        async with self._semaphore:
            attempt = 0
            while True:
                try:
                    maybe_stream = await self._client.chat.completions.create(
                        messages=messages,
                        model=model,
                        stream=stream,
                        max_completion_tokens=max_completion_tokens,
                        temperature=temperature,
                        **kwargs,
                    )
                except RateLimitError as exc:
                    logger.warning("rate limited %r", exc)
                    attempt += 1
                    if attempt == 2:
                        raise exc
                    await asyncio.sleep(10 * 2**attempt + random.random())
                    continue
                if stream:
                    answer = await OpenAIAnswer.from_astream(
                        cast(AsyncStream[ChatCompletionChunk], maybe_stream),
                        ThreeStringIO.with_print() if verbose >= 1 else None,
                    )
                else:
                    answer = OpenAIAnswer.from_nonstream(cast(ChatCompletion, maybe_stream))
                break
        if verbose >= 1:
            print("-" * 60)
            print(
                "Usage: prompt={}, completion={}, reasoning={}".format(
                    answer.prompt_tokens, answer.completion_tokens, answer.reasoning_tokens
                )
            )
        return answer


class Agent(BaseAgent):
    async def _tutor_schedule(self, text: str) -> str:
        if not text:
            return ""
        user_msg = self._templates["tutor_schedule"].render(text=text)
        answer = await self._ask(user_msg, stream=False, max_completion_tokens=4096)
        return answer.nonempty_content

    tutor_schedule = with_fallback(_tutor_schedule, lambda self, text: "")

    async def _syllabus_overview(self, name: str, text: str) -> str:
        if not text:
            return ""
        user_msg = self._templates["syllabus_overview"].render(name=name, text=text)
        answer = await self._ask(user_msg, stream=False, max_completion_tokens=4096)
        return answer.nonempty_content

    syllabus_overview = with_fallback(_syllabus_overview, lambda self, name, text: "")

    async def _slide_1(
        self,
        course_code: str,
        course_name: str,
        need: str,
        teacher_msg: str,
        text: str,
        syllabus_overview: str,
    ) -> Slide1Schema:
        if not text:
            return Slide1Schema.fallback()
        user_msg = self._templates["slide_1"].render(
            course_name=course_name,
            course_code=course_code,
            need=need,
            teacher_msg=teacher_msg,
            text=text,
            syllabus_overview=syllabus_overview,
        )
        answer = await self._ask(user_msg, stream=False, reasoning_effort="low", max_completion_tokens=8192)
        output = Slide1Schema.model_validate(answer.content_parse_json())
        return output

    slide_1 = with_fallback(
        _slide_1,
        lambda self, course_code, course_name, need, teacher_msg, text, syllabus_overview: Slide1Schema.fallback(),
    )

    async def _slide_2(
        self,
        course_code: str,
        course_name: str,
        need: str,
        teacher_msg: str,
        text: str,
        knowledge: str,
    ) -> Slide2Schema:
        if not text:
            return Slide2Schema.fallback()
        user_msg = self._templates["slide_2"].render(
            course_name=course_name,
            course_code=course_code,
            need=need,
            teacher_msg=teacher_msg,
            text=text,
            knowledge=knowledge,
        )
        answer = await self._ask(user_msg, stream=False, reasoning_effort="low", max_completion_tokens=8192)
        output = Slide2Schema.model_validate(answer.content_parse_json())
        return output

    slide_2 = with_fallback(
        _slide_2,
        lambda self, course_code, course_name, need, teacher_msg, text, knowledge: Slide2Schema.fallback(),
    )

    async def _outline(
        self,
        univ_name: str,
        course_code: str,
        course_name: str,
        student_name: str,
        teacher_msg: str,
        tutor_name: str,
        text: str,
        tutor_schedule: str,
        syllabus_overview: str,
        knowledge: str,
    ) -> str:
        if not text:
            return ""
        messages: list[dict[str, str]] = []
        user_msg = self._templates["outline_plan"].render(
            univ_name=univ_name,
            course_code=course_code,
            course_name=course_name,
            student_name=student_name,
            teacher_msg=teacher_msg,
            tutor_name=tutor_name,
            text=text,
            tutor_schedule=tutor_schedule,
            syllabus_overview=syllabus_overview,
            knowledge=knowledge,
        )
        messages.append({"role": "user", "content": user_msg})
        answer = await self._ask(user_msg, reasoning_effort="low", max_completion_tokens=16384)
        plan = answer.nonempty_content
        messages.append({"role": "assistant", "content": plan})
        user_msg = self._templates["outline"].render()
        messages.append({"role": "user", "content": user_msg})
        answer = await self._ask(messages, max_completion_tokens=16384)
        outline = answer.nonempty_content
        user_msg = self._templates["markdown_fix"].render(text=outline)
        answer = await self._ask(user_msg, max_completion_tokens=16384)
        fixed_outline = answer.nonempty_content
        return fixed_outline

    # fmt: off
    outline = with_fallback(
        _outline,
        lambda self, univ_name, course_code, course_name, student_name, teacher_msg, tutor_name, text, tutor_schedule, syllabus_overview, knowledge: "",
    )
    # fmt: on

    async def _keypoints(self, pages: Sequence[tuple[int, str]]) -> list[KeypointsSchemaKeypoint]:
        if not pages or sum(len(it[1]) for it in pages) == 0:
            return []
        user_msg = self._templates["keypoints"].render(pages=pages)
        answer = await self._ask(user_msg, reasoning_effort="low", max_completion_tokens=8192)
        output = KeypointsSchema.model_validate(answer.content_parse_json())
        return output.keypoints

    keypoints = with_fallback(_keypoints, lambda self, pages: [])

    async def _question(self, name: str, page_no: int, pages: Sequence[tuple[int, str]]) -> QuestionSchema:
        # do not retry, let attempt +1
        correct_option = random.choice("ABCD")
        user_msg = self._templates["question"].render(
            name=name, page_no=page_no, pages=pages, correct_option=correct_option
        )
        answer = await self._ask(user_msg, reasoning_effort="low", max_completion_tokens=8192)
        output = QuestionsSchema.model_validate(answer.content)
        return output.questions[0]

    async def _solution(
        self, name: str, page_no: int, pages: Sequence[tuple[int, str]], question: str
    ) -> SolutionSchema:
        # do not retry, let attempt +1
        user_msg = self._templates["solution"].render(name=name, page_no=page_no, pages=pages, question=question)
        answer = await self._ask(user_msg, reasoning_effort="low", max_completion_tokens=8192)
        output = SolutionSchema.model_validate(answer.content)
        return output

    async def _keypoint_question(
        self, name: str, page_no: int, pages: Sequence[tuple[int, str]]
    ) -> KeypointQuestion | None:
        for _ in range(2):
            try:
                question = await self._question(name, page_no, pages)
            except Exception:
                logger.warning("question fail")
                continue
            try:
                solution = await self._solution(name, page_no, pages, question.str_content())
            except Exception:
                logger.warning("solution fail")
                continue
            break
        else:
            logger.warning("question or solution fail for %r", name)
            return None
        return KeypointQuestion(
            keypoint=name,
            page_no=page_no,
            stem=question.body,
            options=question.options,
            solution=solution.solution,
            answer=solution.answer,
        )

    keypoint_question = with_fallback(_keypoint_question, lambda self, name, page_no, pages: None)

    async def _revision(
        self,
        univ_name: str,
        course_code: str,
        course_name: str,
        student_name: str,
        tutor_name: str,
        tutor_pages: Sequence[tuple[int, str]],
        keypoint_names: Sequence[str],
    ) -> str:
        if not tutor_pages:
            return ""
        messages: list[dict[str, str]] = []
        user_msg = self._templates["revision_plan"].render(
            univ_name=univ_name,
            course_code=course_code,
            course_name=course_name,
            student_name=student_name,
            tutor_name=tutor_name,
            pages=tutor_pages,
            keypoint_names=keypoint_names,
        )
        messages.append({"role": "user", "content": user_msg})
        answer = await self._ask(user_msg, reasoning_effort="low", max_completion_tokens=16384)
        plan = answer.nonempty_content
        messages.append({"role": "assistant", "content": plan})
        user_msg = self._templates["revision"].render()
        messages.append({"role": "user", "content": user_msg})
        answer = await self._ask(messages, max_completion_tokens=16384)
        revision = answer.nonempty_content
        user_msg = self._templates["markdown_fix"].render(text=revision)
        answer = await self._ask(user_msg, max_completion_tokens=16384)
        fixed_revision = answer.nonempty_content
        return fixed_revision

    revision = with_fallback(
        _revision,
        lambda self, univ_name, course_code, course_name, student_name, tutor_name, tutor_pages, keypoint_names: "",
    )
