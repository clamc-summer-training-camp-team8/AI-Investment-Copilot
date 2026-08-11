from __future__ import annotations

import json
from pathlib import Path

from app.ai.providers.local import judge_impact
from app.core.enums import ImpactDirection, SignalDirection


CASES = Path(__file__).parents[2] / "fixtures" / "ai" / "evidence_cases.json"


def test_fixed_evidence_cases_cover_impact_directions() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    impact_cases = [case for case in cases if case["kind"] == "impact"]

    assert {case["id"] for case in impact_cases} == {
        "support-001",
        "conflict-001",
        "uncertain-001",
        "neutral-001",
    }
    for case in impact_cases:
        verdict = judge_impact(case["text"])
        assert verdict.impact_direction.value == {
            "support": ImpactDirection.SUPPORT.value,
            "conflict": ImpactDirection.CONFLICT.value,
            "neutral": ImpactDirection.NEUTRAL.value,
        }[case["expected_impact"]]
        if "expected_signal" in case:
            assert verdict.signal_direction.value == {
                "uncertain": SignalDirection.UNCERTAIN.value,
                "neutral": SignalDirection.NEUTRAL.value,
            }[case["expected_signal"]]


def test_fixed_evidence_case_marks_missing_source_for_review() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    insufficient = next(case for case in cases if case["id"] == "insufficient-001")

    assert insufficient["text"] == ""
    assert insufficient["expected_review_reason"] == "missing_source"