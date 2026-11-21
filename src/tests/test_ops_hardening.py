"""v0.1.6 회귀 — 운영 안정화: 요청 제한, 문의 유실 대비(알림·미러·조회).

1. HTTP 요청 제한 — 기본값이 있으면 429 + Retry-After 로 끊고, `/healthz` 는 예외.
   IP 는 저장하지 않고 프로세스 난수로 해시한 메모리 키만 쓴다.
2. `/v1/inquiry` 유실 대비 — 접수 성공 직후 웹훅 알림과 JSONL 미러를 남기고, 재시작 때
   미러에서 DB 로 복구한다. 기본 알림에는 연락처를 넣지 않는다(채널 노출 방지).
3. 문의 조회 — `GET /v1/inquiries` 는 관리자 토큰이 있을 때만, 없으면 404.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import api, notify, rate_limit, usage  # noqa: E402
from franchise_kr.server import config_from_env, make_handler  # noqa: E402
from franchise_kr.store import Store  # noqa: E402

KST = timezone(timedelta(hours=9))
DISABLED = {"admin_token": "", "rate_limit_per_minute": 0, "rate_write_per_minute": 0,
            "rate_window_seconds": 60, "env": {}}


def free_port():
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    server.server_close()
    return port


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RateLimiterTest(unittest.TestCase):
    def test_limit_then_retry_after(self):
        clock = FakeClock()
        limiter = rate_limit.RateLimiter(2, 60, clock=clock)
        self.assertTrue(limiter.check("k")["allowed"])
        second = limiter.check("k")
        self.assertTrue(second["allowed"])
        self.assertEqual(second["remaining"], 0)
        blocked = limiter.check("k")
        self.assertFalse(blocked["allowed"])
        self.assertGreaterEqual(blocked["retry_after"], 1)

    def test_window_resets(self):
        clock = FakeClock()
        limiter = rate_limit.RateLimiter(1, 60, clock=clock)
        self.assertTrue(limiter.check("k")["allowed"])
        self.assertFalse(limiter.check("k")["allowed"])
        clock.advance(61)
        self.assertTrue(limiter.check("k")["allowed"])

    def test_keys_are_isolated(self):
        limiter = rate_limit.RateLimiter(1, 60, clock=FakeClock())
        self.assertTrue(limiter.check("a")["allowed"])
        self.assertTrue(limiter.check("b")["allowed"])
        self.assertFalse(limiter.check("a")["allowed"])

    def test_client_key_does_not_leak_ip(self):
        key = rate_limit.client_key("203.0.113.9")
        self.assertNotIn("203.0.113", key)
        self.assertNotEqual(key, rate_limit.client_key("203.0.113.10"))

    def test_env_limits(self):
        cfg = rate_limit.limits_from_env({"FRNC_RATE_LIMIT_PER_MINUTE": "30",
                                          "FRNC_RATE_WRITE_PER_MINUTE": "5",
                                          "FRNC_RATE_WINDOW_SECONDS": "120"})
        self.assertEqual(cfg["per_minute"], 30)
        self.assertEqual(cfg["write_per_minute"], 5)
        self.assertEqual(cfg["window_seconds"], 120.0)
        self.assertEqual(rate_limit.limits_from_env({})["per_minute"],
                         rate_limit.DEFAULT_PER_MINUTE)


class HttpBase(unittest.TestCase):
    handler = None
    store = None

    @classmethod
    def build(cls, config=None, limiter=None, inquiry_limiter=None, store=None):
        cls.store = store or Store(":memory:")
        cls.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(cls.store, config=config or dict(DISABLED), limiter=limiter,
                         inquiry_limiter=inquiry_limiter))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path, headers=None):
        request = urllib.request.Request(self.url(path), headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read().decode("utf-8"), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), dict(exc.headers)

    def post(self, path, payload, headers=None):
        request = urllib.request.Request(
            self.url(path), data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


class RateLimitOverHttpTest(HttpBase):
    @classmethod
    def setUpClass(cls):
        cls.build(config=dict(DISABLED, rate_limit_per_minute=2),
                  limiter=rate_limit.RateLimiter(2, 60))

    def test_third_request_is_429_with_retry_after(self):
        first = self.get("/robots.txt")
        second = self.get("/robots.txt")
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertIn("X-RateLimit-Remaining", first[2])
        status, body, headers = self.get("/robots.txt")
        self.assertEqual(status, 429)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "rate_limited")
        self.assertIn("Retry-After", headers)
        self.assertTrue(payload["message_ko"])
        # 끊은 요청은 익명 카운터에 flag 로만 남는다.
        stats = usage.statistics(self.store, days=1)
        self.assertGreaterEqual(stats["totals"]["flags"].get(usage.FLAG_RATE_LIMIT, 0), 1)

    def test_healthz_is_exempt(self):
        for _ in range(4):
            status, body, _headers = self.get("/healthz")
            self.assertEqual(status, 200, body[:200])
        self.assertEqual(json.loads(body)["service"], "frnc")


class ForwardedForLimitTest(HttpBase):
    """프록시 뒤에서도 클라이언트별로 나뉘는지(X-Forwarded-For 마지막 값)."""

    @classmethod
    def setUpClass(cls):
        cls.build(config=dict(DISABLED), limiter=rate_limit.RateLimiter(1, 60))

    def test_each_forwarded_client_gets_its_own_bucket(self):
        first = self.get("/robots.txt", headers={"X-Forwarded-For": "203.0.113.1"})
        second = self.get("/robots.txt", headers={"X-Forwarded-For": "203.0.113.2"})
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        again = self.get("/robots.txt", headers={"X-Forwarded-For": "203.0.113.1"})
        self.assertEqual(again[0], 429)
        # 프록시가 체인을 붙이면 마지막 값이 실제 클라이언트다.
        chained = self.get("/robots.txt",
                           headers={"X-Forwarded-For": "10.0.0.5, 203.0.113.9"})
        self.assertEqual(chained[0], 200)


class InquiryLimitHttpTest(HttpBase):
    @classmethod
    def setUpClass(cls):
        cls.build(config=dict(DISABLED), inquiry_limiter=rate_limit.RateLimiter(1, 60))

    def test_second_inquiry_is_429(self):
        status, body = self.post("/v1/inquiry", {"contact": "a@example.com", "topic": "other"})
        self.assertEqual(status, 200, body)
        status, body = self.post("/v1/inquiry", {"contact": "b@example.com", "topic": "other"})
        self.assertEqual(status, 429, body)
        self.assertEqual(body["error"], "rate_limited")


class _CaptureHandler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length)
        type(self).received.append(json.loads(body.decode("utf-8")))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        return


class NotifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _CaptureHandler.received = []
        cls.hook = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
        cls.hook_port = cls.hook.server_address[1]
        threading.Thread(target=cls.hook.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.hook.shutdown()
        cls.hook.server_close()

    def env(self, **extra):
        env = {"FRNC_INQUIRY_WEBHOOK_URL": f"http://127.0.0.1:{self.hook_port}/hook"}
        env.update(extra)
        return env

    def test_webhook_payload_hides_contact_by_default(self):
        _CaptureHandler.received = []
        alert = notify.deliver({"contact": "person@example.com", "topic": "franchise_review",
                                "message": "BBQ 조건 검토 부탁드립니다."},
                               "F00007", "2026-11-21", env=self.env())
        self.assertTrue(alert["webhook"]["delivered"], alert)
        self.assertTrue(alert["durable_copy"])
        self.assertEqual(len(_CaptureHandler.received), 1)
        payload = _CaptureHandler.received[0]
        self.assertEqual(payload["event"], "frnc.inquiry")
        self.assertEqual(payload["receipt"], "F00007")
        self.assertNotIn("contact", payload)
        self.assertIn("새 문의", payload["text"])
        self.assertIn("BBQ", payload["message_preview_ko"])

    def test_contact_is_included_only_when_enabled(self):
        _CaptureHandler.received = []
        notify.deliver({"contact": "person@example.com", "topic": "other", "message": ""},
                       "F00008", "2026-11-21",
                       env=self.env(FRNC_INQUIRY_WEBHOOK_CONTACT="1"))
        self.assertEqual(_CaptureHandler.received[0]["contact"], "person@example.com")
        self.assertTrue(_CaptureHandler.received[0]["contact_included"])

    def test_webhook_failure_does_not_block_submission(self):
        dead = free_port()
        env = {"FRNC_INQUIRY_WEBHOOK_URL": f"http://127.0.0.1:{dead}/hook"}
        alert = notify.deliver({"contact": "x@example.com", "topic": "other", "message": ""},
                               "F00009", "2026-11-21", env=env)
        self.assertTrue(alert["webhook"]["configured"])
        self.assertFalse(alert["webhook"]["delivered"])
        self.assertFalse(alert["durable_copy"])

    def test_mirror_survives_and_restores(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "inquiries.jsonl")
            env = {"FRNC_INQUIRY_MIRROR": path}
            store = Store(":memory:")
            with mock_environ(env):
                result = api.submit_inquiry({"contact": "mirror@example.com",
                                             "topic": "api_mcp", "message": "복구 확인"},
                                            store)
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["alert"]["mirror"]["written"], result["alert"])
            self.assertTrue(os.path.exists(path))
            # 재시작으로 DB 가 비었다고 가정 — 미러에서 되돌린다.
            fresh = Store(":memory:")
            self.assertEqual(fresh.inquiry_count(), 0)
            restored = notify.restore(fresh, env=env)
            self.assertEqual(restored["imported"], 1, restored)
            self.assertEqual(fresh.inquiry_count(), 1)
            # 같은 파일을 다시 복구해도 중복으로 들어가지 않는다.
            self.assertEqual(notify.restore(fresh, env=env)["imported"], 0)
            fresh.close()
            store.close()

    def test_status_never_exposes_the_url(self):
        status = notify.status(self.env())
        blob = json.dumps(status, ensure_ascii=False)
        self.assertTrue(status["webhook"]["configured"])
        self.assertIn("127.0.0.1", status["webhook"]["host"])
        self.assertNotIn("/hook", blob)


class mock_environ:
    """os.environ 패치 헬퍼(테스트 간 환경변수 누수 방지)."""

    def __init__(self, values):
        self.values = values
        self.old = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.old[key] = os.environ.get(key)
            os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


class AdminInquiryTest(HttpBase):
    @classmethod
    def setUpClass(cls):
        cls.build(config=dict(DISABLED, admin_token="test-token"), store=Store(":memory:"))
        api.submit_inquiry({"contact": "reply@example.com", "topic": "franchise_review",
                            "message": "조건 검토 부탁드립니다."}, cls.store)

    def test_requires_token(self):
        status, body, _ = self.get("/v1/inquiries")
        self.assertEqual(status, 401)
        self.assertFalse(json.loads(body)["ok"])

    def test_wrong_token_is_401(self):
        status, _body, _ = self.get("/v1/inquiries", headers={"X-Admin-Token": "nope"})
        self.assertEqual(status, 401)

    def test_token_returns_recent_with_contact(self):
        status, body, _ = self.get("/v1/inquiries", headers={"X-Admin-Token": "test-token"})
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["summary"]["total"], 1)
        self.assertTrue(payload["recent"])
        self.assertEqual(payload["recent"][0]["contact"], "reply@example.com")
        self.assertTrue(payload["recent"][0]["receipt"].startswith("F"))
        self.assertFalse(payload["privacy"]["in_usage_stats"])
        self.assertNotIn("reply@example.com", json.dumps(usage.statistics(self.store, days=7),
                                                        ensure_ascii=False))

    def test_query_token_also_works(self):
        status, _body, _ = self.get("/v1/inquiries?token=test-token")
        self.assertEqual(status, 200)


class AdminInquiryDisabledTest(HttpBase):
    @classmethod
    def setUpClass(cls):
        cls.build(config=dict(DISABLED))

    def test_404_when_no_admin_token_configured(self):
        status, body, _ = self.get("/v1/inquiries")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")


class ConfigTest(unittest.TestCase):
    def test_config_reads_new_env(self):
        cfg = config_from_env({"FRNC_RATE_LIMIT_PER_MINUTE": "120",
                               "FRNC_ADMIN_TOKEN": "secret-token",
                               "FRNC_DB": ":memory:"})
        self.assertEqual(cfg["rate_limit_per_minute"], 120)
        self.assertEqual(cfg["admin_token"], "secret-token")

    def test_health_payload_reports_alerts_without_secrets(self):
        from franchise_kr.server import health_payload

        store = Store(":memory:")
        payload = health_payload(store, config_from_env({"FRNC_DB": ":memory:"}))
        self.assertIn("inquiries", payload)
        self.assertIn("alerts", payload)
        self.assertFalse(payload["alerts"]["webhook"]["configured"])
        self.assertIn("rate_limit", payload)
        self.assertFalse(payload["rate_limit"]["stores_ip"])
        store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
