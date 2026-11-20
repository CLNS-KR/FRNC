"""함정 코퍼스 검사 — 17건·조문 대조·판정 함수 누락 없음."""
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
        self.assertLessEqual(len(self.cases), 17)
        self.assertEqual(len(self.cases), 17)

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
                        "closure_rate_hidden", "essential_items_margin"):
            self.assertEqual(by_id[trap_id]["severity"], models.SEVERITY_HIGH, trap_id)

    def test_list_risk_cases_reports_verification(self):
        payload = engine.list_risk_cases()
        self.assertEqual(payload["count"], 17)
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

    def test_new_cases_trigger_and_clear_on_their_fields(self):
        flagged = engine.check_franchise_risk({
            "brand_name": "A", "essential_price_hidden": True,
            "essential_items_broad": True, "margin_raise_unilateral": True,
            "resale_price_bound": True, "discount_forbidden": True,
        })
        ids = [row["trap_id"] for row in flagged["risk_points"]]
        for trap_id in ("essential_items_margin", "resale_price_maintenance"):
            self.assertIn(trap_id, ids)
        cleared = engine.check_franchise_risk({
            "brand_name": "A", "essential_price_hidden": False,
            "essential_items_broad": False, "margin_raise_unilateral": False,
            "resale_price_bound": False, "discount_forbidden": False,
        })
        clear_ids = [row["trap_id"] for row in cleared["clear_points"]]
        for trap_id in ("essential_items_margin", "resale_price_maintenance"):
            self.assertIn(trap_id, clear_ids)

    def test_cited_annexes_are_part_of_the_verified_file(self):
        for case_id in ("essential_items_margin", "resale_price_maintenance"):
            case = next(row for row in self.cases if row["id"] == case_id)
            keys = case["law_refs"]
            self.assertTrue(any("정보공개서의 기재사항" in key for key in keys), case_id)
            self.assertTrue(any("불공정거래행위" in key for key in keys), case_id)
            for key, anchor in (case.get("law_excerpt_anchors") or {}).items():
                record = engine.law_record(key)
                self.assertIsNotNone(record, key)
                self.assertIn(anchor, engine.law_full_text(record), f"{case_id}: {anchor}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
