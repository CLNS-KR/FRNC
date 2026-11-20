"""판정 엔진 테스트 — 정규화·세 가지 판정·신호별 동작·질문·금액·비교."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import engine, models  # noqa: E402

NORMAL = {
    "brand_name": "샘플치킨",
    "industry": "치킨",
    "disclosure_days_before": 21,
    "contract_doc_days_before": 21,
    "payment_route": "escrow",
    "revenue_written": True,
    "revenue_estimate_doc": True,
    "interior_designated": "free",
    "territory": "exclusive",
    "closure_rate_3y_pct": 5,
    "legal_violation": False,
    "termination_grace_months": 2,
    "disclosure_registered": True,
    "mandatory_purchase": False,
    "supplier_designated": False,
    "sales_target": False,
    "price_fixing": False,
    "ad_cost_burden": "shared",
    "penalty_ratio_pct": 10,
}


def check(**kwargs):
    payload = dict(NORMAL)
    payload.update(kwargs)
    return engine.check_franchise_risk(payload)


def triggered_ids(result):
    return [row["trap_id"] for row in result["risk_points"]]


class MoneyParsingTest(unittest.TestCase):
    def test_korean_units(self):
        self.assertEqual(engine.parse_money("3억"), 300_000_000)
        self.assertEqual(engine.parse_money("1억 2,300만"), 123_000_000)
        self.assertEqual(engine.parse_money("5,000만원"), 50_000_000)
        self.assertEqual(engine.parse_money("1,100만"), 11_000_000)
        self.assertEqual(engine.parse_money("33000000"), 33_000_000)
        self.assertEqual(engine.parse_money(50_000_000), 50_000_000)
        self.assertIsNone(engine.parse_money("모름"))
        self.assertIsNone(engine.parse_money(""))

    def test_numbers_and_booleans(self):
        self.assertEqual(engine.parse_number("15%"), 15.0)
        self.assertEqual(engine.parse_number(7), 7.0)
        self.assertIsNone(engine.parse_number(""))
        self.assertTrue(engine.parse_bool("예"))
        self.assertTrue(engine.parse_bool("y"))
        self.assertFalse(engine.parse_bool("아니오"))
        self.assertFalse(engine.parse_bool(False))
        self.assertIsNone(engine.parse_bool("모름"))


class NormalizationTest(unittest.TestCase):
    def test_korean_keys_are_accepted(self):
        terms = engine.normalize_terms({
            "브랜드명": "샘플치킨", "가맹비": "1,100만원", "인테리어": "5,500만원",
            "보증금": "1,000만원", "정보공개서_경과일": 3, "가맹금납부": "본사",
        })
        self.assertEqual(terms["brand_name"], "샘플치킨")
        self.assertEqual(terms["franchise_fee_krw"], 11_000_000)
        self.assertEqual(terms["interior_krw"], 55_000_000)
        self.assertEqual(terms["deposit_krw"], 10_000_000)
        self.assertEqual(terms["disclosure_days_before"], 3)
        self.assertEqual(terms["payment_route"], "hq_account")

    def test_unknown_keys_and_values_are_ignored(self):
        terms = engine.normalize_terms({"nope": "x", "가맹비": "모름", "territory": "몰라"})
        self.assertNotIn("franchise_fee_krw", terms)
        self.assertNotIn("territory", terms)
        self.assertNotIn("nope", terms)

    def test_nested_terms_block(self):
        terms = engine.normalize_terms({"terms": {"brand_name": "A", "payment_route": "none"}})
        self.assertEqual(terms["brand_name"], "A")
        self.assertEqual(terms["payment_route"], "none")


class VerdictTest(unittest.TestCase):
    def test_same_day_contract_is_check_likely_high(self):
        result = check(disclosure_days_before=0)
        self.assertEqual(result["verdict"]["code"], models.VERDICT_CHECK)
        self.assertEqual(result["counts"]["high"], 1)
        self.assertIn("same_day_contract", triggered_ids(result))

    def test_14_days_is_clear_and_13_is_triggered(self):
        self.assertNotIn("same_day_contract", triggered_ids(check(disclosure_days_before=14,
                                                                  contract_doc_days_before=14)))
        self.assertIn("same_day_contract", triggered_ids(check(disclosure_days_before=13,
                                                               contract_doc_days_before=13)))

    def test_advisor_review_shortens_limit_to_seven(self):
        with_advisor = check(disclosure_days_before=10, contract_doc_days_before=10,
                             advisor_reviewed=True)
        without_advisor = check(disclosure_days_before=10, contract_doc_days_before=10,
                                advisor_reviewed=False)
        self.assertNotIn("same_day_contract", triggered_ids(with_advisor))
        self.assertIn("same_day_contract", triggered_ids(without_advisor))
        five_days = check(disclosure_days_before=5, contract_doc_days_before=5,
                          advisor_reviewed=True)
        self.assertIn("same_day_contract", triggered_ids(five_days))
        self.assertIn("7일", five_days["risk_points"][0]["note_ko"])

    def test_verbal_revenue_is_high(self):
        result = check(revenue_written=False, revenue_estimate_doc=False,
                       revenue_claim_ko="월 5천 보장")
        self.assertIn("revenue_verbal_guarantee", triggered_ids(result))
        self.assertEqual(result["counts"]["high"], 1)

    def test_written_revenue_is_clear(self):
        result = check(revenue_written=True, revenue_estimate_doc=True,
                       revenue_claim_ko="월 5천 보장")
        self.assertNotIn("revenue_verbal_guarantee", triggered_ids(result))

    def test_hq_account_is_triggered_but_not_double_counted_as_escrow(self):
        result = check(payment_route="hq_account")
        self.assertIn("payment_to_hq_account", triggered_ids(result))
        self.assertNotIn("no_escrow", triggered_ids(result))

    def test_escrow_none_triggers_escrow_trap_only(self):
        result = check(payment_route="none")
        self.assertIn("no_escrow", triggered_ids(result))
        self.assertNotIn("payment_to_hq_account", triggered_ids(result))

    def test_interior_severity(self):
        forced = check(interior_designated="forced")
        partial = check(interior_designated="partial")
        self.assertEqual(forced["risk_points"][0]["severity"], models.SEVERITY_HIGH)
        self.assertEqual(partial["risk_points"][0]["severity"], models.SEVERITY_MEDIUM)

    def test_territory_severity(self):
        none = check(territory="none")
        defined = check(territory="defined")
        self.assertEqual(none["risk_points"][0]["severity"], models.SEVERITY_HIGH)
        self.assertEqual(defined["risk_points"][0]["severity"], models.SEVERITY_MEDIUM)

    def test_closure_rate_thresholds(self):
        self.assertEqual(check(closure_rate_3y_pct=16)["risk_points"][0]["severity"],
                         models.SEVERITY_HIGH)
        self.assertEqual(check(closure_rate_3y_pct=9)["risk_points"][0]["severity"],
                         models.SEVERITY_MEDIUM)
        self.assertNotIn("closure_rate_hidden", triggered_ids(check(closure_rate_3y_pct=4)))

    def test_normal_conditions_are_low_risk(self):
        result = check()
        self.assertEqual(result["verdict"]["code"], models.VERDICT_LOW)
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["risk_points"], [])
        self.assertEqual(result["coverage"]["missing_axes"], [])

    def test_missing_key_axis_is_info_needed_not_low_risk(self):
        payload = dict(NORMAL)
        payload.pop("closure_rate_3y_pct")
        result = engine.check_franchise_risk(payload)
        self.assertEqual(result["verdict"]["code"], models.VERDICT_INFO)
        self.assertEqual(result["coverage"]["missing_axes"], ["closure_rate_3y_pct"])
        self.assertIn("폐점률", " ".join(result["questions_ko"]))

    def test_unknown_is_never_reported_as_clear(self):
        result = engine.check_franchise_risk({"brand_name": "X"})
        self.assertEqual(result["verdict"]["code"], models.VERDICT_INFO)
        self.assertEqual(result["risk_points"], [])
        self.assertTrue(result["unknown_points"])
        clear_ids = [row["trap_id"] for row in result["clear_points"]]
        self.assertNotIn("same_day_contract", clear_ids)

    def test_empty_input_does_not_crash(self):
        result = engine.check_franchise_risk({})
        self.assertTrue(result["verdict"]["code"])
        self.assertIn("확정 판정이 아닙니다", result["disclaimer_ko"])

    def test_questions_are_capped_and_actionable(self):
        result = engine.check_franchise_risk({"brand_name": "X"})
        self.assertLessEqual(len(result["questions_ko"]), 10)
        self.assertGreaterEqual(len(result["questions_ko"]), 5)


class MoneyBlockTest(unittest.TestCase):
    def test_component_sum(self):
        result = check(franchise_fee_krw="1,100만원", education_fee_krw="330만원",
                       deposit_krw="1,000만원", interior_krw="5,500만원",
                       equipment_krw="2,000만원", other_krw="300만원")
        money = result["money"]
        self.assertEqual(money["total_krw"], 102_300_000)
        self.assertEqual(money["total_source"], "computed")
        self.assertIn("1억", money["total_ko"])
        shares = {row["label_ko"]: row["share_pct"] for row in money["components"]}
        self.assertAlmostEqual(shares["인테리어"], 53.8, places=1)

    def test_explicit_total_wins(self):
        result = check(total_investment_krw="2억", franchise_fee_krw="1,100만원")
        self.assertEqual(result["money"]["total_krw"], 200_000_000)
        self.assertEqual(result["money"]["total_source"], "input")

    def test_penalty_ratio_from_amount(self):
        result = check(total_investment_krw="1억", penalty_krw="3,000만원")
        row = [item for item in result["risk_points"] if item["trap_id"] == "excessive_penalty"]
        self.assertTrue(row)
        self.assertEqual(row[0]["severity"], models.SEVERITY_MEDIUM)


class LawBasisTest(unittest.TestCase):
    def test_every_risk_point_has_verified_law_text(self):
        result = check(disclosure_days_before=0, payment_route="hq_account",
                       interior_designated="forced", territory="none")
        self.assertTrue(result["law_basis"])
        for row in result["law_basis"]:
            self.assertTrue(row["excerpt_ko"], row["key"])
            self.assertIn("law.go.kr", row["source_url"])
        keys = {row["key"] for row in result["law_basis"]}
        self.assertIn("가맹사업법:제7조", keys)
        self.assertIn("가맹사업법:제6조의5", keys)
        self.assertIn("가맹사업법 시행령:불공정거래행위의 유형 또는 기준(제13조제1항관련)", keys)

    def test_search_law_article(self):
        record = engine.search_law_article("제7조")
        self.assertTrue(record["ok"])
        self.assertIn("14일", record["text"])
        self.assertEqual(record["law"], "가맹사업법")

    def test_search_law_article_by_number_and_decree(self):
        self.assertTrue(engine.search_law_article("9조")["ok"])
        decree = engine.search_law_article("시행령 제13조")
        self.assertTrue(decree["ok"])
        self.assertEqual(decree["law"], "가맹사업법 시행령")
        self.assertFalse(engine.search_law_article("없는조문")["ok"])


class CompareTest(unittest.TestCase):
    def test_compare_costs_and_risks(self):
        result = engine.compare_franchise_terms({
            "a": {"brand_name": "A", "total_investment_krw": "1억",
                  "disclosure_days_before": 0, "payment_route": "hq_account"},
            "b": {"brand_name": "B", "total_investment_krw": "1억 3,000만원",
                  "disclosure_days_before": 21, "payment_route": "escrow",
                  "revenue_written": True, "revenue_estimate_doc": True,
                  "interior_designated": "free", "territory": "exclusive",
                  "closure_rate_3y_pct": 5, "legal_violation": False,
                  "termination_grace_months": 2},
        })
        self.assertEqual(result["a"]["verdict"]["code"], models.VERDICT_CHECK)
        self.assertGreater(result["a"]["counts"]["high"], 0)
        rows = {row["field"]: row for row in result["rows"]}
        self.assertEqual(rows["total_investment_krw"]["winner"], "a")
        self.assertIn("3,000만원", str(rows["total_investment_krw"]["gap_ko"]))
        self.assertEqual(rows["payment_route"]["winner"], "b")
        self.assertTrue(any("유리" in item or "유리" in item for item in result["differences_ko"]))
        self.assertIn("확정 판정이 아닙니다", result["recommendation_ko"])

    def test_compare_requires_both_sides(self):
        with self.assertRaises(ValueError):
            engine.compare_franchise_terms({"a": {"brand_name": "A"}})
        with self.assertRaises(ValueError):
            engine.compare_franchise_terms({})

    def test_compare_unknown_values_are_not_decided(self):
        result = engine.compare_franchise_terms({"a": {"brand_name": "A"},
                                                 "b": {"brand_name": "B"}})
        for row in result["rows"]:
            if row["a_value"] is None or row["b_value"] is None:
                self.assertEqual(row["winner"], "unknown")


class SummaryTest(unittest.TestCase):
    def test_summary_mentions_brand_and_top_item(self):
        result = check(disclosure_days_before=0)
        self.assertIn("샘플치킨", result["summary_ko"])
        self.assertIn("가장 먼저", result["summary_ko"])

    def test_score_increases_with_severity(self):
        one_high = check(disclosure_days_before=0)["risk_score"]
        two_high = check(disclosure_days_before=0, payment_route="hq_account")["risk_score"]
        self.assertGreater(two_high, one_high)


if __name__ == "__main__":
    unittest.main(verbosity=2)
