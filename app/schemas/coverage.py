"""行业总览（本地板块/公司覆盖目录）API 契约。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CoverageSectorIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128)
    code: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=500)


class CoverageSectorUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128)


class CoverageCompanyIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    security_id: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    ticker: str | None = Field(default=None, max_length=32)
    industry: str | None = Field(default=None, max_length=128)
    market: str | None = Field(default=None, max_length=32)
    owner: str | None = Field(default=None, max_length=64)


class CoverageCompanyUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: str | None = Field(default=None, max_length=16)
    owner: str | None = Field(default=None, max_length=64)


class CoverageCompanyOut(BaseModel):
    coverage_company_id: str
    sector_id: str
    security_id: str
    name: str
    ticker: str | None = None
    industry: str | None = None
    market: str | None = None
    owner: str
    status: str
    thesis_id: str | None = None
    thesis_title: str | None = None
    thesis_status: str | None = None
    thesis_count: int = 0
    hypothesis_count: int = 0
    configured_metric_count: int = 0
    updated_at: datetime | None = None


class CoverageSectorOut(BaseModel):
    sector_id: str
    name: str
    code: str | None = None
    description: str | None = None
    status: str
    companies: list[CoverageCompanyOut] = Field(default_factory=list)
