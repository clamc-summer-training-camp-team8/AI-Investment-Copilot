"""从公告正文抽取最小可复算事实。

P0 只覆盖独立盲标已经证明最影响方向判断的两类同比变化：营业收入与销量/交付量。
这里不调用模型，也不直接生成投资证据；抽取结果只是带原文定位的候选事实。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from app.ingest.segmentation import Segment

EXTRACTION_VERSION = "body-facts-v1"

_METRICS: tuple[tuple[str, str, str], ...] = (
    ("营业收入同比", "revenue_yoy", r"(?:营业收入|营收|海外收入)"),
    ("销量/交付量同比", "delivery_yoy", r"(?:销量|销售量|交付量|交付|产量)"),
)
_COMPARISON = r"(?:同比|比上年同期|较上年同期|较去年同期|较上年同月|较去年同月)"
_UP = r"(?:增长|增加|上升|提升|提高)"
_DOWN = r"(?:下降|减少|降低|下滑|同比减少)"
_NUMBER = r"(?P<first>[+-]?\d+(?:\.\d+)?)\s*%"
_RANGE = rf"{_NUMBER}(?:\s*(?:[-~～至到])\s*(?P<second>[+-]?\d+(?:\.\d+)?)\s*%)?"


@dataclass(frozen=True)
class ExtractedFact:
    fact_id: str
    document_id: str
    locator: str
    fact_type: str
    metric_name: str
    direction: str
    raw_text: str
    extraction_version: str
    change_rate_low: Decimal | None = None
    change_rate_high: Decimal | None = None


def _rate(raw: str) -> Decimal:
    return Decimal(raw) / Decimal("100")


def _fact_id(document_id: str, locator: str, fact_type: str, raw_text: str) -> str:
    digest = sha256(f"{document_id}|{locator}|{fact_type}|{raw_text}".encode()).hexdigest()[:24]
    return f"FACT-{digest}"


def _match(text: str, metric_pattern: str) -> tuple[str, Decimal, Decimal] | None:
    directional = re.search(
        rf"{metric_pattern}.{{0,160}}?{_COMPARISON}.{{0,50}}?"
        rf"(?P<direction>{_UP}|{_DOWN}).{{0,12}}?{_RANGE}",
        text,
    )
    if directional:
        values = [abs(_rate(directional.group("first")))]
        if directional.group("second"):
            values.append(abs(_rate(directional.group("second"))))
        direction = "增长" if re.fullmatch(_UP, directional.group("direction")) else "下降"
        return direction, min(values), max(values)

    signed = re.search(
        rf"{metric_pattern}.{{0,160}}?{_COMPARISON}.{{0,20}}?{_RANGE}",
        text,
    )
    if signed and signed.group("first").startswith(("+", "-")):
        signed_values = [_rate(signed.group("first"))]
        if signed.group("second"):
            signed_values.append(_rate(signed.group("second")))
        direction = "增长" if max(signed_values) > 0 else "下降"
        values = [abs(value) for value in signed_values]
        return direction, min(values), max(values)
    return None


def extract_key_facts(segments: list[Segment]) -> list[ExtractedFact]:
    """逐段抽取事实；同一段同一指标只保留一个可核验结果。"""
    facts: list[ExtractedFact] = []
    for segment in segments:
        normalized = re.sub(r"\s+", " ", segment.content).strip()
        for metric_name, fact_type, metric_pattern in _METRICS:
            matched = _match(normalized, metric_pattern)
            if matched is None:
                continue
            direction, low, high = matched
            facts.append(
                ExtractedFact(
                    fact_id=_fact_id(segment.document_id, segment.locator, fact_type, normalized),
                    document_id=segment.document_id,
                    locator=segment.locator,
                    fact_type=fact_type,
                    metric_name=metric_name,
                    direction=direction,
                    change_rate_low=low,
                    change_rate_high=high,
                    raw_text=normalized,
                    extraction_version=EXTRACTION_VERSION,
                )
            )
    return facts
