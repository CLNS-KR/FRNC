"""공정거래위원회 가맹정보 오픈API 실시간 어댑터 + 내장 샘플 폴백.

중요 — 지금 이 키는 가맹정보 API 에 **등록되어 있지 않습니다**
-------------------------------------------------------------
`tools/verify_ftc_apis.py` 로 18개 데이터셋을 실제 호출한 결과(2026-11-21):
승인 0 · 키 미등록(코드 30) 17 · 오퍼레이션 미확인(코드 12) 1. 그래서 이 모듈은
1) 활용신청이 승인되면 **같은 코드로** 실데이터를 조회하고,
2) 승인 전에는 내장 샘플로 응답 구조와 화면을 그대로 보여 주며,
3) 어떤 데이터셋을 신청해야 하는지 `apply_urls` 로 알려 줍니다.

정직한 한계
-----------
성공 응답(코드 00)을 아직 받아 보지 못했으므로, 응답 행 추출(`_rows`)은 문서화된
`response.body.items.item` · `items` · `data` 세 형태를 모두 받도록 방어적으로 썼습니다.
승인 후 첫 호출에서 형태가 다르면 `rows()` 가 빈 목록을 돌려주고 `status` 가
`unexpected_shape` 로 남습니다(조용히 0건으로 답하지 않습니다).

인증키는 환경변수에서만 읽고, 예외 메시지·응답·파일에 남기지 않습니다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import engine

KST = timezone(timedelta(hours=9))
PROJECT_DIR = Path(__file__).resolve().parents[2]
SAMPLE_PATH = Path(__file__).resolve().parent / "sample_brands.json"
VERIFICATION_GLOB = "api-verification-*.json"
HOST = "https://apis.data.go.kr/1130000"

CODE_OK = "0"
CODE_NO_SERVICE = "12"
CODE_NOT_REGISTERED = "30"

# 승인 상태별 사람용 안내
STATUS_MESSAGES_KO = {
    "live": "공정거래위원회 가맹정보 API 실데이터입니다.",
    "not_approved": ("공정거래위원회 가맹정보 API 활용신청이 아직 승인되지 않아 내장 샘플로 보여 줍니다. "
                     "아래 신청 주소에서 활용신청하면 같은 화면이 실데이터로 바뀝니다."),
    "no_key": "공공데이터포털 인증키가 설정되지 않아 내장 샘플로 보여 줍니다.",
    "not_found": "해당 이름의 브랜드를 찾지 못했습니다. 브랜드명을 짧게(예: '치킨') 넣거나 브랜드관리번호로 조회하세요.",
    "network_error": "공정거래위원회 API 응답을 받지 못해 내장 샘플로 보여 줍니다.",
    "unexpected_shape": ("API가 200으로 응답했지만 행 구조를 해석하지 못했습니다. "
                         "0건으로 단정하지 않습니다."),
}

HOW_TO_CONFIRM_KO = [
    "가맹사업정보제공시스템(franchise.ftc.go.kr)에서 브랜드명으로 등록 정보공개서를 검색",
    "정보공개서 등록번호·최근 등록일과 본부가 준 문서를 대조",
    "가맹점 변동(신규·계약종료·계약해지)과 평균매출액을 최근 3년치로 확인",
    "본부의 공정위 시정조치·과징금 이력 확인",
]

# 0건·미발견일 때 **항상** 붙는 고정 안내.
# 0건은 '그런 브랜드가 없다'도, '문제없다·안전하다'도 아니다 — 단정 금지의 핵심 문장이다.
ZERO_RESULT_NOTICE_KO = (
    "검색 결과가 0건이라는 것은 '그런 브랜드가 없다'는 뜻도, '문제없다·안전하다'는 뜻도 아닙니다. "
    "브랜드명 표기(띄어쓰기·영문/한글·줄임말)가 다르거나, 아직 조회 데이터에 없는 경우일 수 있습니다. "
    "가맹사업정보제공시스템에서 등록 정보공개서를 직접 확인하세요."
)


class FtcError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", hint_ko: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.hint_ko = hint_ko


# ---------------------------------------------------------------------------
# 검증 파일(오퍼레이션·승인 상태) 로드
# ---------------------------------------------------------------------------
def _latest_verification_path() -> Optional[Path]:
    try:
        files = sorted(PROJECT_DIR.glob(VERIFICATION_GLOB))
    except OSError:
        return None
    return files[-1] if files else None


@lru_cache(maxsize=1)
def verification() -> Dict[str, Any]:
    path = _latest_verification_path()
    if path is None:
        return {"datasets": [], "link_only": [], "apply_urls": [], "generated_at": None}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"datasets": [], "link_only": [], "apply_urls": [], "generated_at": None}
    data["_path"] = str(path.name)
    return data


def dataset_index() -> Dict[str, Dict[str, Any]]:
    return {row["key"]: row for row in verification().get("datasets") or [] if row.get("key")}


def dataset_summary() -> Dict[str, Any]:
    data = verification()
    rows = data.get("datasets") or []
    counts = {"total": len(rows),
              "approved": sum(1 for row in rows if row.get("approval") == "approved"),
              "not_registered": sum(1 for row in rows if row.get("approval") == "not_registered"),
              "unverified": sum(1 for row in rows if row.get("approval") == "unverified")}
    return {
        "generated_at": data.get("generated_at"),
        "file": data.get("_path"),
        "counts": counts,
        "apply_urls": data.get("apply_urls") or [],
        "datasets": [
            {key: row.get(key) for key in
             ("key", "dataset_id", "title_ko", "why_ko", "endpoint", "approval", "code", "apply_url")}
            for row in rows
        ],
        "link_only": data.get("link_only") or [],
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def service_key(env: Optional[Dict[str, str]] = None) -> str:
    source = os.environ if env is None else env
    return str(source.get("DATA_GO_KR_SERVICE_KEY") or "").strip()


def _urlopen(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "frnc/0.1 (+data.go.kr franchise)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _code_of(body: str, status: Optional[int]) -> str:
    match = re.search(r'"?returnReasonCode"?\s*[:>]\s*"?(-?\d+)', body)
    if match:
        return match.group(1)
    match = re.search(r'"resultCode"\s*:\s*"?([A-Za-z0-9-]+)', body)
    if match:
        return match.group(1)
    return f"http_{status}" if status is not None else "unknown"


class FtcClient:
    """한 인증키로 여러 가맹정보 데이터셋을 부르는 최소 클라이언트."""

    def __init__(self, key: str, *, timeout: float = 20.0,
                 opener: Optional[Callable[[str, float], bytes]] = None) -> None:
        self.key = str(key or "").strip()
        self.timeout = timeout
        self._opener = opener or _urlopen

    def call(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """엔드포인트 1회 호출 → `{code, status, rows, raw_shape}`. 키는 예외 메시지에 남기지 않는다."""
        if not self.key:
            return {"code": "no_key", "status": None, "rows": [], "raw_shape": "none"}
        query = {"serviceKey": self.key}
        for key, value in params.items():
            if value is None or value == "":
                continue
            query[key] = str(value)
        url = endpoint + "?" + urllib.parse.urlencode(query)
        status: Optional[int] = None
        try:
            body = self._opener(url, self.timeout).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                body = ""
        except Exception as exc:  # noqa: BLE001 - 네트워크 오류는 상태로 돌려준다
            return {"code": "network_error", "status": None, "rows": [],
                    "raw_shape": type(exc).__name__}
        code = _code_of(body, status)
        payload: Any = None
        if body.strip().startswith(("{", "[")):
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
        # 성공 응답에는 오류 코드가 없으므로, JSON 본문이 해석되면 코드 00 으로 본다.
        if code in ("unknown", "http_200") and payload is not None:
            code = CODE_OK
        if code == "00":
            code = CODE_OK
        rows, shape = _rows(payload)
        return {"code": code, "status": status, "rows": rows, "raw_shape": shape}


def _rows(payload: Any) -> Tuple[List[Dict[str, Any]], str]:
    """문서화된 세 봉투(`response.body.items.item`·`items`·`data`)와 중첩 목록을 방어적으로 해석."""
    if not isinstance(payload, dict):
        return [], "none"
    if "response" in payload and isinstance(payload["response"], dict):
        body = payload["response"].get("body") or {}
        items = body.get("items") if isinstance(body, dict) else None
        if isinstance(items, dict):
            item = items.get("item")
            if isinstance(item, list):
                return [row for row in item if isinstance(row, dict)], "response.items.item"
            if isinstance(item, dict):
                return [item], "response.items.item"
        if isinstance(items, list):
            return [row for row in items if isinstance(row, dict)], "response.items"
    if "items" in payload:
        items = payload["items"]
        if isinstance(items, dict):
            item = items.get("item")
            if isinstance(item, list):
                return [row for row in item if isinstance(row, dict)], "items.item"
            if isinstance(item, dict):
                return [item], "items.item"
            if all(isinstance(value, (str, int, float)) for value in items.values()):
                return [items], "items"
        if isinstance(items, list):
            return [row for row in items if isinstance(row, dict)], "items"
    if isinstance(payload.get("data"), list):
        return [row for row in payload["data"] if isinstance(row, dict)], "data"
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return [row for row in value if isinstance(row, dict)], "nested_list"
    return [], "unknown"


# ---------------------------------------------------------------------------
# 실시간 조회
# ---------------------------------------------------------------------------
def _year_candidates(year: Optional[int]) -> List[int]:
    if year:
        return [int(year)]
    today = datetime.now(KST)
    return [today.year - 1, today.year - 2, today.year - 3]


def _brand_params(year: int) -> Dict[str, Any]:
    return {"pageNo": 1, "numOfRows": 100, "resultType": "json", "jngBizCrtraYr": year}


def _brand_params_with_code(brand_code: str, year: int) -> Dict[str, Any]:
    return {**_brand_params(year), "brandMnno": brand_code}


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _pick(row: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _num(value: Any) -> Optional[float]:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def normalize_brand_row(row: Dict[str, Any], year: Optional[int] = None,
                        data_state: str = "live") -> Dict[str, Any]:
    """API 행(또는 샘플 행) → 화면·API 공통 필드."""
    def amount(*names: str) -> Optional[int]:
        value = _num(_pick(row, *names))
        return int(value) if value is not None else None

    return {
        "data_state": data_state,
        "base_year": int(_num(_pick(row, "baseYear", "jngBizCrtraYr")) or (year or 0)) or None,
        "brand_name": _pick(row, "brandNm", "brand_name"),
        "brand_code": _pick(row, "brandMnno", "brand_code"),
        "hq_name": _pick(row, "corpNm", "jnghdqrtrsNm", "hq_name"),
        "hq_code": _pick(row, "jnghdqrtrsMnno", "hq_code"),
        "industry_large": _pick(row, "indutyLclasNm", "industry_large"),
        "industry_mid": _pick(row, "indutyMlsfcNm", "industry_mid"),
        "main_product": _pick(row, "majrGdsNm", "main_product"),
        "started_on": _pick(row, "jngBizStrtDate", "started_on"),
        "brno": _pick(row, "brno"),
        "stores_year_end": amount("frcsCnt", "stores_year_end"),
        "new_stores": amount("newFrcsCnt", "new_stores"),
        "terminated": amount("ctrtTrmnCnt", "terminated"),
        "cancelled": amount("ctrtCnncCnt", "cancelled"),
        "avg_sales_krw": amount("avrgSalesAmt", "avg_sales_krw"),
        "unit_area_sales_krw": amount("arUnitAvrgSalesAmt", "unit_area_sales_krw"),
        "franchise_fee_krw": amount("jnntAmt", "franchise_fee_krw"),
        "deposit_krw": amount("gtnAmt", "deposit_krw"),
        "education_fee_krw": amount("edcAmt", "education_fee_krw"),
        "interior_per_m2_krw": amount("intrrAmt", "interior_per_m2_krw"),
        "disclosure_no": _pick(row, "infoPblsRgsNo", "disclosure_no"),
        "disclosure_registered_on": _pick(row, "infoPblsRgsDe", "disclosure_registered_on"),
        "legal_violation_count": amount("lawVioltCnt", "legal_violation_count"),
        "closure_rate_3y_pct": _num(_pick(row, "closure_rate_3y_pct")),
        "avg_store_area_m2": _num(_pick(row, "avg_store_area_m2")),
        "note_ko": _pick(row, "note_ko") or "",
    }


def sample_brands() -> Dict[str, Any]:
    try:
        with open(SAMPLE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"brands": [], "note_ko": ""}


def sample_lookup(query: str = "", brand_code: str = "") -> List[Dict[str, Any]]:
    rows = sample_brands().get("brands") or []
    target = _norm(query)
    code = _norm(brand_code)
    found = []
    for row in rows:
        if code and _norm(row.get("brandMnno")) == code:
            found.append(row)
            continue
        if target and target in _norm(row.get("brandNm")):
            found.append(row)
    if not found and not target and not code:
        found = rows[:3]
    return [normalize_brand_row(row, data_state="sample") for row in found]


def closure_rate_from_rows(row: Dict[str, Any]) -> Optional[float]:
    """연초·신규·종료·해지로 폐점률을 추정(연초 = 연말 - 신규 + 종료 + 해지)."""
    end = _num(row.get("frcsCnt") or row.get("stores_year_end"))
    new = _num(row.get("newFrcsCnt") or row.get("new_stores"))
    term = _num(row.get("ctrtTrmnCnt") or row.get("terminated"))
    cancel = _num(row.get("ctrtCnncCnt") or row.get("cancelled"))
    if None in (end, new, term, cancel):
        return None
    start = end - new + term + cancel
    if start <= 0:
        return None
    return round((term + cancel) / start * 100.0, 1)


def lookup(brand_name: str = "", brand_code: str = "", year: Optional[int] = None,
           client: Optional[FtcClient] = None,
           env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """브랜드 1건(또는 검색어 일치 목록)의 정보공개서 요약.

    승인 전이면 내장 샘플 + 신청 주소를 돌려주고, `data_state` 로 항상 구분한다.
    0건·미발견이면 `zero_result=True` 와 고정 안내 문구를 붙인다(단정 금지).
    """
    result = _lookup_impl(brand_name, brand_code, year, client, env)
    status = str(result.get("status") or "")
    brands = result.get("brands") or []
    # 확정된 0건만 센다. 승인 전·키 없음·네트워크 실패·해석 실패는 '0건'이 아니다.
    zero = status == "not_found" or (status == "live" and not brands)
    result["zero_result"] = zero
    result["zero_result_notice_ko"] = ZERO_RESULT_NOTICE_KO
    return result


def _lookup_impl(brand_name: str = "", brand_code: str = "", year: Optional[int] = None,
                 client: Optional[FtcClient] = None,
                 env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    index = dataset_index()
    summary = dataset_summary()
    name = str(brand_name or "").strip()
    code = str(brand_code or "").strip()
    if client is None:
        key = service_key(env)
        client = FtcClient(key) if key else None
    entry = index.get("brand_list") or {}
    result: Dict[str, Any] = {
        "query": {"brand_name": name or None, "brand_code": code or None, "year": year},
        "data_state": "sample",
        "status": "no_key",
        "brands": [],
        "apply_urls": summary.get("apply_urls") or [],
        "datasets": [entry] if entry else [],
        "message_ko": STATUS_MESSAGES_KO["no_key"],
        "how_to_confirm_ko": HOW_TO_CONFIRM_KO,
        "sample_notice_ko": sample_brands().get("note_ko", ""),
        "source_ko": sample_brands().get("source_ko", ""),
        "disclosure_portal": "https://franchise.ftc.go.kr",
        "checked_at": engine.now_iso(),
    }
    if client is not None and entry.get("endpoint"):
        attempt = _live_attempt(client, entry, name, code, year, index)
        if attempt["status"] == "live":
            result.update(attempt)
            return result
        if attempt["status"] == "not_found":
            result.update({"status": "not_found", "message_ko": STATUS_MESSAGES_KO["not_found"]})
            result["datasets"] = attempt.get("datasets") or result["datasets"]
            return result
        result.update({"status": attempt["status"], "code": attempt.get("code"),
                       "message_ko": STATUS_MESSAGES_KO.get(attempt["status"],
                                                           STATUS_MESSAGES_KO["network_error"]),
                       "apply_urls": attempt.get("apply_urls") or result["apply_urls"],
                       "datasets": attempt.get("datasets") or result["datasets"]})
        # 승인 전·네트워크 실패에도 화면 구조를 보여 줄 샘플을 함께 채운다(항상 data_state 로 구분).
        result["brands"] = sample_lookup(name, code)
        result["data_state"] = "sample"
        return result
    brands = sample_lookup(name, code)
    if brands:
        result["brands"] = brands
        if result["status"] == "no_key":
            result["status"] = "sample"
    elif name or code:
        result["status"] = "not_found"
        result["message_ko"] = STATUS_MESSAGES_KO["not_found"]
    else:
        result["brands"] = sample_lookup()
        result["status"] = "sample"
    return result


def _live_attempt(client: FtcClient, entry: Dict[str, Any], name: str, code: str,
                  year: Optional[int], index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    datasets = [entry]
    apply_urls: List[str] = []
    last_code = ""
    last_shape = "none"
    for candidate_year in _year_candidates(year):
        params = (_brand_params_with_code(code, candidate_year) if code
                  else _brand_params(candidate_year))
        response = client.call(entry["endpoint"], params)
        last_code = str(response["code"])
        last_shape = str(response.get("raw_shape") or "none")
        if last_code != CODE_OK:
            break
        rows = response["rows"]
        if rows:
            matched = _match_rows(rows, name, code)
            if not matched:
                continue
            enriched, extra_datasets, extra_apply = _enrich(client, matched, index)
            datasets.extend(extra_datasets)
            apply_urls.extend(extra_apply)
            brands = [normalize_brand_row(row, candidate_year, "live") for row in enriched]
            for brand in brands:
                if brand.get("closure_rate_3y_pct") is None:
                    brand["closure_rate_3y_pct"] = closure_rate_from_rows(brand) or None
            return {
                "status": "live",
                "data_state": "live",
                "code": last_code,
                "brands": brands,
                "datasets": datasets,
                "apply_urls": apply_urls,
                "message_ko": STATUS_MESSAGES_KO["live"],
            }
    if last_code == CODE_OK:
        if last_shape in ("unknown", "none"):
            return {"status": "unexpected_shape", "code": last_code, "datasets": datasets}
        return {"status": "not_found", "code": last_code, "datasets": datasets}
    if last_code == CODE_NOT_REGISTERED:
        return {"status": "not_approved", "code": last_code, "datasets": datasets,
                "apply_urls": [entry.get("apply_url")] if entry.get("apply_url") else []}
    if last_code == CODE_NO_SERVICE:
        return {"status": "not_approved", "code": last_code, "datasets": datasets,
                "apply_urls": [entry.get("apply_url")] if entry.get("apply_url") else []}
    if last_code == "no_key":
        return {"status": "no_key", "code": last_code}
    if last_code == "network_error":
        return {"status": "network_error", "code": last_code}
    return {"status": "not_approved", "code": last_code, "datasets": datasets}


def _match_rows(rows: List[Dict[str, Any]], name: str, code: str) -> List[Dict[str, Any]]:
    target_name = _norm(name)
    target_code = _norm(code)
    out: List[Dict[str, Any]] = []
    for row in rows:
        row_code = _norm(_pick(row, "brandMnno", "brand_code"))
        row_name = _norm(_pick(row, "brandNm", "brand_name"))
        if target_code and row_code == target_code:
            out.append(row)
        elif target_name and target_name in row_name:
            out.append(row)
    return out[:10]


def _enrich(client: FtcClient, matched: List[Dict[str, Any]],
            index: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]],
                                                       List[str]]:
    """본부 일반·브랜드 가맹점 현황을 승인된 경우에만 덧붙인다(실패는 무시)."""
    datasets: List[Dict[str, Any]] = []
    apply_urls: List[str] = []
    enriched: List[Dict[str, Any]] = []
    hq_entry = index.get("hq_general") or {}
    store_entry = index.get("brand_stores") or {}
    for row in matched:
        merged = dict(row)
        hq_code = _pick(row, "jnghdqrtrsMnno")
        if hq_entry.get("endpoint") and hq_code:
            response = client.call(hq_entry["endpoint"], {
                "pageNo": 1, "numOfRows": 5, "resultType": "json",
                "jngBizCrtraYr": _pick(row, "jngBizCrtraYr") or "",
                "jnghdqrtrsMnno": hq_code,
            })
            datasets.append({key: hq_entry.get(key) for key in
                             ("key", "dataset_id", "title_ko", "approval", "apply_url")})
            if str(response["code"]) == CODE_OK and response["rows"]:
                hq_row = response["rows"][0]
                for key, names in (
                    ("hq_name", ("corpNm", "jnghdqrtrsNm")),
                    ("industry_large", ("indutyLclasNm",)),
                    ("industry_mid", ("indutyMlsfcNm",)),
                ):
                    value = _pick(hq_row, *names)
                    if value and not _pick(merged, *names):
                        merged[names[0]] = value
            elif str(response["code"]) == CODE_NOT_REGISTERED and hq_entry.get("apply_url"):
                apply_urls.append(hq_entry["apply_url"])
        brand_code = _pick(row, "brandMnno")
        if store_entry.get("endpoint") and brand_code:
            response = client.call(store_entry["endpoint"], {
                "pageNo": 1, "numOfRows": 5, "resultType": "json",
                "jngBizCrtraYr": _pick(row, "jngBizCrtraYr") or "",
                "brandMnno": brand_code,
            })
            datasets.append({key: store_entry.get(key) for key in
                             ("key", "dataset_id", "title_ko", "approval", "apply_url")})
            if str(response["code"]) == CODE_OK and response["rows"]:
                store_row = response["rows"][0]
                for source, target in (("frcsCnt", "frcsCnt"), ("avrgSalesAmt", "avrgSalesAmt"),
                                       ("ctrtTrmnCnt", "ctrtTrmnCnt"),
                                       ("ctrtCnncCnt", "ctrtCnncCnt")):
                    value = _pick(store_row, source)
                    if value not in (None, ""):
                        merged[target] = value
            elif str(response["code"]) == CODE_NOT_REGISTERED and store_entry.get("apply_url"):
                apply_urls.append(store_entry["apply_url"])
        enriched.append(merged)
    return enriched, datasets, apply_urls


def health_block() -> Dict[str, Any]:
    """healthz·meta 에 넣는 실시간 어댑터 상태(키 값은 절대 넣지 않는다)."""
    summary = dataset_summary()
    key_present = bool(service_key())
    return {
        "live_api": "configured" if key_present else "no_key",
        "approval": summary["counts"],
        "verification_file": summary.get("file"),
        "verified_at": summary.get("generated_at"),
        "apply_urls": summary.get("apply_urls") or [],
    }
