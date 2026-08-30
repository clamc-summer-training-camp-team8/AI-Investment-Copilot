"""local 提供者：规则实现，不外发任何数据。

这是默认提供者（`settings.llm_provider == "local"`），存在两个理由：

1. **离线降级**：未配置外部端点时仍可运行确定性工作流，且不发出任何请求。
2. **工程**：其他模块开发与 CI 不依赖外部服务，闭环可以在 CI 里完整跑通。

它给出的是确定性的、可解释的抽取结果，不假装是模型。置信度按规则命中强度给，
不是随机数——随机置信度会让降级逻辑的测试变成碰运气。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.ai.prompts.templates import (
    EVENT_EXTRACTION,
    EVENT_IMPACT,
    HYPOTHESIS_QUALITY,
    METRIC_EXPLAIN,
    METRIC_RECOMMEND,
    REVIEW_DRAFT,
    THESIS_DRAFT,
)
from app.core.config import Settings
from app.core.enums import AiStatus, ImpactDirection, SignalDirection
from app.core.timeutil import now

# 判断影响方向的词表。命中数量决定置信度，规则透明可复算。
_NEGATIVE_CUES = (
    "下调",
    "低于",
    "调整为",
    "压力",
    "放缓",
    "下降",
    "收紧",
    "提高本地化",
    "谨慎",
)
_POSITIVE_CUES = ("增长", "高于", "新签", "改善", "超预期", "提升", "扩大")

_HYPOTHESIS_CUES: dict[str, tuple[str, ...]] = {
    "行业": ("装机", "需求", "行业", "政策", "补贴"),
    "经营": ("订单", "合同", "交付", "收入"),
    "盈利": ("毛利率", "成本", "利润", "盈利"),
}


@dataclass(frozen=True)
class ImpactVerdict:
    """local 提供者对单条事件的判断。"""

    signal_direction: SignalDirection
    impact_direction: ImpactDirection
    strength: float
    confidence: float
    rationale: str
    transmission_path: str


def _count(text: str, cues: tuple[str, ...]) -> int:
    return sum(1 for cue in cues if cue in text)


def judge_impact(text: str) -> ImpactVerdict:
    """按词表判断方向与强度。

    正负线索同时出现时返回不确定并给低置信——这类文本恰恰是最需要人看的，
    强行归类会制造错误的证据方向（标注规范 §4：证据冲突标记需人工复核，
    不得强制归类）。
    """
    negative = _count(text, _NEGATIVE_CUES)
    positive = _count(text, _POSITIVE_CUES)

    if negative and positive:
        return ImpactVerdict(
            signal_direction=SignalDirection.UNCERTAIN,
            impact_direction=ImpactDirection.NEUTRAL,
            strength=0.3,
            confidence=0.45,
            rationale="正负线索同时出现，方向存在争议，需人工判断",
            transmission_path="待人工确认",
        )
    if negative:
        strength = min(0.5 + 0.15 * negative, 0.9)
        return ImpactVerdict(
            signal_direction=SignalDirection.NEGATIVE,
            impact_direction=ImpactDirection.CONFLICT,
            strength=strength,
            confidence=min(0.6 + 0.1 * negative, 0.9),
            rationale=f"命中 {negative} 个负向线索",
            transmission_path="事件 → 关联假设的不利变化 → 需重估预期",
        )
    if positive:
        strength = min(0.5 + 0.15 * positive, 0.9)
        return ImpactVerdict(
            signal_direction=SignalDirection.POSITIVE,
            impact_direction=ImpactDirection.SUPPORT,
            strength=strength,
            confidence=min(0.6 + 0.1 * positive, 0.9),
            rationale=f"命中 {positive} 个正向线索",
            transmission_path="事件 → 关联假设的有利变化 → 维持预期",
        )
    return ImpactVerdict(
        signal_direction=SignalDirection.NEUTRAL,
        impact_direction=ImpactDirection.NEUTRAL,
        strength=0.2,
        confidence=0.5,
        rationale="未命中方向线索",
        transmission_path="无明确传导路径",
    )


def guess_hypothesis_type(text: str) -> str:
    best, best_hits = "其他", 0
    for htype, cues in _HYPOTHESIS_CUES.items():
        hits = _count(text, cues)
        if hits > best_hits:
            best, best_hits = htype, hits
    return best


class LocalProvider:
    """规则实现的模型网关。接口与 http 提供者一致，便于替换。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def model_version(self) -> str:
        return self._settings.llm_model_version

    @property
    def supports_repair(self) -> bool:
        return False

    def analyze_event_impact(
        self,
        *,
        document_id: str,
        security_id: str,
        segment_locator: str,
        segment_text: str,
        disclosure_time: str,
        candidates: list[dict[str, Any]],
        evidence_contexts: list[dict[str, Any]],
        event_type: str = "其他",
        occurred_on: str | None = None,
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """产出符合 contracts/ai/event_impact.schema.json 的载荷。"""
        # The deterministic provider deliberately ignores retrieval text.  It
        # keeps the pilot's execution contract testable without pretending a
        # lexical rule engine can consume semantic RAG context.
        _ = evidence_contexts, repair_errors
        verdict = judge_impact(segment_text)
        return {
            "document_id": document_id,
            "security_id": security_id,
            "event": {
                "event_type": event_type,
                "event_time": occurred_on,
                "disclosure_time": disclosure_time,
                "fact": segment_text[:500],
                "evidence_locator": segment_locator,
            },
            "impacts": [
                {
                    "thesis_id": str(candidate.get("thesis_id") or ""),
                    "hypothesis_id": str(candidate.get("hypothesis_id") or ""),
                    "relevance": "相关",
                    "inference": verdict.rationale,
                    "citations": [segment_locator],
                    "unsupported_claims": [],
                    "signal": {
                        "direction": verdict.signal_direction.value,
                        "impact_direction": verdict.impact_direction.value,
                        "strength": verdict.strength,
                        "confidence": verdict.confidence,
                        "horizon": "中期",
                        "rationale": verdict.rationale,
                        "transmission_path": verdict.transmission_path,
                        "suggested_tracking": _tracking_hints(segment_text),
                        "requires_human_review": True,
                    },
                }
                for candidate in candidates
            ],
            "model_version": self.model_version,
            "prompt_version": EVENT_IMPACT.version,
            "generated_at": now().isoformat(),
            "ai_status": AiStatus.CANDIDATE.value,
        }

    def analyze_event_impacts(
        self,
        *,
        document_id: str,
        security_id: str,
        events: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """本地测试提供者保持批量契约；仅在明确配置 local 时使用。"""
        results = []
        for event in events:
            analysis = self.analyze_event_impact(
                document_id=document_id,
                security_id=security_id,
                segment_locator=str(event["segment_locator"]),
                segment_text=str(event["segment_text"]),
                disclosure_time=str(event["disclosure_time"]),
                candidates=list(event["candidates"]),
                evidence_contexts=list(event["evidence_contexts"]),
                event_type=str(event.get("event_type") or "其他"),
                occurred_on=(str(event["occurred_on"]) if event.get("occurred_on") else None),
                repair_errors=repair_errors,
            )
            results.append({"event_id": str(event["event_id"]), "analysis": analysis})
        return {
            "results": results,
            "model_version": self.model_version,
            "prompt_version": f"{EVENT_IMPACT.version}-batch-v1",
            "generated_at": now().isoformat(),
            "ai_status": AiStatus.CANDIDATE.value,
        }

    def extract_events(
        self,
        *,
        document_id: str,
        segments: list[tuple[str, str]],
        disclosure_time: str,
    ) -> dict[str, Any]:
        """离线降级：复用确定性规则，但输出与结构化模型相同的契约。"""
        del disclosure_time
        events: list[dict[str, Any]] = []
        keywords = {
            "订单": ("订单", "中标", "合同"),
            "政策": ("政策", "补贴", "监管", "关税"),
            "管理层表述": ("管理层", "展望", "指引", "说明会"),
            "业绩": ("财报", "毛利率", "收入同比", "业绩"),
        }
        for locator, content in segments:
            normalized = content.strip()
            if re.fullmatch(r"(?:[^\n]{0,80})?(?:公告|报告|通知|说明书)", normalized):
                continue
            event_type = next(
                (kind for kind, cues in keywords.items() if any(cue in normalized for cue in cues)),
                "其他",
            )
            if event_type == "其他" and not re.search(r"\d+(?:\.\d+)?%?|\d+", normalized):
                continue
            events.append(
                {
                    "event_type": event_type,
                    "fact": normalized[:500],
                    "occurred_on": None,
                    "evidence_locator": locator,
                    "confidence": 0.65,
                    "security_mentions": [],
                }
            )
        return {
            "document_id": document_id,
            "events": events,
            "model_version": self.model_version,
            "prompt_version": EVENT_EXTRACTION.version,
            "generated_at": now().isoformat(),
            "ai_status": AiStatus.CANDIDATE.value,
        }

    def draft_thesis(
        self,
        *,
        security_id: str,
        view: str,
        segments: list[tuple[str, str]],
        source_document_id: str | None = None,
        investment_context: dict[str, Any] | None = None,
        industry_metrics: list[dict[str, Any]] | None = None,
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """从资料正文生成卡片草稿。

        标题与核心观点截断到 PRD 4.3 的 40 / 200 字上限。假设不足两条时补一条
        兜底观察项——Schema 要求至少两条，硬性凑数不如显式标注为待补充。
        """
        _ = investment_context, industry_metrics, repair_errors
        hypotheses = _extract_hypotheses(segments)
        return {
            "source_document_id": source_document_id,
            "security_id": security_id,
            "title": (view or segments[0][1] if segments else view)[:40],
            "direction": None,
            "core_view": (view or (segments[0][1] if segments else ""))[:200],
            "hypotheses": hypotheses,
            "risks": _extract_risks(segments),
            "invalidation_suggestions": _extract_invalidation(segments),
            "citations": [locator for locator, _ in segments],
            "unsupported_claims": [] if segments else ["无资料支撑，全部内容为用户输入"],
            "model_version": self.model_version,
            "prompt_version": THESIS_DRAFT.version,
            "generated_at": now().isoformat(),
            "ai_status": AiStatus.CANDIDATE.value,
            "confidence": 0.7 if len(hypotheses) >= 2 else 0.5,
        }

    def explain_metric(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        calc_result: dict[str, Any],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """解释程序结果，不重新计算或修正输入数值。"""
        verdict = str(calc_result.get("verdict") or calc_result.get("status") or "信息不足")
        summary = str(
            calc_result.get("display_text")
            or calc_result.get("summary")
            or json.dumps(calc_result, ensure_ascii=False, sort_keys=True)
            or "程序没有提供可解释结果"
        )
        return {
            "security_id": security_id,
            "hypothesis_id": hypothesis_id,
            "summary": summary[:500],
            "meaning": f"程序规则结论为“{verdict}”，需结合假设“{hypothesis}”人工判断。",
            "suggested_tracking": ["按相同口径跟踪下一报告期程序计算结果"],
            "calculation_source": "app.calc",
            "confidence": 0.8 if calc_result else 0.4,
            "model_version": self.model_version,
            "prompt_version": METRIC_EXPLAIN.version,
            "generated_at": now().isoformat(),
            "ai_status": AiStatus.CANDIDATE.value,
        }

    def recommend_metrics(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        industry: str,
        catalog_version: str,
        candidates: list[dict[str, Any]],
        top_k: int,
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """离线实现按工具召回分排序，保证目录约束和测试可复现。"""
        del industry, repair_errors
        selected = candidates[: max(1, min(top_k, 20))]
        recommendations: list[dict[str, Any]] = []
        for candidate in selected:
            reasons = candidate.get("matching_reasons") or []
            relation_type = str(candidate.get("relation_type") or "代理指标")
            score = float(candidate.get("retrieval_score") or 0)
            recommendations.append(
                {
                    "metric_id": str(candidate["metric_id"]),
                    "metric_version": str(candidate["metric_version"]),
                    "metric_name": str(candidate["metric_name"]),
                    "relation_type": relation_type,
                    "rationale": (
                        "；".join(str(item) for item in reasons)
                        or f"该指标可用于观察假设“{hypothesis}”中的相关变量"
                    ),
                    "expected_direction": candidate.get("expected_direction"),
                    "observation_frequency": str(candidate["observation_frequency"]),
                    "availability_grade": str(candidate["availability_grade"]),
                    "source_ids": [str(item) for item in candidate.get("source_ids") or []],
                    "threshold_policy": str(candidate["threshold_policy"]),
                    "confidence": min(0.9, max(0.55, 0.5 + score / 40)),
                }
            )
        confidence = (
            min(item["confidence"] for item in recommendations) if recommendations else 0.4
        )
        return {
            "security_id": security_id,
            "hypothesis_id": hypothesis_id,
            "catalog_version": catalog_version,
            "recommendations": recommendations,
            "unmatched_concepts": [] if recommendations else [hypothesis],
            "requires_human_review": True,
            "confidence": confidence,
            "model_version": self.model_version,
            "prompt_version": METRIC_RECOMMEND.version,
            "generated_at": now().isoformat(),
            "ai_status": AiStatus.CANDIDATE.value,
        }

    def draft_review(
        self,
        *,
        security_id: str,
        thesis_id: str,
        period_start: str,
        period_end: str,
        records: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """按输入记录生成复盘草稿，不补充外部事实。"""
        supporting: list[str] = []
        conflicting: list[str] = []
        open_questions: list[str] = []
        citations: list[str] = []
        for record in records:
            statement = str(
                record.get("fact") or record.get("summary") or record.get("title") or ""
            )
            direction = str(record.get("impact_direction") or record.get("direction") or "")
            if direction == ImpactDirection.SUPPORT.value and statement:
                supporting.append(statement[:300])
            elif direction == ImpactDirection.CONFLICT.value and statement:
                conflicting.append(statement[:300])
            elif statement:
                open_questions.append(statement[:300])
            locator = str(record.get("locator") or record.get("evidence_locator") or "")
            if re.fullmatch(r"[A-Za-z0-9_.-]+#paragraph-[0-9]+", locator):
                citations.append(locator)
        return {
            "security_id": security_id,
            "thesis_id": thesis_id,
            "period_start": period_start,
            "period_end": period_end,
            "summary": f"复盘区间内收到 {len(records)} 条已有记录，结论需研究员确认。",
            "supporting_changes": supporting,
            "conflicting_changes": conflicting,
            "open_questions": open_questions,
            "citations": list(dict.fromkeys(citations)),
            "requires_human_review": True,
            "confidence": 0.75 if records else 0.4,
            "model_version": self.model_version,
            "prompt_version": REVIEW_DRAFT.version,
            "generated_at": now().isoformat(),
            "ai_status": AiStatus.CANDIDATE.value,
        }

    def hypothesis_quality(
        self,
        *,
        security_id: str,
        thesis_id: str,
        title: str,
        core_view: str,
        hypotheses: list[dict[str, Any]],
        repair_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.ai.quality.hypothesis_structure import inspect_hypotheses

        checked = inspect_hypotheses([dict(item) for item in hypotheses])
        results = [
            {
                "hypothesis_id": str(item.get("hypothesis_id") or ""),
                "logic_dimension": str(item.get("logic_dimension") or "待确认"),
                "duplicate_with": [],
                "crosses_with": [],
                "quality_warning": str(item.get("quality_warning") or ""),
            }
            for item in checked
        ]
        return {
            "thesis_id": thesis_id,
            "summary": f"已检查 {len(results)} 条假设的维度、重复和交叉关系。",
            "results": results,
            "requires_human_review": True,
            "confidence": 0.75,
            "model_version": self.model_version,
            "prompt_version": HYPOTHESIS_QUALITY.version,
            "generated_at": now().isoformat(),
            "ai_status": AiStatus.CANDIDATE.value,
        }


def _tracking_hints(text: str) -> list[str]:
    hints: list[str] = []
    if "订单" in text:
        hints.append("跟踪订单转化为收入的进度")
    if "毛利率" in text:
        hints.append("跟踪后续季度毛利率是否回升")
    if "政策" in text or "补贴" in text:
        hints.append("跟踪政策实施细则落地情况")
    return hints


def _split_clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"[。；;]", text) if len(c.strip()) >= 8]


def _extract_hypotheses(segments: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """从资料里挑出可作为假设的陈述句。

    只取前 5 条（Schema 上限），第一条标核心（PRD 5.1 要求至少一条核心）。
    """
    candidates: list[dict[str, Any]] = []
    for locator, content in segments:
        for clause in _split_clauses(content):
            if not any(cue in clause for cue in ("增长", "需求", "订单", "毛利率", "收入", "装机")):
                continue
            candidates.append(
                {
                    "statement": clause[:200],
                    "hypothesis_type": guess_hypothesis_type(clause),
                    "importance": "核心" if not candidates else "辅助",
                    "metric_suggestions": _metric_hints(clause),
                    "evidence_locator": locator,
                }
            )
            if len(candidates) == 5:
                return candidates

    while len(candidates) < 2:
        candidates.append(
            {
                "statement": "待研究员补充可验证的关键假设",
                "hypothesis_type": "其他",
                "importance": "核心" if not candidates else "辅助",
                "metric_suggestions": [],
                "evidence_locator": None,
            }
        )
    from app.ai.quality.hypothesis_structure import inspect_hypotheses
    return inspect_hypotheses(candidates)


def _metric_hints(text: str) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    if "收入" in text:
        hints.append({"metric_name": "海外收入同比", "unit": "%", "observation_frequency": "季度"})
    if "毛利率" in text:
        hints.append(
            {"metric_name": "海外项目毛利率", "unit": "%", "observation_frequency": "季度"}
        )
    if "装机" in text or "需求" in text:
        hints.append(
            {"metric_name": "行业大型储能装机同比", "unit": "%", "observation_frequency": "季度"}
        )
    return hints


def _extract_risks(segments: list[tuple[str, str]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for locator, content in segments:
        for clause in _split_clauses(content):
            if any(cue in clause for cue in ("风险", "压力", "受", "影响", "不确定")):
                risks.append({"statement": clause[:200], "evidence_locator": locator})
                break
    return risks[:5]


def _extract_invalidation(segments: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """抽取失效条件建议。

    识别「若…且…」结构并给出 require_all=True。把 AND 读成 OR 会让单指标不达标
    就判失效，是最伤研究员信任的误报类型。
    """
    suggestions: list[dict[str, Any]] = []
    for _, content in segments:
        for clause in _split_clauses(content):
            if "若" not in clause and "低于" not in clause:
                continue
            if "需要重新评估" in clause or "重新评估" in clause or "低于" in clause:
                suggestions.append(
                    {
                        "statement": clause[:200],
                        "require_all": "且" in clause,
                        "consecutive_periods": 2 if "连续两个季度" in clause else None,
                    }
                )
    return suggestions[:5]
