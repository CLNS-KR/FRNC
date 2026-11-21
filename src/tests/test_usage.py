"""익명 카운터·문의 보관 테스트."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import usage  # noqa: E402
from franchise_kr.store import Store  # noqa: E402


class PathKeyTest(unittest.TestCase):
    def test_tool_paths_collapse(self):
        self.assertEqual(usage.path_key("/v1/tools/check_franchise_risk"), "/v1/tools")
        self.assertEqual(usage.path_key("/"), "/")
        self.assertEqual(usage.path_key("/healthz?x=1"), "/healthz")

    def test_unknown_paths_become_404(self):
        self.assertEqual(usage.path_key("/random-brand-name"), "/404")
        self.assertEqual(usage.path_key("no-slash"), "/404")

    def test_query_is_stripped(self):
        self.assertEqual(usage.path_key("/v1/stats?days=3"), "/v1/stats")


class StatisticsTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_counts_and_privacy_flags(self):
        usage.record_request(self.store, "GET", "/")
        usage.record_request(self.store, "POST", "/v1/tools/check_franchise_risk")
        usage.record_tool(self.store, "check_franchise_risk",
                          {"ok": True, "result": {"verdict": {"code": "check_likely"}}})
        stats = usage.statistics(self.store, days=1)
        self.assertEqual(stats["totals"]["requests"], 2)
        self.assertEqual(stats["totals"]["tools"]["check_franchise_risk"], 1)
        self.assertEqual(stats["totals"]["verdicts"]["check_likely"], 1)
        # 브랜드 조회어는 결과가 0건일 때만 비식별로 남긴다(그 사실을 숨기지 않는다).
        self.assertEqual(stats["privacy"]["stores_brand_names"], "zero_result_only")
        self.assertEqual(stats["privacy"]["stores_search_terms"], "zero_result_only")
        self.assertIn("/v1/tools", stats["totals"]["paths"])

    def test_sample_flag(self):
        usage.record_tool(self.store, "lookup_brand_disclosure",
                          {"ok": True, "tool": "lookup_brand_disclosure",
                           "result": {"data_state": "sample", "brands": []}})
        stats = usage.statistics(self.store, days=1)
        self.assertEqual(stats["totals"]["flags"].get("sample_data"), 1)

    def test_window_clamped(self):
        self.assertEqual(usage.statistics(self.store, days=999)["window_days"], usage.MAX_DAYS)
        self.assertEqual(usage.statistics(self.store, days="x")["window_days"],
                         usage.DEFAULT_DAYS)
        self.assertEqual(len(usage.statistics(self.store, days=3)["days"]), 3)


class InquiryTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_save_and_duplicate(self):
        data, error = usage.normalize_inquiry(
            {"contact": "a@example.com", "topic": "api_mcp", "message": "hi"})
        self.assertIsNone(error)
        saved = usage.save_inquiry(self.store, data)
        self.assertTrue(saved["stored"])
        again = usage.save_inquiry(self.store, data)
        self.assertTrue(again["duplicate"])

    def test_contact_is_trimmed_and_control_chars_removed(self):
        data, _ = usage.normalize_inquiry({"contact": "  a" "@" "b.co\x00  ", "topic": "other"})
        self.assertEqual(data["contact"], "a" + "@" + "b.co")

    def test_purge_old_inquiries(self):
        self.store.add_inquiry("2026-01-01", "other", "old@example.com", "")
        self.store.add_inquiry("2026-11-20", "other", "new@example.com", "")
        removed = usage.purge_inquiries(self.store, keep_days=180, day="2026-11-21")
        self.assertEqual(removed, 1)
        self.assertEqual(self.store.inquiry_count(), 1)

    def test_summary_has_no_contacts(self):
        self.store.add_inquiry("2026-11-20", "api_mcp", "secret@example.com", "내용")
        summary = usage.inquiry_summary(self.store)
        self.assertNotIn("secret@example.com", str(summary))
        self.assertEqual(summary["total"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
