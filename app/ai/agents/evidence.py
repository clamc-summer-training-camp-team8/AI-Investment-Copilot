"""候选影响结果的引用、完整性和一致性校验。"""

from __future__ import annotations

import re
from contextlib import suppress
from datetime import datetime

from app.ai.agents.types import (
    AgentImpact,
    AgentRunResult,
    EvidenceConsistency,
    EvidenceGrade,
    EvidenceValidation,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_HIGH_AUTHORITY = ("cninfo", "巨潮", "sse", "上交所", "szse", "深交所", "gov", "政府")
_MEDIUM_AUTHORITY = ("company", "公司公告", "annual_report", "定期报告")


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _authority(source: str) -> float:
    normalized = source.lower()
    if any(item in normalized for item in _HIGH_AUTHORITY):
        return 1.0
    if any(item in normalized for item in _MEDIUM_AUTHORITY):
        return 0.8
    if source and source != "unknown":
        return 0.6
    return 0.4


def _transmission_score(payload: dict[str, object]) -> float:
    signal = payload.get("signal")
    if not isinstance(signal, dict):
        return 0.0
    path = str(signal.get("transmission_path") or "").strip()
    if not path or "待人工" in path or "无明确" in path:
        return 0.0
    links = max(path.count("→"), path.count("->"))
    return min(links / 3, 1.0)


class EvidenceAgent:
    """只校验证据边界，不写数据库，也不替换模型结论。"""

    @staticmethod
    def validate_impact(impact: AgentImpact) -> EvidenceValidation:
        payload = impact.outcome.payload
        allowed = {item.locator for item in impact.retrieval.items}
        event = payload.get("event")
        primary_locator = None
        if isinstance(event, dict) and event.get("evidence_locator"):
            primary_locator = str(event["evidence_locator"])
            allowed.add(primary_locator)
        citations = payload.get("citations")
        cited: list[str] = [primary_locator] if primary_locator else []
        if isinstance(citations, list):
            for citation in citations:
                if isinstance(citation, dict) and citation.get("locator"):
                    cited.append(str(citation["locator"]))
                elif isinstance(citation, str):
                    cited.append(citation)
        missing = sorted(set(cited) - allowed)
        unsupported = payload.get("unsupported_claims")
        unsupported_claims = (
            tuple(str(item) for item in unsupported) if isinstance(unsupported, list) else ()
        )
        valid = bool(cited) and not missing and not unsupported_claims
        signal = payload.get("signal")
        model_requires_review = not isinstance(signal, dict) or bool(
            signal.get("requires_human_review", True)
        )
        return EvidenceValidation(
            valid=valid,
            cited_locators=tuple(dict.fromkeys(cited)),
            missing_locators=tuple(missing),
            unsupported_claims=unsupported_claims,
            requires_human_review=(
                model_requires_review or not valid or impact.outcome.ai_status.value != "候选"
            ),
        )

    @staticmethod
    def validate_thesis_citations(
        payload: dict[str, object],
        *,
        allowed_locators: set[str],
    ) -> EvidenceValidation:
        citations = payload.get("citations")
        cited = (
            tuple(str(item) for item in citations if isinstance(item, str))
            if isinstance(citations, list)
            else ()
        )
        missing = tuple(sorted(set(cited) - allowed_locators))
        unsupported = payload.get("unsupported_claims")
        unsupported_claims = (
            tuple(str(item) for item in unsupported) if isinstance(unsupported, list) else ()
        )
        requires_citation = bool(allowed_locators)
        valid = (
            (bool(cited) if requires_citation else True) and not missing and not unsupported_claims
        )
        return EvidenceValidation(
            valid=valid,
            cited_locators=cited,
            missing_locators=missing,
            unsupported_claims=unsupported_claims,
            requires_human_review=not valid,
        )

    @staticmethod
    def check_consistency(impact: AgentImpact) -> EvidenceConsistency:
        payload = impact.outcome.payload
        validation = EvidenceAgent.validate_impact(impact)
        reasons: list[str] = []
        security_id = str(payload.get("security_id") or "")
        entity_matched = bool(security_id) and any(
            chunk.security_id == security_id for chunk in impact.retrieval.items
        )
        if not entity_matched:
            reasons.append("entity_mismatch")
        event = payload.get("event")
        fact = str(event.get("fact") or "") if isinstance(event, dict) else ""
        cited = set(validation.cited_locators)
        cited_text = " ".join(
            item.content for item in impact.retrieval.items if item.locator in cited
        )
        fact_tokens = _tokens(fact)
        context_tokens = _tokens(cited_text)
        overlap = len(fact_tokens & context_tokens)
        fact_supported = not fact or (overlap >= 2 and overlap / max(len(fact_tokens), 1) >= 0.4)
        if not fact_supported:
            reasons.append("fact_not_supported")
        positive = any(cue in cited_text or cue in fact for cue in ("增长", "提升", "改善", "增加"))
        negative = any(cue in cited_text or cue in fact for cue in ("下降", "压力", "风险", "减少"))
        conflicting = positive and negative
        if conflicting:
            reasons.append("conflicting_evidence")
        return EvidenceConsistency(entity_matched, fact_supported, conflicting, tuple(reasons))

    @staticmethod
    def grade_impact(impact: AgentImpact, *, max_age_days: int = 180) -> EvidenceGrade:
        """为候选影响结果计算可解释的证据完整性分数。"""
        validation = EvidenceAgent.validate_impact(impact)
        cited = set(validation.cited_locators)
        valid_cited = cited - set(validation.missing_locators)
        cited_chunks = [item for item in impact.retrieval.items if item.locator in valid_cited]
        sources = {item.source for item in cited_chunks}
        disclosure_time = None
        event = impact.outcome.payload.get("event")
        if isinstance(event, dict) and event.get("disclosure_time"):
            with suppress(ValueError):
                disclosure_time = datetime.fromisoformat(str(event["disclosure_time"]))
        stale_count = 0
        if disclosure_time is not None:
            for item in cited_chunks:
                if (disclosure_time - item.published_at).days > max_age_days:
                    stale_count += 1
        missing = list(validation.missing_locators)
        if not validation.cited_locators:
            missing.append("citations")
        if validation.unsupported_claims:
            missing.append("unsupported_claims")
        citation_score = len(valid_cited) / max(len(cited), 1)
        authority_score = (
            sum(_authority(item.source) for item in cited_chunks) / len(cited_chunks)
            if cited_chunks
            else 0.0
        )
        freshness_score = 1 - stale_count / len(cited_chunks) if cited_chunks else 0.0
        event_fact = str(event.get("fact") or "") if isinstance(event, dict) else ""
        fact_tokens = _tokens(event_fact)
        cited_tokens = _tokens(" ".join(item.content for item in cited_chunks))
        claim_support_score = (
            len(fact_tokens & cited_tokens) / len(fact_tokens) if fact_tokens else 1.0
        )
        corroboration_score = min(
            max(len(sources), len({item.document_id for item in cited_chunks})) / 2,
            1.0,
        )
        transmission_score = _transmission_score(impact.outcome.payload)
        score = round(
            0.30 * citation_score
            + 0.15 * authority_score
            + 0.15 * freshness_score
            + 0.20 * claim_support_score
            + 0.10 * corroboration_score
            + 0.10 * transmission_score,
            3,
        )
        consistency = EvidenceAgent.check_consistency(impact)
        return EvidenceGrade(
            score=score,
            passed=(
                not missing
                and score >= 0.7
                and claim_support_score >= 0.4
                and not consistency.conflicting
            ),
            cited_count=len(cited),
            valid_cited_count=len(valid_cited),
            source_count=len(sources),
            stale_count=stale_count,
            missing=tuple(sorted(set(missing))),
            citation_score=round(citation_score, 3),
            source_authority_score=round(authority_score, 3),
            freshness_score=round(freshness_score, 3),
            claim_support_score=round(claim_support_score, 3),
            corroboration_score=round(corroboration_score, 3),
            transmission_score=round(transmission_score, 3),
        )

    @staticmethod
    def validate_run(result: AgentRunResult) -> list[EvidenceValidation]:
        return [EvidenceAgent.validate_impact(impact) for impact in result.impacts]
