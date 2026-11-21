"""v0.1.5 회귀 테스트 — P0(브랜드 미발견·중복 입력·거짓 상태) + P1(웹 조회·문구·링크).

브리프의 결함 네 건을 **같은 자리에서 다시 깨지지 않게** 고정합니다.
1. P0-1 유명 브랜드 `not_found` — `getBrandinfo` 는 이름 검색 파라미터가 없어 전체 페이지를
   받아 색인으로 만든다. `BBQ`·`교촌`·`BHC`·`메가커피` 가 색인에서 즉시 찾힌다.
2. P0-2 `payment_route` 중복 id — 렌더는 `SELECTS` 한 곳에서만, 프리셋 "정상 조건" 은 low_risk.
3. P0-3 데이터 상태 거짓 표기 — `15125467` 승인(=live)을 파일·화면·llms·meta 가 같이 말한다.
4. P1 웹 브랜드 조회 카드·확인 질문형 문구·CLNS 크로스 링크·사람용 404.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from franchise_kr import (brand_index, engine, live_api, models, static_files,  # noqa: E402
                          web_ui)


def read_project(name: str) -> str:
    with open(os.path.join(PROJECT, name), "r", encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------------------
# P0-1 — 유명 브랜드를 색인에서 찾는다
# ---------------------------------------------------------------------------
class BrandIndexTest(unittest.TestCase):
    FAMOUS = ("BBQ", "교촌", "BHC", "메가커피", "투썸플레이스")

    @classmethod
    def setUpClass(cls):
        cls.meta = brand_index.meta()

    def test_index_is_shipped_and_loaded(self):
        self.assertTrue(self.meta["available"], self.meta)
        self.assertGreater(self.meta["count"], 20000, self.meta)
        self.assertGreaterEqual(int(self.meta["year"] or 0), 2023)
        self.assertIn(int(self.meta["year"]), [int(y) for y in self.meta["years"]])

    def test_index_file_is_in_the_repository(self):
        path = os.path.join(PROJECT, "data", "brands_index.json.gz")
        self.assertTrue(os.path.exists(path), path)
        self.assertGreater(os.path.getsize(path), 100_000)

    def test_famous_brands_are_found_without_any_api_key(self):
        with mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": ""}):
            for name in self.FAMOUS:
                result = live_api.lookup(name)
                self.assertEqual(result["status"], "live", name)
                self.assertEqual(result["data_state"], "live", name)
                self.assertEqual(result["data_source"], "index", name)
                self.assertFalse(result["zero_result"], name)
                self.assertTrue(result["brands"], name)
                self.assertTrue(result["brands"][0]["brand_code"].startswith("BRD_"), name)

    def test_bbq_is_the_first_hit_for_bbq(self):
        result = live_api.lookup("BBQ")
        first = result["brands"][0]
        self.assertIn("BBQ", (first["brand_name"] or "").upper())
        self.assertIn("비비큐", first["brand_name"])

    def test_lookup_by_brand_code(self):
        code = live_api.lookup("BBQ")["brands"][0]["brand_code"]
        result = live_api.lookup("", code)
        self.assertEqual(result["status"], "live")
        self.assertEqual(result["brands"][0]["brand_code"], code)

    def test_spelling_difference_is_tolerated(self):
        # 등록명은 '메가엠지씨커피(MEGA MGC COFFEE)' — 사용자는 '메가커피' 로 찾는다.
        result = live_api.lookup("메가커피")
        self.assertEqual(result["status"], "live")
        self.assertIn("메가엠지씨커피", result["brands"][0]["brand_name"])

    def test_search_ranking_prefers_exact_then_prefix(self):
        rows = brand_index.search("교촌")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["brandNm"], "교촌치킨")
        rows = brand_index.search("파리바게뜨")
        self.assertEqual(rows[0]["brandNm"], "파리바게뜨")

    def test_search_returns_empty_for_blank_query(self):
        self.assertEqual(brand_index.search("", ""), [])

    def test_not_found_is_not_definitive(self):
        result = live_api.lookup("존재하지않는브랜드명xyz")
        self.assertEqual(result["status"], "not_found")
        self.assertTrue(result["zero_result"])
        message = result["message_ko"]
        self.assertIn("단정하지 않습니다", message)
        self.assertIn("색인", message)
        self.assertIn(f"{int(self.meta['count']):,}", message)
        # 0건 고정 안내도 그대로 붙는다.
        self.assertIn("'문제없다·안전하다'는 뜻도 아닙니다", result["zero_result_notice_ko"])

    def test_directory_only_brand_is_explained_not_dismissed(self):
        # 스타벅스는 가맹 브랜드 목록에 없다(직영). 그래도 '없다'고 단정하지 않는다.
        result = live_api.lookup("스타벅스")
        self.assertTrue(result["zero_result"])
        self.assertNotIn("등록된 브랜드가 아닙니다", result["message_ko"])
        self.assertIn("가맹사업정보제공시스템", result["message_ko"])

    def test_paging_stops_at_short_page_and_reports_completeness(self):
        calls = {"pages": []}

        def opener(url, timeout):
            page = re.search(r"pageNo=(\d+)", url)
            calls["pages"].append(int(page.group(1)) if page else 0)
            size = len(calls["pages"])
            rows = [{"brandNm": f"브랜드{size}", "brandMnno": f"BRD_{size}"}]
            return json.dumps({"items": rows, "totalCount": 5000}).encode("utf-8")

        client = live_api.FtcClient("dummy", opener=opener)
        rows, info = brand_index.fetch_rows(client, "https://example.invalid/getBrandinfo", 2026)
        self.assertEqual(len(rows), 1)          # 한 페이지만 받고 멈춘다(짧은 페이지)
        self.assertTrue(info["complete"])
        self.assertEqual(calls["pages"], [1])

    def test_paging_reports_incomplete_when_page_cap_hits(self):
        def opener(url, timeout):
            rows = [{"brandNm": "가득", "brandMnno": "BRD_X"} for _ in range(1000)]
            return json.dumps({"items": rows, "totalCount": 5000}).encode("utf-8")

        client = live_api.FtcClient("dummy", opener=opener)
        rows, info = brand_index.fetch_rows(client, "https://example.invalid/getBrandinfo", 2026,
                                            max_pages=2)
        self.assertEqual(len(rows), 2000)
        self.assertFalse(info["complete"])

    def test_partial_scan_is_not_counted_as_zero_result(self):
        def opener(url, timeout):
            rows = [{"brandNm": "가득", "brandMnno": "BRD_X"} for _ in range(1000)]
            return json.dumps({"items": rows, "totalCount": 500000}).encode("utf-8")

        client = live_api.FtcClient("dummy", opener=opener)
        result = live_api.lookup("없는브랜드", client=client)
        self.assertEqual(result["status"], "partial_scan")
        self.assertFalse(result["zero_result"])
        self.assertIn("단정하지 않습니다", result["message_ko"])

    def test_meta_exposes_index_size(self):
        block = live_api.health_block()
        self.assertTrue(block["brand_index"]["available"])
        self.assertEqual(block["brand_index"]["count"], self.meta["count"])
        self.assertNotIn("serviceKey", json.dumps(block, ensure_ascii=False))


# ---------------------------------------------------------------------------
# P0-2 — payment_route 중복 렌더 없음 + 프리셋 회귀
# ---------------------------------------------------------------------------
class PaymentRouteRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page({"data_state": "live"})

    def test_payment_route_is_rendered_once(self):
        self.assertEqual(self.html.count('name="payment_route"'), 1)
        self.assertEqual(self.html.count('id="payment_route"'), 1)

    def test_every_select_field_is_rendered_once(self):
        for name, _label, _rows in web_ui.SELECTS:
            self.assertEqual(self.html.count(f'name="{name}"'), 1, name)
            self.assertEqual(self.html.count(f'id="{name}"'), 1, name)

    def test_no_duplicate_ids_at_all(self):
        ids = re.findall(r'\bid="([^"]+)"', self.html)
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        self.assertEqual(duplicates, [], f"중복 id: {duplicates}")

    def _collect(self, values):
        """브라우저처럼 id 로 채우고 폼 필드를 모은다(같은 name 이 하나만 있으니 그대로 전달)."""
        payload = {}
        for name, value in values.items():
            self.assertIn(f'id="{name}"', self.html, name)
            payload[name] = str(value)
        return payload

    def test_normal_preset_yields_low_risk_zero(self):
        preset = [row for row in web_ui.PRESETS if row["id"] == "normal"][0]
        payload = self._collect(dict(preset["values"], brand_name="샘플치킨"))
        result = engine.check_franchise_risk(payload)
        self.assertEqual(result["verdict"]["code"], models.VERDICT_LOW)
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["counts"]["triggered"], 0)

    def test_risky_presets_still_trigger(self):
        for preset_id, expected in (("same_day", models.VERDICT_CHECK),
                                    ("verbal_sales", models.VERDICT_CHECK),
                                    ("interior_forced", models.VERDICT_CHECK)):
            preset = [row for row in web_ui.PRESETS if row["id"] == preset_id][0]
            payload = self._collect(dict(preset["values"], brand_name="샘플치킨"))
            self.assertEqual(engine.check_franchise_risk(payload)["verdict"]["code"], expected,
                             preset_id)

    def test_preset_values_are_present_in_the_rendered_form(self):
        for preset in web_ui.PRESETS:
            for field in preset["values"]:
                self.assertIn(f'id="{field}"', self.html, f"{preset['id']}:{field}")


# ---------------------------------------------------------------------------
# P0-3 — 데이터 상태를 사실대로
# ---------------------------------------------------------------------------
class DataStateTruthTest(unittest.TestCase):
    def test_verification_file_marks_brand_list_approved(self):
        data = json.loads(read_project("api-verification-2026-11-21.json"))
        rows = {row["key"]: row for row in data["datasets"]}
        brand = rows["brand_list"]
        self.assertEqual(brand["dataset_id"], "15125467")
        self.assertEqual(brand["approval"], "approved")
        self.assertIn(str(brand["code"]), ("0", "00"))
        self.assertGreaterEqual(data["counts"]["approved"], 1)
        self.assertNotIn("serviceKey=", json.dumps(data, ensure_ascii=False))

    def test_summary_counts_approved_datasets(self):
        summary = live_api.dataset_summary()
        self.assertGreaterEqual(summary["counts"]["approved"], 1)
        approved = [row for row in summary["datasets"] if row["approval"] == "approved"]
        self.assertIn("15125467", {row["dataset_id"] for row in approved})

    def test_state_is_live_when_index_or_approval_exists(self):
        self.assertEqual(live_api.data_state(), "live")

    def test_home_banner_has_no_false_approval_claim(self):
        html = web_ui.render_page({})
        for false_claim in ("승인 전이라", "활용신청 승인 전", "승인되지 않아 내장 샘플",
                            "아직 승인되지 않아"):
            self.assertNotIn(false_claim, html, false_claim)
        self.assertIn("실데이터로 동작", html)
        self.assertIn("색인", html)

    def test_llms_and_meta_have_no_false_approval_claim(self):
        llms = static_files.llms_txt()
        self.assertNotIn("승인 전까지", llms)
        self.assertIn("브랜드 색인", llms)
        meta = json.loads(json.dumps(
            __import__("franchise_kr.api", fromlist=["api"]).call_tool("get_service_meta", {})))
        note = meta["result"]["meta"]["data_note_ko"]
        self.assertNotIn("승인 전", note)
        self.assertEqual(meta["result"]["meta"]["data_state"], "live")
        self.assertIn("brand_index", meta["result"]["meta"])

    def test_verify_tool_treats_00_as_approved(self):
        from tools import verify_ftc_apis

        body = json.dumps({"resultCode": "00", "totalCount": "1",
                           "items": [{"brandNm": "테스트"}]})
        with mock.patch.object(verify_ftc_apis, "_call", return_value=(200, body)):
            row = verify_ftc_apis.probe_dataset("dummy-key",
                                                verify_ftc_apis.DATASETS[0])
        self.assertEqual(row["approval"], "approved", row)

    def test_verify_tool_still_marks_30_as_not_registered(self):
        from tools import verify_ftc_apis

        body = json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
            "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
            "returnReasonCode": "30"}}})
        with mock.patch.object(verify_ftc_apis, "_call", return_value=(200, body)):
            row = verify_ftc_apis.probe_dataset("dummy-key", verify_ftc_apis.DATASETS[2])
        self.assertEqual(row["approval"], "not_registered")


# ---------------------------------------------------------------------------
# P1 — 웹 조회 카드·확인 질문형 문구·크로스 링크·404
# ---------------------------------------------------------------------------
class WebBrandCardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page({})

    def test_brand_card_exists(self):
        for marker in ('id="brand-card"', "브랜드 정보공개서 조회", 'id="brand-q"',
                       'id="brand-run"', 'id="brand-result"'):
            self.assertIn(marker, self.html, marker)

    def test_brand_card_calls_the_lookup_tool(self):
        self.assertIn("/v1/tools/lookup_brand_disclosure", self.html)
        self.assertIn("function brandLookup()", self.html)
        self.assertIn("brand_name", self.html)

    def test_brand_card_does_not_create_an_engine_field(self):
        # 카드 입력은 판정 폼(name=)이 아니다 — 엔진 입력으로 새지 않게 name 속성을 두지 않는다.
        self.assertNotIn('name="brand_q"', self.html)
        self.assertNotIn('name="brand-q"', self.html)

    def test_brand_card_carries_no_result_caution(self):
        self.assertIn("0건은 '등록된 브랜드가 없다'도", self.html)

    def test_llms_links_the_card(self):
        self.assertIn("/#brand-card", static_files.llms_txt())


class UnknownPointWordingTest(unittest.TestCase):
    def test_unknown_points_are_questions(self):
        result = engine.check_franchise_risk({"brand_name": "BBQ"})
        self.assertTrue(result["unknown_points"])
        for row in result["unknown_points"]:
            self.assertTrue(row["title_ko"].endswith("확인했나요?"), row["title_ko"])
            self.assertNotIn("구두로 '월 매출 보장' 약속", row["title_ko"])

    def test_unknown_points_keep_the_case_title_for_reference(self):
        result = engine.check_franchise_risk({"brand_name": "BBQ"})
        cases = {row["case_title_ko"] for row in result["unknown_points"]}
        self.assertIn("구두로 '월 매출 보장' 약속, 서면 산정서 없음", cases)

    def test_triggered_points_keep_their_statement_title(self):
        result = engine.check_franchise_risk({"disclosure_days_before": 0})
        titles = [row["title_ko"] for row in result["risk_points"]]
        self.assertTrue(any("당일" in title for title in titles), titles)
        self.assertFalse(any(title.endswith("확인했나요?") for title in titles), titles)

    def test_every_trap_has_a_question_form(self):
        for case in engine.trap_cases():
            self.assertTrue(case.get("check_ko"), case["id"])
            self.assertTrue(case["check_ko"].endswith("확인했나요?"), case["id"])


class CrossLinkAndNotFoundTest(unittest.TestCase):
    def test_home_footer_links_clns(self):
        html = web_ui.render_page({})
        self.assertIn("https://clns-kr.onrender.com/", html)
        self.assertIn(">CLNS</a>", html)

    def test_guide_footer_links_clns(self):
        from franchise_kr import guides

        for slug in ("cooling-off-14days", "franchise-fee-escrow"):
            page = guides.render_item(slug) or ""
            self.assertIn("https://clns-kr.onrender.com/", page, slug)

    def test_llms_mentions_clns(self):
        self.assertIn("clns-kr.onrender.com", static_files.llms_txt())

    def test_human_404_page(self):
        page = web_ui.render_not_found("/nope?x=1")
        self.assertIn("<!doctype html>", page)
        self.assertIn("찾지 못했습니다", page)
        self.assertIn('href="/"', page)
        self.assertIn('href="/guides/"', page)
        self.assertIn("noindex", page)
        # 주소를 그대로 되비추되 태그는 이스케이프한다.
        self.assertIn("/nope?x=1", page)
        escaped = web_ui.render_not_found("/<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", escaped)
        self.assertIn("&lt;script&gt;", escaped)

    def test_render_yaml_points_at_frnc_onrender(self):
        text = read_project("render.yaml")
        self.assertIn("name: frnc\n", text)
        self.assertIn("value: https://frnc.onrender.com", text)
        self.assertNotIn("frnc-kr", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
