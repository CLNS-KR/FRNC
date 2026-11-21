"""패키징 검사 — Dockerfile·render.yaml·server.json·.env.example·README."""
from __future__ import annotations

import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))


def read(name):
    with open(os.path.join(PROJECT, name), "r", encoding="utf-8") as handle:
        return handle.read()


class DockerfileTest(unittest.TestCase):
    def setUp(self):
        self.text = read("Dockerfile")

    def test_base_image_and_no_pip(self):
        self.assertIn("FROM python:3.12-slim", self.text)
        self.assertNotIn("RUN pip", self.text)
        self.assertNotIn("requirements.txt", self.text)
        self.assertIn("PYTHONPATH=/app/src", self.text)

    def test_runs_as_non_root(self):
        self.assertIn("adduser", self.text)
        self.assertIn("USER app", self.text)

    def test_copies_verification_files_and_starts_server(self):
        self.assertIn("law-verification.json", self.text)
        self.assertIn("api-verification-*.json", self.text)
        self.assertIn('CMD ["python", "-m", "franchise_kr.server"]', self.text)

    def test_healthcheck(self):
        self.assertIn("HEALTHCHECK", self.text)
        self.assertIn("/healthz", self.text)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.text = read("render.yaml")

    def test_service_shape(self):
        self.assertIn("runtime: docker", self.text)
        self.assertIn("healthCheckPath: /healthz", self.text)
        # 서비스 이름·공개 주소는 https://frnc.onrender.com 과 일치해야 한다(옛 frnc-kr 금지).
        self.assertIn("name: frnc\n", self.text)
        self.assertNotIn("frnc-kr", self.text)
        self.assertIn("PUBLIC_BASE_URL", self.text)
        self.assertIn("value: https://frnc.onrender.com", self.text)

    def test_secret_is_not_inlined(self):
        self.assertIn("DATA_GO_KR_SERVICE_KEY", self.text)
        self.assertIn("sync: false", self.text)
        self.assertNotRegex(self.text, r"DATA_GO_KR_SERVICE_KEY\s*\n\s*value: [A-Za-z0-9]{16,}")


class ServerJsonTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(PROJECT, "server.json"), "r", encoding="utf-8") as handle:
            self.data = json.load(handle)

    def test_fields(self):
        self.assertEqual(self.data["name"], "io.github.CLNS-KR/frnc")
        self.assertIn("FRNC", self.data["title"])
        self.assertTrue(self.data["repository"]["url"].startswith("https://github.com/"))
        self.assertEqual(self.data["remotes"][0]["type"], "streamable-http")
        self.assertTrue(self.data["remotes"][0]["url"].endswith("/mcp"))

    def test_version_matches_code(self):
        import sys
        sys.path.insert(0, os.path.join(PROJECT, "src"))
        from franchise_kr.version import __version__
        self.assertEqual(self.data["version"], __version__)


class EnvAndIgnoreTest(unittest.TestCase):
    def test_env_example_documents_everything(self):
        text = read(".env.example")
        for key in ("DATA_GO_KR_SERVICE_KEY", "LAW_GO_KR_OC", "PORT", "HOST",
                    "PUBLIC_BASE_URL", "FRNC_DB"):
            self.assertIn(key, text, key)

    def test_dockerignore_excludes_tests_and_secrets(self):
        text = read(".dockerignore")
        for item in (".env", ".private-terms", "src/tests", "data/app.sqlite*"):
            self.assertIn(item, text)

    def test_gitignore_excludes_db(self):
        text = read(".gitignore")
        self.assertIn("data/app.sqlite", text)


class WorkflowTest(unittest.TestCase):
    """CI·레지스트리 게시 워크플로 — 툴 개수 단언과 게시 단계가 빠지지 않게 고정한다."""

    def test_test_workflow_asserts_seven_tools_and_smokes_scan(self):
        text = read(".github/workflows/test.yml")
        self.assertIn('== 7', text)
        self.assertNotIn('== 6', text)
        self.assertIn("/v1/tools/scan_contract_text", text)
        self.assertIn("scan_flagged", text)
        self.assertIn("not_a_clearance_ko", text)

    def test_publish_workflow_publishes_with_oidc(self):
        text = read(".github/workflows/publish-mcp-registry.yml")
        for marker in ("tags: [\"v*\"]", "workflow_dispatch", "id-token: write",
                       "mcp-publisher login github-oidc", "mcp-publisher publish",
                       "cosign verify-blob", "server.json", "remotes"):
            self.assertIn(marker, text, marker)
        self.assertNotIn("MCP_GITHUB_PAT", text)
        self.assertNotIn("ghp_", text)

    def test_server_json_url_matches_publish_workflow_check(self):
        text = read(".github/workflows/publish-mcp-registry.yml")
        with open(os.path.join(PROJECT, "server.json"), "r", encoding="utf-8") as handle:
            url = json.load(handle)["remotes"][0]["url"]
        self.assertIn("remotes", text)
        self.assertTrue(url.startswith("https://"))


class ReadmeTest(unittest.TestCase):
    def setUp(self):
        self.text = read("README.md")

    def test_readme_covers_the_basics(self):
        for marker in ("FRNC", "프랜차이즈", "확정 판정이 아닙니다", "/mcp", "/v1/tools",
                       "활용신청", "law-verification.json", "MIT",
                       "scan_contract_text", "특약·계약서 문구 1초 스캔",
                       "제시된 패턴에서 잡히지 않았을 뿐"):
            self.assertIn(marker, self.text, marker)

    def test_readme_documents_verification_limits(self):
        # 실측 승인 수(2026-11-21 기준 4/18)와 색인·미승인 데이터셋 한계를 적어 둔다.
        self.assertIn("승인 4", self.text)
        self.assertIn("brands_index.json.gz", self.text)
        self.assertIn("미승인", self.text)

    def test_readme_does_not_leak_secrets(self):
        self.assertNotIn("serviceKey=", self.text)
        self.assertNotRegex(self.text, r"DATA_GO_KR_SERVICE_KEY=[A-Za-z0-9]{10,}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
