"""인라인 자바스크립트 구조 검사 — esprima 없이 하는 괄호·문자열·정규식 균형 검증.

외부 의존(pip) 없이 돌아야 하므로 파서 대신 작은 토크나이저를 씁니다. 문자열·주석·정규식
리터럴을 걷어낸 **코드만** 남겨 괄호 짝과 템플릿 문자열 금지를 확인합니다. 브라우저에서
한 줄이라도 문법이 깨지면 화면 전체가 죽기 때문에, 배포 전 최소 방어선으로 둡니다.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import guides, web_ui  # noqa: E402

REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%~^<>")


def strip_js(source: str) -> str:
    """문자열·주석·정규식 리터럴을 지운 코드만 돌려준다."""
    out = []
    index = 0
    length = len(source)
    previous = ""            # 직전 의미 있는 문자(정규식 판별용)
    while index < length:
        char = source[index]
        if source.startswith("//", index):
            newline = source.find("\n", index)
            index = length if newline < 0 else newline
            continue
        if source.startswith("/*", index):
            close = source.find("*/", index + 2)
            index = length if close < 0 else close + 2
            continue
        if char in "'\"":
            quote = char
            index += 1
            while index < length:
                if source[index] == "\\":
                    index += 2
                    continue
                if source[index] == quote:
                    index += 1
                    break
                index += 1
            out.append("S")
            previous = "S"
            continue
        if char == "/" and (previous == "" or previous in REGEX_PRECEDERS):
            # 정규식 리터럴 — 문자 클래스 안의 '/' 는 종료가 아니다.
            index += 1
            in_class = False
            while index < length:
                current = source[index]
                if current == "\\":
                    index += 2
                    continue
                if current == "[":
                    in_class = True
                elif current == "]":
                    in_class = False
                elif current == "/" and not in_class:
                    index += 1
                    break
                index += 1
            # 플래그(g, i, m …)는 문자 하나로 뭉갠다.
            while index < length and source[index].isalpha():
                index += 1
            out.append("R")
            previous = "R"
            continue
        if not char.isspace():
            previous = char
        out.append(char)
        index += 1
    return "".join(out)


def inline_scripts(page: str) -> list:
    return [block for block in re.findall(r"<script>(.*?)</script>", page, re.S)]


class JsStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = web_ui.render_page({"data_state": "sample"})
        cls.script = "\n".join(inline_scripts(cls.home))
        cls.code = strip_js(cls.script)

    def test_home_has_one_inline_script(self):
        self.assertEqual(len(inline_scripts(self.home)), 1)

    def test_tokens_are_balanced(self):
        for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
            self.assertEqual(self.code.count(opener), self.code.count(closer),
                             f"불균형: {opener}{closer}")

    def test_no_template_literals(self):
        # 백틱은 CSP 인라인 스크립트와 문자열 이스케이프에서 사고가 나기 쉬워 쓰지 않는다.
        self.assertNotIn("`", self.script)
        self.assertNotIn("${", self.code)

    def test_strip_js_really_removes_strings(self):
        sample = "var a = '}'; // }\nvar b = /[{}]/g; /* } */ var c = 1;"
        self.assertEqual(strip_js(sample).count("{"), 0)
        self.assertEqual(strip_js(sample).count("}"), 0)

    def test_functions_are_named_or_anonymous(self):
        for match in re.finditer(r"\bfunction\b", self.code):
            tail = self.code[match.end():match.end() + 2].strip()
            self.assertTrue(tail.startswith("(") or re.match(r"[A-Za-z_$]", tail),
                            f"function 뒤가 비정상: {self.code[match.end():match.end() + 20]!r}")

    def test_no_dangerous_dom_apis(self):
        for forbidden in ("innerHTML = document.cookie", "eval(", "new Function",
                          "document.write", "window.location =", "localStorage",
                          "sessionStorage", "document.cookie"):
            self.assertNotIn(forbidden, self.code.replace(" ", "") if " " in forbidden else self.code,
                             forbidden)

    def test_every_referenced_element_exists(self):
        document_ids = set(re.findall(r'id="([^"]+)"', self.home))
        referenced = set(re.findall(r'\$\("([^"]+)"\)', self.script))
        referenced |= set(re.findall(r'getElementById\("([^"]+)"\)', self.script))
        self.assertEqual(referenced - document_ids, set())

    def test_share_and_prefill_helpers_present(self):
        self.assertIn('id="share"', self.home)
        self.assertIn("function shareLink()", self.script)
        self.assertIn("function prefillFromUrl()", self.script)
        self.assertIn("URLSearchParams", self.script)
        self.assertIn("encodeURIComponent", self.script)
        self.assertIn('"?brand="', self.script)
        self.assertIn('"#check"', self.script)
        self.assertIn("prefillFromUrl();", self.script)

    def test_share_link_carries_only_brand(self):
        # 공유 링크 조립식에 금액·조건·연락처 필드가 섞이지 않았는지.
        match = re.search(r"function shareLink\(\) \{(.*?)\n  \}", self.script, re.S)
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn("brand_name", body)
        for forbidden in ("franchise_fee_krw", "interior_krw", "contact", "email",
                          "disclosure_days_before", "revenue_claim_ko"):
            self.assertNotIn(forbidden, body, forbidden)

    def test_guide_pages_have_no_inline_script(self):
        for slug in guides.slugs():
            page = guides.render_item(slug) or ""
            self.assertEqual(inline_scripts(page), [], slug)
            self.assertEqual(re.findall(r"<script[^>]*>", page).__len__(),
                             page.count('<script type="application/ld+json">'), slug)


if __name__ == "__main__":
    unittest.main(verbosity=2)
