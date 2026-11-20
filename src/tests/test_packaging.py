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
        self.assertIn("name: frnc-kr", self.text)
        self.assertIn("PUBLIC_BASE_URL", self.text)

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


class ReadmeTest(unittest.TestCase):
    def setUp(self):
        self.text = read("README.md")

    def test_readme_covers_the_basics(self):
        for marker in ("FRNC", "프랜차이즈", "확정 판정이 아닙니다", "/mcp", "/v1/tools",
                       "활용신청", "law-verification.json", "MIT"):
            self.assertIn(marker, self.text, marker)

    def test_readme_documents_verification_limits(self):
        self.assertRegex(self.text, r"승인\s*0")
        self.assertIn("샘플", self.text)

    def test_readme_does_not_leak_secrets(self):
        self.assertNotIn("serviceKey=", self.text)
        self.assertNotRegex(self.text, r"DATA_GO_KR_SERVICE_KEY=[A-Za-z0-9]{10,}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
