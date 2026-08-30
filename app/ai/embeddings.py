"""第一版本地 RAG 使用的确定性向量基线。

默认实现没有额外依赖且可复算：把字符 unigram、bigram 和 ASCII 单词特征哈希到
256 维归一化向量。它只是检索基线，不代表通用语义理解能力。生产向量模型必须使用
新的版本号，确保历史向量仍可复算且评测结果可以比较。
"""

from __future__ import annotations

import math
import re
from hashlib import blake2b

EMBEDDING_DIMENSIONS = 256
LOCAL_EMBEDDING_VERSION = "hash-char-2gram-v1"


def embed_text(text: str, *, version: str = LOCAL_EMBEDDING_VERSION) -> list[float]:
    """按指定版本生成归一化向量，不支持时显式拒绝。"""
    if version != LOCAL_EMBEDDING_VERSION:
        raise ValueError(f"本地 embedding 不支持版本 {version!r}")
    normalized = "".join(text.lower().split())
    words = re.findall(r"[a-z0-9]+", text.lower())
    features = list(normalized) + [normalized[i : i + 2] for i in range(len(normalized) - 1)]
    features.extend(words)
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for feature in features:
        digest = blake2b(feature.encode("utf-8"), digest_size=8, person=b"copilot-v1").digest()
        number = int.from_bytes(digest, "big")
        index = number % EMBEDDING_DIMENSIONS
        vector[index] += -1.0 if number & (1 << 63) else 1.0
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude:
        vector = [value / magnitude for value in vector]
    return vector
