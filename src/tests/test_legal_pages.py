"""정적 고지 페이지(`/privacy`·`/terms`·`/about`)·공유 카드 회귀 테스트 — 0.1.9.

확인하는 것
- 세 주소가 실제 HTTP 200 HTML 로 열리고 HEAD 도 200 이다.
- canonical·og:image 가 홈·가이드·고지 페이지에 있고, `/static/og.png` 는 실제 1200×630 PNG 다.
- 이미지 파일이 없어도 표준 라이브러리 생성 PNG 로 200 이 유지된다.
- 푸터·사이트맵·익명 카운터가 세 주소를 안다.
- 익명 운영 원칙: 실명·직업·개인 연락처·상대 서비스 핸들이 없다.
"""
from __future__ import annotations

import os
import re
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import guides, legal, static_files, usage, web_ui  # noqa: E402
from franchise_kr.server import make_handler  # noqa: E402
from franchise_kr.store import Store  # noqa: E402

SLUGS = ("privacy", "terms", "about")


class LegalPagesHttpTest(unittest.TestCase):
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
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()

    def test_pages_served_as_html(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                status, content_type, body = self._get(f"/{slug}")
                self.assertEqual(status, 200)
                self.assertIn("text/html", content_type)
                text = body.decode("utf-8")
                self.assertIn(legal.TITLES[slug], text)
                self.assertIn('lang="ko"', text)

    def test_trailing_slash_and_head(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                self.assertEqual(self._get(f"/{slug}/")[0], 200)
                req = urllib.request.Request(f"http://127.0.0.1:{self.port}/{slug}", method="HEAD")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)

    def test_canonical_and_og_image(self):
        root = static_files.base_url()
        home = self._get("/")[2].decode("utf-8")
        self.assertIn(f'<link rel="canonical" href="{root}/">', home)
        self.assertIn(f'<meta property="og:image" content="{root}/static/og.png">', home)
        guide = guides.GUIDES[0]["slug"]
        page = self._get(f"/guides/{guide}")[2].decode("utf-8")
        self.assertIn(f'<meta property="og:image" content="{root}/static/og.png">', page)
        self.assertIn(f'<link rel="canonical" href="{root}/guides/{guide}">', page)
        for slug in SLUGS:
            with self.subTest(slug=slug):
                text = self._get(f"/{slug}")[2].decode("utf-8")
                self.assertIn(f'<link rel="canonical" href="{root}/{slug}">', text)
                self.assertIn(f'<meta property="og:image" content="{root}/static/og.png">', text)

    def test_og_png_is_1200x630(self):
        status, content_type, body = self._get("/static/og.png")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", body[16:24]), (1200, 630))

    def test_unknown_path_still_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/privacy-policy")
        self.assertEqual(ctx.exception.code, 404)


class LegalContentTest(unittest.TestCase):
    def test_home_footer_links_pages(self):
        page = web_ui.render_page({"data_state": "sample"})
        for slug in SLUGS:
            self.assertIn(f'href="/{slug}"', page)

    def test_sitemap_lists_pages(self):
        xml = static_files.sitemap_xml()
        root = static_files.base_url()
        for slug in SLUGS:
            self.assertIn(f"<loc>{root}/{slug}</loc>", xml)

    def test_stats_counts_pages_not_404(self):
        for slug in SLUGS:
            self.assertEqual(usage.path_key(f"/{slug}"), f"/{slug}")

    def test_privacy_retention_and_delete_path(self):
        body = legal.render("privacy")
        self.assertIn("180일", body)
        self.assertIn("/v1/inquiry", body)
        self.assertIn("삭제", body)
        self.assertIn("IP", body)
        self.assertIn("0건", body)

    def test_terms_disclaims_expert_substitution(self):
        body = legal.render("terms")
        self.assertIn("확정하지 않습니다", body)
        self.assertIn("가맹거래사", body)
        self.assertIn("무료", body)
        self.assertIn("책임", body)

    def test_about_covers_three_services_and_sources(self):
        body = legal.render("about")
        for name in ("FRNC", "CLNS", "GRNT"):
            self.assertIn(name, body)
        self.assertIn("가맹사업법", body)
        self.assertIn("정보공개서", body)

    def test_fallback_png_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            body = static_files.load_og_image({"FRNC_OG_IMAGE": os.path.join(tmp, "missing.png")})
        self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", body[16:24]), (1200, 630))

    def test_no_identity_leak(self):
        forbidden = [r"@[a-z0-9.-]+\.(?:com|net|co\.kr|kr)", r"01\d[- ]?\d{3,4}[- ]?\d{4}",
                     r"조" r"종사", r"파" r"일럿", r"@pi" r"lot", r"Pilo" r"tage", r"비" r"행"]
        for slug in SLUGS:
            body = legal.render(slug)
            for pattern in forbidden:
                with self.subTest(slug=slug, pattern=pattern):
                    self.assertIsNone(re.search(pattern, body, re.IGNORECASE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
