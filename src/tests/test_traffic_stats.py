"""`/v1/stats` 트래픽 구분(`/healthz` 버전 포함) 회귀 테스트 — 0.1.9.

확인하는 것
- `/v1/stats` 가 경로를 묶음(`traffic.by_channel`)으로, 요청 종류를 셋(`traffic.by_client`)으로 접는다.
- 구분은 익명 카운트다 — User-Agent 원문을 넘겨도 저장되지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import usage  # noqa: E402
from franchise_kr.server import make_handler  # noqa: E402
from franchise_kr.store import Store  # noqa: E402
from franchise_kr.version import __version__  # noqa: E402


class TrafficStatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.store))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_healthz_reports_version(self):
        self.assertEqual(self._get("/healthz")["version"], __version__)

    def test_stats_traffic_buckets(self):
        usage.record_request(self.store, "GET", "/", client="browser")
        usage.record_request(self.store, "GET", "/robots.txt", client="bot")
        usage.record_request(self.store, "POST", "/v1/tools/lookup_brand_disclosure",
                             client="bot")
        usage.record_request(self.store, "GET", "/guides/", client="browser")
        data = self._get("/v1/stats?days=7")
        traffic = data["traffic"]
        self.assertGreaterEqual(traffic["by_channel"]["web"], 2)
        self.assertGreaterEqual(traffic["by_channel"]["crawler_files"], 1)
        self.assertGreaterEqual(traffic["by_channel"]["api"], 1)
        self.assertGreaterEqual(traffic["by_client"]["bot"], 2)
        self.assertEqual(data["privacy"]["stores_user_agent"], False)


class ClassificationUnitTest(unittest.TestCase):
    def test_client_class(self):
        self.assertEqual(usage.client_class("Mozilla/5.0 Safari/605"), "browser")
        self.assertEqual(usage.client_class("ClaudeBot/1.0"), "bot")
        self.assertEqual(usage.client_class(""), "other")
        self.assertEqual(usage.client_class("weird"), "other")

    def test_channel_of(self):
        self.assertEqual(usage.channel_of("/guides/"), "web")
        self.assertEqual(usage.channel_of("/terms"), "web")
        self.assertEqual(usage.channel_of("/llms.txt"), "crawler_files")
        self.assertEqual(usage.channel_of("/v1/meta"), "api")
        self.assertEqual(usage.channel_of("/v1/mcp"), "mcp")
        self.assertEqual(usage.channel_of("/favicon.ico"), "assets")
        self.assertEqual(usage.channel_of("/404"), "not_found")

    def test_raw_user_agent_is_not_counted(self):
        store = Store(":memory:")
        try:
            usage.record_request(store, "GET", "/", client="Mozilla/5.0 (X11)")
            rows = store.usage_rows(usage.today_kst(), usage.today_kst())
        finally:
            store.close()
        self.assertEqual([row for row in rows if row["kind"] == usage.KIND_CLIENT], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
