"""0건 브랜드 조회 익명 집계 테스트.

브리프: 0건/미발견일 때 개인식별자(전화번호·이메일 등)를 지우고 앞 30자만
`/v1/stats` 의 `zero_result_queries` 에 익명 카운트한다. 그리고 0건은 절대
'문제없음·안전'이라는 뜻이 아니라는 고정 안내를 유지한다.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import api, live_api, usage  # noqa: E402
from franchise_kr.store import Store  # noqa: E402

MISSING = "존재하지않는가맹브랜드명"


class SanitizeQueryTest(unittest.TestCase):
    def test_removes_identifiers(self):
        query = usage.sanitize_query("홍길동 " "010-" "1234-" "5678 hong@example.com")
        self.assertNotIn("010", query)
        self.assertNotIn("example.com", query)
        self.assertNotIn("@", query)
        self.assertIn("홍길동", query)

    def test_removes_urls_and_handles(self):
        query = usage.sanitize_query("https://blog.example.com/치킨 @brand_name 치킨")
        self.assertNotIn("http", query)
        self.assertNotIn("@", query)
        self.assertIn("치킨", query)

    def test_masks_digits(self):
        self.assertEqual(usage.sanitize_query("31아이스크림"), "N아이스크림")
        self.assertEqual(usage.sanitize_query("1992년생"), "N년생")

    def test_length_limit(self):
        long_name = "가" * 80
        self.assertEqual(len(usage.sanitize_query(long_name)), usage.MAX_QUERY_CHARS)
        self.assertEqual(usage.MAX_QUERY_CHARS, 30)

    def test_empty_and_digit_only(self):
        for value in ("", "   ", "010-" "1234-" "5678", "1234567", "!@#$"):
            self.assertEqual(usage.sanitize_query(value), "", value)

    def test_rrn_removed(self):
        query = usage.sanitize_query("900101-1234567 치킨")
        self.assertNotIn("900101", query)
        self.assertIn("치킨", query)


class ZeroResultStatsTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def lookup(self, name=MISSING, day=None):
        args = {"brand_name": name}
        with self._env():
            result = api.call_tool("lookup_brand_disclosure", args, store=self.store)
        if day is not None:
            # 날짜를 고정해 일별 집계를 검사한다(카운터를 그 날짜로 옮긴다).
            usage.record_tool(self.store, "lookup_brand_disclosure", result, args, day)
        return result

    @staticmethod
    def _env():
        import unittest.mock as mock
        return mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": ""})

    def test_not_found_is_zero_and_flagged(self):
        result = self.lookup()
        payload = result["result"]
        self.assertEqual(payload["status"], "not_found")
        self.assertTrue(payload["zero_result"])
        self.assertIn("0건", payload["zero_result_notice_ko"])
        self.assertIn("'문제없다·안전하다'는 뜻도 아닙니다", payload["zero_result_notice_ko"])
        stats = usage.statistics(self.store, days=1)
        self.assertEqual(stats["totals"]["flags"].get(usage.FLAG_ZERO), 1)
        top = stats["zero_result_queries"][0]
        self.assertEqual(top["query"], MISSING)
        self.assertEqual(top["count"], 1)
        self.assertEqual(top["reason"], "not_found")

    def test_found_result_is_not_recorded(self):
        with self._env():
            result = api.call_tool("lookup_brand_disclosure", {"brand_name": "샘플치킨"},
                                   store=self.store)
        self.assertFalse(result["result"]["zero_result"])
        stats = usage.statistics(self.store, days=1)
        self.assertEqual(stats["zero_result_queries"], [])
        self.assertEqual(stats["days"][0]["zero_result_queries"], [])
        self.assertNotIn(usage.FLAG_ZERO, stats["totals"]["flags"])

    def test_sample_or_unapproved_is_not_zero(self):
        # 키가 없어 샘플로 응답한 경우는 '확정 0건'이 아니다.
        result = api.call_tool("lookup_brand_disclosure", {"brand_name": MISSING},
                              store=Store(":memory:"))
        self.assertTrue(result["result"]["zero_result"])  # 샘플에도 없으면 not_found
        # 승인 전 상태(not_approved)를 흉내 내면 0건으로 세지 않는다.
        fake = {"ok": True, "tool": "lookup_brand_disclosure",
                "result": {"status": "not_approved", "brands": [], "data_state": "sample"}}
        usage.record_tool(self.store, "lookup_brand_disclosure", fake,
                          {"brand_name": "아무브랜드"})
        stats = usage.statistics(self.store, days=1)
        self.assertEqual(stats["zero_result_queries"], [])
        self.assertNotIn(usage.FLAG_ZERO, stats["totals"]["flags"])

    def test_identifiers_never_reach_stats(self):
        name = "홍길동 " "010-" "9876-" "5432 hong@example.com 치킨"
        self.lookup(name)
        _, body, _ = None, json.dumps(usage.statistics(self.store, days=1), ensure_ascii=False), None
        self.assertNotIn("010-9876", body)
        self.assertNotIn("example.com", body)
        self.assertNotIn("hong", body)
        self.assertIn("치킨", body)
        # 원본 문자열이 DB 어디에도 남지 않는다.
        rows = self.store.usage_rows(usage.today_kst(), usage.today_kst())
        keys = " ".join(str(row["key"]) for row in rows)
        self.assertNotIn("010", keys)
        self.assertNotIn("@", keys)

    def test_counts_aggregate_by_query(self):
        for _ in range(3):
            self.lookup()
        self.lookup("다른없는브랜드")
        stats = usage.statistics(self.store, days=1)
        top = stats["zero_result_queries"]
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0]["query"], MISSING)
        self.assertEqual(top[0]["count"], 3)

    def test_per_day_buckets(self):
        today = usage.today_kst()
        yesterday = usage._shift(today, -1)
        with self._env():
            result = {"ok": True, "tool": "lookup_brand_disclosure",
                      "result": live_api.lookup(MISSING)}
        usage.record_tool(self.store, "lookup_brand_disclosure", result,
                          {"brand_name": MISSING}, today)
        usage.record_tool(self.store, "lookup_brand_disclosure", result,
                          {"brand_name": "어제없던브랜드"}, yesterday)
        stats = usage.statistics(self.store, days=2)
        days = {row["date"]: row for row in stats["days"]}
        self.assertEqual([row["query"] for row in days[today]["zero_result_queries"]], [MISSING])
        self.assertEqual([row["query"] for row in days[yesterday]["zero_result_queries"]],
                         ["어제없던브랜드"])
        self.assertEqual(sum(row["count"] for row in stats["zero_result_queries"]), 2)

    def test_privacy_block_is_explicit(self):
        stats = usage.statistics(self.store, days=1)
        privacy = stats["privacy"]
        self.assertEqual(privacy["stores_brand_names"], "zero_result_only")
        self.assertEqual(privacy["stores_search_terms"], "zero_result_only")
        self.assertFalse(privacy["stores_inputs"])
        block = privacy["zero_result_queries"]
        self.assertTrue(block["results_are_not_stored"])
        self.assertEqual(block["max_chars"], 30)
        self.assertIn("전화번호", "".join(block["removed_ko"]))
        self.assertIn("이메일", "".join(block["removed_ko"]))
        self.assertIn("0건", privacy["note_ko"])
        self.assertEqual(stats["days"][0]["zero_result_queries"], [])

    def test_zero_result_notice_exists_in_meta(self):
        result = api.call_tool("get_service_meta", {})
        notice = result["result"]["zero_result_notice_ko"]
        self.assertEqual(notice, live_api.ZERO_RESULT_NOTICE_KO)
        self.assertIn("안전", notice)  # '안전하다는 뜻이 아니다'는 문장 자체를 유지
        self.assertNotIn("문제없습니다", notice)

    def test_text_summary_includes_notice_when_zero(self):
        result = self.lookup()
        summary = api.text_summary(result)
        self.assertIn("0건", summary)


class GuidePathStatsTest(unittest.TestCase):
    def test_guide_paths_are_counted_separately(self):
        self.assertEqual(usage.path_key("/guides/"), "/guides/")
        self.assertEqual(usage.path_key("/guides/cooling-off-14days"),
                         "/guides/cooling-off-14days")
        self.assertEqual(usage.path_key("/guides/없는가이드"), "/404")
        self.assertEqual(usage.path_key("/guides/cooling-off-14days?brand=샘플"),
                         "/guides/cooling-off-14days")


if __name__ == "__main__":
    unittest.main(verbosity=2)
