"""HTTP 스모크 테스트 — 실제 소켓으로 라우팅·헤더·JSON-RPC 를 검증."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr.server import make_handler  # noqa: E402
from franchise_kr.store import Store  # noqa: E402


class HttpTest(unittest.TestCase):
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

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=5) as response:
            return response.status, response.read().decode("utf-8"), dict(response.headers)

    def post(self, path, payload, raw=None, content_type="application/json"):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.url(path), data=body, method="POST",
                                         headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def status(self, path, method="GET"):
        request = urllib.request.Request(self.url(path), method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    # --- 기본 페이지·정적 파일 ----------------------------------------------
    def test_home_page(self):
        status, body, headers = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("FRNC", body)
        self.assertIn("프랜차이즈 창업 전 10초 리스크 체크", body)
        self.assertIn("Franchise, simplified.", body)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertIn("prefers-color-scheme: dark", body)

    def test_healthz(self):
        status, body, _ = self.get("/healthz")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "frnc")
        self.assertEqual(payload["trap_cases"], 17)
        self.assertEqual(payload["guides"], 17)
        self.assertGreaterEqual(payload["law_articles"], 130)
        self.assertIn("approval", payload["live_api"])
        self.assertNotIn("serviceKey", body)

    def test_seo_files(self):
        _, robots, _ = self.get("/robots.txt")
        self.assertIn("Sitemap:", robots)
        _, sitemap, _ = self.get("/sitemap.xml")
        self.assertIn("<urlset", sitemap)
        _, llms, _ = self.get("/llms.txt")
        self.assertIn("check_franchise_risk", llms)
        self.assertIn("확정 판정이 아니", llms)
        _, card, _ = self.get("/.well-known/mcp/server-card.json")
        self.assertEqual(len(json.loads(card)["tools"]), 7)

    def test_guides_index_and_pages(self):
        status, body, headers = self.get("/guides/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("프랜차이즈 계약", body)
        self.assertIn('"@type":"CollectionPage"', body)
        self.assertIn('href="/guides/cooling-off-14days"', body)
        status, page, headers = self.get("/guides/cooling-off-14days")
        self.assertEqual(status, 200)
        self.assertIn('rel="canonical"', page)
        self.assertIn('"@type":"FAQPage"', page)
        self.assertIn("14일", page)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_guides_redirect_and_404(self):
        import urllib.request
        request = urllib.request.Request(self.url("/guides"), method="GET")
        # 리다이렉트를 따라가지 않고 상태·Location 만 본다.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(request, timeout=5)
            self.fail("301 이 나지 않음")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 301)
            self.assertEqual(exc.headers.get("Location"), "/guides/")
        self.assertEqual(self.status("/guides/no-such-guide"), 404)
        self.assertEqual(self.status("/guides/cooling-off-14days/extra"), 404)
        self.assertEqual(self.status("/guides/cooling-off-14days", "HEAD"), 200)
        self.assertEqual(self.status("/guides/no-such-guide", "HEAD"), 404)

    def test_manifest_and_meta(self):
        _, body, _ = self.get("/v1/mcp")
        self.assertEqual(len(json.loads(body)["tools"]), 7)
        _, body, _ = self.get("/v1/meta")
        meta = json.loads(body)["result"]
        self.assertEqual(len(meta["verdicts"]), 3)
        self.assertIn("apply_urls", meta["data_sources"])

    def test_head_and_options(self):
        for path in ("/", "/healthz", "/v1/meta", "/v1/stats", "/robots.txt", "/llms.txt",
                     "/sitemap.xml", "/.well-known/mcp/server-card.json"):
            self.assertEqual(self.status(path, "HEAD"), 200, path)
        self.assertEqual(self.status("/mcp", "OPTIONS"), 204)
        self.assertEqual(self.status("/v1/tools/check_franchise_risk", "OPTIONS"), 204)

    # --- 툴 호출 ------------------------------------------------------------
    def test_tool_post(self):
        status, body = self.post("/v1/tools/check_franchise_risk", {
            "brand_name": "샘플치킨", "disclosure_days_before": 0,
            "payment_route": "hq_account", "revenue_written": False,
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["result"]["verdict"]["code"], "check_likely")
        self.assertTrue(body["result"]["law_basis"])

    def test_tool_errors(self):
        self.assertEqual(self.post("/v1/tools/nope", {})[0], 404)
        status, body = self.post("/v1/tools/compare_franchise_terms", {"a": {}})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_argument")

    def test_scan_contract_text_tool(self):
        status, body = self.post("/v1/tools/scan_contract_text", {
            "text": "제3조 가맹점사업자는 인테리어를 당사가 지정한 업체를 통해서만 시공한다."})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        payload = body["result"]
        self.assertEqual(payload["verdict"]["code"], "scan_flagged")
        self.assertTrue(payload["findings"])
        self.assertIn("필요합니다", payload["not_a_clearance_ko"])
        self.assertEqual(payload["meta"]["version"], "0.1.3")

        status, body = self.post("/v1/tools/scan_contract_text", {
            "text": "가맹금은 예치기관에 예치한다. 본부는 2개월 이상의 유예기간을 둔다."})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["verdict"]["code"], "scan_no_match")
        self.assertEqual(body["result"]["findings"], [])

        status, body = self.post("/v1/tools/scan_contract_text", {})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_argument")

        status, body = self.post("/v1/tools/scan_contract_text", None, raw=b"{oops")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_json")

    def test_invalid_json_and_limits(self):
        status, body = self.post("/v1/tools/get_service_meta", None, raw=b"{oops")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_json")
        status, body = self.post("/v1/tools/get_service_meta", None,
                                 raw=b"{}" + b" " * (70 * 1024))
        self.assertEqual(status, 413)
        status, body = self.post("/v1/tools/get_service_meta", None, raw=b"[]")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_argument")

    def test_unknown_route_and_method(self):
        self.assertEqual(self.status("/nope"), 404)
        self.assertEqual(self.status("/mcp", "GET"), 405)
        self.assertEqual(self.status("/v1/inquiry", "GET"), 405)

    # --- MCP ----------------------------------------------------------------
    def test_mcp_initialize_and_call(self):
        status, body = self.post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                          "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["serverInfo"]["name"], "frnc")
        self.assertIn("확정 판정이 아닙니다", body["result"]["instructions"])

        status, body = self.post("/v1/mcp", {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "check_franchise_risk",
                       "arguments": {"brand_name": "X", "disclosure_days_before": 0}},
        })
        self.assertEqual(status, 200)
        structured = body["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertIn("check_likely", structured["result"]["verdict"]["code"])
        self.assertIn("text", body["result"]["content"][0]["type"])

    def test_mcp_notification_returns_202(self):
        request = urllib.request.Request(
            self.url("/mcp"),
            data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 202)
            self.assertEqual(response.read(), b"")

    def test_mcp_batch_and_errors(self):
        _, body = self.post("/mcp", [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "nope", "arguments": {}}},
        ])
        self.assertEqual(len(body), 3)
        self.assertEqual(len(body[1]["result"]["tools"]), 7)
        self.assertEqual(body[2]["error"]["code"], -32602)

    def test_mcp_parse_error(self):
        status, body = self.post("/mcp", None, raw=b"{not json")
        self.assertEqual(status, 200)
        self.assertEqual(body["error"]["code"], -32700)

    # --- 문의·통계 ----------------------------------------------------------
    def test_inquiry_flow_and_privacy(self):
        status, body = self.post("/v1/inquiry", {
            "contact": "review@example.com", "topic": "franchise_review",
            "message": "샘플치킨 조건 검토 부탁드립니다."})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["receipt"].startswith("F"))
        self.assertNotIn("review@example.com", json.dumps(body, ensure_ascii=False))
        self.assertFalse(body["privacy"]["echoed_back"])
        # 같은 내용 두 번은 중복으로 접수
        status2, body2 = self.post("/v1/inquiry", {
            "contact": "review@example.com", "topic": "franchise_review",
            "message": "샘플치킨 조건 검토 부탁드립니다."})
        self.assertTrue(body2.get("duplicate"))

    def test_inquiry_errors(self):
        status, body = self.post("/v1/inquiry", {"contact": "", "topic": "other"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "contact_too_short")

    def test_stats_are_anonymous(self):
        self.get("/")
        self.post("/v1/tools/check_franchise_risk", {"brand_name": "비밀브랜드명",
                                                     "disclosure_days_before": 0})
        _, body, _ = self.get("/v1/stats?days=1")
        stats = json.loads(body)
        self.assertFalse(stats["privacy"]["stores_ip"])
        self.assertEqual(stats["privacy"]["stores_brand_names"], "zero_result_only")
        self.assertEqual(stats["privacy"]["stores_search_terms"], "zero_result_only")
        self.assertGreaterEqual(stats["totals"]["requests"], 2)
        self.assertIn("check_franchise_risk", stats["totals"]["tools"])
        self.assertIn("check_likely", stats["totals"]["verdicts"])
        blob = json.dumps(stats, ensure_ascii=False)
        self.assertNotIn("비밀브랜드명", blob)
        for key in stats["totals"]["paths"]:
            self.assertNotIn("?", key)
            self.assertTrue(key.startswith("/"))

    def test_zero_result_queries_over_http(self):
        status, body = self.post("/v1/tools/lookup_brand_disclosure",
                                 {"brand_name": "없는브랜드 010-1111-2222"})
        self.assertEqual(status, 200)
        self.assertTrue(body["result"]["zero_result"])
        _, stats_body, _ = self.get("/v1/stats?days=1")
        stats = json.loads(stats_body)
        self.assertIn("zero_result_queries", stats)
        self.assertTrue(stats["zero_result_queries"])
        self.assertNotIn("010-1111", stats_body)
        self.assertNotIn("2222", stats_body)
        self.assertEqual(stats["privacy"]["stores_brand_names"], "zero_result_only")
        for row in stats["zero_result_queries"]:
            self.assertLessEqual(len(row["query"]), 30)

    def test_inquiry_contact_never_in_stats(self):
        _, body, _ = self.get("/v1/stats?days=7")
        self.assertNotIn("review@example.com", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
