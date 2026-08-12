"""Deterministic embedding baseline used by the first local RAG pilot.

The default model is deliberately dependency-free and reproducible: character
unigrams/bigrams and ASCII word tokens are feature-hashed into a normalized
256-dimensional vector.  It is a retrieval baseline, not a claim of general
semantic understanding.  A production embedding model must use a new version
identifier so results remain comparable and old vectors remain reproducible.
"""

from __future__ import annotations

import math
import re
from hashlib import blake2b

EMBEDDING_DIMENSIONS = 256
LOCAL_EMBEDDING_VERSION = "hash-char-2gram-v1"


def embed_text(text: str, *, version: str = LOCAL_EMBEDDING_VERSION) -> list[float]:
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
