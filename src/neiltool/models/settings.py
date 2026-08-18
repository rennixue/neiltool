import os
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

StrPath = str | os.PathLike[str]


class OperationError(Exception):
    def __init__(self, msg: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.data = data or {}


class AgentSettings(BaseModel):
    api_key: str
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    concurrency: int = 10
    models: dict[str, str]


class GotenbergSettings(BaseModel):
    base_url: str
    use_auth: bool = False
    username: str = ""
    password: str = ""

    @model_validator(mode="after")
    def validate_auth(self) -> Self:
        if self.use_auth:
            if not self.username or not self.password:
                raise ValueError("Both username and password must not be empty if use_auth is true.")
        return self


class LlamacloudSettings(BaseModel):
    api_key: str
    concurrency: int = 10


class MoonshotSettings(BaseModel):
    api_key: str
    base_url: str = "https://api.moonshot.cn/v1"
    concurrency: int = 10


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_nested_delimiter="_", env_nested_max_split=1)

    daobi_database_url: str
    database_url: str
    doc2txt: AgentSettings
    gotenberg: GotenbergSettings
    llamacloud: LlamacloudSettings
    moonshot: MoonshotSettings
    base_url: HttpUrl
    static_dir: Path
    static_url: HttpUrl
    tmp_dir: Path
    volcengine: AgentSettings
