"""함정 코퍼스 검사 — 15건·조문 대조·판정 함수 누락 없음."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import engine, models  # noqa: E402


class TrapCorpusTest(unittest.TestCase):
    def setUp(self):
        self.cases = engine.trap_cases()
        self.law = engine.load_law()

    def test_case_count_is_within_brief_range(self):
        self.assertGreaterEqual(len(self.cases), 10)
        self.assertLessEqual(len(self.cases), 15)
        self.assertEqual(len(self.cases), 15)

    def test_ids_are_unique(self):
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_case_has_an_evaluator(self):
        for case in self.cases:
            self.assertIn(case["id"], engine.EVALUATORS, case["id"])

    def test_every_evaluator_belongs_to_a_case(self):
        ids = {case["id"] for case in self.cases}
        for trap_id in engine.EVALUATORS:
            self.assertIn(trap_id, ids, trap_id)

    def test_required_fields_are_present(self):
        for case in self.cases:
            for field in ("id", "title_ko", "category", "severity", "trigger_ko",
                          "summary_ko", "why_ko", "regret_ko", "fix_ko", "ask_ko",
                          "checklist_ko", "law_refs"):
                self.assertTrue(case.get(field), f"{case['id']} missing {field}")
            self.assertIn(case["severity"], models.SEVERITY_ORDER, case["id"])
            self.assertIn(case["category"], models.CATEGORY_LABELS_KO, case["id"])
            self.assertGreaterEqual(len(case["checklist_ko"]), 2, case["id"])

    def test_every_law_reference_exists_in_verified_corpus(self):
        articles = self.law.get("articles") or {}
        annexes = self.law.get("annexes") or {}
        for case in self.cases:
            self.assertTrue(case["law_refs"], case["id"])
            for key in case["law_refs"]:
                self.assertTrue(key in articles or key in annexes,
                                f"{case['id']} references unknown law key {key}")

    def test_law_reference_text_is_meaningful(self):
        for case in self.cases:
            for key in case["law_refs"]:
                self.assertGreaterEqual(len(engine.law_excerpt(key, 5000)), 40, key)

    def test_high_risk_cases_cover_the_brief_examples(self):
        by_id = {case["id"]: case for case in self.cases}
        for trap_id in ("same_day_contract", "revenue_verbal_guarantee",
                        "payment_to_hq_account", "interior_forced", "no_territory",
                        "closure_rate_hidden"):
            self.assertEqual(by_id[trap_id]["severity"], models.SEVERITY_HIGH, trap_id)

    def test_list_risk_cases_reports_verification(self):
        payload = engine.list_risk_cases()
        self.assertEqual(payload["count"], 15)
        for case in payload["cases"]:
            self.assertTrue(case["law_verified"], case["trap_id"])
            self.assertTrue(case["severity_label_ko"])
        self.assertEqual(len(payload["laws"]), 2)

    def test_case_texts_do_not_promise_certainty(self):
        banned = ("반드시 위법", "100%", "무조건 사기")
        for case in self.cases:
            text = " ".join([case["why_ko"], case["summary_ko"], case["fix_ko"]])
            for word in banned:
                self.assertNotIn(word, text, case["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
