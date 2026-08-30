from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankingProfile:
    name: str
    keyword_weight: float
    vector_weight: float
    graph_weight: float
    prior_weight: float
    minimum_relevance: float = 0.01

    @property
    def relevance_weight(self) -> float:
        return 1.0 - self.prior_weight


_PROFILES = {
    "document_search": RankingProfile("document_search", 0.45, 0.55, 0.0, 0.10),
    "hypothesis_match": RankingProfile("hypothesis_match", 0.35, 0.65, 0.0, 0.25),
    # The local baseline uses a character-hash embedding.  Give Chinese literal
    # overlap equal weight so official fact slices are not buried by title noise.
    "primary_context": RankingProfile("primary_context", 0.80, 0.20, 0.0, 0.40),
    "knowledge_browse": RankingProfile(
        "knowledge_browse", 0.20, 0.80, 0.0, 0.70, minimum_relevance=0.0
    ),
}


def get_profile(name: str) -> RankingProfile:
    try:
        return _PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"未知排序 Profile: {name}") from exc


def profile_names() -> tuple[str, ...]:
    return tuple(_PROFILES)
