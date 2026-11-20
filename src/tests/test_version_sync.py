"""버전·브랜드 문자열이 코드·매니페스트·문서에서 같은지 확인."""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import models, static_files, web_ui  # noqa: E402
from franchise_kr.version import (SERVICE_NAME, SERVICE_TAGLINE, SERVICE_TITLE_KO,  # noqa: E402
                                  __version__)


class VersionSyncTest(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(__version__, "0.1.1")

    def test_server_json_version(self):
        with open(os.path.join(PROJECT, "server.json"), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["version"], __version__)

    def test_dockerfile_label(self):
        with open(os.path.join(PROJECT, "Dockerfile"), "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(f'org.opencontainers.image.version="{__version__}"', text)

    def test_web_page_shows_version(self):
        html = web_ui.render_page({"data_state": "sample"})
        self.assertIn(f"v{__version__}", html)

    def test_brand_strings_are_single_source(self):
        html = web_ui.render_page({"data_state": "sample"})
        self.assertEqual(SERVICE_NAME, "FRNC")
        self.assertIn(SERVICE_TITLE_KO, html)
        self.assertIn(SERVICE_TAGLINE, html)
        card = static_files.server_card()
        self.assertEqual(card["serverInfo"]["version"], __version__)
        self.assertIn("FRNC", card["title"])

    def test_llms_and_sitemap(self):
        llms = static_files.llms_txt()
        self.assertIn("FRNC", llms)
        self.assertIn(__version__.replace(".", ".") if False else "FRNC", llms)
        sitemap = static_files.sitemap_xml()
        self.assertIn("<loc>https://frnc-kr.onrender.com/</loc>", sitemap)

    def test_schema_version(self):
        self.assertEqual(models.SCHEMA_VERSION, "1.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
