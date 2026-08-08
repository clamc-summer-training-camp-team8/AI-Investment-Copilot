"""解析结果的公共数据结构。

解析层只产出文本与定位，不调模型（`.importlinter` 强制 app.ingest 不得 import
app.ai）。理由：解析必须确定性，同一份文件两次解析要得到相同结果，否则
parser_version 失去意义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

PARSER_VERSION = "v1"


class ParseError(Exception):
    """解析失败。

    调用方必须保留原文件并记录原因（PRD 7.4：保留文件，展示失败原因，允许重新
    上传或转为文本）。不允许删除原文件。
    """

    def __init__(self, reason: str, *, recoverable: bool = True) -> None:
        super().__init__(reason)
        self.reason = reason
        self.recoverable = recoverable


@dataclass(frozen=True)
class RawSegment:
    """原始段落。locator 由切片阶段统一生成，这里只给序号与页码。"""

    ordinal: int
    content: str
    page: int | None = None


@dataclass(frozen=True)
class ParsedDocument:
    """一份文档的解析结果。

    published_at 允许为 None，但调用方在入库前必须补齐：DQ-001 规定该字段为空是
    阻断级错误，且**不允许用入库时间兜底**——用入库时间填充会直接造成未来信息
    泄露（ingest/README.md）。
    """

    title: str | None
    segments: list[RawSegment]
    published_at: datetime | None = None
    doc_type: str | None = None
    parser_version: str = PARSER_VERSION
    warnings: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(s.content for s in self.segments)
