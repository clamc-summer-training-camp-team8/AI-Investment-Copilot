"""Deterministic semantic chunking used by historical asset reprocessing."""

from __future__ import annotations

import re

from app.ingest.segmentation import Segment, build_locator

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])\s*")


def semantic_chunks(
    document_id: str,
    text: str,
    *,
    max_chars: int = 800,
    min_chars: int = 80,
) -> list[Segment]:
    """Build bounded, sentence-aligned chunks without overwriting canonical segments."""
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n|\r?\n", text):
        normalized = re.sub(r"\s+", " ", paragraph).strip()
        if not normalized:
            continue
        units.extend(part for part in _SENTENCE_BOUNDARY.split(normalized) if part)
    chunks: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                unit[index : index + max_chars] for index in range(0, len(unit), max_chars)
            )
            continue
        candidate = f"{current}{unit}" if current else unit
        if current and len(candidate) > max_chars and len(current) >= min_chars:
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        if chunks and len(current) < min_chars and len(chunks[-1]) + len(current) <= max_chars:
            chunks[-1] += current
        else:
            chunks.append(current)
    return [
        Segment(
            document_id=document_id,
            locator=build_locator(document_id, ordinal),
            ordinal=ordinal,
            content=content,
            content_kind="semantic",
            extraction_method="body_snapshot",
        )
        for ordinal, content in enumerate(chunks, start=1)
    ]
