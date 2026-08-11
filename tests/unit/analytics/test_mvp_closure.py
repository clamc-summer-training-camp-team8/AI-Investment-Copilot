from __future__ import annotations

import copy
import json
import unittest

from analytics.pipelines.mvp_closure import (
    DEFAULT_AI_EVALUATION,
    DEFAULT_DATASET,
    DEFAULT_OUTPUT,
    apply_ai_model_evaluation,
    evaluate_dataset,
    load_dataset,
)
from analytics.pipelines.researcher_review import (
    apply_researcher_review,
    validate_researcher_reviews,
)


class MvpClosureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = load_dataset(DEFAULT_DATASET)

    def test_nine_company_closure_metrics(self) -> None:
        result = evaluate_dataset(self.dataset)

        self.assertEqual(result["workflow_validation"], "passed_with_limitations")
        self.assertEqual(result["production_mvp_acceptance"], "not_passed")
        self.assertEqual(result["blocking_errors"], [])
        self.assertEqual(result["metrics"]["company_count"], 9)
        self.assertEqual(result["metrics"]["event_count"], 27)
        self.assertEqual(result["metrics"]["observation_count"], 36)
        self.assertEqual(
            result["metrics"]["candidate_proxy_direction_agreement"],
            {
                "numerator": 27,
                "denominator": 27,
                "interpretation": "规则与同一阈值口径的代理复核一致率，不是独立AI准确率",
            },
        )

    def test_yunnan_baiyao_exercises_risk_then_divergence(self) -> None:
        result = evaluate_dataset(self.dataset)
        events = [event for event in result["events"] if event["company_name"] == "云南白药"]

        self.assertEqual(
            [event["suggested_status"].value for event in events],
            [
                "验证中",
                "重大风险",
                "出现分歧",
            ],
        )
        self.assertEqual([event["consecutive_breaches"] for event in events], [1, 2, 0])

    def test_contract_rejects_future_period_at_disclosure(self) -> None:
        invalid = copy.deepcopy(self.dataset)
        invalid["cases"][0]["observations"][1]["disclosed_at"] = "2024-06-01"

        result = evaluate_dataset(invalid)

        self.assertEqual(result["workflow_validation"], "failed")
        self.assertTrue(
            any("尚未结束的报告期" in error for error in result["blocking_errors"]),
            result["blocking_errors"],
        )

    def test_contract_rejects_an_unapproved_company(self) -> None:
        invalid = copy.deepcopy(self.dataset)
        invalid["cases"][0]["company_name"] = "未批准公司"

        result = evaluate_dataset(invalid)

        self.assertEqual(result["workflow_validation"], "failed")
        self.assertTrue(
            any("公司集合" in error for error in result["blocking_errors"]),
            result["blocking_errors"],
        )

    def test_researcher_gold_has_required_coverage_and_double_review(self) -> None:
        result = evaluate_dataset(self.dataset)
        review = validate_researcher_reviews(
            result["events"],
            DEFAULT_OUTPUT / "review_queue.csv",
            DEFAULT_OUTPUT / "review_queue-1.csv",
            DEFAULT_OUTPUT / "researcher_gold_v1.csv",
        )

        self.assertEqual(review["status"], "PASS", review["errors"])
        self.assertEqual(review["double_reviewed_events"], 6)
        self.assertEqual(review["double_direction_agreement"], {"numerator": 6, "denominator": 6})

    def test_live_ai_artifact_closes_bounded_production_gate(self) -> None:
        result = evaluate_dataset(self.dataset)
        review = validate_researcher_reviews(
            result["events"],
            DEFAULT_OUTPUT / "review_queue.csv",
            DEFAULT_OUTPUT / "review_queue-1.csv",
            DEFAULT_OUTPUT / "researcher_gold_v1.csv",
        )
        apply_researcher_review(result, review)
        artifact = json.loads(DEFAULT_AI_EVALUATION.read_text(encoding="utf-8"))

        evaluation = apply_ai_model_evaluation(result, artifact)

        self.assertEqual(evaluation["status"], "PASS", evaluation["errors"])
        self.assertEqual(evaluation["exact_matches"], 27)
        self.assertEqual(evaluation["unique_request_count"], 27)
        self.assertEqual(result["production_mvp_acceptance"], "passed_with_limitations")

    def test_ai_gate_rejects_an_untraceable_artifact(self) -> None:
        result = evaluate_dataset(self.dataset)
        artifact = json.loads(DEFAULT_AI_EVALUATION.read_text(encoding="utf-8"))
        artifact["results"][0]["request_id"] = None

        evaluation = apply_ai_model_evaluation(result, artifact)

        self.assertEqual(evaluation["status"], "FAIL")
        self.assertTrue(any("request_id" in error for error in evaluation["errors"]))
        self.assertEqual(result["production_mvp_acceptance"], "not_passed")


if __name__ == "__main__":
    unittest.main()
