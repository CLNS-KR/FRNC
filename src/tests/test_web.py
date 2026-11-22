"""웹 UI 테스트 — 다크 모드 토큰·프리셋 4개·복사·문의 폼·외부 의존 0.

0.1.12 부터는 첫 화면 단순화(입력 1개 + 버튼 1개 + 예시 3개, 나머지는 접힘)를
`SimpleLayoutTest` 가 함께 지킨다.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import engine, web_ui  # noqa: E402


def root_block(css: str) -> str:
    match = re.search(r":root\{(.*?)\}", css, re.S)
    return match.group(1) if match else ""


def dark_block(css: str) -> str:
    match = re.search(r"@media \(prefers-color-scheme: dark\)\{(.*?)\n\}", css, re.S)
    return match.group(1) if match else ""


def tokens(block: str) -> set:
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", block))


class WebUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page({"data_state": "sample"})
        cls.css = web_ui.BASE_CSS

    def test_brand_and_tagline(self):
        self.assertIn("FRNC", self.html)
        self.assertIn("프랜차이즈 창업 전 10초 리스크 체크", self.html)
        self.assertIn("Franchise, simplified.", self.html)

    def test_dark_mode_defines_every_token(self):
        light, dark = root_block(self.css), dark_block(self.css)
        self.assertTrue(light)
        self.assertTrue(dark)
        light_tokens, dark_tokens = tokens(light), tokens(dark)
        self.assertTrue(light_tokens)
        missing = light_tokens - dark_tokens
        self.assertEqual(missing, set(), f"다크 모드에 빠진 토큰: {sorted(missing)}")

    def test_every_used_variable_is_defined(self):
        defined = tokens(root_block(self.css))
        used = set(re.findall(r"var\((--[a-z0-9-]+)\)", self.css))
        undefined = used - defined
        self.assertEqual(undefined, set(), f"정의 없는 변수: {sorted(undefined)}")

    def test_core_tokens_exist(self):
        defined = tokens(root_block(self.css))
        for token in ("--bg", "--card", "--ink", "--ink-soft", "--line", "--brand",
                      "--ok", "--warn", "--info", "--danger", "--radius"):
            self.assertIn(token, defined, token)

    def test_mobile_responsive(self):
        self.assertIn('name="viewport" content="width=device-width, initial-scale=1"', self.html)
        self.assertIn("@media (max-width:700px)", self.css)
        self.assertIn("@media (max-width:760px)", self.css)

    def test_four_one_click_presets(self):
        self.assertEqual(len(web_ui.PRESETS), 4)
        for preset in web_ui.PRESETS:
            self.assertIn(f'data-preset="{preset["id"]}"', self.html)
            self.assertIn(preset["title"], self.html)
        ids = [preset["id"] for preset in web_ui.PRESETS]
        self.assertEqual(sorted(ids), sorted(["same_day", "verbal_sales",
                                              "interior_forced", "normal"]))

    def test_preset_values_are_valid_engine_inputs(self):
        for preset in web_ui.PRESETS:
            for field, value in preset["values"].items():
                self.assertIn(field, engine.FIELD_ALIASES, field)
                if field in engine.ENUM_FIELDS:
                    self.assertIn(str(value), engine.ENUM_FIELDS[field], field)
        normal = dict(web_ui.PRESETS[3]["values"], brand_name="샘플치킨")
        result = engine.check_franchise_risk(normal)
        self.assertEqual(result["verdict"]["code"], "low_risk")
        risky = dict(web_ui.PRESETS[0]["values"], brand_name="샘플치킨")
        self.assertEqual(engine.check_franchise_risk(risky)["verdict"]["code"],
                         "check_likely")

    def test_copy_button_and_inquiry_form(self):
        self.assertIn('id="copy"', self.html)
        self.assertIn("요약 복사", self.html)
        self.assertIn('id="inquiry"', self.html)
        self.assertIn('id="inq-contact"', self.html)
        self.assertIn('id="inq-topic"', self.html)
        self.assertIn("/v1/inquiry", self.html)

    def test_no_identity_inputs(self):
        for forbidden in ('name="rrn"', 'name="resident"', 'type="password"',
                          'name="email"', "주민등록번호를 입력"):
            self.assertNotIn(forbidden, self.html, forbidden)

    def test_privacy_statements(self):
        self.assertIn("서버에 저장하지 않습니다", self.html)
        self.assertIn("확정 판정 아님", self.html)
        self.assertIn("이름·연락처·주민등록번호는 받지 않고", self.html)

    def test_no_external_assets_or_storage(self):
        for forbidden in ("<script src=", "@import", "cdn.", "localStorage",
                          "sessionStorage", "document.cookie", "fonts.googleapis"):
            self.assertNotIn(forbidden, self.html, forbidden)

    def test_result_rendering_hooks_exist(self):
        for marker in ('id="result"', 'id="result-card"', 'id="status"',
                       "/v1/tools/check_franchise_risk", "navigator.clipboard"):
            self.assertIn(marker, self.html, marker)

    def test_all_enum_options_are_offered(self):
        for field, options in engine.ENUM_FIELDS.items():
            if field not in ("payment_route", "interior_designated", "territory",
                             "ad_cost_burden"):
                continue
            for option in options:
                if option == "unknown":
                    continue
                self.assertIn(f'value="{option}"', self.html, f"{field}:{option}")

    def test_key_inputs_present(self):
        for field in ("brand_name", "franchise_fee_krw", "interior_krw", "deposit_krw",
                      "disclosure_days_before", "payment_route", "revenue_claim_ko",
                      "interior_designated", "territory", "closure_rate_3y_pct",
                      "termination_grace_months", "penalty_ratio_pct"):
            self.assertIn(f'id="{field}"', self.html, field)

    def test_grant_and_disclosure_links(self):
        self.assertIn("https://grnt-kr.onrender.com/", self.html)
        self.assertIn("https://franchise.ftc.go.kr", self.html)
        self.assertIn("GRNT에서 확인", self.html)

    def test_data_state_notice_changes_for_live(self):
        live_html = web_ui.render_page({"data_state": "live"})
        self.assertIn("실데이터로 동작", live_html)
        self.assertNotIn("내장 샘플로 동작", live_html)

    def test_script_is_syntactically_balanced(self):
        script = self.html.split("<script>", 1)[1].split("</script>", 1)[0]
        for opener, closer in (("{", "}"), ("(", ")"), ("[", "]")):
            self.assertEqual(script.count(opener), script.count(closer), opener)
        self.assertNotIn("`", script)

    def test_script_ids_exist_in_document(self):
        script = self.html.split("<script>", 1)[1].split("</script>", 1)[0]
        document_ids = set(re.findall(r'id="([^"]+)"', self.html))
        referenced = set(re.findall(r'\$\("([^"]+)"\)', script))
        referenced |= set(re.findall(r'getElementById\("([^"]+)"\)', script))
        missing = referenced - document_ids
        self.assertEqual(missing, set(), f"문서에 없는 id 참조: {sorted(missing)}")

    def test_form_field_names_are_engine_inputs(self):
        names = set(re.findall(r'<(?:input|select|textarea)[^>]*\bname="([a-z0-9_]+)"',
                               self.html))
        self.assertTrue(names)
        # 문의 폼은 판정 입력이 아니라 별도 경로다.
        names -= {"contact", "topic", "message"}
        for name in sorted(names):
            self.assertIn(name, engine.FIELD_ALIASES, f"폼 필드 {name} 이(가) 엔진 별칭에 없음")

    def test_presets_use_form_fields_only(self):
        form_ids = set(re.findall(r'<(?:input|select|textarea)[^>]*\bname="([a-z0-9_]+)"',
                                  self.html))
        for preset in web_ui.PRESETS:
            for field in preset["values"]:
                self.assertIn(field, form_ids, f"{preset['id']}: {field}")

    def test_share_link_and_prefill(self):
        self.assertIn('id="share"', self.html)
        self.assertIn("공유 링크 복사", self.html)
        self.assertIn("function shareLink()", self.html)
        self.assertIn("function prefillFromUrl()", self.html)
        self.assertIn("URLSearchParams", self.html)
        self.assertIn("encodeURIComponent", self.html)
        # 공유 링크는 브랜드명만 담고 금액·조건은 담지 않는다.
        self.assertIn('"?brand="', self.html)
        self.assertIn('"#check"', self.html)
        self.assertIn("브랜드명만 담깁니다", self.html)

    def test_home_links_to_guides(self):
        self.assertIn('href="/guides/"', self.html)
        self.assertIn("가이드 17종", self.html)
        self.assertIn("가이드 전체 17종 보기", self.html)
        for slug in ("cooling-off-14days", "franchise-fee-escrow", "territory-protection",
                     "franchisee-association"):
            self.assertIn(f'href="/guides/{slug}"', self.html, slug)

    def test_zero_result_notice_on_home(self):
        self.assertIn("0건이어도", self.html)
        self.assertIn("조회 결과가 0건", self.html)

    def test_meta_tags_for_social(self):
        self.assertIn('property="og:title"', self.html)
        self.assertIn('name="theme-color"', self.html)
        self.assertIn('media="(prefers-color-scheme: dark)"', self.html)


class SimpleLayoutTest(unittest.TestCase):
    """0.1.12 — 첫 화면은 한 가지 일만, 나머지는 접어 두고 결과는 신호등부터."""

    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page({"data_state": "sample"})

    def hero_before_details(self) -> str:
        block = self.html[self.html.index('id="brand-card"'):]
        return block[:block.index('<details class="more"')]

    def detail_block(self) -> str:
        block = self.html[self.html.index('id="more"'):]
        return block[:block.index("</details>")]

    def test_first_screen_is_one_input_and_one_button(self):
        top = self.hero_before_details()
        top = top[:top.index('<div class="chips">')]
        self.assertEqual(len(re.findall(r"<input\b", top)), 1)
        self.assertEqual(len(re.findall(r"<button\b", top)), 1)
        self.assertEqual(len(re.findall(r"<select\b", top)), 0)
        self.assertIn('id="run"', top)
        self.assertIn("리스크 확인하기", top)
        self.assertIn("브랜드명", self.html)

    def test_advanced_conditions_are_collapsed_by_default(self):
        self.assertIn('<details class="more" id="more">', self.html)
        self.assertNotIn('<details class="more" id="more" open', self.html)
        self.assertIn("상세 조건 입력", self.html)
        # 프리셋 4개와 판정 입력은 접힌 안쪽에만 있다.
        detail = self.detail_block()
        for field in ("franchise_fee_krw", "interior_krw", "disclosure_days_before",
                      "payment_route", "interior_designated", "territory",
                      "legal_violation", "closure_rate_3y_pct", "penalty_ratio_pct"):
            self.assertIn(f'id="{field}"', detail, field)
        for preset in web_ui.PRESETS:
            self.assertIn(f'data-preset="{preset["id"]}"', detail, preset["id"])

    def test_hero_speaks_plain_korean(self):
        top = self.hero_before_details()
        for word in ("정보공개서", "FDD", "MCP", "API", "JSON", "브랜드관리번호",
                     "REST", "스키마"):
            self.assertNotIn(word, top, word)

    def test_three_example_chips(self):
        hero = self.hero_before_details()
        chips = re.findall(r'class="chip" data-query="([^"]+)"', hero)
        self.assertEqual(len(chips), 3)
        self.assertEqual(chips, web_ui.QUICK_BRANDS)

    def test_quiet_sections_sit_after_the_result(self):
        order = [self.html.index('id="result-card"'), self.html.index('id="scan-card"'),
                 self.html.index('id="siblings"'), self.html.index('id="inquiry"'),
                 self.html.index('<p class="foot">')]
        self.assertEqual(order, sorted(order))

    def test_data_state_note_moved_below_the_tools(self):
        self.assertIn('id="data-state-note"', self.html)
        self.assertGreater(self.html.index('id="data-state-note"'),
                           self.html.index('id="scan-card"'))

    def test_result_is_a_signal_card_then_four_metrics(self):
        for marker in ('class="signal ', "종합 판정", 'class="metrics"',
                       "먼저 확인할 것", "본부에 물어볼 질문", "자세히 보기",
                       "data-qi", "data-oi"):
            self.assertIn(marker, self.html, marker)
        # 결과 렌더 순서: 신호 카드 → 브랜드 정보 → 지표 → 신호 목록 → 질문 → 자세히 보기
        render = self.html[self.html.index("function render(result, brand)"):]
        render = render[:render.index("function run()")]
        positions = [render.index(token) for token in
                     ("var html = signalBlock(", "html += factsBlock(brand",
                      "html += metricsBlock(",
                      "class=\"result-head\">먼저 확인할 것", "html += quick;",
                      "class=\"result-head\">본부에 물어볼 질문",
                      "html += detailsBlock(")]
        self.assertEqual(positions, sorted(positions))

    def test_quick_answers_are_valid_engine_inputs(self):
        self.assertGreaterEqual(len(web_ui.QUICK_ANSWERS), 3)
        for item in web_ui.QUICK_ANSWERS:
            self.assertIn(item["field"], engine.FIELD_ALIASES, item["field"])
            for opt in item["opts"]:
                for field, value in opt["set"].items():
                    self.assertIn(field, engine.FIELD_ALIASES, field)
                    if field in engine.ENUM_FIELDS:
                        self.assertIn(str(value), engine.ENUM_FIELDS[field], field)
        answered = {}
        for item in web_ui.QUICK_ANSWERS:
            answered.update(item["opts"][0]["set"])
        result = engine.check_franchise_risk(dict(answered, brand_name="샘플치킨"))
        self.assertGreaterEqual(result["coverage"]["answered_axes"], 5)

    def test_quick_answer_buttons_map_to_real_form_fields(self):
        detail = self.detail_block()
        for item in web_ui.QUICK_ANSWERS:
            for field in item["opts"][0]["set"]:
                self.assertIn(f'id="{field}"', detail, field)


if __name__ == "__main__":
    unittest.main(verbosity=2)
