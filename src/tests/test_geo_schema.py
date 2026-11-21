"""AI 검색(GEO)·검색엔진용 출력 검사 — JSON-LD·robots·sitemap·llms.txt.

검증하는 것
-----------
1. 홈에 구조화 데이터가 있고, Organization · WebSite · WebApplication 이 `@id` 로 이어지는지
2. 모든 JSON-LD 블록이 **유효한 JSON** 이고 `@context`/`@type` 을 갖는지
3. robots.txt 가 주요 AI 크롤러를 빠뜨리지 않았는지, sitemap 이 XML 로 읽히는지
4. llms.txt 링크가 전부 절대 주소인지, 구조화 데이터 안내가 있는지
5. 홈 인라인 `<script>` 가 구조화 데이터 삽입 뒤에도 그대로 파싱되는지(먼저 나오는 `<script>` 가 본문 스크립트인지)
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from franchise_kr import guides, legal, static_files, web_ui  # noqa: E402
from franchise_kr.version import SERVICE_URL  # noqa: E402

LD_PATTERN = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
AI_CRAWLERS = ("GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-SearchBot", "PerplexityBot",
               "Google-Extended", "CCBot", "Applebot-Extended", "Bingbot")


def _blocks(page: str):
    return [json.loads(body) for body in LD_PATTERN.findall(page)]


class HomeJsonLdTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = web_ui.render_page({"data_state": "sample"})

    def test_graph_is_linked(self):
        blocks = _blocks(self.page)
        self.assertEqual(len(blocks), 1)
        graph = blocks[0]["@graph"]
        self.assertEqual([node["@type"] for node in graph],
                         ["Organization", "WebSite", "WebApplication"])
        ids = {node["@id"] for node in graph}
        website = next(node for node in graph if node["@type"] == "WebSite")
        app = next(node for node in graph if node["@type"] == "WebApplication")
        self.assertIn(website["publisher"]["@id"], ids)
        self.assertEqual(app["isPartOf"]["@id"], website["@id"])
        self.assertEqual(app["offers"]["price"], "0")
        self.assertTrue(app["isAccessibleForFree"])
        self.assertTrue(app["featureList"])
        self.assertEqual(website["potentialAction"]["@type"], "SearchAction")
        self.assertIn("?brand=", website["potentialAction"]["target"]["urlTemplate"])

    def test_urls_use_service_url(self):
        graph = _blocks(self.page)[0]["@graph"]
        for node in graph:
            self.assertTrue(node["@id"].startswith(SERVICE_URL), node["@id"])
            self.assertTrue(node["url"].startswith(SERVICE_URL), node["url"])

    def test_inline_script_still_first_bare_script(self):
        # 홈 테스트들이 page.split("<script>", 1) 로 본문 스크립트를 꺼낸다 — 구조화 데이터는
        # type 속성이 있으므로 그 앞에 와도 첫 '<script>' 가 바뀌지 않아야 한다.
        self.assertTrue(self.page.split("<script>", 1)[1].lstrip().startswith("(function"))

    def test_head_meta_complete(self):
        head = self.page.split("</head>", 1)[0]
        for marker in ('<title>', 'name="description"', 'rel="canonical"',
                       'property="og:title"', 'property="og:url"', 'name="twitter:card"',
                       'name="theme-color"'):
            self.assertIn(marker, head, marker)
        self.assertEqual(head.count("<title>"), 1)


class PageJsonLdTest(unittest.TestCase):
    def test_guides_index_and_item(self):
        index = guides.render_index()
        types = [block["@type"] for block in _blocks(index)]
        self.assertIn("CollectionPage", types)
        self.assertIn("BreadcrumbList", types)

        slug = guides.slugs()[0]
        page = guides.render_item(slug)
        blocks = _blocks(page)
        faq = next(block for block in blocks if block["@type"] == "FAQPage")
        self.assertGreaterEqual(len(faq["mainEntity"]), 2)
        for question in faq["mainEntity"]:
            self.assertEqual(question["@type"], "Question")
            self.assertTrue(question["acceptedAnswer"]["text"])

    def test_legal_pages_have_valid_json(self):
        for path in ("/about", "/privacy", "/terms"):
            page = legal.render(path)
            self.assertIsNotNone(page, path)
            for block in _blocks(page):
                self.assertIn("@context", block)

    def test_no_unescaped_closing_tag(self):
        for page in (web_ui.render_page({"data_state": "sample"}), guides.render_index(),
                     guides.render_item(guides.slugs()[0])):
            for body in LD_PATTERN.findall(page):
                self.assertNotIn("</", body.replace("<\\/", ""))


class CrawlerFilesTest(unittest.TestCase):
    def test_robots_allows_ai_crawlers(self):
        text = static_files.robots_txt("https://example.test")
        self.assertIn("Disallow: /v1/", text)
        self.assertIn("Sitemap: https://example.test/sitemap.xml", text)
        self.assertIn("llms.txt", text)
        for crawler in AI_CRAWLERS:
            self.assertIn(f"User-agent: {crawler}", text, crawler)
            block = text.split(f"User-agent: {crawler}", 1)[1].split("\n\n", 1)[0]
            self.assertIn("Allow: /", block, crawler)

    def test_sitemap_is_valid_xml(self):
        xml = static_files.sitemap_xml("https://example.test")
        root = ElementTree.fromstring(xml)
        namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        locs = [node.text for node in root.iter(f"{namespace}loc")]
        self.assertTrue(locs)
        self.assertEqual(len(locs), len(set(locs)))
        for loc in locs:
            self.assertTrue(loc.startswith("https://example.test/"), loc)
        for path in ("/", "/guides/", "/about", "/privacy", "/terms"):
            self.assertIn("https://example.test" + path, locs, path)
        for slug in guides.slugs():
            self.assertIn(f"https://example.test/guides/{slug}", locs, slug)
        for node in root.iter(f"{namespace}lastmod"):
            self.assertRegex(node.text, r"^\d{4}-\d{2}-\d{2}$")

    def test_llms_links_are_absolute(self):
        text = static_files.llms_txt()
        links = re.findall(r"\]\(([^)]+)\)", text)
        self.assertTrue(links)
        for link in links:
            self.assertTrue(link.startswith("http"), link)
        self.assertIn("## 구조화 데이터(JSON-LD)", text)
        for marker in ("## 사람용", "## 기계용 (MCP · JSON-RPC 2.0)", "## 기계용 (REST JSON)",
                       "check_likely", "info_needed", "low_risk"):
            self.assertIn(marker, text, marker)

    def test_server_card_lists_tools(self):
        card = static_files.server_card()
        self.assertFalse(card["authentication"]["required"])
        self.assertTrue(card["tools"])
        self.assertEqual(card["serverInfo"]["name"], "frnc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
