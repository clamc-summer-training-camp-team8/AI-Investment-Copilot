from __future__ import annotations

import math

import pytest

from app.ai.embeddings import EMBEDDING_DIMENSIONS, embed_text


def test_hash_embedding_is_deterministic_and_normalized() -> None:
    first = embed_text("营业收入同比增长 30%")
    second = embed_text("营业收入同比增长 30%")
    assert first == second
    assert len(first) == EMBEDDING_DIMENSIONS
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)


def test_hash_embedding_rejects_unversioned_model_change() -> None:
    with pytest.raises(ValueError, match="不支持版本"):
        embed_text("测试", version="unknown-v2")
