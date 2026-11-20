"""툴 레지스트리·응답 봉투·MCP 매니페스트 테스트."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import api, engine, models  # noqa: E402

EXPECTED_TOOLS = {
    "check_franchise_risk", "scan_contract_text", "lookup_brand_disclosure",
    "compare_franchise_terms", "list_risk_cases", "get_law_article", "get_service_meta",
}

SAMPLE = {
    "brand_name": "샘플치킨", "industry": "치킨",
    "franchise_fee_krw": "1,100만원", "interior_krw": "5,500만원",
    "disclosure_days_before": 0, "payment_route": "hq_account",
    "revenue_claim_ko": "월 5천 보장", "revenue_written": False,
}


class ToolRegistryTest(unittest.TestCase):
    def test_expected_tools_exist(self):
        names = {definition["name"] for definition in api.TOOL_DEFS}
        self.assertEqual(names, EXPECTED_TOOLS)
        self.assertEqual(len(api.mcp_tools()), 7)

    def test_every_tool_has_schema_and_description(self):
        for tool in api.mcp_tools():
            self.assertTrue(tool["description"], tool["name"])
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertIn("readOnlyHint", tool["annotations"])

    def test_manifest_shape(self):
        manifest = api.mcp_manifest()
        self.assertEqual(manifest["name"], "frnc")
        self.assertEqual(len(manifest["tools"]), 7)
        self.assertTrue(manifest["version"].startswith("frnc/"))

    def test_check_tool_envelope(self):
        result = api.call_tool("check_franchise_risk", SAMPLE)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "check_franchise_risk")
        payload = result["result"]
        for key in ("verdict", "risk_score", "counts", "risk_points", "questions_ko",
                    "checklist_ko", "money", "law_basis", "next_steps", "startup_support",
                    "disclaimer_ko", "scope_limits_ko", "checked_at", "schema_version", "meta"):
            self.assertIn(key, payload, key)
        self.assertEqual(payload["startup_support"]["url"], "https://grnt-kr.onrender.com/")
        self.assertEqual(payload["verdict"]["code"], models.VERDICT_CHECK)
        self.assertIn("샘플치킨", payload["summary_ko"])

    def test_lookup_tool_falls_back_to_sample(self):
        with mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": ""}):
            result = api.call_tool("lookup_brand_disclosure", {"brand_name": "샘플치킨"})
        self.assertTrue(result["ok"])
        payload = result["result"]
        self.assertEqual(payload["data_state"], "sample")
        self.assertIn(payload["status"], ("no_key", "sample", "not_approved"))
        self.assertTrue(payload["brands"])
        self.assertTrue(payload["apply_urls"] or payload["status"] == "sample")

    def test_compare_tool(self):
        result = api.call_tool("compare_franchise_terms", {
            "a": {"brand_name": "A", "total_investment_krw": "1억"},
            "b": {"brand_name": "B", "total_investment_krw": "1억 2,000만원"},
        })
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["result"]["rows"]), len(engine.COMPARE_ROWS))

    def test_list_cases_tool_with_filter(self):
        result = api.call_tool("list_risk_cases", {"severity": "high"})
        self.assertTrue(result["ok"])
        cases = result["result"]["cases"]
        self.assertTrue(cases)
        for case in cases:
            self.assertEqual(case["severity"], "high")
            self.assertTrue(case["law_verified"])

    def test_law_tool(self):
        result = api.call_tool("get_law_article", {"article": "제9조"})
        self.assertTrue(result["ok"])
        self.assertIn("예상매출액", result["result"]["text"])
        self.assertEqual(result["result"]["law"], "가맹사업법")

    def test_law_tool_not_found(self):
        result = api.call_tool("get_law_article", {"article": "없는조문"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")

    def test_meta_tool(self):
        result = api.call_tool("get_service_meta", {})
        payload = result["result"]
        self.assertEqual(payload["meta"]["service"], "FRNC")
        self.assertEqual(len(payload["verdicts"]), 3)
        self.assertEqual(len(payload["key_axes"]), 8)
        self.assertEqual(payload["trap_cases"], 17)
        self.assertFalse(payload["meta"]["privacy"]["stores_inputs"])
        self.assertTrue(payload["data_sources"]["apply_urls"])

    def test_meta_includes_guides(self):
        from franchise_kr import guides
        payload = api.call_tool("get_service_meta", {})["result"]
        block = payload["guides"]
        self.assertEqual(block["index"], "/guides/")
        self.assertEqual(block["count"], 17)
        self.assertEqual(len(block["items"]), 17)
        self.assertEqual([row["slug"] for row in block["items"]], guides.slugs())
        for row in block["items"]:
            self.assertEqual(row["path"], f"/guides/{row['slug']}")
            self.assertTrue(row["question"].endswith("?"))
        self.assertEqual(payload["meta"]["endpoints"]["guides"], "/guides/")

    def test_meta_declares_zero_result_brand_storage(self):
        payload = api.call_tool("get_service_meta", {})["result"]
        privacy = payload["meta"]["privacy"]
        self.assertEqual(privacy["stores_brand_names"], "zero_result_only")
        self.assertFalse(privacy["stores_inputs"])
        self.assertIn("0건", privacy["note_ko"])

    def test_lookup_zero_result_has_fixed_notice(self):
        with mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": ""}):
            result = api.call_tool("lookup_brand_disclosure",
                                   {"brand_name": "존재하지않는가맹브랜드명"})
        payload = result["result"]
        self.assertTrue(payload["zero_result"])
        self.assertIn("0건", payload["zero_result_notice_ko"])
        self.assertNotIn("문제없습니다", api.text_summary(result))

    def test_unknown_tool_and_invalid_arguments(self):
        unknown = api.call_tool("nope", {})
        self.assertEqual(unknown["error"], "unknown_tool")
        invalid = api.call_tool("compare_franchise_terms", {"a": {"brand_name": "A"}})
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error"], "invalid_argument")
        missing = api.call_tool("lookup_brand_disclosure", {})
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"], "invalid_argument")

    def test_text_summary_is_human_readable(self):
        for name, args in (
            ("check_franchise_risk", SAMPLE),
            ("lookup_brand_disclosure", {"brand_name": "샘플치킨"}),
            ("compare_franchise_terms", {"a": {"brand_name": "A"}, "b": {"brand_name": "B"}}),
            ("list_risk_cases", {}),
            ("get_law_article", {"article": "제7조"}),
            ("get_service_meta", {}),
        ):
            result = api.call_tool(name, args)
            summary = api.text_summary(result)
            self.assertTrue(summary.strip(), name)
            self.assertNotIn("None", summary, name)
            self.assertLessEqual(len(summary), 1200, name)

    def test_inquiry_validation(self):
        bad = api.submit_inquiry({"contact": "", "topic": "other"})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"], "contact_too_short")
        bad_topic = api.submit_inquiry({"contact": "a@b.co", "topic": "nope"})
        self.assertEqual(bad_topic["error"], "invalid_topic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
