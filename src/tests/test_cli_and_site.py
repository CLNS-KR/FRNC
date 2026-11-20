"""CLI·소유확인·정적 파일 보조 테스트."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from franchise_kr import site_verification, static_files  # noqa: E402


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ, PYTHONPATH=SRC, DATA_GO_KR_SERVICE_KEY="")
        return subprocess.run([sys.executable, "-m", "franchise_kr.cli", *args],
                              capture_output=True, text=True, timeout=60, env=env,
                              cwd=os.path.dirname(SRC))

    def test_check_command(self):
        out = self.run_cli("check", "--brand", "샘플치킨", "--days", "0", "--payment", "hq_account")
        self.assertEqual(out.returncode, 0, out.stderr[-300:])
        payload = json.loads(out.stdout)
        self.assertEqual(payload["verdict"]["code"], "check_likely")
        self.assertIn("샘플치킨", payload["summary_ko"])

    def test_law_command(self):
        out = self.run_cli("law", "제6조의5")
        self.assertEqual(out.returncode, 0)
        payload = json.loads(out.stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("예치", payload["text"])

    def test_lookup_command(self):
        out = self.run_cli("lookup", "--brand", "샘플치킨")
        self.assertEqual(out.returncode, 0)
        payload = json.loads(out.stdout)
        self.assertEqual(payload["data_state"], "sample")

    def test_cases_command(self):
        out = self.run_cli("cases")
        self.assertEqual(out.returncode, 0)
        payload = json.loads(out.stdout)
        self.assertEqual(payload["count"], 15)


class SiteVerificationTest(unittest.TestCase):
    def test_no_env_means_no_output(self):
        self.assertEqual(site_verification.meta_tags({}), "")
        self.assertIsNone(site_verification.file_body("/x.html", {}))

    def test_tokens_are_sanitized(self):
        tags = site_verification.meta_tags({
            "GOOGLE_SITE_VERIFICATION": 'abc"onload="alert(1)',
            "NAVER_SITE_VERIFICATION": "naver123",
        })
        # 위험한 문자(따옴표·부등호·괄호)는 모두 제거되어 속성 밖으로 나가지 못한다.
        self.assertNotIn('onload="', tags)
        self.assertNotIn("onload=", tags)
        self.assertIn('content="abconloadalert1"', tags)
        self.assertIn('name="naver-site-verification"', tags)

    def test_verification_files_are_whitelisted(self):
        env = {"SITE_VERIFICATION_FILES": json.dumps({
            "google123.html": "google-site-verification: google123.html",
            "../../etc/passwd": "bad",
        })}
        self.assertEqual(site_verification.file_body("/google123.html", env),
                         "google-site-verification: google123.html")
        self.assertIsNone(site_verification.file_body("/../../etc/passwd", env))

    def test_page_includes_meta_when_env_set(self):
        from franchise_kr import web_ui
        os.environ["GOOGLE_SITE_VERIFICATION"] = "test-token-123"
        try:
            html = web_ui.render_page({"data_state": "sample"})
        finally:
            os.environ.pop("GOOGLE_SITE_VERIFICATION", None)
        self.assertIn('name="google-site-verification" content="test-token-123"', html)


class StaticFilesTest(unittest.TestCase):
    def test_base_url_env(self):
        os.environ["PUBLIC_BASE_URL"] = "https://example.com/"
        try:
            self.assertEqual(static_files.base_url(), "https://example.com")
            self.assertIn("https://example.com/sitemap.xml", static_files.robots_txt())
            self.assertIn("<loc>https://example.com/</loc>", static_files.sitemap_xml())
        finally:
            os.environ.pop("PUBLIC_BASE_URL", None)

    def test_server_card_tools_and_transports(self):
        card = static_files.server_card()
        self.assertEqual(len(card["tools"]), 6)
        self.assertFalse(card["authentication"]["required"])
        self.assertEqual(card["transport"]["type"], "streamable-http")
        self.assertEqual(card["transports"]["stdio"]["args"][-1], "franchise_kr.mcp_stdio")

    def test_llms_states_sample_mode(self):
        text = static_files.llms_txt()
        self.assertIn("샘플", text)
        self.assertIn("가맹사업정보제공시스템", text)

    def test_llms_and_sitemap_include_guides(self):
        from franchise_kr import guides
        llms = static_files.llms_txt()
        self.assertIn("## 질문형 가이드", llms)
        sitemap = static_files.sitemap_xml()
        self.assertIn("https://frnc-kr.onrender.com/guides/", sitemap)
        for guide in guides.GUIDES:
            self.assertIn(f"https://frnc-kr.onrender.com/guides/{guide['slug']}", llms)
            self.assertIn(f"<loc>https://frnc-kr.onrender.com/guides/{guide['slug']}</loc>", sitemap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
