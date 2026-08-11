"""候选影响结果的引用、完整性和一致性校验。"""

from __future__ import annotations

import re
from datetime import datetime

from app.ai.agents.types import (
    AgentImpact,
    AgentRunResult,
    EvidenceConsistency,
    EvidenceGrade,
    EvidenceValidation,
)


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
    def check_consistency(impact: AgentImpact) -> EvidenceConsistency:
        payload = impact.outcome.payload
        reasons: list[str] = []
        security_id = str(payload.get("security_id") or "")
        entity_matched = bool(security_id) and any(
            chunk.security_id == security_id for chunk in impact.retrieval.items
        )
        if not entity_matched:
            reasons.append("entity_mismatch")
        event = payload.get("event")
        fact = str(event.get("fact") or "") if isinstance(event, dict) else ""
        cited = {item.locator for item in impact.retrieval.items}
        cited_text = " ".join(
            item.content for item in impact.retrieval.items if item.locator in cited
        )
        fact_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", fact))
        context_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", cited_text))
        fact_supported = not fact or len(fact_tokens & context_tokens) >= 2
        if not fact_supported:
            reasons.append("fact_not_supported")
        positive = any(
            cue in cited_text or cue in fact for cue in ("增长", "提升", "改善", "增加")
        )
        negative = any(
            cue in cited_text or cue in fact for cue in ("下降", "压力", "风险", "减少")
        )
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
        sources = {
            item.source for item in impact.retrieval.items if item.locator in valid_cited
        }
        disclosure_time = None
        event = impact.outcome.payload.get("event")
        if isinstance(event, dict) and event.get("disclosure_time"):
            try:
                disclosure_time = datetime.fromisoformat(str(event["disclosure_time"]))
            except ValueError:
                pass
        stale_count = 0
        if disclosure_time is not None:
            for item in impact.retrieval.items:
                if (
                    item.locator in valid_cited
                    and (disclosure_time - item.published_at).days > max_age_days
                ):
                    stale_count += 1
        missing = list(validation.missing_locators)
        if not validation.cited_locators:
            missing.append("citations")
        if validation.unsupported_claims:
            missing.append("unsupported_claims")
        citation_score = min(len(valid_cited) / 2, 1.0)
        source_score = min(len(sources) / 2, 1.0)
        freshness_score = 0.0 if stale_count else 1.0
        score = round(0.6 * citation_score + 0.2 * source_score + 0.2 * freshness_score, 3)
        return EvidenceGrade(
            score=score,
            passed=not missing and score >= 0.6,
            cited_count=len(cited),
            valid_cited_count=len(valid_cited),
            source_count=len(sources),
            stale_count=stale_count,
            missing=tuple(sorted(set(missing))),
        )

    @staticmethod
    def validate_run(result: AgentRunResult) -> list[EvidenceValidation]:
        return [EvidenceAgent.validate_impact(impact) for impact in result.impacts]
