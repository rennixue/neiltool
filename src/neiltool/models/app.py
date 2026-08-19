from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, Field, HttpUrl, RootModel, field_validator, model_validator

from . import enums


class WrapResp(BaseModel):
    code: int = 200
    msg: str | None = None
    data: Any = Field(default_factory=lambda: dict[str, Any]())

    @model_validator(mode="after")
    def ensure_msg_and_data(self) -> Self:
        if self.code // 100 == 2:
            self.msg = None
        if self.code // 100 in (4, 5):
            self.data = {}
        return self


class GetHealthResp(BaseModel):
    status: Literal["UP", "DOWN"]


class PostJobReqFile(BaseModel):
    type: enums.FileType
    ident: int | str | None = None
    name: str
    url: HttpUrl


class PostJobReq(BaseModel):
    type: enums.JobType
    order_id: int
    classroom_id: int | None = None
    teacher_msg: str | None = None
    files: list[PostJobReqFile]

    @field_validator("files", mode="after")
    @classmethod
    def is_good_files(cls, files: list[PostJobReqFile]) -> list[PostJobReqFile]:
        tutor_files = [it for it in files if it.type == enums.FileType.Tutor]
        if len(tutor_files) != 1:
            raise ValueError("must be exactly one tutor file")
        return files


class PostJobResp(BaseModel):
    job_id: int
    status: Literal[enums.JobStatus.Pend]
    file_ids: list[int]


JobIdParam = RootModel[int]


class GetJobStatusResp(BaseModel):
    job_id: int
    status: enums.JobStatus


class GetJobResultRespMaterial(BaseModel):
    material_id: int
    name: str
    tmp_url: HttpUrl


class GetJobResultRespIntro(BaseModel):
    type: Literal[enums.JobType.Intro] = enums.JobType.Intro
    slide: GetJobResultRespMaterial
    outline: GetJobResultRespMaterial


class GetJobResultRespQuestionChoice(BaseModel):
    type: Literal[enums.QuestionType.Choice] = enums.QuestionType.Choice
    question_id: int
    stem: str
    options: Annotated[list[str], Field(min_length=4, max_length=4)]
    solution: str
    answer: Literal["A", "B", "C", "D"]


class GetJobResultRespKeypoint(BaseModel):
    keypoint_id: int
    name: str
    questions: list[GetJobResultRespQuestionChoice]


class GetJobResultRespPage(BaseModel):
    page_no: int
    keypoints: list[GetJobResultRespKeypoint]


class GetJobResultRespRegular(BaseModel):
    type: Literal[enums.JobType.Regular] = enums.JobType.Regular
    revision: GetJobResultRespMaterial
    pages: list[GetJobResultRespPage]


class GetJobResultResp(BaseModel):
    job_id: int
    status: enums.JobStatus
    err_msg: str | None
    generated: Annotated[GetJobResultRespIntro | GetJobResultRespRegular, Field(discriminator="type")] | None


class PutJobClassroomReq(BaseModel):
    classroom_id: int


class PutJobClassroomResp(BaseModel):
    job_id: int
    classroom_id: int | None


MaterialIdParam = RootModel[int]


class GetMaterialResp(BaseModel):
    material_id: int
    job_id: int
    type: enums.MaterialType
    name: str
    tmp_url: str | None
    url: str | None
    text: str


class PutMaterialReq(BaseModel):
    url: HttpUrl


class PutMaterialResp(BaseModel):
    material_id: int
    url: str


QuestionIdParam = RootModel[int]


class PatchQuestionAnswerReq(BaseModel):
    is_correct: bool


class PatchQuestionAnswerResp(BaseModel):
    question_id: int
    attempt: int
    first_correct: bool
    last_correct: bool
