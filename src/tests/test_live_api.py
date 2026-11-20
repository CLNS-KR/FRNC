"""실시간 어댑터 테스트 — 응답 봉투 3형태·승인 상태·샘플 폴백·연도 재시도.

실제 공정위 API 는 이 키에 승인돼 있지 않으므로(코드 30 실측), 여기서는 HTTP 를 흉내 내는
opener 를 넣어 **승인된 경우의 동작**까지 검증합니다.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import live_api  # noqa: E402

ENDPOINT = "https://apis.data.go.kr/1130000/FftcBrandRlsInfo2_Service/getBrandinfo"


def response(items, shape="items"):
    """문서화된 세 봉투 중 하나로 응답 본문을 만든다."""
    if shape == "response":
        payload = {"response": {"header": {"resultCode": "00"},
                                "body": {"items": {"item": items}}}}
    elif shape == "data":
        payload = {"data": items}
    else:
        payload = {"items": items}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def error_body(code="30", message="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"):
    return json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
        "errMsg": message, "returnAuthMsg": "등록되지 않은 서비스키",
        "returnReasonCode": code}}}, ensure_ascii=False).encode("utf-8")


BRAND_ROW = {
    "brandMnno": "BRD_TEST_1", "jnghdqrtrsMnno": "JNG_TEST_1",
    "brandNm": "테스트치킨", "corpNm": "(주)테스트에프앤비",
    "indutyLclasNm": "외식", "indutyMlsfcNm": "치킨", "majrGdsNm": "후라이드",
    "jngBizStrtDate": "20190301", "jngBizCrtraYr": "2024",
    "frcsCnt": "120", "newFrcsCnt": "20", "ctrtTrmnCnt": "8", "ctrtCnncCnt": "4",
    "avrgSalesAmt": "180000000", "jnntAmt": "11000000", "gtnAmt": "10000000",
    "edcAmt": "3300000", "intrrAmt": "1700000",
    "infoPblsRgsNo": "2024000099", "infoPblsRgsDe": "2024-03-01", "lawVioltCnt": "0",
}


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        for marker, value in self.mapping.items():
            if marker in url:
                if isinstance(value, Exception):
                    raise value
                return value
        return error_body("12", "NO_OPENAPI_SERVICE_ERROR")


class RowParsingTest(unittest.TestCase):
    def test_three_envelopes(self):
        for shape in ("items", "response", "data"):
            rows, name = live_api._rows(json.loads(response([BRAND_ROW], shape)))
            self.assertEqual(len(rows), 1, shape)
            self.assertEqual(rows[0]["brandNm"], "테스트치킨")
            self.assertTrue(name)

    def test_single_item_dict(self):
        payload = {"items": {"item": BRAND_ROW}}
        rows, _ = live_api._rows(payload)
        self.assertEqual(len(rows), 1)

    def test_flat_items_dict_is_one_row(self):
        rows, name = live_api._rows({"items": {"brandNm": "A", "frcsCnt": 3}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(name, "items")

    def test_unknown_shape_returns_empty(self):
        rows, name = live_api._rows({"hello": "world"})
        self.assertEqual(rows, [])
        self.assertEqual(name, "unknown")

    def test_error_envelope_has_no_rows(self):
        rows, _ = live_api._rows(json.loads(error_body()))
        self.assertEqual(rows, [])


class NormalizeTest(unittest.TestCase):
    def test_normalize_maps_api_fields(self):
        brand = live_api.normalize_brand_row(BRAND_ROW, 2024, "live")
        self.assertEqual(brand["brand_name"], "테스트치킨")
        self.assertEqual(brand["stores_year_end"], 120)
        self.assertEqual(brand["avg_sales_krw"], 180_000_000)
        self.assertEqual(brand["franchise_fee_krw"], 11_000_000)
        self.assertEqual(brand["base_year"], 2024)
        self.assertEqual(brand["data_state"], "live")

    def test_closure_rate_is_derived_when_missing(self):
        rate = live_api.closure_rate_from_rows(BRAND_ROW)
        # 연초 = 120 - 20 + 8 + 4 = 112 → (8+4)/112 = 10.7%
        self.assertAlmostEqual(rate, 10.7, places=1)

    def test_closure_rate_needs_all_fields(self):
        self.assertIsNone(live_api.closure_rate_from_rows({"frcsCnt": "10"}))


class LookupTest(unittest.TestCase):
    def test_no_key_falls_back_to_sample(self):
        result = live_api.lookup("샘플치킨", env={})
        self.assertEqual(result["data_state"], "sample")
        self.assertTrue(result["brands"])
        self.assertTrue(result["sample_notice_ko"])

    def test_not_registered_reports_apply_url(self):
        opener = FakeOpener({"/getBrandinfo": error_body("30")})
        client = live_api.FtcClient("dummy-key", opener=opener)
        result = live_api.lookup("샘플치킨", client=client)
        self.assertEqual(result["status"], "not_approved")
        self.assertEqual(result["data_state"], "sample")
        self.assertIn("https://www.data.go.kr/data/15125467/openapi.do", result["apply_urls"])
        self.assertTrue(result["brands"])  # 구조를 보여 줄 샘플
        self.assertIn("활용신청", result["message_ko"])

    def test_live_success(self):
        opener = FakeOpener({
            "/getBrandinfo": response([BRAND_ROW], "response"),
        })
        client = live_api.FtcClient("dummy-key", opener=opener)
        result = live_api.lookup("테스트치킨", client=client)
        self.assertEqual(result["status"], "live")
        self.assertEqual(result["data_state"], "live")
        self.assertEqual(result["brands"][0]["brand_name"], "테스트치킨")

    def test_year_retry_until_rows_found(self):
        calls = {"count": 0}

        def opener(url, timeout):
            calls["count"] += 1
            if calls["count"] < 2:
                return response([], "items")
            return response([BRAND_ROW], "items")

        client = live_api.FtcClient("dummy-key", opener=opener)
        result = live_api.lookup("테스트치킨", client=client)
        self.assertEqual(result["status"], "live")
        self.assertGreaterEqual(calls["count"], 2)

    def test_not_found_when_api_responds_without_match(self):
        opener = FakeOpener({"/getBrandinfo": response([BRAND_ROW], "items")})
        client = live_api.FtcClient("dummy-key", opener=opener)
        result = live_api.lookup("없는브랜드", client=client)
        self.assertEqual(result["status"], "not_found")

    def test_unexpected_shape_is_reported_not_silently_empty(self):
        opener = FakeOpener({"/getBrandinfo": json.dumps({"odd": 1}).encode()})
        client = live_api.FtcClient("dummy-key", opener=opener)
        result = live_api.lookup("테스트치킨", client=client)
        self.assertEqual(result["status"], "unexpected_shape")

    def test_network_error_is_reported(self):
        opener = FakeOpener({"/getBrandinfo": OSError("boom")})
        client = live_api.FtcClient("dummy-key", opener=opener)
        result = live_api.lookup("샘플치킨", client=client)
        self.assertEqual(result["status"], "network_error")
        self.assertTrue(result["brands"])

    def test_enrichment_uses_hq_and_store_endpoints(self):
        opener = FakeOpener({
            "/getBrandinfo": response([BRAND_ROW], "items"),
            "FftcJnghdqrtrsGnrlDtl3_Service": error_body("30"),
            "FftcBrandFrcsStatsService": error_body("30"),
        })
        client = live_api.FtcClient("dummy-key", opener=opener)
        result = live_api.lookup("테스트치킨", client=client)
        self.assertEqual(result["status"], "live")
        urls = " ".join(result["apply_urls"])
        self.assertIn("15125450", urls)
        self.assertIn("15110241", urls)

    def test_key_is_never_in_result(self):
        opener = FakeOpener({"/getBrandinfo": error_body("30")})
        client = live_api.FtcClient("SUPER-SECRET-KEY", opener=opener)
        result = live_api.lookup("샘플치킨", client=client)
        self.assertNotIn("SUPER-SECRET-KEY", json.dumps(result, ensure_ascii=False))


class VerificationFileTest(unittest.TestCase):
    def test_summary_reads_probe_results(self):
        summary = live_api.dataset_summary()
        self.assertGreaterEqual(summary["counts"]["total"], 15)
        self.assertTrue(summary["apply_urls"])
        for url in summary["apply_urls"]:
            self.assertTrue(url.startswith("https://www.data.go.kr/data/"))

    def test_every_dataset_has_endpoint_or_reason(self):
        for row in live_api.dataset_summary()["datasets"]:
            self.assertTrue(row["dataset_id"])
            self.assertIn(row["approval"], ("approved", "not_registered", "unverified"))
            if row["approval"] != "unverified":
                self.assertTrue(row["endpoint"], row["key"])

    def test_health_block_has_no_key(self):
        block = live_api.health_block()
        self.assertIn(block["live_api"], ("configured", "no_key"))
        self.assertNotIn("serviceKey", json.dumps(block))

    def test_link_only_datasets_are_documented(self):
        rows = live_api.dataset_summary()["link_only"]
        ids = {row["dataset_id"] for row in rows}
        self.assertIn("15125571", ids)
        for row in rows:
            self.assertTrue(row["note_ko"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
