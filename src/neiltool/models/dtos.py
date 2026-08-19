from pydantic import BaseModel

from . import enums


class InsertJobArgFile(BaseModel):
    type: enums.FileType
    ident: str | None
    name: str
    url: str


class InsertJobRetFile(BaseModel):
    file_id: int
    ident: str | None
    type: enums.FileType
    name: str
    url: str
    status: enums.FileStatus


class InsertJobRet(BaseModel):
    job_id: int
    type: enums.JobType
    order_id: int
    status: enums.JobStatus
    teacher_msg: str | None
    files: list[InsertJobRetFile]


class SelectJobStatusRet(BaseModel):
    job_id: int
    status: enums.JobStatus


class SelectJobResultRetMaterial(BaseModel):
    type: enums.MaterialType
    material_id: int
    name: str
    tmp_url: str | None


class SelectJobResultRetQuestionChoice(BaseModel):
    type: enums.QuestionType
    question_id: int
    stem: str
    options: list[str]
    solution: str
    answer: str


class SelectJobResultRetKeypoint(BaseModel):
    keypoint_id: int
    name: str
    questions: list[SelectJobResultRetQuestionChoice]


class SelectJobResultRetPage(BaseModel):
    page_no: int
    keypoints: list[SelectJobResultRetKeypoint]


class SelectJobResultRet(BaseModel):
    job_id: int
    status: enums.JobStatus
    type: enums.JobType
    err_msg: str | None
    materials: list[SelectJobResultRetMaterial]
    pages: list[SelectJobResultRetPage]


class UpdateJobClassroomIdRet(BaseModel):
    job_id: int
    classroom_id: int | None


class SelectMaterialRet(BaseModel):
    material_id: int
    job_id: int
    type: enums.MaterialType
    name: str
    tmp_url: str | None
    url: str | None
    text: str


class UpdateMaterialUrlRet(BaseModel):
    material_id: int
    url: str


class UpdateQuestionAnswerRet(BaseModel):
    question_id: int
    attempt: int
    first_correct: bool
    last_correct: bool


class UpdateBatchQuestionAnswerRet(BaseModel):
    question_ids: list[int]


class UpdateFileRetPage(BaseModel):
    page_id: int
    page_no: int
    text: str


class UpdateFileRet(BaseModel):
    file_id: int
    type: enums.FileType
    name: str
    pages: list[UpdateFileRetPage]


class InsertKeypointArgQuestion(BaseModel):
    question_no: int
    type: enums.QuestionType
    content: str


class InsertKeypointArg(BaseModel):
    page_id: int
    keypoint_no: int
    name: str
    questions: list[InsertKeypointArgQuestion]
