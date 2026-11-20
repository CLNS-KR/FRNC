"""질문형 가이드 15종 테스트 — 실검증 조문·구조화 데이터·얇은 페이지 방지·이스케이프.

가장 중요한 검사는 `test_guide_numbers_exist_in_cited_law` 입니다.
가이드 본문에 나오는 숫자(14일·7일·2개월·40% 등)는 그 가이드가 인용한 조문 안에
실제로 있어야 합니다. 브리프의 "모든 법령·수치는 law-verification.json 에서 실검증된
조문만 인용"을 테스트로 강제합니다.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import engine, guides, static_files  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(HERE))
LAW_PATH = os.path.join(PROJECT, "law-verification.json")

EXPECTED_SLUGS = {
    "cooling-off-14days", "projected-sales-statement", "franchise-fee-escrow",
    "interior-forced-purchase", "territory-protection", "closure-rate-reading",
    "excessive-penalty", "disclosure-false-claims", "termination-2months",
    "franchisee-association", "direct-store-1year", "ad-promotion-consent",
    "startup-subsidy-link", "renewal-10years", "dispute-mediation",
}


def flat(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


class GuideDataTest(unittest.TestCase):
    def test_fifteen_guides(self):
        self.assertEqual(len(guides.GUIDES), 15)
        self.assertEqual(set(guides.slugs()), EXPECTED_SLUGS)
        self.assertEqual(len(set(guides.slugs())), 15)

    def test_questions_and_topics_are_unique(self):
        questions = [guide["question"] for guide in guides.GUIDES]
        topics = [guide["topic"] for guide in guides.GUIDES]
        self.assertEqual(len(set(questions)), len(questions))
        self.assertEqual(len(set(topics)), len(topics))
        for question in questions:
            self.assertTrue(question.endswith("?"), question)

    def test_no_thin_pages(self):
        for guide in guides.GUIDES:
            slug = guide["slug"]
            self.assertGreaterEqual(len(guide["one_line"]), 60, slug)
            self.assertGreaterEqual(len(guide["points"]), 3, slug)
            self.assertGreaterEqual(len(guide["checklist"]), 3, slug)
            self.assertGreaterEqual(len(guide["pitfalls"]), 2, slug)
            self.assertGreaterEqual(len(guides.faq_pairs(guide)), 5, slug)
            self.assertTrue(guide["keywords"], slug)
            self.assertIn(guide["category"], guides.CATEGORY_LABEL, slug)

    def test_checklist_copy_changes_by_topic(self):
        for slug, (title, question) in guides.CHECK_COPY.items():
            guide = guides.by_slug(slug)
            self.assertIsNotNone(guide, slug)
            page = guides.render_item(slug) or ""
            self.assertIn(f"<h3>{title}</h3>", page, slug)
            self.assertEqual(guides.faq_pairs(guide)[2][0], f"{guide['topic']}: {question}", slug)
        for guide in guides.GUIDES:
            if guide["slug"] in guides.CHECK_COPY:
                continue
            self.assertEqual(guides.checklist_title(guide), guides.DEFAULT_CHECK_TITLE, guide["slug"])
            self.assertEqual(guides.checklist_question(guide),
                             guides.DEFAULT_CHECK_QUESTION, guide["slug"])

    def test_faq_question_particles(self):
        # '확인 순서은' 같은 조사 오류를 잡는다.
        for guide in guides.GUIDES:
            for question, answer in guides.faq_pairs(guide):
                self.assertNotIn("서은", question, guide["slug"])
                self.assertNotIn("순서은", question, guide["slug"])
                self.assertTrue(answer.strip(), question)
        subsidy = guides.by_slug("startup-subsidy-link")
        questions = [question for question, _ in guides.faq_pairs(subsidy)]
        self.assertIn("창업 지원금 확인 순서: 확인 순서는 무엇인가요?", questions)

    def test_related_links_resolve(self):
        for guide in guides.GUIDES:
            self.assertTrue(guide["related"], guide["slug"])
            for slug in guide["related"]:
                self.assertIsNotNone(guides.by_slug(slug), f"{guide['slug']} → {slug}")
                self.assertNotEqual(slug, guide["slug"])

    def test_law_basis_labels_have_no_duplicate_title(self):
        for guide in guides.GUIDES:
            for row in guides.law_blocks(guide):
                label = row.get("label_ko") or ""
                self.assertTrue(label, f"{guide['slug']}: {row['key']}")
                title = str(row.get("title") or "")
                if title:
                    self.assertEqual(label.count(title), 1,
                                     f"{guide['slug']}: {label}")

    def test_annex_rows_carry_effective_date(self):
        # 별표 레코드에는 시행일이 없어 법령 시행일로 채운다(빈 값 노출 방지).
        guide = guides.by_slug("territory-protection")
        self.assertIsNotNone(guide)
        rows = guides.law_blocks(guide)
        annex = [row for row in rows if "별표" in str(row.get("title") or "") or
                 "불공정거래행위" in str(row.get("key") or "")]
        self.assertTrue(annex)
        for row in annex:
            self.assertRegex(str(row["effective_on"]), r"^\d{8}$")

    def test_law_keys_exist_in_verification_file(self):
        with open(LAW_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        known = set(data["articles"]) | set(data["annexes"])
        for guide in guides.GUIDES:
            for key in guide.get("law_keys") or []:
                self.assertIn(key, known, f"{guide['slug']}: {key}")

    def test_every_guide_cites_a_law_unless_declared(self):
        for guide in guides.GUIDES:
            if guide["slug"] in guides.NO_LAW_CLAIM_SLUGS:
                self.assertFalse(guide.get("law_keys"), guide["slug"])
                self.assertTrue(guide.get("law_note_ko"), guide["slug"])
            else:
                self.assertTrue(guide.get("law_keys"), guide["slug"])
                self.assertTrue(guides.law_blocks(guide), guide["slug"])

    def test_guide_numbers_exist_in_cited_law(self):
        """본문의 숫자+단위가 그 가이드의 인용 조문 안에 실제로 있는지."""
        for guide in guides.GUIDES:
            keys = [key for key in guide.get("law_keys") or [] if engine.law_record(key)]
            corpus = flat("".join(engine.law_full_text(engine.law_record(key)) for key in keys))
            numbers = guides.guide_numbers(guide)
            if not keys:
                self.assertEqual(numbers, [], f"{guide['slug']}: 조문 없는 페이지에 수치가 있음 {numbers}")
                continue
            for number, unit in numbers:
                candidates = [f"{number}{unit}"]
                if unit == "%":
                    candidates = [f"100분의{number}", f"{number}퍼센트"]
                self.assertTrue(
                    any(candidate in corpus for candidate in candidates),
                    f"{guide['slug']}: '{number}{unit}' 이(가) 인용 조문에 없음",
                )

    def test_numeric_coverage_across_guides(self):
        """수치를 쓰는 페이지가 충분히 검증되고 있는지(빈 검사로 통과하지 않게)."""
        counted = sum(len(guides.guide_numbers(guide)) for guide in guides.GUIDES)
        self.assertGreaterEqual(counted, 30)
        with_numbers = [guide["slug"] for guide in guides.GUIDES if guides.guide_numbers(guide)]
        self.assertGreaterEqual(len(with_numbers), 10)

    def test_key_periods_are_cited(self):
        by_slug = {guide["slug"]: guide for guide in guides.GUIDES}
        expected = {
            "cooling-off-14days": [("14", "일"), ("7", "일")],
            "termination-2months": [("2", "개월"), ("2", "회")],
            "renewal-10years": [("180", "일"), ("10", "년")],
            "franchise-fee-escrow": [("30", "일"), ("10", "일")],
            "ad-promotion-consent": [("50", "%"), ("70", "%")],
        }
        for slug, tokens in expected.items():
            found = guides.guide_numbers(by_slug[slug])
            for token in tokens:
                self.assertIn(token, found, f"{slug}: {token}")

    def test_cited_articles_exist_in_law_file(self):
        """본문에 적은 '제N조'·'제N조의M' 인용이 실조회 파일에 실제로 있는지."""
        with open(LAW_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        known = set()
        for key in set(data["articles"]) | set(data["annexes"]):
            for part in key.split(":"):
                if part.startswith("제"):
                    known.add(part)
        pattern = re.compile(r"제(\d+)조(?:의(\d+))?")
        for guide in guides.GUIDES:
            text = guide_prose(guide)
            for number, sub_number in pattern.findall(text):
                want = f"제{number}조" + (f"의{sub_number}" if sub_number else "")
                self.assertIn(want, known, f"{guide['slug']}: {want}")

    def test_cited_articles_exist_in_law_file(self):
        """본문에 적은 '제N조'·'제N조의M' 인용이 실조회 파일에 실제로 있는지."""
        with open(LAW_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        known = set()
        for key in set(data["articles"]) | set(data["annexes"]):
            head, _, tail = key.partition(":")
            for part in (head, tail):
                if part.startswith("제"):
                    known.add(part)
                known.update(re.findall(r"제\d+조(?:의\d+)?", part))
        pattern = re.compile(r"제(\d+)조(?:의(\d+))?")
        for guide in guides.GUIDES:
            text = "\n".join(
                [guide["question"], guide["one_line"], guide.get("law_note_ko") or ""]
                + [str(row) for row in guide["points"]]
                + [str(row) for row in guide["checklist"]]
                + [str(row) for row in guide["pitfalls"]]
                + [str(row) for pair in guide.get("faq") or [] for row in pair]
            )
            for number, sub_number in pattern.findall(text):
                want = f"제{number}조" + (f"의{sub_number}" if sub_number else "")
                self.assertIn(want, known, f"{guide['slug']}: {want}")

    def test_relevant_slugs_for_brief_topics(self):
        # 브리프가 지정한 주제가 실제 페이지로 존재하는지(이름만 보고 넘어가지 않게).
        by_slug = {guide["slug"]: guide for guide in guides.GUIDES}
        self.assertIn("14일", by_slug["cooling-off-14days"]["topic"])
        self.assertIn("예상매출액", by_slug["projected-sales-statement"]["topic"])
        self.assertIn("예치", by_slug["franchise-fee-escrow"]["topic"])
        self.assertIn("인테리어", by_slug["interior-forced-purchase"]["topic"])
        self.assertIn("영업지역", by_slug["territory-protection"]["topic"])
        self.assertIn("폐점", by_slug["closure-rate-reading"]["topic"])
        self.assertIn("위약금", by_slug["excessive-penalty"]["topic"])
        self.assertIn("허위", by_slug["disclosure-false-claims"]["topic"])
        self.assertIn("2개월", by_slug["termination-2months"]["topic"])
        self.assertIn("단체", by_slug["franchisee-association"]["topic"])
        self.assertIn("직영점", by_slug["direct-store-1year"]["topic"])
        self.assertIn("광고", by_slug["ad-promotion-consent"]["topic"])
        self.assertIn("지원금", by_slug["startup-subsidy-link"]["topic"])


class GuideRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {guide["slug"]: guides.render_item(guide["slug"]) for guide in guides.GUIDES}
        cls.index = guides.render_index()

    def test_paths(self):
        paths = guides.paths()
        self.assertEqual(paths[0], "/guides/")
        self.assertEqual(len(paths), 16)
        self.assertIn("/guides/cooling-off-14days", paths)

    def test_every_page_renders(self):
        for slug, page in self.pages.items():
            self.assertTrue(page, slug)
            self.assertIn("<!doctype html>", page, slug)
            self.assertIn('lang="ko"', page, slug)
            self.assertIn('name="viewport"', page, slug)
            self.assertIn('rel="canonical"', page, slug)

    def test_unknown_slug_returns_none(self):
        self.assertIsNone(guides.render_item("no-such-guide"))
        self.assertIsNone(guides.render_item(""))
        self.assertIsNone(guides.render_item("../etc/passwd"))

    def test_structured_data_blocks(self):
        for slug, page in self.pages.items():
            blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
            self.assertGreaterEqual(len(blocks), 3, slug)
            parsed = [json.loads(block) for block in blocks]
            types = {item.get("@type") for item in parsed}
            for required in ("FAQPage", "BreadcrumbList", "WebPage"):
                self.assertIn(required, types, f"{slug}: {required}")
            faq = next(item for item in parsed if item.get("@type") == "FAQPage")
            questions = [row["name"] for row in faq["mainEntity"]]
            self.assertGreaterEqual(len(questions), 5, slug)
            self.assertTrue(all(row["acceptedAnswer"]["text"] for row in faq["mainEntity"]), slug)
            self.assertIn(guides.by_slug(slug)["question"], questions, slug)
            breadcrumb = next(item for item in parsed if item.get("@type") == "BreadcrumbList")
            self.assertEqual(len(breadcrumb["itemListElement"]), 3, slug)

    def test_single_h1_is_the_question(self):
        for guide in guides.GUIDES:
            page = self.pages[guide["slug"]]
            headings = re.findall(r"<h1[^>]*>(.*?)</h1>", page, re.S)
            self.assertEqual(len(headings), 1, guide["slug"])
            self.assertEqual(headings[0], html.escape(guide["question"], quote=True))
        index_headings = re.findall(r"<h1[^>]*>(.*?)</h1>", self.index, re.S)
        self.assertEqual(index_headings, ["프랜차이즈 계약, 무엇을 먼저 확인할까요"])

    def test_index_structured_data(self):
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', self.index, re.S)
        parsed = [json.loads(block) for block in blocks]
        types = {item.get("@type") for item in parsed}
        self.assertIn("CollectionPage", types)
        self.assertIn("BreadcrumbList", types)
        self.assertIn("WebPage", types)
        collection = next(item for item in parsed if item.get("@type") == "CollectionPage")
        self.assertEqual(len(collection["hasPart"]), 15)

    def test_page_shows_question_answer_and_law_text(self):
        for guide in guides.GUIDES:
            page = self.pages[guide["slug"]]
            self.assertTrue(html.escape(guide["topic"], quote=True) in page, guide["slug"])
            self.assertTrue(html.escape(guide["question"], quote=True) in page, guide["slug"])
            for row in guides.law_blocks(guide):
                snippet = html.escape(row["excerpt_ko"][:40], quote=True)
                self.assertTrue(snippet in page, f"{guide['slug']}: {row['key']}")

    def test_index_lists_all_guides(self):
        for guide in guides.GUIDES:
            self.assertIn(f'href="/guides/{guide["slug"]}"', self.index, guide["slug"])
            self.assertIn(guide["topic"], self.index, guide["slug"])

    def test_no_external_assets(self):
        for slug, page in self.pages.items():
            for forbidden in ("<script src=", "@import", "cdn.", "fonts.googleapis",
                              "localStorage", "sessionStorage", "document.cookie"):
                self.assertNotIn(forbidden, page, f"{slug}: {forbidden}")
            self.assertNotIn("http://", page, slug)

    def test_escapes_html(self):
        self.assertEqual(guides._esc("<b>&'"), "&lt;b&gt;&amp;&#x27;")
        evil = dict(guides.GUIDES[0])
        evil["slug"] = "escape-probe"
        evil["topic"] = '<script>alert(1)</script>'
        evil["question"] = '"><img src=x onerror=alert(1)>'
        evil["related"] = []
        evil["faq"] = []
        guides.GUIDES.append(evil)
        try:
            page = guides.render_item("escape-probe") or ""
        finally:
            guides.GUIDES.remove(evil)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)

    def test_each_page_links_back_and_to_check(self):
        for slug, page in self.pages.items():
            self.assertIn('href="/guides/"', page, slug)
            self.assertIn('href="/"', page, slug)
            self.assertIn("/#check", page, slug)

    def test_subsidy_guide_links_grant(self):
        page = self.pages["startup-subsidy-link"]
        self.assertIn("https://grnt-kr.onrender.com/", page)
        # 법령 판단이 없는 페이지는 '법이 정한 기준'이라는 제목을 쓰지 않는다.
        self.assertIn("<h3>확인 순서</h3>", page)
        self.assertNotIn("법이 정한 기준", page)
        self.assertIn("법령 판단이나 지원금 자격·금액을 확정하지 않습니다", page)

    def test_law_pages_use_law_heading(self):
        for guide in guides.GUIDES:
            if guide["slug"] in guides.NO_LAW_CLAIM_SLUGS:
                continue
            self.assertIn("<h3>법이 정한 기준</h3>", self.pages[guide["slug"]], guide["slug"])


class GuideFeedsTest(unittest.TestCase):
    def test_sitemap_lists_guides(self):
        sitemap = static_files.sitemap_xml("https://example.com")
        self.assertIn("<loc>https://example.com/guides/</loc>", sitemap)
        for guide in guides.GUIDES:
            self.assertIn(f"<loc>https://example.com/guides/{guide['slug']}</loc>", sitemap)
        self.assertEqual(sitemap.count("<url>"), 17)

    def test_llms_lists_guides(self):
        text = static_files.llms_txt("https://example.com")
        self.assertIn("## 질문형 가이드", text)
        for guide in guides.GUIDES:
            self.assertIn(f"https://example.com/guides/{guide['slug']}", text)
            self.assertIn(guide["question"], text)

    def test_robots_allow_guides(self):
        robots = static_files.robots_txt("https://example.com")
        self.assertIn("Allow: /", robots)
        self.assertIn("Disallow: /v1/", robots)
        self.assertNotIn("Disallow: /guides", robots)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class HtmlStructureTest(unittest.TestCase):
    """손으로 쓴 템플릿의 태그 짝 검사(브라우저가 자동 보정하기 전에 잡는다)."""

    VOID = {"br", "hr", "img", "input", "meta", "link", "source", "col", "area", "base", "wbr"}

    def check(self, page: str, label: str):
        from html.parser import HTMLParser

        void = self.VOID

        class Checker(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.stack = []
                self.errors = []

            def handle_starttag(self, tag, attrs):
                if tag not in void:
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if tag in void:
                    return
                if not self.stack:
                    self.errors.append(f"닫는 태그만 있음: {tag}")
                    return
                if self.stack[-1] == tag:
                    self.stack.pop()
                    return
                if tag in self.stack:
                    while self.stack and self.stack[-1] != tag:
                        self.errors.append(f"닫히지 않음: {self.stack.pop()}")
                    self.stack.pop()
                else:
                    self.errors.append(f"짝 없는 닫는 태그: {tag}")

        checker = Checker()
        checker.feed(page)
        checker.close()
        self.assertEqual(checker.errors, [], label)
        self.assertEqual(checker.stack, [], f"{label}: 닫히지 않은 태그 {checker.stack}")

    def test_home_and_guide_pages_are_well_formed(self):
        self.check(web_ui_pages.home(), "home")
        self.check(guides.render_index(), "index")
        for slug in guides.slugs():
            self.check(guides.render_item(slug) or "", slug)


class _HomePage:
    @staticmethod
    def home():
        from franchise_kr import web_ui

        return web_ui.render_page({"data_state": "sample"})


web_ui_pages = _HomePage()
