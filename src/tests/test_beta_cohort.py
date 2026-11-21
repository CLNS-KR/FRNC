"""0.1.7 — 무료 베타 유입 태그(`cohort`/`source`)와 3종 생태계 링크 회귀 테스트.

두 가지를 고정한다.
1. `POST /v1/inquiry` 의 **선택** 필드 `cohort`(별칭 `source`) — 없으면 종전 요청과 100% 같고,
   있으면 저장ㆍ미러ㆍ웹훅ㆍ관리자 요약(`by_cohort`)까지 태그가 따라간다.
2. 홈 화면의 `같이 쓰는 서비스` 카드 — CLNS(수입·유통)ㆍGRNT(정부지원금)로 가는 한 줄 링크가
   CLNS·GRNT 화면과 같은 문구로 있고, 외부 링크는 새 탭 + noopener 다.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from franchise_kr import api, notify, server, usage, web_ui  # noqa: E402
from franchise_kr.server import make_handler  # noqa: E402
from franchise_kr.store import Store  # noqa: E402
from franchise_kr.version import CLNS_URL, GRANT_URL  # noqa: E402

CONTACT = "beta" + "@" + "frnc.test"
MESSAGE = "베타 파일럿으로 샘플치킨 조건을 검토해 봤습니다"
PHONE = "010" + "-1111-2222"

OLD_SCHEMA = """
CREATE TABLE inquiries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    topic      TEXT NOT NULL,
    contact    TEXT NOT NULL,
    message    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class CohortNormalizeTest(unittest.TestCase):
    def test_absent_tag_is_empty(self):
        for payload in ({"contact": CONTACT, "topic": "api_mcp"},
                        {"contact": CONTACT, "topic": "other", "cohort": ""},
                        {"contact": CONTACT, "topic": "other", "cohort": None}):
            with self.subTest(payload=payload):
                clean, error = usage.normalize_inquiry(payload)
                self.assertIsNone(error)
                self.assertEqual(clean["cohort"], "")

    def test_alias_and_normalization(self):
        clean, error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "other", "cohort": " Beta_Pilot "})
        self.assertIsNone(error)
        self.assertEqual(clean["cohort"], "beta_pilot")
        clean, error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "other", "source": "citechart"})
        self.assertIsNone(error)
        self.assertEqual(clean["cohort"], "citechart")

    def test_boundary_and_bad_values(self):
        clean, error = usage.normalize_inquiry(
            {"contact": CONTACT, "topic": "other", "cohort": "b" * usage.INQUIRY_COHORT_MAX})
        self.assertIsNone(error)
        self.assertEqual(len(clean["cohort"]), 40)
        for value in ("b" * 41, "베타", "beta pilot", "beta/pilot", 7, ["beta_pilot"]):
            with self.subTest(value=value):
                _clean, error = usage.normalize_inquiry(
                    {"contact": CONTACT, "topic": "other", "cohort": value})
                self.assertEqual(error, "invalid_cohort")
                self.assertNotIn("{", usage.INQUIRY_ERRORS_KO["invalid_cohort"])


class CohortStorageTest(unittest.TestCase):
    def test_store_roundtrip_and_summary(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        store.add_inquiry("2026-11-21", "franchise_review", CONTACT, MESSAGE, cohort="beta_pilot")
        store.add_inquiry("2026-11-21", "api_mcp", PHONE, "", cohort="citechart")
        self.assertEqual(store.inquiry_cohort_counts(), {"beta_pilot": 1, "citechart": 1})
        recent = store.recent_inquiries(5)
        self.assertEqual({row["cohort"] for row in recent}, {"beta_pilot", "citechart"})
        summary = usage.inquiry_summary(store)
        counts = {row["cohort"]: row["count"] for row in summary["by_cohort"]}
        self.assertEqual(counts, {"beta_pilot": 1, "citechart": 1})
        self.assertNotIn(CONTACT, json.dumps(summary, ensure_ascii=False))

    def test_existing_db_is_migrated(self):
        directory = tempfile.mkdtemp(prefix="frnc-legacy-")
        path = os.path.join(directory, "app.sqlite")
        conn = sqlite3.connect(path)
        conn.executescript(OLD_SCHEMA)
        conn.execute("INSERT INTO inquiries(day, topic, contact, message, created_at) "
                     "VALUES ('2026-11-20','other','old','이전 문의','2026-11-20T10:00:00')")
        conn.commit()
        conn.close()
        store = Store(path)
        self.addCleanup(store.close)
        store.add_inquiry("2026-11-21", "other", CONTACT, "", cohort="beta_pilot")
        self.assertEqual(store.inquiry_cohort_counts(), {"": 1, "beta_pilot": 1})


class CohortNotifyTest(unittest.TestCase):
    def test_mirror_and_webhook_carry_tag(self):
        directory = tempfile.mkdtemp(prefix="frnc-mirror-")
        mirror = os.path.join(directory, "inquiries.jsonl")
        clean = {"contact": CONTACT, "topic": "franchise_review", "message": MESSAGE,
                 "cohort": "beta_pilot"}
        sent = {}

        class _Response:
            status = 200

            def close(self):
                return None

        def fake_urlopen(request, timeout=None):
            sent["body"] = json.loads(request.data.decode("utf-8"))
            return _Response()

        with mock.patch.dict(os.environ, {"FRNC_INQUIRY_MIRROR": mirror,
                                          "FRNC_INQUIRY_WEBHOOK_URL": "https://hook.example.test/x"},
                             clear=False), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            alert = notify.deliver(clean, "F00001", "2026-11-21")
        self.assertTrue(alert["mirror"]["written"])
        with open(mirror, encoding="utf-8") as handle:
            line = json.loads(handle.readline())
        self.assertEqual(line["cohort"], "beta_pilot")
        self.assertEqual(sent["body"]["cohort"], "beta_pilot")
        self.assertIn("beta_pilot", sent["body"]["text"])
        self.assertNotIn(CONTACT, json.dumps(sent["body"], ensure_ascii=False))

    def test_restore_keeps_tag(self):
        directory = tempfile.mkdtemp(prefix="frnc-restore-")
        mirror = os.path.join(directory, "inquiries.jsonl")
        with open(mirror, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"receipt": "F00001", "day": "2026-11-21",
                                     "topic": "other", "contact": CONTACT,
                                     "message": "미러 문의", "cohort": "citechart"},
                                    ensure_ascii=False) + "\n")
        store = Store(":memory:")
        self.addCleanup(store.close)
        with mock.patch.dict(os.environ, {"FRNC_INQUIRY_MIRROR": mirror}, clear=False):
            result = notify.restore(store)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(store.inquiry_cohort_counts(), {"citechart": 1})

    def test_healthz_stays_without_cohort_counts(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        store.add_inquiry("2026-11-21", "other", CONTACT, "", cohort="beta_pilot")
        public = server.health_payload(store, {})["inquiries"]
        self.assertNotIn("by_cohort", public)
        admin = usage.inquiry_summary(store)
        self.assertEqual(admin["by_cohort"], [{"cohort": "beta_pilot", "count": 1}])

    def test_webhook_omits_tag_when_empty(self):
        clean = {"contact": CONTACT, "topic": "other", "message": ""}
        payload = notify.webhook_payload(clean, "F00002", "2026-11-21", notify.config({}))
        self.assertNotIn("cohort", payload)


class CohortSubmitTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.payload = {"contact": CONTACT, "topic": "franchise_review", "message": MESSAGE}

    def test_response_and_row(self):
        result = api.submit_inquiry({**self.payload, "source": "beta_pilot"}, self.store,
                                    day="2026-11-21")
        self.assertTrue(result["ok"])
        self.assertEqual(result["cohort"], "beta_pilot")
        self.assertNotIn(CONTACT, json.dumps(result, ensure_ascii=False))
        row = self.store.conn.execute("SELECT cohort FROM inquiries").fetchone()
        self.assertEqual(row["cohort"], "beta_pilot")

    def test_without_tag_keeps_old_contract(self):
        result = api.submit_inquiry(self.payload, self.store, day="2026-11-21")
        self.assertTrue(result["ok"])
        self.assertEqual(result["cohort"], "")

    def test_bad_tag_is_rejected(self):
        result = api.submit_inquiry({**self.payload, "cohort": "beta pilot"}, self.store)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_cohort")
        self.assertIn("베타 구분 태그", result["message_ko"])
        self.assertIn("beta_pilot", result["message_ko"])
        self.assertNotIn("{", result["message_ko"])
        self.assertEqual(self.store.inquiry_count(), 0)


class CohortHttpTest(unittest.TestCase):
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

    def _post(self, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/inquiry",
            data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_post_with_cohort(self):
        status, body = self._post({"contact": CONTACT, "topic": "other", "cohort": "beta_pilot"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["cohort"], "beta_pilot")

    def test_post_without_cohort(self):
        status, body = self._post({"contact": "plain" + "@" + "frnc.test", "topic": "other"})
        self.assertEqual(status, 200)
        self.assertEqual(body["cohort"], "")

    def test_bad_cohort_is_400(self):
        status, body = self._post({"contact": CONTACT, "topic": "other", "cohort": "bad tag"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_cohort")


class CohortWebFormTest(unittest.TestCase):
    def setUp(self):
        self.page = web_ui.render_page()

    def test_form_forwards_query_param_tag(self):
        self.assertIn("function cohortTag(", self.page)
        self.assertIn("cohort: cohortTag()", self.page)
        self.assertIn('get("cohort")', self.page)
        self.assertIn("[a-z0-9][a-z0-9._:-]{0,39}", self.page)


class SiblingNavTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = web_ui.render_page()

    def test_card_lists_both_services(self):
        self.assertIn('id="siblings"', self.page)
        card = self.page[self.page.index('id="siblings"'):]
        card = card[:card.index("</section>")]
        self.assertIn("같이 쓰는 서비스", card)
        self.assertIn(CLNS_URL, card)
        self.assertIn(GRANT_URL, card)
        self.assertIn("수입", card)
        self.assertIn("지원금", card)

    def test_footer_has_one_line(self):
        foot = self.page[self.page.index('<p class="foot">'):]
        foot = foot[:foot.index("</p>")]
        self.assertIn("같이 쓰는 도구", foot)
        self.assertIn(CLNS_URL, foot)
        self.assertIn(GRANT_URL, foot)

    def test_external_links_open_safely(self):
        for url in (CLNS_URL, GRANT_URL):
            out = self.page
            seen = 0
            while True:
                at = out.find(url)
                if at == -1:
                    break
                start = out.rindex("<a ", 0, at)
                tag = out[start:out.index(">", start) + 1]
                self.assertIn('target="_blank"', tag, url)
                self.assertIn('rel="noopener noreferrer"', tag, url)
                out = out[at + len(url):]
                seen += 1
            self.assertGreaterEqual(seen, 2, url)

    def test_card_sits_before_the_footer(self):
        self.assertLess(self.page.index('id="siblings"'), self.page.index('<p class="foot">'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
