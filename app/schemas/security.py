"""证券主数据 API 契约。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class SecurityIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    security_id: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    ticker: str | None = Field(default=None, max_length=32)
    industry: str | None = Field(default=None, max_length=128)
    aliases: list[str] = Field(default_factory=list, max_length=20)


class SecurityOut(BaseModel):
    security_id: str
    name: str
    ticker: str | None = None
    industry: str | None = None
    aliases: list[str] = Field(default_factory=list)
