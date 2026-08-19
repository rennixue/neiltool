import enum
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import (
    TEXT,
    VARCHAR,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    select,
    text,
    update,
)
from sqlalchemy.dialects.mysql.types import MEDIUMTEXT
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload, undefer

from .models import dtos, enums

logger = logging.getLogger(__name__)


class Base(AsyncAttrs, DeclarativeBase):
    pass


def values_callable(enum_type: type[enum.Enum]) -> list[Any]:
    return [it.value for it in enum_type]


class JobRecord(Base):
    __tablename__ = "beike_job"
    __table_args__ = {"mysql_default_charset": "utf8mb4"}

    job_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
    type: Mapped[enums.JobType] = mapped_column(Enum(enums.JobType, values_callable=values_callable))
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    classroom_id: Mapped[int | None] = mapped_column(Integer, index=True)
    teacher_msg: Mapped[str | None] = mapped_column(TEXT)
    status: Mapped[enums.JobStatus] = mapped_column(
        Enum(enums.JobStatus, values_callable=values_callable), server_default=text("'pend'")
    )
    err_msg: Mapped[str | None] = mapped_column(VARCHAR(255))
    priv_msg: Mapped[str | None] = mapped_column(TEXT, deferred=True)

    files: Mapped[list["FileRecord"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    materials: Mapped[list["MaterialRecord"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class FileRecord(Base):
    __tablename__ = "beike_file"
    __table_args__ = {"mysql_default_charset": "utf8mb4"}

    file_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("beike_job.job_id", ondelete="cascade"))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
    type: Mapped[enums.FileType] = mapped_column(Enum(enums.FileType, values_callable=values_callable))
    ident: Mapped[str | None] = mapped_column(VARCHAR(255))
    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[enums.FileStatus] = mapped_column(
        Enum(enums.FileStatus, values_callable=values_callable), server_default=text("'pend'")
    )
    err_msg: Mapped[str | None] = mapped_column(VARCHAR(255))
    priv_msg: Mapped[str | None] = mapped_column(TEXT, deferred=True)

    job: Mapped["JobRecord"] = relationship(back_populates="files")
    pages: Mapped[list["PageRecord"]] = relationship(back_populates="file", cascade="all, delete-orphan")


class PageRecord(Base):
    __tablename__ = "beike_page"
    __table_args__ = {"mysql_default_charset": "utf8mb4"}

    page_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("beike_file.file_id", ondelete="cascade"))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
    page_no: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str | None] = mapped_column(MEDIUMTEXT, deferred=True)

    file: Mapped["FileRecord"] = relationship(back_populates="pages")
    keypoints: Mapped[list["KeypointRecord"]] = relationship(back_populates="page", cascade="all, delete-orphan")


class KeypointRecord(Base):
    __tablename__ = "beike_keypoint"
    __table_args__ = {"mysql_default_charset": "utf8mb4"}

    keypoint_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("beike_page.page_id", ondelete="cascade"))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
    keypoint_no: Mapped[int] = mapped_column(SmallInteger)
    name: Mapped[str] = mapped_column(Text)

    page: Mapped["PageRecord"] = relationship(back_populates="keypoints")
    questions: Mapped[list["QuestionRecord"]] = relationship(back_populates="keypoint", cascade="all, delete-orphan")


class QuestionRecord(Base):
    __tablename__ = "beike_question"
    __table_args__ = {"mysql_default_charset": "utf8mb4"}

    question_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    keypoint_id: Mapped[int] = mapped_column(ForeignKey("beike_keypoint.keypoint_id", ondelete="cascade"))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
    question_no: Mapped[int] = mapped_column(SmallInteger)
    type: Mapped[enums.QuestionType] = mapped_column(Enum(enums.QuestionType, values_callable=values_callable))
    content: Mapped[str] = mapped_column(MEDIUMTEXT)
    attempt: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    first_correct: Mapped[bool | None] = mapped_column(Boolean)
    last_correct: Mapped[bool | None] = mapped_column(Boolean)

    keypoint: Mapped["KeypointRecord"] = relationship(back_populates="questions")


class MaterialRecord(Base):
    __tablename__ = "beike_material"
    __table_args__ = {"mysql_default_charset": "utf8mb4"}

    material_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("beike_job.job_id", ondelete="cascade"))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
    type: Mapped[enums.MaterialType] = mapped_column(Enum(enums.MaterialType, values_callable=values_callable))
    name: Mapped[str] = mapped_column(Text)
    tmp_url: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(MEDIUMTEXT, deferred=True)

    job: Mapped["JobRecord"] = relationship(back_populates="materials")


class QuestionRecordChoiceContent(BaseModel):
    stem: str
    options: list[str]
    solution: str
    answer: str


class Database:
    def __init__(self, url: str) -> None:
        self._engine = create_async_engine(url, pool_size=2, pool_recycle=600)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def is_healthy(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                cursor = await conn.execute(text("SELECT 1"))
                assert cursor.scalar_one() == 1
        except Exception as exc:
            logger.error("fail to connect to database: %r", exc)
            return False
        else:
            return True

    async def metadata_create_all(self) -> None:
        async with self._engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def insert_job(
        self,
        type_: enums.JobType,
        order_id: int,
        classroom_id: int | None,
        teacher_msg: str | None,
        files: Sequence[dtos.InsertJobArgFile],
    ) -> dtos.InsertJobRet:
        async with self._session_factory() as session:
            job = JobRecord(
                type=type_,
                order_id=order_id,
                classroom_id=classroom_id,
                teacher_msg=teacher_msg,
                files=[FileRecord(type=file.type, ident=file.ident, name=file.name, url=file.url) for file in files],
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_files: list[FileRecord] = await job.awaitable_attrs.files
        return dtos.InsertJobRet(
            job_id=job.job_id,
            type=job.type,
            order_id=job.order_id,
            status=job.status,
            teacher_msg=teacher_msg,
            files=[
                dtos.InsertJobRetFile(
                    file_id=file.file_id,
                    type=file.type,
                    ident=file.ident,
                    name=file.name,
                    url=file.url,
                    status=file.status,
                )
                for file in job_files
            ],
        )

    async def select_job_status(self, job_id: int) -> dtos.SelectJobStatusRet | None:
        async with self._session_factory() as session:
            result = await session.execute(select(JobRecord.status).where(JobRecord.job_id == job_id))
            status = result.scalar_one_or_none()
            if status is None:
                return None
        return dtos.SelectJobStatusRet(job_id=job_id, status=status)

    async def select_job_result(self, job_id: int) -> dtos.SelectJobResultRet | None:
        async with self._session_factory() as session:
            job = await session.get(
                JobRecord, job_id, options=[selectinload(JobRecord.materials), selectinload(JobRecord.files)]
            )
            if job is None:
                return
            if job.status == enums.JobStatus.Succeed:
                materials = job.materials
                files = job.files
                tutor_files = [it for it in files if it.type == enums.FileType.Tutor]
                if len(tutor_files) == 1:
                    result = await session.execute(
                        select(FileRecord)
                        .where(FileRecord.file_id == tutor_files[0].file_id)
                        .options(
                            selectinload(FileRecord.pages)
                            .selectinload(PageRecord.keypoints)
                            .selectinload(KeypointRecord.questions)
                        )
                    )
                    file = result.scalar_one()
                    pages: list[dtos.SelectJobResultRetPage] = []
                    for page in file.pages:
                        keypoints: list[dtos.SelectJobResultRetKeypoint] = []
                        for keypoint in page.keypoints:
                            questions: list[dtos.SelectJobResultRetQuestionChoice] = []
                            for question in keypoint.questions:
                                type_ = question.type
                                match type_:
                                    case enums.QuestionType.Choice:
                                        try:
                                            content_model = QuestionRecordChoiceContent.model_validate_json(
                                                question.content
                                            )
                                        except ValidationError:
                                            logger.warning(
                                                f"select_job_result: question type {type_!r} content invalid"
                                            )
                                            continue
                                        dto_question = dtos.SelectJobResultRetQuestionChoice(
                                            type=type_,
                                            question_id=question.question_id,
                                            stem=content_model.stem,
                                            options=content_model.options,
                                            solution=content_model.solution,
                                            answer=content_model.answer,
                                        )
                                questions.append(dto_question)
                            keypoints.append(
                                dtos.SelectJobResultRetKeypoint(
                                    keypoint_id=keypoint.keypoint_id, name=keypoint.name, questions=questions
                                )
                            )
                        pages.append(dtos.SelectJobResultRetPage(page_no=page.page_no, keypoints=keypoints))
                else:
                    logger.warning(f"select_job_result: {len(tutor_files)} tutor files")
                    pages = []
            else:
                materials = []
                pages = []
        pages.sort(key=lambda it: it.page_no)
        return dtos.SelectJobResultRet(
            job_id=job_id,
            status=job.status,
            type=job.type,
            err_msg=job.err_msg,
            materials=[
                dtos.SelectJobResultRetMaterial(
                    type=it.type, material_id=it.material_id, name=it.name, tmp_url=it.tmp_url
                )
                for it in materials
            ],
            pages=pages,
        )

    async def update_job_classroom_id(
        self, job_id: int, classroom_id: int | None
    ) -> dtos.UpdateJobClassroomIdRet | None:
        async with self._session_factory() as session:
            job = await session.get(JobRecord, job_id)
            if job is None:
                return None
            job.classroom_id = classroom_id
            session.add(job)
            await session.commit()
        return dtos.UpdateJobClassroomIdRet(job_id=job_id, classroom_id=classroom_id)

    async def select_material(self, material_id: int) -> dtos.SelectMaterialRet | None:
        async with self._session_factory() as session:
            material = await session.get(MaterialRecord, material_id, options=[undefer(MaterialRecord.text)])
            if material is None:
                return None
        return dtos.SelectMaterialRet(
            material_id=material.material_id,
            job_id=material.job_id,
            type=material.type,
            name=material.name,
            tmp_url=material.tmp_url,
            url=material.url,
            text=material.text,
        )

    async def update_material_url(self, material_id: int, url: str) -> dtos.UpdateMaterialUrlRet | None:
        async with self._session_factory() as session:
            material = await session.get(MaterialRecord, material_id)
            if material is None:
                return None
            material.url = url
            session.add(material)
            await session.commit()
        return dtos.UpdateMaterialUrlRet(material_id=material_id, url=url)

    async def update_question_answer(self, question_id: int, is_correct: bool) -> dtos.UpdateQuestionAnswerRet | None:
        async with self._session_factory() as session:
            question = await session.get(QuestionRecord, question_id)
            if question is None:
                return None
            await session.execute(
                update(QuestionRecord)
                .where(QuestionRecord.question_id == question_id)
                .values(attempt=QuestionRecord.attempt + 1)
            )
            await session.refresh(question, ["attempt"])
            if question.attempt == 1:
                question.first_correct = is_correct
            question.last_correct = is_correct
            session.add(question)
            await session.commit()
        if question.first_correct is None:
            logger.warning("update_question_answer: question.first_correct is null")
            first_correct = is_correct
        else:
            first_correct = question.first_correct
        return dtos.UpdateQuestionAnswerRet(
            question_id=question_id,
            attempt=question.attempt,
            first_correct=first_correct,
            last_correct=is_correct,
        )

    async def update_batch_question_answer(self, pairs: list[tuple[int, bool]]) -> dtos.UpdateBatchQuestionAnswerRet:
        question_ids: list[int] = []
        async with self._session_factory() as session:
            # usually few questions
            for question_id, is_correct in pairs:
                question = await session.get(QuestionRecord, question_id)
                if question is None:
                    continue
                await session.execute(
                    update(QuestionRecord)
                    .where(QuestionRecord.question_id == question_id)
                    .values(attempt=QuestionRecord.attempt + 1)
                )
                await session.refresh(question, ["attempt"])
                if question.attempt == 1:
                    question.first_correct = is_correct
                question.last_correct = is_correct
                session.add(question)
                question_ids.append(question_id)
            await session.commit()
        return dtos.UpdateBatchQuestionAnswerRet(question_ids=question_ids)

    async def update_job_succeed(self, job_id: int) -> None:
        async with self._session_factory() as session:
            job = await session.get(JobRecord, job_id)
            if job is None:
                return None
            job.status = enums.JobStatus.Succeed
            session.add(job)
            await session.commit()

    async def update_job_fail(self, job_id: int, err_msg: str, priv_msg: str | None) -> None:
        async with self._session_factory() as session:
            job = await session.get(JobRecord, job_id)
            if job is None:
                return None
            job.status = enums.JobStatus.Fail
            job.err_msg = err_msg
            if priv_msg:
                job.priv_msg = priv_msg
            session.add(job)
            await session.commit()

    async def update_file_succeed(self, file_id: int, texts: Sequence[str]) -> dtos.UpdateFileRet | None:
        async with self._session_factory() as session:
            file = await session.get(FileRecord, file_id)
            if file is None:
                return None
            file.status = enums.FileStatus.Succeed
            session.add_all(
                [PageRecord(file_id=file_id, page_no=page_no, text=text_) for page_no, text_ in enumerate(texts, 1)]
            )
            session.add(file)
            await session.commit()
            await session.refresh(file)
            result = await session.execute(
                select(PageRecord).where(PageRecord.file_id == file_id).order_by(PageRecord.page_no)
            )
            file_pages = result.scalars()
        dto_pages: list[dtos.UpdateFileRetPage] = []
        for file_page in file_pages:
            page_no = file_page.page_no
            if page_no >= 1 and page_no <= len(texts):
                dto_pages.append(
                    dtos.UpdateFileRetPage(page_id=file_page.page_id, page_no=page_no, text=texts[page_no - 1])
                )
        return dtos.UpdateFileRet(file_id=file_id, type=file.type, name=file.name, pages=dto_pages)

    async def update_file_fail(self, file_id: int, err_msg: str, priv_msg: str | None) -> None:
        async with self._session_factory() as session:
            file = await session.get(FileRecord, file_id)
            if file is None:
                return None
            file.status = enums.FileStatus.Fail
            file.err_msg = err_msg
            if priv_msg:
                file.priv_msg = priv_msg
            session.add(file)
            await session.commit()

    async def insert_material(
        self, job_id: int, type_: enums.MaterialType, name: str, tmp_url: str | None, text_: str
    ) -> int:
        async with self._session_factory() as session:
            material = MaterialRecord(job_id=job_id, type=type_, name=name, tmp_url=tmp_url, text=text_)
            session.add(material)
            await session.commit()
            await session.refresh(material)
        return material.material_id

    async def update_material_tmp_url(self, material_id: int, tmp_url: str | None) -> None:
        async with self._session_factory() as session:
            material = await session.get(MaterialRecord, material_id)
            if material is None:
                return None
            material.tmp_url = tmp_url
            session.add(material)
            await session.commit()

    async def insert_keypoints(self, keypoints: Sequence[dtos.InsertKeypointArg]) -> None:
        async with self._session_factory() as session:
            for dto_keypoint in keypoints:
                keypoint = KeypointRecord(
                    page_id=dto_keypoint.page_id,
                    keypoint_no=dto_keypoint.keypoint_no,
                    name=dto_keypoint.name,
                    questions=[
                        QuestionRecord(
                            question_no=dto_question.question_no,
                            type=dto_question.type,
                            content=dto_question.content,
                        )
                        for dto_question in dto_keypoint.questions
                    ],
                )
                session.add(keypoint)
            await session.commit()
