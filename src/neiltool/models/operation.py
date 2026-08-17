import re
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class OperationError(Exception):
    def __init__(self, msg: str, data: Any | None = None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.data = data

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.msg!r}, data={self.data!r})"


# region order
class OrderInfo(BaseModel):
    order_id: int
    order_name: str
    order_type: int
    course_code: str
    course_name: str
    univ_name: str
    student_name: str
    needs: dict[str, str] = Field(default_factory=lambda: {})
    remote_files: list["OrderFileRemote"] = Field(default_factory=lambda: [])
    local_files: list["OrderFileLocal"] = Field(default_factory=lambda: [])

    @field_validator("order_type", mode="before")
    @classmethod
    def validate_int(cls, v: object) -> object:
        if isinstance(v, int):
            return v
        if v is None:
            return -1
        return v

    @field_validator("course_code", "course_name", "univ_name", "student_name", mode="before")
    @classmethod
    def validate_str(cls, v: object) -> object:
        if isinstance(v, str):
            return v
        if v is None:
            return ""
        return v

    @classmethod
    def fallback(cls, order_id: int) -> Self:
        return cls(
            order_id=order_id,
            order_name="",
            order_type=-1,
            course_code="",
            course_name="",
            univ_name="",
            student_name="",
            needs={},
            remote_files=[],
            local_files=[],
        )


class OrderFileRemote(BaseModel):
    order_id: int
    file_id: int
    name: str
    url: str


class OrderFileLocal(BaseModel):
    order_id: int
    file_id: int
    namelike: Path
    path: Path
    txt_path: Path | None = None

    @property
    def name(self) -> str:
        return str(self.namelike)


# endregion


# region intro slide
class Slide1SchemaKnowledge(BaseModel):
    model_config = {"populate_by_name": True}

    group: str = Field("", validation_alias="模块")
    keypoints: list[str] = Field(default_factory=lambda: [], validation_alias="知识点")


class Slide1Schema(BaseModel):
    model_config = {"populate_by_name": True}

    course_name: str = Field("", validation_alias="课程名称")
    course_code: str = Field("", validation_alias="课程代码")
    assessment: str = Field("", validation_alias="考核项")
    knowledges: list[Slide1SchemaKnowledge] = Field(default_factory=lambda: [], validation_alias="知识体系")

    @classmethod
    def fallback(cls) -> Self:
        return Slide1Schema()  # type: ignore


class Slide2Schema(BaseModel):
    model_config = {"populate_by_name": True}

    course_name: str = Field("", validation_alias="课程名称")
    course_code: str = Field("", validation_alias="课程代码")
    what: str = Field("", validation_alias="学习目标")
    how: str = Field("", validation_alias="课程规划")
    why: str = Field("", validation_alias="为什么这样规划")
    objectives: list[str] = Field(default_factory=lambda: [], validation_alias="课程将完成")
    phases: list[str] = Field(default_factory=lambda: [], validation_alias="课程阶段")
    afterclass: str = Field("", validation_alias="课后任务")

    @classmethod
    def fallback(cls) -> Self:
        return Slide2Schema()  # type: ignore


class SlideData(BaseModel):
    course_name: str
    course_code: str
    assessment: str
    knowledges: list[tuple[str, list[str]]]
    what: str
    how: str
    why: str
    objectives: list[str]
    phases: list[str]
    afterclass: str

    @classmethod
    def from_two_schemas(cls, s1: Slide1Schema, s2: Slide2Schema) -> Self:
        return cls(
            course_name=s2.course_name or s1.course_name,
            course_code=s2.course_code or s1.course_code,
            assessment=s1.assessment,
            knowledges=[(knowledge.group, [it for it in knowledge.keypoints]) for knowledge in s1.knowledges],
            what=s2.what,
            how=s2.how,
            why=s2.why,
            objectives=s2.objectives,
            phases=s2.phases,
            afterclass=s2.afterclass,
        )


# endregion intro slide


# region regular knowledge
class KeypointsSchemaKeypoint(BaseModel):
    page_no: int
    name: str


class KeypointsSchema(BaseModel):
    keypoints: list[KeypointsSchemaKeypoint]


class QuestionSchema(BaseModel):
    body: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)

    @model_validator(mode="before")
    @classmethod
    def validate_string(cls, data: object) -> object:
        if isinstance(s := data, str):
            data = {}
            offsets: list[tuple[int, int]] = []
            for m in re.finditer(r"\n([-+*]?\s*[A-D])[\.\)]\s*", s):
                offsets.append((m.start(1), m.end()))
            if len(offsets) == 0:
                return {}
            body = s[: offsets[0][0]].strip()
            options: list[str] = []
            if len(offsets) >= 1:
                for (_, start), (stop, _) in zip(offsets[:-1], offsets[1:]):
                    options.append(s[start:stop].strip())
                options.append(s[offsets[-1][1] :].strip())
            return {"body": body, "options": options}
        return data

    def str_content(self) -> str:
        return self.body + "\n" + "\n".join(label + ". " + option for label, option in zip("ABCD", self.options))


class QuestionsSchema(BaseModel):
    questions: list[QuestionSchema] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def validate_string(cls, data: object) -> object:
        if isinstance(s := data, str):
            questions: list[QuestionSchema] = []
            for m in re.finditer(r"(?s)<question>(.+?)</question>", s):
                try:
                    question = QuestionSchema.model_validate(m[1].strip())
                except ValidationError:
                    pass
                else:
                    questions.append(question)
            return {"questions": questions}
        return data


class SolutionSchema(BaseModel):
    solution: str
    answer: Literal["A", "B", "C", "D"]

    @model_validator(mode="before")
    @classmethod
    def validate_string(cls, data: object) -> object:
        if isinstance(s := data, str):
            data = {}
            if m := re.search(r"(?s)<solution>(.+?)</solution>", s):
                solution = m[1].strip()
                data["solution"] = solution
            if m := re.search(r"(?s)<answer>(.+?)</answer>", s):
                answer = m[1].strip().upper()
                if answer in ("A", "B", "C", "D"):
                    data["answer"] = answer
                elif m_ans := re.search(r"[ABCD]", answer):
                    data["answer"] = m_ans[0]
        return data


class KeypointQuestion(BaseModel):
    keypoint: str
    page_no: int
    stem: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    solution: str
    answer: Literal["A", "B", "C", "D"]

    def str_question(self) -> str:
        return self.stem + "\n" + "\n".join(label + ") " + option for label, option in zip("ABCD", self.options))


class RunRegularOutputQuestion(BaseModel):
    stem: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    solution: str
    answer: Literal["A", "B", "C", "D"]


class RunRegularOutputKeypoint(BaseModel):
    name: str
    questions: list[RunRegularOutputQuestion]


class RunRegularOutputPage(BaseModel):
    page_no: int
    keypoints: list[RunRegularOutputKeypoint]


# endregion


class RunIntroOutput(BaseModel):
    slide: SlideData
    outline: str


class RunRegularOutput(BaseModel):
    pages: list[RunRegularOutputPage]
    revision: str
