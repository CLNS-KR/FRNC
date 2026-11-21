"""v0.1.6 회귀 — 승인 데이터셋(15125490·15125491) 반영과 `lookup_brand_disclosure` 필드 계약.

Pilotage(@pilot) 검수 리포트의 두 항목을 같은 자리에서 다시 깨지지 않게 고정합니다.
1. 승인된 가맹점 및 직영점(15125490)·가맹점 변경현황(15125491)이 조회 경로에 실제로
   반영되는지 — 특히 15125490 은 **시·도 행과 '전체' 행을 함께** 주므로 모두 더하면 두 배가
   됩니다(2026-11-21 실측: BBQ 2,316 → 잘못 4,632). 색인에도 합계를 함께 저장합니다.
2. 툴 설명과 실제 응답 필드가 같은 말을 하는지 — 비어 있는 필드는 `field_status.null` 이
   이유·데이터셋 번호·활용신청 주소를 밝히고, '최근 3년 폐점률'처럼 실제로 주지 않는 값을
   설명이 약속하지 않습니다.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import api, brand_index, live_api  # noqa: E402


def response(items, shape="items"):
    if shape == "response":
        return json.dumps({"response": {"header": {"resultCode": "00"},
                                        "body": {"items": {"item": items}}}}).encode("utf-8")
    return json.dumps({"items": items}, ensure_ascii=False).encode("utf-8")


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        for marker, value in self.mapping.items():
            if marker in url:
                return value
        return json.dumps({"items": [], "totalCount": 0}).encode("utf-8")


AREA_ROWS = [
    {"areaNm": "서울", "frcsCnt": 300, "dmsCnt": 12},
    {"areaNm": "부산", "frcsCnt": 120, "dmsCnt": 4},
    {"areaNm": "경기", "frcsCnt": 380, "dmsCnt": 10},
]
TOTAL_ROW = {"areaNm": "전체", "frcsCnt": 800, "dmsCnt": 26}


class StoreTotalTest(unittest.TestCase):
    """15125490 — '전체' 행을 지역 행과 더하지 않는다."""

    def test_total_row_is_not_added_to_area_rows(self):
        totals = live_api._sum_area_rows(AREA_ROWS + [TOTAL_ROW])
        self.assertEqual(totals["frcsCnt"], 800)
        self.assertEqual(totals["dmsCnt"], 26)
        self.assertEqual(totals["areas"], 3)
        self.assertTrue(totals["total_row"])

    def test_area_rows_are_summed_when_no_total_row(self):
        totals = live_api._sum_area_rows(AREA_ROWS)
        self.assertEqual(totals["frcsCnt"], 800)
        self.assertEqual(totals["dmsCnt"], 26)
        self.assertFalse(totals["total_row"])

    def test_index_store_totals_keeps_total_and_area_count(self):
        rows = [{**row, "brandMnno": "BRD_X"} for row in AREA_ROWS + [TOTAL_ROW]]

        class FakeClient:
            def __init__(self):
                self.calls = []

            def call(self, endpoint, params):
                self.calls.append(params["pageNo"])
                page = rows if params["pageNo"] == 1 else []
                return {"code": "0", "status": 200, "rows": page,
                        "raw_shape": "items", "total": len(rows)}

        totals, info = brand_index.store_totals(FakeClient(), "https://example.invalid/store",
                                                2025, page_size=1000, max_pages=3)
        self.assertEqual(totals["BRD_X"]["frcsCnt"], 800)
        self.assertEqual(totals["BRD_X"]["dmsCnt"], 26)
        self.assertEqual(totals["BRD_X"]["areas"], 3)
        self.assertTrue(info["complete"])


class EnrichmentTest(unittest.TestCase):
    """실시간 조회가 15125490·15125491 을 실제로 브랜드 행에 합치는지."""

    def _lookup(self):
        brand_row = {"brandNm": "테스트치킨", "brandMnno": "BRD_T1", "jnghdqrtrsMnno": "JNG_T1",
                     "corpNm": "(주)테스트", "jngBizCrtraYr": "2025"}
        change_row = {"jngBizCrtraYr": "2025", "brandMnno": "BRD_T1", "acntgYr": "2024",
                      "ystFrcsCnt": 700, "yndFrcsCnt": 800, "newFrcsCnt": 130,
                      "ctrtEndFrcsCnt": 30, "ctrtCncltnFrcsCnt": 0}
        opener = FakeOpener({
            "/getBrandinfo": response([brand_row]),
            "FftcBrandFrcsDropInfo3_Service": response(AREA_ROWS + [TOTAL_ROW]),
            "FftcBrandFrcsChghst2_Service": response([change_row]),
        })
        client = live_api.FtcClient("dummy-key", opener=opener)
        return live_api.lookup("테스트치킨", client=client), opener

    def test_store_counts_come_from_total_row(self):
        result, _opener = self._lookup()
        self.assertEqual(result["status"], "live")
        brand = result["brands"][0]
        self.assertEqual(brand["stores_year_end"], 800)      # 1,600 이 아니다
        self.assertEqual(brand["direct_stores"], 26)
        self.assertEqual(brand["stores_area_count"], 3)

    def test_closure_rate_is_one_year_with_basis(self):
        result, _opener = self._lookup()
        brand = result["brands"][0]
        self.assertEqual(brand["start_stores"], 700)
        self.assertEqual(brand["terminated"], 30)
        self.assertEqual(brand["cancelled"], 0)
        # (30 + 0) / 700 = 4.3%
        self.assertEqual(brand["closure_rate_pct"], 4.3)
        self.assertEqual(brand["closure_rate_year"], 2024)
        self.assertIn("연초 700곳", brand["closure_rate_basis_ko"])
        self.assertNotIn("closure_rate_3y_pct", brand)

    def test_two_enrichment_datasets_are_reported(self):
        result, _opener = self._lookup()
        keys = {row.get("key") for row in result["datasets"]}
        self.assertIn("brand_direct_stores", keys)
        self.assertIn("brand_store_change", keys)


class ShippedIndexStoresTest(unittest.TestCase):
    """배포 이미지에 들어가는 색인이 가맹점 수를 함께 들고 있는지(인증키 없이도)."""

    def test_index_reports_store_coverage(self):
        meta = brand_index.meta()
        self.assertTrue(meta["available"], meta)
        self.assertTrue(meta["stores"]["available"], meta["stores"])
        self.assertEqual(meta["stores"]["dataset_id"], "15125490")
        self.assertGreater(meta["stores"]["rows_with_stores"], 20000, meta["stores"])

    def test_bbq_store_counts_without_any_key(self):
        with mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": ""}):
            result = live_api.lookup("BBQ")
        self.assertEqual(result["data_source"], "index")
        brand = result["brands"][0]
        self.assertIn("비비큐", brand["brand_name"])
        self.assertEqual(brand["stores_year_end"], 2316)
        self.assertEqual(brand["direct_stores"], 71)
        self.assertEqual(brand["stores_area_count"], 17)
        self.assertEqual(brand["stores_source"], "brand_direct_stores_index")

    def test_index_search_exposes_store_fields(self):
        row = brand_index.search("BBQ")[0]
        self.assertIn("frcsCnt", row)
        self.assertIn("dmsCnt", row)
        self.assertEqual(int(row["frcsCnt"]), 2316)


class FieldContractTest(unittest.TestCase):
    """툴 설명 ↔ 실제 null 필드 정렬."""

    def setUp(self):
        self.definition = api.TOOL_INDEX["lookup_brand_disclosure"]
        self.description = self.definition["description_ko"]

    def test_description_mentions_field_status_and_approved_datasets(self):
        for marker in ("field_status", "15125490", "15125491", "승인"):
            self.assertIn(marker, self.description, marker)

    def test_description_does_not_promise_three_year_closure_rate(self):
        self.assertNotIn("최근 3년 폐점률", self.description)
        self.assertIn("closure_rate_basis_ko", self.description)

    def test_description_names_the_missing_datasets_as_null(self):
        for marker in ("평균매출", "가맹비", "법 위반", "null"):
            self.assertIn(marker, self.description, marker)

    def test_null_fields_carry_reason_dataset_and_apply_url(self):
        with mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": ""}):
            result = live_api.lookup("BBQ")
        status = result["field_status"]
        self.assertIn("brand_name", status["returned"])
        self.assertIn("stores_year_end", status["returned"])
        nulls = {item["field"]: item for item in status["null"]}
        self.assertIn("avg_sales_krw", nulls)
        avg = nulls["avg_sales_krw"]
        self.assertEqual(avg["dataset_id"], "15110241")
        self.assertEqual(avg["approval"], "not_registered")
        self.assertTrue(avg["apply_url"].startswith("https://www.data.go.kr/data/"))
        self.assertTrue(avg["reason_ko"])
        # 승인됐지만 인증키가 없어 실시간 재조회를 안 한 경우를 구분해 적는다.
        self.assertIn("인증키가 없어", nulls["closure_rate_pct"]["reason_ko"])
        # 가맹정보 데이터셋에 아예 없는 항목은 그렇게 적는다.
        self.assertIn("정보공개서", nulls["disclosure_no"]["reason_ko"])
        self.assertIn("null", status["meaning_ko"])
        self.assertIn("null", result["null_meaning_ko"])

    def test_zero_result_has_empty_field_status(self):
        with mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": ""}):
            result = live_api.lookup("존재하지않는브랜드명xyz")
        self.assertTrue(result["zero_result"])
        self.assertEqual(result["field_status"]["null"], [])
        self.assertIn("결과가 없어", result["field_status"]["scope_ko"])

    def test_sample_response_marks_missing_values_as_sample(self):
        result = live_api.lookup("샘플치킨", env={})
        self.assertEqual(result["data_state"], "sample")
        reasons = [item["reason_ko"] for item in result["field_status"]["null"]]
        self.assertTrue(any("샘플" in reason for reason in reasons), reasons)

    def test_text_summary_lists_empty_fields(self):
        with mock.patch.dict(os.environ, {"DATA_GO_KR_SERVICE_KEY": ""}):
            result = api.call_tool("lookup_brand_disclosure", {"brand_name": "BBQ"})
        summary = api.text_summary(result)
        self.assertIn("BBQ", summary.upper())
        self.assertIn("가맹점 2,316", summary)
        self.assertIn("값이 빈 항목", summary)

    def test_every_field_spec_has_a_label(self):
        for field, label, dataset_key, note in live_api.FIELD_SPECS:
            self.assertTrue(field)
            self.assertTrue(label)
            if dataset_key:
                self.assertIn(dataset_key, live_api.DATASET_IDS)
            else:
                self.assertTrue(note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
