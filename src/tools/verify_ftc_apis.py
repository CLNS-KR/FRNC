"""공정거래위원회 가맹정보 오픈API 를 **실제로 호출해** 오퍼레이션·승인 상태를 확인한다.

왜 필요한가
-----------
가맹정보 API 는 데이터셋 78건이 서비스(`Fftc*_Service`)마다 오퍼레이션 이름이 제각각이고,
data.go.kr 상세 페이지에는 베이스 주소만 보입니다. 오퍼레이션 이름을 추측해 넣으면
`NO_OPENAPI_SERVICE_ERROR`(12) 가 오고, 이름이 맞고 키만 미승인이면 코드 30
(`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`)이 옵니다. 그래서 후보 이름을 실제로 쏘아
**12/30 을 구분**하면 어떤 조합이 진짜 서비스인지 확인할 수 있습니다.

결과는 `api-verification-YYYY-MM-DD.json` 에 남기고, 서버의 실시간 어댑터(`live_api.py`)는
이 파일의 `endpoint`·`operation`·`approval` 을 그대로 씁니다. 승인 전이면 오프라인
샘플로 답하고 `apply_urls` 로 활용신청 주소를 안내합니다.

사용
----
    DATA_GO_KR_SERVICE_KEY=<키> PYTHONPATH=src python -m tools.verify_ftc_apis
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

KST = timezone(timedelta(hours=9))
HOST = "https://apis.data.go.kr/1130000"
PORTAL = "https://www.data.go.kr/data/{dataset_id}/openapi.do"

# data.go.kr 식별자 · 이름 · 서비스 · 후보 오퍼레이션(앞에서부터 시도)
DATASETS: List[Dict[str, Any]] = [
    {
        "key": "brand_list", "dataset_id": "15125467",
        "title_ko": "가맹정보_브랜드 목록 정보",
        "service": "FftcBrandRlsInfo2_Service",
        "operations": ["getBrandinfo", "getbrandinfo", "getBrandList"],
        "why_ko": "브랜드명·가맹본부·업종·가맹사업 개시일 — 브랜드 검색의 시작점",
    },
    {
        "key": "hq_general", "dataset_id": "15125450",
        "title_ko": "가맹정보_가맹본부 일반 정보 상세",
        "service": "FftcJnghdqrtrsGnrlDtl3_Service",
        "operations": ["getjnghdqrtrsGnlinfo2", "getJnghdqrtrsGnlinfo2"],
        "why_ko": "본부 업체명·대표자·기업규모·주소·브랜드 수",
    },
    {
        "key": "brand_stores", "dataset_id": "15110241",
        "title_ko": "가맹정보_브랜드별 가맹점 현황(평균매출)",
        "service": "FftcBrandFrcsStatsService",
        "operations": ["getBrandFrcsStats"],
        "why_ko": "가맹점 수·신규·계약종료·해지·평균매출 — 폐점률 계산의 핵심",
    },
    {
        "key": "brand_direct_stores", "dataset_id": "15125490",
        "title_ko": "가맹정보_브랜드 가맹점 및 직영점정보",
        "service": "FftcBrandFrcsDropInfo3_Service",
        "operations": ["getbrandFrcsDmsstus2", "getBrandFrcsDmsstus2"],
        "why_ko": "지역별 가맹점·직영점 수",
    },
    {
        "key": "brand_store_change", "dataset_id": "15125491",
        "title_ko": "가맹정보_브랜드 가맹점 변경현황",
        "service": "FftcBrandFrcsChghst2_Service",
        "operations": ["getbrandFrcsFlctnstus", "getBrandFrcsFlctnstus"],
        "why_ko": "연초·신규·계약종료·계약해지·연말 가맹점 수",
    },
    {
        "key": "brand_startup_amount", "dataset_id": "15110265",
        "title_ko": "가맹정보_브랜드별 창업 금액 현황",
        "service": "FftcBrandFntnStatsService",
        "operations": ["getBrandFntnStats"],
        "why_ko": "가맹비·보증금·교육비 등 창업 금액 통계",
    },
    {
        "key": "brand_interior_cost", "dataset_id": "15125479",
        "title_ko": "가맹정보_브랜드 가맹점 인테리어 비용정보",
        "service": "FftcBrandFrcsIntInfo2_Service",
        "operations": ["getbrandFrcsBzmnIntrrctinfo", "getBrandFrcsBzmnIntrrctinfo"],
        "why_ko": "단위면적 인테리어 금액·점포 기준면적",
    },
    {
        "key": "brand_franchise_fee", "dataset_id": "15125476",
        "title_ko": "가맹정보_브랜드 가맹점 사업자 가맹금 정보",
        "service": "FftcbrandfrcsjnntinfoService",
        "operations": ["getbrandFrcsJnntinfo", "getBrandFrcsJnntinfo"],
        "why_ko": "가맹금 항목·금액",
    },
    {
        "key": "brand_burden", "dataset_id": "15125475",
        "title_ko": "가맹정보_브랜드 가맹점 사업자의 부담금정보",
        "service": "FftcBrandFrcsAlotmInfo2_Service",
        "operations": ["getbrandFrcsbzmnAlotminfo", "getBrandFrcsBzmnAlotminfo"],
        "why_ko": "영업 중 부담금 항목",
    },
    {
        "key": "brand_fee_deposit", "dataset_id": "15125480",
        "title_ko": "가맹정보_브랜드 가맹점 사업자의 예치금정보",
        "service": "FftcBrandFrcsAlotmCtInfo2_Service",
        "operations": ["getbrandFrcsBzmnDepoinfo", "getBrandFrcsBzmnDepoinfo"],
        "why_ko": "예치금액·예치제도 여부 — 가맹금 예치 확인",
    },
    {
        "key": "hq_violation", "dataset_id": "15125463",
        "title_ko": "가맹정보_가맹본부 법 위반정보",
        "service": "FftcJnghdqrtrsExctvVioltInfo2_Service",
        "operations": ["getjnghdqrtrsLawVioltinfo", "getjnghdqrtrsLawViol", "getJnghdqrtrsLawViol"],
        "why_ko": "시정조치·민사소송 패소·형벌선고 건수",
    },
    {
        "key": "hq_corrective", "dataset_id": "15125464",
        "title_ko": "가맹정보_가맹본부 법 위반 시정조치",
        "service": "FftcjnghdqrtrscorecactninfoService",
        "operations": ["getjnghdqrtrsCorecActninfo", "getjnghdqrtrsCorecActni"],
        "why_ko": "시정조치 내역",
    },
    {
        "key": "hq_penalty", "dataset_id": "15125466",
        "title_ko": "가맹정보_가맹본부 법 위반 형벌선고",
        "service": "FftcjnghdqrtrspetyadjuinfoService",
        "operations": ["getjnghdqrtrsPetyAdjuinfo", "getjnghdqrtrsPetyAdjuinf"],
        "why_ko": "형벌선고 내역",
    },
    {
        "key": "brand_iprs", "dataset_id": "15125471",
        "title_ko": "가맹정보_브랜드 지식재산권",
        "service": "FftcbrandiprsinfoService",
        "operations": ["getbrandIprsinfo", "getBrandIprsinfo"],
        "why_ko": "상표 출원·등록 — 영업표지 권리 확인",
    },
    {
        "key": "brand_store_period", "dataset_id": "15125484",
        "title_ko": "가맹정보_브랜드 가맹점 사업자 가맹기간",
        "service": "FftcBrandFrcsStrtInfo2_Service",
        "operations": ["getbrandFrcsPdinfo", "getBrandFrcsPdinfo"],
        "why_ko": "최초·연장 계약년수, 권장 종업원 수",
    },
    {
        "key": "brand_compare", "dataset_id": "15125517",
        "title_ko": "가맹정보_브랜드 비교 목록",
        "service": "FftcBrandCompInfo2_Service",
        "operations": ["getbrandCompListinfo", "getBrandCompListinfo"],
        "why_ko": "브랜드 간 비교용 요약",
    },
    {
        "key": "hq_history", "dataset_id": "15125452",
        "title_ko": "가맹정보_가맹본부 일반 정보 변경 이력",
        "service": "FftcjnghdqrtrsInfoChghst2_Service",
        "operations": ["getjnghdqrtrsGnlHist", "getjnghdqrtrsGnlHistory"],
        "why_ko": "본부 정보 변경 이력",
    },
    {
        "key": "brand_unit_sales", "dataset_id": "15125494",
        "title_ko": "가맹정보_브랜드 가맹점 단위면적당 평균 매출",
        "service": "FftcBrandFrcsUnitAvrSalInfo3_Service",
        "operations": ["getbrandFrcsBzmnAvrgsalinfo", "getBrandFrcsBzmnAvrgsalinfo",
                       "getbrandFrcsBzmnAvrgs"],
        "why_ko": "면적당 매출 — 임차료 대비 손익 판단",
    },
]

# 오퍼레이션이 공개되지 않은(LINK 형) 데이터셋 — 호출 대상이 아니다.
LINK_ONLY = [
    {"key": "disclosure_list", "dataset_id": "15125569",
     "title_ko": "가맹정보_정보공개서_목록_조회",
     "note_ko": "정보공개서 목록 — data.go.kr 제공형태 LINK(문서 열람). REST 호출 주소 없음."},
    {"key": "disclosure_toc", "dataset_id": "15125570",
     "title_ko": "가맹정보_정보공개서_목차_조회",
     "note_ko": "정보공개서 목차 — 제공형태 LINK."},
    {"key": "disclosure_body", "dataset_id": "15125571",
     "title_ko": "가맹정보_정보공개서_본문_조회",
     "note_ko": ("정보공개서 본문 — 제공형태 LINK. 검증 시점에 REST 오퍼레이션 주소가 "
                "공개되어 있지 않았고, 본문은 가맹사업정보제공시스템(franchise.ftc.go.kr)에서 "
                "열람하는 문서입니다.")},
]

CODE_HINTS = {
    "0": "정상",
    "10": "요청 파라미터 오류",
    "12": "해당 오퍼레이션 없음(서비스명·오퍼레이션 확인 필요)",
    "20": "접근 거부(트래픽 초과 등)",
    "22": "일일 호출 한도 초과",
    "30": "인증키가 이 서비스에 등록되지 않음 — 활용신청 필요",
    "31": "활용기간 만료",
}


def _code_of(body: str, status: int) -> str:
    match = re.search(r'"?returnReasonCode"?\s*[:>]\s*"?(-?\d+)', body)
    if match:
        return match.group(1)
    match = re.search(r'"resultCode"\s*:\s*"?([A-Z0-9-]+)', body)
    if match:
        return match.group(1)
    return "http_%s" % status


def _call(url: str, timeout: float = 25.0) -> tuple:
    request = urllib.request.Request(url, headers={
        "User-Agent": "frnc/0.1 (+data.go.kr franchise)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - 네트워크 실패도 결과로 남긴다
        return "ERR", str(exc)[:200]


def probe_dataset(key: str, item: Dict[str, Any]) -> Dict[str, Any]:
    params = {
        "serviceKey": key, "pageNo": "1", "numOfRows": "2", "resultType": "json",
        "jngBizCrtraYr": "2024", "brandMnno": "BRD_20080100007",
    }
    attempts = []
    chosen: Optional[Dict[str, Any]] = None
    for operation in item["operations"]:
        url = f"{HOST}/{item['service']}/{operation}?" + urllib.parse.urlencode(params)
        status, body = _call(url)
        code = _code_of(body, status)
        attempts.append({"operation": operation, "http_status": status, "code": code,
                         "message": _snippet(body)})
        if code not in ("12",):
            chosen = {"operation": operation, "code": code, "http_status": status}
            break
    if chosen is None:
        chosen = {"operation": None, "code": "12", "http_status": attempts[-1]["http_status"]}
    approved = chosen["code"] == "0"
    return {
        "key": item["key"],
        "dataset_id": item["dataset_id"],
        "title_ko": item["title_ko"],
        "why_ko": item["why_ko"],
        "service": item["service"],
        "endpoint": f"{HOST}/{item['service']}/{chosen['operation']}" if chosen["operation"] else None,
        "operation": chosen["operation"],
        "approval": "approved" if approved else (
            "not_registered" if chosen["code"] == "30" else "unverified"),
        "code": chosen["code"],
        "code_hint_ko": CODE_HINTS.get(chosen["code"], ""),
        "apply_url": PORTAL.format(dataset_id=item["dataset_id"]),
        "attempts": attempts,
    }


def _snippet(body: str) -> str:
    text = re.sub(r"\s+", " ", str(body or "")).strip()
    return text[:220]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="가맹정보 오픈API 승인 상태 실측")
    parser.add_argument("--key", default=os.environ.get("DATA_GO_KR_SERVICE_KEY", ""))
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    service_key = (args.key or "").strip()
    if not service_key:
        print("DATA_GO_KR_SERVICE_KEY 가 없습니다.", file=sys.stderr)
        return 2
    stamp = datetime.now(KST)
    results = [probe_dataset(service_key, item) for item in DATASETS]
    approved = [row for row in results if row["approval"] == "approved"]
    not_registered = [row for row in results if row["approval"] == "not_registered"]
    unverified = [row for row in results if row["approval"] == "unverified"]
    payload = {
        "generated_at": stamp.isoformat(timespec="seconds"),
        "provider": "공정거래위원회 가맹정보 (data.go.kr 1130000)",
        "note_ko": (
            "각 데이터셋의 오퍼레이션을 실제 호출해 응답 코드를 기록했습니다. "
            "코드 30 은 오퍼레이션이 존재하지만 이 인증키가 해당 서비스에 등록되지 않았다는 뜻이고, "
            "코드 12 는 오퍼레이션 이름이 존재하지 않는다는 뜻입니다(추측 금지 확인용). "
            "인증키 값은 파일에 남기지 않았습니다."
        ),
        "counts": {
            "total": len(results), "approved": len(approved),
            "not_registered": len(not_registered), "unverified": len(unverified),
            "link_only": len(LINK_ONLY),
        },
        "datasets": results,
        "link_only": [dict(item, apply_url=PORTAL.format(dataset_id=item["dataset_id"]))
                      for item in LINK_ONLY],
        "apply_urls": sorted({row["apply_url"] for row in not_registered}),
    }
    out = args.out or f"api-verification-{stamp.strftime('%Y-%m-%d')}.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    print(f"{out}: 전체 {len(results)} · 승인 {len(approved)} · 미등록 {len(not_registered)} "
          f"· 미확인 {len(unverified)}")
    for row in results:
        print(f"  {row['approval']:14} {row['code']:>3} {row['dataset_id']} {row['title_ko']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
