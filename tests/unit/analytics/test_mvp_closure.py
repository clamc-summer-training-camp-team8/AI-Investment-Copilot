from __future__ import annotations

import copy
import unittest

from analytics.pipelines.mvp_closure import DEFAULT_DATASET, evaluate_dataset, load_dataset


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


if __name__ == "__main__":
    unittest.main()
