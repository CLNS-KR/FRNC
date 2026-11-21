"""공정거래위원회 가맹정보 오픈API 실시간 어댑터 + 로컬 브랜드 색인 + 내장 샘플 폴백.

지금 상태(2026-11-21 실호출, `api-verification-2026-11-21.json`)
---------------------------------------------------------------
승인 4 · 키 미등록(코드 30) 13 · 오퍼레이션 미확인(코드 12) 1.
승인된 데이터셋은 브랜드 목록(15125467) · 가맹본부 일반(15125450) ·
가맹점 및 직영점(15125490) · 가맹점 변경현황(15125491) 입니다.

브랜드명 조회는 두 단계로 답합니다.
1) **로컬 브랜드 색인**(`brand_index`, `data/brands_index.json.gz`) — `getBrandinfo` 에는
   브랜드명 검색 파라미터가 없어 전체 페이지를 훑어 만든 색인입니다. `BBQ`·`교촌`·`BHC`
   같은 등록 브랜드를 이름으로 즉시 찾습니다.
2) 색인에 없으면 **실시간 API 전체 페이지 재조회** → 그래도 없으면 `not_found`
   (끝까지 받지 못했으면 `partial_scan` 으로 남기고 '없다'고 단정하지 않습니다).

가맹점 수·직영점 수·폐점률(2026-11-21 실측으로 고친 것)
---------------------------------------------------
- `15125490`(가맹점 및 직영점)은 **지역(시·도) 행과 '전체' 행을 함께** 돌려줍니다.
  예전에는 이걸 모두 더해 `BBQ` 가맹점 수를 4,632개로 두 배 부풀렸습니다(실제 연말 2,316개).
  지금은 **'전체' 행이 있으면 그 값을 쓰고**, 없을 때만 시·도 행을 합칩니다.
- `15125491`(가맹점 변경현황)은 `jngBizCrtraYr`+`brandMnno` 를 **반드시** 요구합니다(전체
  목록 호출은 코드 11). 그래서 이 데이터는 실시간 조회에서만 붙이고, 색인에는 넣지 않습니다.
- 폐점률은 '최근 3년'이 아니라 **기준연도의 전년 대비 1년 변동**입니다. 응답 필드는
  `closure_rate_pct`(연간) + `closure_rate_year` + `closure_rate_basis_ko`(연초·연말·신규·
  계약종료·계약해지)로 나눠 적고, 3년치를 모르는 값을 '3년 폐점률'이라 부르지 않습니다.
- 승인되지 않은 데이터셋이 주는 값(평균매출·가맹비·법 위반 이력 등)은 `null` 이며, 응답의
  `field_status.null` 이 **왜 비었는지·어떤 데이터셋인지·활용신청 주소**를 밝힙니다.
  `null` 은 '0'도 '없음·문제없음'도 아닙니다(`NULL_MEANING_KO`).
- 응답 행 추출(`_rows`)은 문서화된 `response.body.items.item` · `items` · `data` 세 형태를
  모두 받도록 방어적으로 썼습니다. 형태가 다르면 `status` 가 `unexpected_shape` 로 남고
  조용히 0건으로 답하지 않습니다.

인증키는 환경변수(또는 실행 진입점이 읽는 `.env`)에서만 읽고, 예외 메시지·응답·파일에
남기지 않습니다.
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

from . import brand_index, engine

KST = timezone(timedelta(hours=9))
PROJECT_DIR = Path(__file__).resolve().parents[2]
SAMPLE_PATH = Path(__file__).resolve().parent / "sample_brands.json"
VERIFICATION_GLOB = "api-verification-*.json"
HOST = "https://apis.data.go.kr/1130000"
BRAND_DATASET = "15125467"

CODE_OK = "0"
CODE_NO_SERVICE = "12"
CODE_NOT_REGISTERED = "30"

# 승인 상태별 사람용 안내(화면·API·MCP 공통). 단정 표현은 쓰지 않는다.
STATUS_MESSAGES_KO = {
    "live": "공정거래위원회 가맹정보 API 실데이터입니다.",
    "index": ("공정거래위원회 가맹정보 브랜드 목록(승인된 데이터셋)을 전체 페이지 훑어 만든 "
              "로컬 색인에서 찾았습니다."),
    "not_approved": ("이 데이터셋은 이 인증키로 등록되어 있지 않아 응답을 받지 못했습니다. "
                     "아래 신청 주소에서 활용신청하면 같은 화면이 실데이터로 채워집니다."),
    "no_key": ("인증키가 설정되지 않아 실시간 조회 없이 로컬 브랜드 색인·내장 샘플로만 "
               "보여 줍니다."),
    "not_found": ("등록 브랜드 색인에서 찾지 못했습니다. 브랜드명 표기가 다를 수 있으니 "
                  "짧게 넣거나 브랜드관리번호(BRD_...)로 조회해 보세요."),
    "partial_scan": ("API 전체 목록을 끝까지 받지 못해 '없다'고 단정하지 않습니다. "
                     "잠시 뒤 다시 조회하거나 브랜드관리번호로 조회해 보세요."),
    "network_error": "공정거래위원회 API 응답을 받지 못했습니다. 브랜드관리번호로 다시 시도해 보세요.",
    "unexpected_shape": ("API가 200으로 응답했지만 행 구조를 해석하지 못했습니다. "
                         "0건으로 단정하지 않습니다."),
}

# `not_found` 는 색인 규모·기준연도를 함께 말한다(과도한 단정 방지).
def not_found_message(name: str = "", index_meta: Optional[Dict[str, Any]] = None) -> str:
    meta = index_meta or brand_index.meta()
    head = f"'{name}' 브랜드를 " if name else "브랜드를 "
    if meta.get("available"):
        scope = (f"등록 브랜드 색인({int(meta.get('count') or 0):,}건 · "
                 f"{meta.get('year')}년 기준)")
    else:
        scope = "가맹정보 API 응답"
    return (f"{scope}에서 {head}찾지 못했습니다. "
            "표기(띄어쓰기·영문/한글·줄임말)가 다르거나 아직 목록에 없는 경우일 수 있어 "
            "'없다'고 단정하지 않습니다. 이름을 짧게 넣거나 브랜드관리번호(BRD_...)로 "
            "조회하고, 등록 정보공개서는 가맹사업정보제공시스템에서 확인하세요.")

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

# `null` 의 뜻 — 화면·API·MCP 가 같은 문장을 쓴다.
NULL_MEANING_KO = (
    "null 은 '0'도 '없음·문제없음'도 아닙니다. 그 값을 주는 공정위 데이터셋이 아직 이 인증키에 "
    "승인되지 않았거나, 이 브랜드·기준연도에 값이 없거나, 서버에 인증키가 없어 실시간 재조회를 "
    "하지 않은 경우입니다. 어느 경우인지는 field_status.null 이 항목별로 밝힙니다."
)

# 가맹점 및 직영점 데이터셋(15125490)은 지역 행과 '전체' 합계 행을 함께 준다.
STORE_TOTAL_AREA = "전체"

# 데이터셋 키 → 데이터셋 번호(검증 파일을 못 읽어도 근거를 밝힐 수 있게).
DATASET_IDS = {
    "brand_list": "15125467", "hq_general": "15125450", "brand_stores": "15110241",
    "brand_direct_stores": "15125490", "brand_store_change": "15125491",
    "brand_startup_amount": "15110265", "brand_interior_cost": "15125479",
    "brand_franchise_fee": "15125476", "brand_burden": "15125475",
    "brand_fee_deposit": "15125480", "hq_violation": "15125463",
    "hq_corrective": "15125464", "hq_penalty": "15125466", "brand_iprs": "15125471",
    "brand_store_period": "15125484", "brand_compare": "15125517", "hq_history": "15125452",
    "brand_unit_sales": "15125494",
}

# `lookup_brand_disclosure` 응답 필드 ↔ 그 값을 주는 데이터셋.
# (필드, 화면 라벨, 데이터셋 키 또는 None, 데이터셋이 없을 때의 설명)
FIELD_SPECS = (
    ("brand_name", "브랜드명", "brand_list", ""),
    ("brand_code", "브랜드관리번호", "brand_list", ""),
    ("hq_name", "가맹본부", "brand_list", ""),
    ("industry_large", "업종(대)", "brand_list", ""),
    ("industry_mid", "업종(중)", "brand_list", ""),
    ("main_product", "주요상품", "brand_list", ""),
    ("started_on", "가맹사업 개시일", "brand_list", ""),
    ("base_year", "기준연도", "brand_list", ""),
    ("brno", "사업자등록번호", "brand_list", ""),
    ("stores_year_end", "가맹점 수(자료 회계연도 연말)", "brand_direct_stores", ""),
    ("direct_stores", "직영점 수", "brand_direct_stores", ""),
    ("stores_area_count", "지역(시·도) 수", "brand_direct_stores", ""),
    ("start_stores", "연초 가맹점 수", "brand_store_change", ""),
    ("new_stores", "신규 가맹점", "brand_store_change", ""),
    ("terminated", "계약종료", "brand_store_change", ""),
    ("cancelled", "계약해지", "brand_store_change", ""),
    ("closure_rate_pct", "연간 폐점률(%)", "brand_store_change", ""),
    ("avg_sales_krw", "가맹점 평균매출액", "brand_stores", ""),
    ("franchise_fee_krw", "가맹비", "brand_startup_amount", ""),
    ("education_fee_krw", "가맹교육비", "brand_startup_amount", ""),
    ("deposit_krw", "가맹보증금", "brand_startup_amount", ""),
    ("interior_per_m2_krw", "인테리어 비용(㎡당)", "brand_interior_cost", ""),
    ("legal_violation_count", "법 위반 이력", "hq_violation", ""),
    ("disclosure_no", "정보공개서 등록번호", None,
     "브랜드 목록·가맹점 데이터셋에는 정보공개서 등록번호가 없습니다. "
     "가맹사업정보제공시스템(franchise.ftc.go.kr)에서 직접 확인하세요."),
    ("disclosure_registered_on", "정보공개서 등록일", None,
     "브랜드 목록·가맹점 데이터셋에는 등록일이 없습니다. "
     "가맹사업정보제공시스템(franchise.ftc.go.kr)에서 직접 확인하세요."),
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


def brand_endpoint() -> str:
    """브랜드 목록(15125467) 오퍼레이션 주소 — 검증 파일의 값을 그대로 쓴다."""
    entry = dataset_index().get("brand_list") or {}
    return str(entry.get("endpoint") or "").strip()


def data_state(env: Optional[Dict[str, str]] = None) -> str:
    """브랜드 조회가 실제로 무엇을 근거로 답하는지 — `live` / `sample`.

    승인된 데이터셋이 있거나 로컬 색인이 있으면 `live`(공개 API 결과를 근거로 답한다).
    둘 다 없을 때만 `sample`(내장 가상 데이터)이다.
    """
    summary = dataset_summary()
    if summary["counts"]["approved"] > 0 and service_key(env):
        return "live"
    if brand_index.meta().get("available"):
        return "live"
    if summary["counts"]["approved"] > 0:
        return "live"
    return "sample"


def state_note_ko(env: Optional[Dict[str, str]] = None, state: Optional[str] = None) -> str:
    """화면·llms.txt 상단 상태 문장 — 사실과 다른 안내("승인 전이라 샘플")를 쓰지 않는다.

    `state` 를 주면 그 값(live/sample)에 맞춰 쓴다(화면이 넘겨 준 값 우선).
    """
    summary = dataset_summary()
    counts = summary["counts"]
    idx = brand_index.meta()
    current = (state or data_state(env) or "").strip().lower()
    approved_titles = [row.get("title_ko") for row in summary.get("datasets") or []
                       if row.get("approval") == "approved"]
    parts: List[str] = []
    if current == "live":
        if service_key(env):
            parts.append("브랜드 조회는 공정위 가맹정보 API 실데이터로 동작합니다.")
        else:
            parts.append("브랜드 조회는 공정위 가맹정보 API 실데이터로 동작합니다"
                         "(승인 데이터셋 전체 페이지로 만든 색인 기준).")
        if idx.get("available"):
            parts.append(f"브랜드 목록(승인) 색인 {int(idx.get('count') or 0):,}건 · "
                         f"{idx.get('year')}년 기준"
                         + (f" · 색인 갱신 {str(idx.get('built_at'))[:10]}" if idx.get("built_at") else "")
                         + ".")
        else:
            parts.append("로컬 색인이 없어 조회할 때마다 전체 페이지를 훑습니다.")
    else:
        parts.append("공정위 가맹정보 API 승인 데이터셋이 없어 브랜드 조회는 내장 샘플로 동작합니다.")
    if current == "live" and counts["approved"]:
        parts.append(f"승인 데이터셋 {counts['approved']}/{counts['total']}종"
                     + (f"({', '.join(t for t in approved_titles if t)})" if approved_titles else "") + ".")
    if not service_key(env):
        parts.append("서버 인증키가 없어 실시간 재조회(가맹점 수·변동)는 하지 않습니다.")
    parts.append("리스크 판정은 입력한 조건과 법제처 실조회 조문으로 그대로 계산합니다.")
    return " ".join(parts)


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
        """엔드포인트 1회 호출 → `{code, status, rows, raw_shape, total}`. 키는 예외 메시지에 남기지 않는다."""
        if not self.key:
            return {"code": "no_key", "status": None, "rows": [], "raw_shape": "none",
                    "total": None}
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
                    "raw_shape": type(exc).__name__, "total": None}
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
        return {"code": code, "status": status, "rows": rows, "raw_shape": shape,
                "total": _total_count(payload)}


def _total_count(payload: Any) -> Optional[int]:
    """봉투 어디에 있든 `totalCount` 를 찾아 정수로 돌려준다(페이지 순회 종료 판단용)."""
    if not isinstance(payload, dict):
        return None
    candidates: List[Any] = [payload.get("totalCount")]
    response = payload.get("response")
    if isinstance(response, dict):
        body = response.get("body")
        if isinstance(body, dict):
            candidates.append(body.get("totalCount"))
        candidates.append(response.get("totalCount"))
    for value in candidates:
        try:
            return int(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


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


def _brand_params(year: int, page: int = 1, size: int = 100) -> Dict[str, Any]:
    return {"pageNo": page, "numOfRows": size, "resultType": "json", "jngBizCrtraYr": year}


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


def _first_num(row: Dict[str, Any], *names: str) -> Optional[float]:
    """여러 이름 중 **처음으로 값이 있는** 숫자(0 도 유효한 값으로 본다)."""
    for name in names:
        if name in row and row[name] not in (None, ""):
            value = _num(row[name])
            if value is not None:
                return value
    return None


def normalize_brand_row(row: Dict[str, Any], year: Optional[int] = None,
                        data_state: str = "live") -> Dict[str, Any]:
    """API 행(또는 색인 행) → 화면·API 공통 필드.

    가맹점 수(`stores_year_end`)는 '전체' 합계 기준입니다. 색인이 미리 계산해 둔 값이면
    `stores_source=brand_direct_stores_index`, 실시간 호출이면 `brand_direct_stores` 입니다.
    """
    def amount(*names: str) -> Optional[int]:
        value = _num(_pick(row, *names))
        return int(value) if value is not None else None

    return {
        "data_state": data_state,
        "base_year": int(_num(_pick(row, "baseYear", "jngBizCrtraYr")) or (year or 0)) or None,
        "acntg_year": int(_num(_pick(row, "acntgYr")) or 0) or None,
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
        "direct_stores": amount("dmsCnt", "direct_stores"),
        "stores_area_count": amount("stores_area_count"),
        "stores_source": _pick(row, "stores_source"),
        "start_stores": amount("ystFrcsCnt", "start_stores"),
        "new_stores": amount("newFrcsCnt", "new_stores"),
        "terminated": amount("ctrtEndFrcsCnt", "ctrtTrmnCnt", "terminated"),
        "cancelled": amount("ctrtCncltnFrcsCnt", "ctrtCnncCnt", "cancelled"),
        "avg_sales_krw": amount("avrgSalesAmt", "avg_sales_krw"),
        "unit_area_sales_krw": amount("arUnitAvrgSalesAmt", "unit_area_sales_krw"),
        "franchise_fee_krw": amount("jnntAmt", "franchise_fee_krw"),
        "deposit_krw": amount("gtnAmt", "deposit_krw"),
        "education_fee_krw": amount("edcAmt", "education_fee_krw"),
        "interior_per_m2_krw": amount("intrrAmt", "interior_per_m2_krw"),
        "disclosure_no": _pick(row, "infoPblsRgsNo", "disclosure_no"),
        "disclosure_registered_on": _pick(row, "infoPblsRgsDe", "disclosure_registered_on"),
        "legal_violation_count": amount("lawVioltCnt", "legal_violation_count"),
        "closure_rate_pct": _num(_pick(row, "closure_rate_pct")),
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
    brands = [normalize_brand_row(row, data_state="sample") for row in found]
    for brand in brands:
        _apply_closure(brand)   # 샘플이어도 계산 근거가 있으면 같은 규칙으로 폐점률을 채운다.
    return brands


def closure_basis(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """연초·연말·신규·계약종료·계약해지로 **1년** 폐점률과 그 근거를 계산한다.

    연초 값(`ystFrcsCnt`)이 있으면 그대로 쓰고, 없으면 연초 = 연말 - 신규 + 종료 + 해지로
    되돌립니다. 세 해를 모르는 값을 '3년 폐점률'이라고 부르지 않습니다.
    """
    end = _first_num(row, "yndFrcsCnt", "frcsCnt", "stores_year_end")
    start = _first_num(row, "ystFrcsCnt", "start_stores")
    new = _first_num(row, "newFrcsCnt", "new_stores")
    term = _first_num(row, "ctrtEndFrcsCnt", "ctrtTrmnCnt", "terminated")
    cancel = _first_num(row, "ctrtCncltnFrcsCnt", "ctrtCnncCnt", "cancelled")
    if start is None:
        if None in (end, new, term, cancel):
            return None
        start = end - new + term + cancel
    if start is None or start <= 0 or term is None or cancel is None:
        return None
    basis: Dict[str, Any] = {
        "start_stores": int(start),
        "terminated": int(term),
        "cancelled": int(cancel),
        "rate_pct": round((term + cancel) / start * 100.0, 1),
    }
    if end is not None:
        basis["end_stores"] = int(end)
    if new is not None:
        basis["new_stores"] = int(new)
    return basis


def closure_rate_from_rows(row: Dict[str, Any]) -> Optional[float]:
    """1년 폐점률(%) — 근거가 모자라면 None(0을 돌려주지 않는다)."""
    basis = closure_basis(row)
    return basis["rate_pct"] if basis else None


def _closure_basis_ko(basis: Dict[str, Any], year: Optional[int]) -> str:
    head = f"{year}년 " if year else ""
    parts = [f"{head}연초 {basis['start_stores']:,}곳"]
    if "end_stores" in basis:
        parts.append(f"연말 {basis['end_stores']:,}곳")
    moves = []
    if "new_stores" in basis:
        moves.append(f"신규 {basis['new_stores']:,}")
    moves.append(f"계약종료 {basis['terminated']:,}")
    moves.append(f"계약해지 {basis['cancelled']:,}")
    return " → ".join(parts) + " · " + " · ".join(moves)


def field_status(brands: List[Dict[str, Any]], datasets: Optional[List[Dict[str, Any]]] = None,
                 *, data_source: str = "", key_present: bool = False,
                 data_state: str = "") -> Dict[str, Any]:
    """조회 결과의 **필드 계약** — 어떤 값이 실렸고, 비어 있는 필드는 왜 비었는지.

    툴 설명(`api.py` `lookup_brand_disclosure`)과 응답이 같은 말을 하게 만드는 장치입니다.
    `null` 을 '0'이나 '없음·문제없음'으로 읽지 않도록 사유·데이터셋·신청 주소를 함께 돌려줍니다.
    """
    if not brands:
        return {
            "scope_ko": "조회 결과가 없어 필드별 상태를 계산하지 않았습니다.",
            "returned": [],
            "null": [],
            "meaning_ko": NULL_MEANING_KO,
        }
    known: Dict[str, Dict[str, Any]] = {}
    for row in dataset_summary().get("datasets") or []:
        if row.get("key"):
            known[str(row["key"])] = dict(row)
    for row in datasets or []:
        key = row.get("key")
        if not key:
            continue
        merged = dict(known.get(str(key)) or {})
        merged.update({name: value for name, value in row.items() if value not in (None, "")})
        known[str(key)] = merged

    brand = brands[0]
    returned: List[str] = []
    missing: List[Dict[str, Any]] = []
    for field, label, dataset_key, note_ko in FIELD_SPECS:
        value = brand.get(field)
        if value not in (None, "", []):
            returned.append(field)
            continue
        item: Dict[str, Any] = {"field": field, "label_ko": label}
        if dataset_key:
            entry = known.get(dataset_key) or {}
            approval = str(entry.get("approval") or "unknown")
            item.update({
                "dataset": dataset_key,
                "dataset_id": entry.get("dataset_id") or DATASET_IDS.get(dataset_key, ""),
                "title_ko": entry.get("title_ko") or "",
                "approval": approval,
            })
            if approval == "not_registered":
                item["reason_ko"] = ("이 인증키로 그 데이터셋이 등록되어 있지 않아 값이 비었습니다"
                                     "(활용신청이 필요합니다).")
                if entry.get("apply_url"):
                    item["apply_url"] = entry["apply_url"]
            elif approval == "unverified":
                item["reason_ko"] = ("그 데이터셋의 오퍼레이션 주소를 아직 확인하지 못해 "
                                     "값이 비었습니다.")
            elif approval == "approved" and data_state == "sample":
                item["reason_ko"] = ("내장 샘플 응답이라 실제 값이 아닙니다"
                                     "(API 승인·인증키 설정 후 채워집니다).")
            elif approval == "approved" and not key_present and data_source == "index":
                item["reason_ko"] = ("서버에 인증키가 없어 실시간 재조회를 하지 않았습니다"
                                     "(색인에 있는 값만 표시).")
            elif approval == "approved":
                item["reason_ko"] = ("승인된 데이터셋이지만 이 브랜드·기준연도에 값이 없습니다"
                                     "(0이라는 뜻은 아닙니다).")
            else:
                item["reason_ko"] = "값을 주는 데이터셋의 승인 상태를 확인하지 못했습니다."
        else:
            item["reason_ko"] = note_ko or "가맹정보 API 데이터셋에 없는 항목입니다."
        missing.append(item)
    return {
        "scope_ko": ("가장 위 결과 1건 기준입니다." if len(brands) > 1
                     else "조회 결과 1건 기준입니다."),
        "brand_code": brand.get("brand_code"),
        "returned": returned,
        "null": missing,
        "meaning_ko": NULL_MEANING_KO,
    }


def lookup(brand_name: str = "", brand_code: str = "", year: Optional[int] = None,
           client: Optional[FtcClient] = None,
           env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """브랜드 1건(또는 검색어 일치 목록)의 정보공개서 요약.

    순서: ① 로컬 브랜드 색인 → ② 실시간 API 전체 페이지 → ③ 내장 샘플.
    `data_state`(live/sample)·`data_source`(index/api/sample)로 항상 근거를 밝힌다.
    0건·미발견이면 `zero_result=True` 와 고정 안내 문구를 붙인다(단정 금지).
    """
    result = _lookup_impl(brand_name, brand_code, year, client, env)
    status = str(result.get("status") or "")
    brands = result.get("brands") or []
    # 확정된 0건만 센다. 승인 전·키 없음·네트워크 실패·해석 실패·부분 수집은 '0건'이 아니다.
    zero = status == "not_found" or (status == "live" and not brands)
    result["zero_result"] = zero
    result["zero_result_notice_ko"] = ZERO_RESULT_NOTICE_KO
    result["field_status"] = field_status(
        brands, result.get("datasets") or [],
        data_source=str(result.get("data_source") or ""),
        key_present=bool(service_key(env)),
        data_state=str(result.get("data_state") or ""))
    result["null_meaning_ko"] = NULL_MEANING_KO
    return result


def _base_result(name: str, code: str, year: Optional[int]) -> Dict[str, Any]:
    summary = dataset_summary()
    entry = dataset_index().get("brand_list") or {}
    return {
        "query": {"brand_name": name or None, "brand_code": code or None, "year": year},
        "data_state": "sample",
        "data_source": "sample",
        "status": "no_key",
        "brands": [],
        "apply_urls": summary.get("apply_urls") or [],
        "datasets": [entry] if entry else [],
        "message_ko": STATUS_MESSAGES_KO["no_key"],
        "how_to_confirm_ko": HOW_TO_CONFIRM_KO,
        "sample_notice_ko": sample_brands().get("note_ko", ""),
        "source_ko": sample_brands().get("source_ko", ""),
        "disclosure_portal": "https://franchise.ftc.go.kr",
        "brand_index": brand_index.meta(),
        "checked_at": engine.now_iso(),
    }


def _index_usable(year: Optional[int]) -> bool:
    meta = brand_index.meta()
    if not meta.get("available"):
        return False
    if year is None:
        return True
    return int(year) in [int(item) for item in meta.get("years") or []]


def _lookup_impl(brand_name: str = "", brand_code: str = "", year: Optional[int] = None,
                 client: Optional[FtcClient] = None,
                 env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    index = dataset_index()
    name = str(brand_name or "").strip()
    code = str(brand_code or "").strip()
    # 테스트·임베딩에서 client 를 직접 주면 그 응답을 그대로 검증할 수 있게 색인 신뢰를 끈다.
    explicit_client = client is not None
    if client is None:
        key = service_key(env)
        client = FtcClient(key) if key else None
    entry = index.get("brand_list") or {}
    result = _base_result(name, code, year)

    if not name and not code:
        # 검색어 없이 부르면 화면 구조를 보여 줄 예시만 돌려준다(0건으로 세지 않는다).
        result["brands"] = sample_lookup()
        result["status"] = "sample"
        return result

    # ① 로컬 브랜드 색인 — 등록 브랜드를 이름만으로 즉시 찾는다.
    if _index_usable(year):
        rows = brand_index.search(name, code)
        if rows:
            enriched, extra_datasets, extra_apply = _enrich(client, rows, index, limit=1)
            brands = _normalize_all(enriched, year)
            meta = brand_index.meta()
            result.update({
                "status": "live",
                "data_state": "live",
                "data_source": "index",
                "code": CODE_OK,
                "brands": brands,
                "datasets": [entry] + extra_datasets,
                "apply_urls": sorted(set(extra_apply)),
                "message_ko": (f"{STATUS_MESSAGES_KO['index']} "
                               f"색인 {int(meta.get('count') or 0):,}건 · "
                               f"{meta.get('year')}년 기준"
                               + (f" · 색인 갱신 {str(meta.get('built_at'))[:10]}"
                                  if meta.get("built_at") else "")
                               + ". 가맹점 수·평균매출 같은 상세 수치는 해당 데이터셋이 "
                                 "승인된 경우에만 채워집니다."),
            })
            return result

    # ② 실시간 API — 색인에 없거나 다른 연도를 지정했을 때.
    #    색인이 최신(45일 이내)이면 이름 미매칭을 이미 확정으로 보고 전체 페이지 순회를 생략한다
    #    (등록 브랜드 1만 건대 × 연도별 순회는 30초가 걸린다). 관리번호 조회는 1회 호출이라 늘 시도한다.
    index_meta = brand_index.meta()
    trust_index = (bool(index_meta.get("fresh")) and bool(index_meta.get("available"))
                   and not explicit_client and year is None)
    if client is not None and entry.get("endpoint") and (code or not trust_index):
        attempt = _live_attempt(client, entry, name, code, year, index)
        if attempt["status"] == "live":
            result.update(attempt)
            result["data_source"] = "api"
            result.setdefault("brand_index", brand_index.meta())
            return result
        if attempt["status"] == "not_found":
            # API 가 끝까지 응답한 미발견은 '샘플'이 아니라 실데이터 기준의 결과다.
            result.update({"status": "not_found", "data_state": "live", "data_source": "api",
                           "message_ko": not_found_message(name or code)})
            result["datasets"] = attempt.get("datasets") or result["datasets"]
            return result
        result.update({"status": attempt["status"], "code": attempt.get("code"),
                       "message_ko": STATUS_MESSAGES_KO.get(attempt["status"],
                                                           STATUS_MESSAGES_KO["network_error"]),
                       "apply_urls": attempt.get("apply_urls") or result["apply_urls"],
                       "datasets": attempt.get("datasets") or result["datasets"]})
        result["brands"] = sample_lookup(name, code)
        result["data_state"] = "sample"
        result["data_source"] = "sample"
        return result

    # ③ 색인도 API 도 없을 때 — 내장 샘플로 구조만 보여 준다.
    brands = sample_lookup(name, code)
    if brands:
        result["brands"] = brands
        result["status"] = "sample"
        result["data_source"] = "sample"
        return result
    result["status"] = "not_found"
    if brand_index.meta().get("available"):
        result["data_state"] = "live"
        result["data_source"] = "index"
    else:
        result["data_source"] = "sample"
    result["message_ko"] = not_found_message(name or code)
    return result


def _normalize_all(rows: List[Dict[str, Any]], year: Optional[int]) -> List[Dict[str, Any]]:
    brands = [normalize_brand_row(row, year, "live") for row in rows]
    for brand in brands:
        _apply_closure(brand)
    return brands


def _apply_closure(brand: Dict[str, Any]) -> None:
    """폐점률이 비어 있으면 연초·연말·변동으로 계산해 근거 문장까지 붙인다."""
    if brand.get("closure_rate_pct") is not None:
        return
    basis = closure_basis(brand)
    if not basis:
        return
    year = brand.get("acntg_year") or brand.get("base_year")
    brand["closure_rate_pct"] = basis["rate_pct"]
    brand["start_stores"] = basis["start_stores"]
    brand["terminated"] = basis["terminated"]
    brand["cancelled"] = basis["cancelled"]
    if "new_stores" in basis and brand.get("new_stores") is None:
        brand["new_stores"] = basis["new_stores"]
    if "end_stores" in basis and brand.get("stores_year_end") is None:
        brand["stores_year_end"] = basis["end_stores"]
    brand["closure_rate_year"] = int(year) if year else None
    brand["closure_rate_basis_ko"] = _closure_basis_ko(basis, brand["closure_rate_year"])


def _scan_brand_rows(client: "FtcClient", endpoint: str, candidate_year: int,
                     code: str) -> Tuple[List[Dict[str, Any]], bool, str, str]:
    """한 연도의 브랜드 목록을 얻는다 → (rows, complete, code, shape).

    관리번호를 알면 1회 호출로 끝나고, 이름만 있으면 전체 페이지를 순회한다.
    """
    if code:
        response = client.call(endpoint, _brand_params_with_code(code, candidate_year))
        return (response["rows"], True, str(response["code"]),
                str(response.get("raw_shape") or "none"))
    rows, info = brand_index.fetch_rows(client, endpoint, candidate_year)
    return rows, bool(info.get("complete")), str(info.get("code") or ""), str(info.get("shape") or "")


def _live_attempt(client: FtcClient, entry: Dict[str, Any], name: str, code: str,
                  year: Optional[int], index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    datasets = [entry]
    apply_urls: List[str] = []
    last_code = ""
    last_shape = "none"
    complete_scan = False
    for candidate_year in _year_candidates(year):
        rows, complete, last_code, last_shape = _scan_brand_rows(
            client, entry["endpoint"], candidate_year, code)
        if last_code != CODE_OK:
            break
        if last_shape in ("unknown", "none"):
            return {"status": "unexpected_shape", "code": last_code, "datasets": datasets}
        complete_scan = complete_scan or complete
        matched = _match_rows(rows, name, code) if rows else []
        if not matched:
            if not complete:
                break
            continue
        enriched, extra_datasets, extra_apply = _enrich(client, matched, index)
        datasets.extend(extra_datasets)
        apply_urls.extend(extra_apply)
        return {
            "status": "live",
            "data_state": "live",
            "code": last_code,
            "brands": _normalize_all(enriched, candidate_year),
            "datasets": datasets,
            "apply_urls": sorted(set(apply_urls)),
            "message_ko": STATUS_MESSAGES_KO["live"],
        }
    if last_code == CODE_OK:
        if last_shape in ("unknown", "none"):
            return {"status": "unexpected_shape", "code": last_code, "datasets": datasets}
        if not complete_scan:
            # 끝까지 받지 못했으므로 '없다'고 단정하지 않는다.
            return {"status": "partial_scan", "code": last_code, "datasets": datasets}
        return {"status": "not_found", "code": last_code, "datasets": datasets}
    if last_code in (CODE_NOT_REGISTERED, CODE_NO_SERVICE):
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


# 본부 일반·가맹점 현황 응답 필드 → 브랜드 행 필드
HQ_FIELD_MAP = (
    ("hq_name", ("corpNm", "jnghdqrtrsNm", "jnghdqrtrsConmNm")),
    ("industry_large", ("indutyLclasNm",)),
    ("industry_mid", ("indutyMlsfcNm",)),
)
# 가맹점 변경현황(15125491) 은 연초·신규·종료·해지·연말 가맹점 수를 준다 → 폐점률 계산.
STORE_CHANGE_FIELD_MAP = (
    ("acntgYr", "acntgYr"),
    ("ystFrcsCnt", "ystFrcsCnt"),
    ("yndFrcsCnt", "frcsCnt"),
    ("newFrcsCnt", "newFrcsCnt"),
    ("ctrtEndFrcsCnt", "ctrtTrmnCnt"),
    ("ctrtCncltnFrcsCnt", "ctrtCnncCnt"),
)
STORE_STATS_FIELD_MAP = (
    ("frcsCnt", "frcsCnt"),
    ("avrgSalesAmt", "avrgSalesAmt"),
    ("ctrtTrmnCnt", "ctrtTrmnCnt"),
    ("ctrtCnncCnt", "ctrtCnncCnt"),
)


def _sum_area_rows(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """가맹점 및 직영점 데이터셋(15125490)의 지역 행 → 브랜드 합계.

    이 데이터셋은 시·도 행 17개와 **'전체' 합계 행 1개를 함께** 돌려줍니다. 모두 더하면
    가맹점 수가 두 배가 됩니다(2026-11-21 실측: `BBQ` 2,316개 → 잘못 4,632개).
    그래서 '전체' 행이 있으면 **그 값만** 쓰고, 없을 때만 지역 행을 합칩니다.
    """
    area_rows: List[Dict[str, Any]] = []
    total_rows: List[Dict[str, Any]] = []
    for row in rows:
        area = str(_pick(row, "areaNm") or "").strip()
        (total_rows if area == STORE_TOTAL_AREA else area_rows).append(row)
    source_rows = total_rows[:1] if total_rows else area_rows
    totals = {"frcsCnt": None, "dmsCnt": None, "areas": len(area_rows),
              "total_row": bool(total_rows)}
    for row in source_rows:
        value = _num(_pick(row, "frcsCnt"))
        if value is not None:
            totals["frcsCnt"] = (totals["frcsCnt"] or 0) + int(value)
        value = _num(_pick(row, "dmsCnt"))
        if value is not None:
            totals["dmsCnt"] = (totals["dmsCnt"] or 0) + int(value)
    return totals


def dataset_callable(entry: Dict[str, Any]) -> bool:
    """이 데이터셋을 실제로 호출해도 되는가 — 승인된 것만 부른다(미등록은 200% 코드 30)."""
    return bool(entry.get("endpoint")) and str(entry.get("approval") or "") == "approved"


def _enrich(client: Optional[FtcClient], matched: List[Dict[str, Any]],
            index: Dict[str, Dict[str, Any]], limit: int = 10, *,
            skip_hq: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """승인된 데이터셋으로 본부·가맹점 수·변동을 덧붙인다(실패는 무시, 앞 `limit` 건만).

    인증키가 없으면(client=None) 호출 없이 행을 그대로 돌려준다 — 색인만으로 즉시 답한다.
    색인이 이미 가맹점·직영점 합계를 갖고 있으면(`data/brands_index.json.gz`, 15125490) 그 값을
    그대로 쓰고 호출을 아낀다. 호출은 서로 독립이므로 스레드로 함께 보낸다.
    """
    datasets: List[Dict[str, Any]] = []
    apply_urls: List[str] = []
    if client is None:
        return list(matched), datasets, apply_urls
    hq_entry = index.get("hq_general") or {}
    store_entry = index.get("brand_stores") or {}
    change_entry = index.get("brand_store_change") or {}
    direct_entry = index.get("brand_direct_stores") or {}

    def _dataset_row(entry: Dict[str, Any]) -> Dict[str, Any]:
        return {key: entry.get(key) for key in
                ("key", "dataset_id", "title_ko", "approval", "apply_url")}

    # 승인되지 않은 데이터셋은 부르지 않는다(호출 낭비·지연). 대신 근거와 신청 주소를 남긴다.
    for entry in (hq_entry, store_entry, change_entry, direct_entry):
        if not entry.get("key") or dataset_callable(entry):
            continue
        if _dataset_row(entry) not in datasets:
            datasets.append(_dataset_row(entry))
        if entry.get("apply_url") and entry["apply_url"] not in apply_urls:
            apply_urls.append(entry["apply_url"])

    jobs: List[Dict[str, Any]] = []
    for position, row in enumerate(matched):
        if position >= max(0, int(limit)):
            continue
        year = _pick(row, "jngBizCrtraYr") or ""
        hq_code = _pick(row, "jnghdqrtrsMnno", "hq_code")
        brand_code = _pick(row, "brandMnno", "brand_code")
        has_hq_name = bool(_pick(row, "corpNm", "jnghdqrtrsNm", "hq_name"))
        if dataset_callable(hq_entry) and hq_code and not skip_hq and not has_hq_name:
            jobs.append({"position": position, "role": "hq", "entry": hq_entry, "row": row,
                         "params": {"pageNo": 1, "numOfRows": 5, "resultType": "json",
                                    "jngBizCrtraYr": year, "jnghdqrtrsMnno": hq_code}})
        if brand_code and dataset_callable(direct_entry):
            # 색인이 이미 가맹점·직영점 합계를 갖고 있으면 그 값을 쓰고 부르지 않는다.
            prefilled = (_first_num(row, "frcsCnt") is not None
                         and _first_num(row, "dmsCnt") is not None)
            if prefilled:
                if direct_entry.get("key") and _dataset_row(direct_entry) not in datasets:
                    datasets.append(_dataset_row(direct_entry))
            else:
                jobs.append({"position": position, "role": "direct", "entry": direct_entry,
                             "row": row,
                             "params": {"pageNo": 1, "numOfRows": 100, "resultType": "json",
                                        "jngBizCrtraYr": year, "brandMnno": brand_code}})
        if brand_code and dataset_callable(change_entry):
            jobs.append({"position": position, "role": "change", "entry": change_entry, "row": row,
                         "params": {"pageNo": 1, "numOfRows": 5, "resultType": "json",
                                    "jngBizCrtraYr": year, "brandMnno": brand_code}})
        if brand_code and dataset_callable(store_entry):
            jobs.append({"position": position, "role": "stats", "entry": store_entry, "row": row,
                         "params": {"pageNo": 1, "numOfRows": 5, "resultType": "json",
                                    "jngBizCrtraYr": year, "brandMnno": brand_code}})

    responses = _call_jobs(client, jobs)

    enriched = [dict(row) for row in matched]
    for job, response in zip(jobs, responses):
        entry = job["entry"]
        if entry.get("key") and _dataset_row(entry) not in datasets:
            datasets.append(_dataset_row(entry))
        merged = enriched[job["position"]]
        code = str(response.get("code") or "")
        rows = response.get("rows") or []
        if code == CODE_OK and rows:
            _apply_enrichment(job, merged, rows)
        elif code == CODE_NOT_REGISTERED and entry.get("apply_url"):
            if entry["apply_url"] not in apply_urls:
                apply_urls.append(entry["apply_url"])
    # 기준연도 자료가 아직 비어 있는 브랜드가 있다(예: 2026년 등록분). 그때만 직전 연도로 한 번 더.
    retry: List[Dict[str, Any]] = []
    for job in jobs:
        if job["role"] not in ("direct", "change"):
            continue
        merged = enriched[job["position"]]
        if job["role"] == "direct":
            missing = merged.get("frcsCnt") in (None, "") or merged.get("dmsCnt") in (None, "")
        else:
            missing = (merged.get("ctrtTrmnCnt") in (None, "")
                       or merged.get("frcsCnt") in (None, ""))
        previous = _previous_year(job["params"].get("jngBizCrtraYr"))
        if missing and previous:
            retry.append({**job, "params": {**job["params"], "jngBizCrtraYr": previous}})
    for job, response in zip(retry, _call_jobs(client, retry)):
        if str(response.get("code") or "") == CODE_OK and response.get("rows"):
            _apply_enrichment(job, enriched[job["position"]], response["rows"])
    return enriched, datasets, apply_urls


def _previous_year(value: Any) -> str:
    try:
        year = int(str(value))
    except (TypeError, ValueError):
        return ""
    return str(year - 1) if year > 1990 else ""


def _call_jobs(client: FtcClient, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """독립 호출을 함께 보낸다(결과 순서는 jobs 순서 그대로)."""
    if not jobs:
        return []
    if len(jobs) == 1:
        return [client.call(jobs[0]["entry"]["endpoint"], jobs[0]["params"])]
    try:
        from concurrent.futures import ThreadPoolExecutor
    except ImportError:  # pragma: no cover - 표준 라이브러리라 발생하지 않지만 방어
        return [client.call(job["entry"]["endpoint"], job["params"]) for job in jobs]
    with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
        futures = [pool.submit(client.call, job["entry"]["endpoint"], job["params"]) for job in jobs]
        return [future.result() for future in futures]


def _apply_enrichment(job: Dict[str, Any], merged: Dict[str, Any],
                      rows: List[Dict[str, Any]]) -> None:
    """응답 행을 브랜드 행에 합친다(이미 있는 값은 덮지 않는다)."""
    role = job["role"]
    detail = rows[0]
    if role == "hq":
        for target, names in HQ_FIELD_MAP:
            value = _pick(detail, *names)
            if value and not _pick(merged, *names):
                merged[names[0]] = value
        return
    if role == "direct":
        totals = _sum_area_rows(rows)
        if totals["frcsCnt"] is not None and merged.get("frcsCnt") in (None, ""):
            merged["frcsCnt"] = str(totals["frcsCnt"])
            merged["stores_source"] = "brand_direct_stores"
            merged["stores_area_count"] = totals["areas"]
        if totals["dmsCnt"] is not None and merged.get("dmsCnt") in (None, ""):
            merged["dmsCnt"] = str(totals["dmsCnt"])
        return
    mapping = STORE_CHANGE_FIELD_MAP if role == "change" else STORE_STATS_FIELD_MAP
    for source, target in mapping:
        value = _pick(detail, source)
        if value not in (None, "") and merged.get(target) in (None, ""):
            merged[target] = value


def health_block() -> Dict[str, Any]:
    """healthz·meta 에 넣는 실시간 어댑터 상태(키 값은 절대 넣지 않는다)."""
    summary = dataset_summary()
    key_present = bool(service_key())
    index_meta = brand_index.meta()
    return {
        "live_api": "configured" if key_present else "no_key",
        "data_state": data_state(),
        "approval": summary["counts"],
        "approved_datasets": [
            {"dataset_id": row.get("dataset_id"), "title_ko": row.get("title_ko")}
            for row in summary.get("datasets") or [] if row.get("approval") == "approved"
        ],
        "verification_file": summary.get("file"),
        "verified_at": summary.get("generated_at"),
        "apply_urls": summary.get("apply_urls") or [],
        "brand_index": {key: index_meta.get(key) for key in
                        ("available", "count", "year", "built_at", "file", "stores")},
    }
