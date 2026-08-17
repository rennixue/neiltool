import enum


class JobType(enum.StrEnum):
    Intro = "intro"
    Regular = "regular"


class JobStatus(enum.StrEnum):
    Pend = "pend"
    Succeed = "succeed"
    Fail = "fail"


class FileType(enum.StrEnum):
    Tutor = "tutor"
    Syllabus = "syllabus"


class FileStatus(enum.StrEnum):
    Pend = "pend"
    Succeed = "succeed"
    Fail = "fail"


class QuestionType(enum.StrEnum):
    Choice = "choice"


class MaterialType(enum.StrEnum):
    Slide = "slide"
    Outline = "outline"
    Revision = "revision"
