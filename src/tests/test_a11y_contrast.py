"""다크 모드·라이트 모드 색 대비(WCAG 2.1) 4.5:1 계산 테스트.

화면에서 실제로 쓰이는 전경/배경 조합만 검사합니다. 토큰만 맞고 조합이 어긋나면
읽기 어려운 화면이 되므로, (전경 토큰, 배경 토큰) 쌍을 고정해 두고 비율을 계산합니다.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import guides, web_ui  # noqa: E402

MIN_RATIO = 4.5
LIGHT = ":root\\{(.*?)\\}"
DARK = r"@media \(prefers-color-scheme: dark\)\{\s*:root\{(.*?)\}"

# 화면에서 실제로 조합되는 (글자, 배경) 쌍
PAIRS = [
    ("ink", "bg"), ("ink", "card"), ("ink", "surface-2"), ("ink", "surface-3"),
    ("ink-soft", "bg"), ("ink-soft", "card"), ("ink-soft", "surface-2"),
    ("brand", "bg"), ("brand", "card"), ("on-brand", "brand"),
    ("brand-ink", "brand-soft"), ("ink-soft", "surface-3"),
    ("ok", "ok-soft"), ("warn", "warn-soft"), ("info", "info-soft"), ("danger", "danger-soft"),
    ("ok", "card"), ("warn", "card"), ("info", "card"), ("danger", "card"),
    ("ok", "bg"), ("warn", "bg"), ("info", "bg"), ("danger", "bg"),
]


def token_block(css: str, pattern: str) -> dict:
    """색 토큰만(대비 계산용) — 값이 hex 인 것."""
    match = re.search(pattern, css, re.S)
    block = match.group(1) if match else ""
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;", block))


def token_names(css: str, pattern: str) -> set:
    match = re.search(pattern, css, re.S)
    block = match.group(1) if match else ""
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", block))


def rgb(value: str):
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    return tuple(int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))


def luminance(value: str) -> float:
    def channel(raw: float) -> float:
        return raw / 12.92 if raw <= 0.03928 else ((raw + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(part) for part in rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(foreground: str, background: str) -> float:
    first, second = luminance(foreground), luminance(background)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


class ContrastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.light = token_block(web_ui.BASE_CSS, LIGHT)
        cls.dark = token_block(web_ui.BASE_CSS, DARK)

    def test_both_modes_have_color_tokens(self):
        self.assertTrue(self.light)
        self.assertTrue(self.dark)
        self.assertEqual(set(self.light) - set(self.dark), set())

    def test_all_pairs_pass_in_both_modes(self):
        for name, tokens in (("light", self.light), ("dark", self.dark)):
            for foreground, background in PAIRS:
                fg = tokens.get(f"--{foreground}")
                bg = tokens.get(f"--{background}")
                self.assertIsNotNone(fg, f"{name}: --{foreground}")
                self.assertIsNotNone(bg, f"{name}: --{background}")
                ratio = contrast(fg, bg)
                self.assertGreaterEqual(
                    round(ratio, 2), MIN_RATIO,
                    f"{name}: --{foreground} on --{background} = {ratio:.2f} (< {MIN_RATIO})",
                )

    def test_guide_pages_use_only_defined_tokens(self):
        defined = token_names(web_ui.BASE_CSS, LIGHT)
        self.assertIn("--radius", defined)
        self.assertIn("--shadow", defined)
        css = web_ui.BASE_CSS + guides.GUIDE_CSS
        used = set(re.findall(r"var\((--[a-z0-9-]+)\)", css))
        self.assertEqual(used - defined, set())
        # 가이드 페이지의 한 줄 답 상자도 같은 대비 기준을 넘는다.
        answer_fg = self.light["--brand-ink"]
        answer_bg = self.light["--brand-soft"]
        self.assertGreaterEqual(round(contrast(answer_fg, answer_bg), 2), MIN_RATIO)
        dark_fg = self.dark["--brand-ink"]
        dark_bg = self.dark["--brand-soft"]
        self.assertGreaterEqual(round(contrast(dark_fg, dark_bg), 2), MIN_RATIO)

    def test_rendered_pages_have_no_color_override(self):
        # 페이지에 인라인으로 색을 덮어쓰는 style 이 없어야 토큰 대비가 유지된다.
        for page in [web_ui.render_page({"data_state": "sample"})] + [
                guides.render_item(slug) or "" for slug in guides.slugs()]:
            inline = re.findall(r'style="([^"]*)"', page)
            for value in inline:
                self.assertNotIn("color:", value.replace(" ", ""))
                self.assertNotIn("background:", value.replace(" ", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
