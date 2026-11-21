"""브랜드 색인 — 공정위 가맹정보 `getBrandinfo` 를 **전체 페이지** 훑어 만든 로컬 색인.

왜 필요한가
-----------
`getBrandinfo`(데이터셋 15125467)는 **브랜드명 검색 파라미터가 없습니다**. `brandNm` 을 붙여도
무시되고 `pageNo`/`numOfRows` 로만 훑을 수 있습니다(2026-11-21 실측: 2026년 10,299건 ·
2025년 11,164건, `numOfRows=1000` 까지 허용). 그래서 예전 코드는 1페이지 100건만 뒤져
`BBQ`·`교촌` 같은 브랜드를 못 찾고 `not_found` 를 돌려줬습니다.

해결
----
1) 오프라인: 전체 페이지를 훑어 `data/brands_index.json.gz` 로 저장(빌드 스크립트
   `tools/sync_brands_index.py`, 주 1회 GitHub Actions 갱신).
2) 온라인: 색인에서 즉시 찾고, 색인에 없으면 실시간 API 를 전체 페이지로 재조회합니다.

색인 행에는 공개 API 가 준 식별 정보(브랜드명·관리번호·본부·업종·주요상품·개시일·사업자번호·
기준연도)만 넣습니다. 인증키·개인정보는 넣지 않습니다.

가맹점 수·직영점 수(15125490)
------------------------------
브랜드 목록만으로는 "이 브랜드가 몇 곳인지"를 알 수 없어, 색인을 만들 때 승인된
**가맹점 및 직영점 데이터셋(15125490)** 도 연도별로 전체 페이지 훑어 같이 저장합니다
(`--with-stores`). 그러면 인증키가 없어도 가맹점 수·직영점 수가 바로 나오고, 서버가
인증키를 가졌을 때도 조회마다 20만 행짜리 데이터셋을 다시 부르지 않습니다.

주의: 이 데이터셋은 시·도 행 17개와 **'전체' 합계 행**을 함께 줍니다. 모두 더하면 두 배가
되므로 '전체' 행이 있으면 그 값만 씁니다(2026-11-21 실측: `BBQ` 2,316개).

가맹점 변경현황(15125491)은 `jngBizCrtraYr`+`brandMnno` 를 반드시 요구해 전체 목록으로
받을 수 없습니다(코드 11). 그래서 연초·신규·계약종료·계약해지·폐점률은 색인에 넣지 않고
실시간 조회에서만 붙입니다.
"""
from __future__ import annotations

import gzip
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

KST = timezone(timedelta(hours=9))
PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_INDEX_PATH = PROJECT_DIR / "data" / "brands_index.json.gz"
INDEX_VERSION = 1
PAGE_SIZE = 1000
PAGE_SIZE_MAX = 1000
MAX_PAGES = 40          # 40,000건까지 — 현재 전체 1만 건대라 12페이지면 끝난다.
MAX_MATCHES = 10
# 색인 기본 연도: 올해·작년·재작년·3년 전. 짧게 끝난 브랜드도 이름으로 찾을 수 있게 넣는다.
DEFAULT_YEAR_SPAN = 4

# 색인 행에 남길 필드(공개 API 식별 정보만). 긴 키를 짧게 줄여 파일을 작게 유지한다.
ROW_FIELDS = (
    ("n", "brandNm"), ("c", "brandMnno"), ("h", "jnghdqrtrsMnno"), ("co", "corpNm"),
    ("il", "indutyLclasNm"), ("im", "indutyMlsfcNm"), ("p", "majrGdsNm"),
    ("s", "jngBizStrtDate"), ("b", "brno"), ("y", "jngBizCrtraYr"),
)

# 가맹점 및 직영점(15125490) 합계 — 색인에 같이 저장하는 숫자.
STORE_FIELDS = (
    ("fs", "frcsCnt"), ("ds", "dmsCnt"), ("ar", "stores_area_count"),
    ("sfs", "stores_source"),
)
STORE_TOTAL_AREA = "전체"
STORE_DATASET_ID = "15125490"
STORE_PAGE_SIZE = 1000
STORE_MAX_PAGES = 400      # 연간 18~20만 행(2026-11-21 실측) → 200페이지 선


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _pick(row: Dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def index_path(value: Optional[str] = None) -> Path:
    raw = (value or os.environ.get("FRNC_BRANDS_INDEX") or "").strip()
    return Path(raw) if raw else DEFAULT_INDEX_PATH


def _compact(row: Dict[str, Any]) -> Dict[str, Any]:
    return {short: _pick(row, long) for short, long in ROW_FIELDS}


def _expand(row: Dict[str, Any]) -> Dict[str, Any]:
    """색인 행(짧은 키) → API 필드명 행(`normalize_brand_row` 가 그대로 읽는다)."""
    out: Dict[str, Any] = {}
    for short, long in ROW_FIELDS + STORE_FIELDS:
        value = row.get(short)
        if value not in (None, ""):
            out[long] = value
    return out


# ---------------------------------------------------------------------------
# 실시간 전체 페이지 조회
# ---------------------------------------------------------------------------
def fetch_rows(client: Any, endpoint: str, year: int, *, page_size: int = PAGE_SIZE,
               max_pages: int = MAX_PAGES) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """`getBrandinfo` 전체 페이지를 순회한다.

    멈추는 조건: (1) 마지막 페이지(받은 행 < page_size), (2) totalCount 도달,
    (3) `max_pages` 상한. `complete=False` 면 '끝까지 봤다'고 말하지 않는다.
    한 페이지라도 코드 오류/형태 오류면 그 사실을 `code`·`shape` 로 돌려준다.
    """
    rows: List[Dict[str, Any]] = []
    info: Dict[str, Any] = {"pages": 0, "total": None, "complete": False, "code": "", "shape": ""}
    size = max(1, min(int(page_size or PAGE_SIZE), PAGE_SIZE_MAX))
    for page in range(1, max(1, int(max_pages)) + 1):
        response = client.call(endpoint, {
            "pageNo": page, "numOfRows": size, "resultType": "json", "jngBizCrtraYr": year,
        })
        info["pages"] = page
        info["code"] = str(response.get("code") or "")
        info["shape"] = str(response.get("raw_shape") or "")
        if info["code"] not in ("0", "00"):
            break
        if info["shape"] in ("unknown", "none"):
            break
        page_rows = [row for row in (response.get("rows") or []) if isinstance(row, dict)]
        rows.extend(page_rows)
        total = _int(response.get("total"))
        if total:
            info["total"] = total
        if len(page_rows) < size:
            info["complete"] = True
            break
        if total and len(rows) >= total:
            info["complete"] = True
            break
    return rows, info


def _int(value: Any) -> Optional[int]:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def store_totals(client: Any, endpoint: str, year: int, *,
                 page_size: int = STORE_PAGE_SIZE,
                 max_pages: int = STORE_MAX_PAGES,
                 workers: int = 1) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """`15125490` 전체 페이지 → `{브랜드관리번호: {frcsCnt, dmsCnt, areas, total_row}}`.

    지역 행과 '전체' 합계 행이 함께 오므로, '전체' 행이 있으면 그 값을 쓰고 없을 때만
    지역 행을 합칩니다(둘 다 더하면 두 배). 끝까지 못 받았으면 `complete=False`.
    `workers`>1 이면 페이지를 여러 개씩 동시에 받습니다(색인 빌드 시간 단축).
    """
    totals: Dict[str, Dict[str, Any]] = {}
    info: Dict[str, Any] = {"year": int(year), "pages": 0, "total": None,
                            "complete": False, "code": "", "shape": ""}
    size = max(1, min(int(page_size or STORE_PAGE_SIZE), PAGE_SIZE_MAX))
    workers = max(1, int(workers or 1))
    page = 1
    while page <= max(1, int(max_pages)):
        batch = [p for p in range(page, min(page + workers, max_pages + 1))]
        responses = _page_responses(client, endpoint, batch, size, year)
        stop = False
        for current, response in zip(batch, responses):
            info["pages"] = current
            info["code"] = str(response.get("code") or "")
            info["shape"] = str(response.get("raw_shape") or "")
            if info["code"] not in ("0", "00") or info["shape"] in ("unknown", "none"):
                stop = True
                break
            page_rows = [row for row in (response.get("rows") or []) if isinstance(row, dict)]
            _merge_store_rows(totals, page_rows)
            total = _int(response.get("total"))
            if total:
                info["total"] = total
            if len(page_rows) < size:
                info["complete"] = True
                stop = True
                break
            if total and current * size >= total:
                info["complete"] = True
                stop = True
                break
        if stop:
            break
        page += len(batch)
    info["brands"] = len(totals)
    return totals, info


def _page_responses(client: Any, endpoint: str, pages: List[int], size: int,
                    year: int) -> List[Dict[str, Any]]:
    """페이지 여러 장을 (가능하면) 동시에 받는다 — 결과 순서는 `pages` 그대로."""
    params = [{"pageNo": page, "numOfRows": size, "resultType": "json",
               "jngBizCrtraYr": year} for page in pages]
    if len(params) <= 1:
        return [client.call(endpoint, params[0])] if params else []
    try:
        from concurrent.futures import ThreadPoolExecutor
    except ImportError:  # pragma: no cover - 표준 라이브러리 방어
        return [client.call(endpoint, item) for item in params]
    with ThreadPoolExecutor(max_workers=len(params)) as pool:
        futures = [pool.submit(client.call, endpoint, item) for item in params]
        return [future.result() for future in futures]


def _merge_store_rows(totals: Dict[str, Dict[str, Any]], page_rows: List[Dict[str, Any]]) -> None:
    for row in page_rows:
        code = str(row.get("brandMnno") or "").strip()
        if not code:
            continue
        bucket = totals.setdefault(code, {"frcsCnt": None, "dmsCnt": None,
                                          "areas": 0, "total_row": False})
        area = str(row.get("areaNm") or "").strip()
        frcs = _int(row.get("frcsCnt"))
        dms = _int(row.get("dmsCnt"))
        if area == STORE_TOTAL_AREA:
            bucket["total_row"] = True
            if frcs is not None:
                bucket["frcsCnt"] = frcs
            if dms is not None:
                bucket["dmsCnt"] = dms
            continue
        bucket["areas"] += 1
        if bucket["total_row"]:
            continue          # 합계 행이 이미 있으면 지역 행은 더하지 않는다.
        if frcs is not None:
            bucket["frcsCnt"] = (bucket["frcsCnt"] or 0) + frcs
        if dms is not None:
            bucket["dmsCnt"] = (bucket["dmsCnt"] or 0) + dms


def build(client: Any, endpoint: str, years: Iterable[int], *, page_size: int = PAGE_SIZE,
          max_pages: int = MAX_PAGES, with_stores: bool = False,
          store_endpoint: str = "", store_page_size: int = STORE_PAGE_SIZE,
          store_max_pages: int = STORE_MAX_PAGES, store_workers: int = 1) -> Dict[str, Any]:
    """여러 연도를 훑어 색인 페이로드를 만든다(최신 연도 우선).

    `with_stores=True` 이고 `store_endpoint` 가 있으면 승인된 가맹점 및 직영점(15125490)도
    연도별로 훑어 각 행에 가맹점 수·직영점 수를 붙입니다(인증키 없이도 값이 나온다).

    `k` = 그 브랜드가 실린 연도 수 — 규모의 거친 대리 지표로 정렬에만 쓴다
    (가맹점 수가 아니라 '몇 년치 목록에 올라 있었는지'다).
    """
    year_list = [int(year) for year in years]
    rows: List[Dict[str, Any]] = []
    report = []
    for year in year_list:
        fetched, info = fetch_rows(client, endpoint, year, page_size=page_size,
                                   max_pages=max_pages)
        report.append({"year": year, **info, "rows": len(fetched)})
        rows.extend(_compact(row) for row in fetched)
    store_report: List[Dict[str, Any]] = []
    with_stores_count = 0
    if with_stores and store_endpoint:
        for year in year_list:
            totals, info = store_totals(client, store_endpoint, year, page_size=store_page_size,
                                        max_pages=store_max_pages, workers=store_workers)
            store_report.append(info)
            filled = 0
            for row in rows:
                if str(row.get("y")) != str(year):
                    continue
                value = totals.get(str(row.get("c") or ""))
                if not value or value.get("frcsCnt") is None:
                    continue
                row["fs"] = value["frcsCnt"]
                row["ds"] = value["dmsCnt"]
                row["ar"] = value["areas"]
                row["sfs"] = "brand_direct_stores_index"
                filled += 1
            with_stores_count += filled
            info["filled_rows"] = filled
    presence: Dict[str, int] = {}
    for row in rows:
        key = str(row.get("c") or _norm(row.get("n")))
        presence[key] = presence.get(key, 0) + 1
    for row in rows:
        key = str(row.get("c") or _norm(row.get("n")))
        row["k"] = presence.get(key, 1)
    rows.sort(key=lambda row: (-(_int(row.get("y")) or 0), _norm(row.get("n")), row.get("c") or ""))
    primary = _int(rows[0]["y"]) if rows else (year_list[0] if year_list else None)
    payload = {
        "version": INDEX_VERSION,
        "built_at": datetime.now(KST).isoformat(timespec="seconds"),
        "source": "공정거래위원회 가맹정보 오픈API · FftcBrandRlsInfo2_Service/getBrandinfo",
        "dataset_id": "15125467",
        "endpoint": endpoint,
        "page_size": page_size,
        "years": year_list,
        "primary_year": primary,
        "count": len(rows),
        "fetches": report,
        "stores": ({
            "dataset_id": STORE_DATASET_ID,
            "endpoint": store_endpoint,
            "fetches": store_report,
            "rows_with_stores": with_stores_count,
        } if with_stores and store_endpoint else {}),
        "rows": rows,
    }
    return payload


def save(payload: Dict[str, Any], path: Optional[str] = None) -> Path:
    target = index_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = target.with_suffix(target.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=9) as handle:
        handle.write(raw)
    tmp.replace(target)
    return target


_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def load(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """색인 파일을 읽는다(없거나 깨졌으면 None — 예외를 올리지 않는다)."""
    target = index_path(path)
    try:
        stat = target.stat()
    except OSError:
        return None
    key = str(target)
    cached = _CACHE.get(key)
    if cached and cached[0] == stat.st_mtime and cached[1].get("_size") == stat.st_size:
        return cached[1]
    try:
        with gzip.open(target, "rb") as handle:
            payload = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError, EOFError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        return None
    payload["_path"] = target.name
    payload["_size"] = stat.st_size
    _CACHE[key] = (stat.st_mtime, payload)
    return payload


def clear_cache() -> None:
    _CACHE.clear()


FRESH_DAYS = 45


def age_days(built_at: Any) -> Optional[int]:
    """색인이 며칠 전 것인지(파싱 실패면 None)."""
    text = str(built_at or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=KST)
    return max(0, int((datetime.now(KST) - stamp).total_seconds() // 86400))


def meta(path: Optional[str] = None) -> Dict[str, Any]:
    """색인 상태 요약(파일이 없으면 available=False).

    `stores` 는 색인에 함께 저장된 가맹점 및 직영점(15125490) 합계의 적용 범위다.
    """
    payload = load(path)
    if payload is None:
        return {"available": False, "count": 0, "year": None, "built_at": None,
                "age_days": None, "fresh": False, "file": index_path(path).name,
                "stores": {"available": False, "rows_with_stores": 0}}
    age = age_days(payload.get("built_at"))
    stores = payload.get("stores") or {}
    rows_with_stores = int(stores.get("rows_with_stores") or 0)
    return {
        "available": True,
        "count": int(payload.get("count") or 0),
        "year": payload.get("primary_year"),
        "years": payload.get("years") or [],
        "built_at": payload.get("built_at"),
        "age_days": age,
        "fresh": age is not None and age <= FRESH_DAYS,
        "file": payload.get("_path"),
        "dataset_id": payload.get("dataset_id"),
        "source": payload.get("source"),
        "stores": {
            "available": rows_with_stores > 0,
            "dataset_id": stores.get("dataset_id") or STORE_DATASET_ID,
            "rows_with_stores": rows_with_stores,
        },
    }


def _rank(norm_name: str, query: str) -> int:
    """0 정확히 같음 · 1 앞에서 시작 · 2 괄호·중간에 통째로 · 3 뒤에 붙음 · 4 글자 순서만 맞음."""
    if norm_name == query:
        return 0
    if norm_name.startswith(query):
        return 1
    if f"({query})" in norm_name or f"[{query}]" in norm_name:
        return 2
    if query in norm_name:
        return 3 if norm_name.endswith(query) else 2
    if len(query) >= 2 and _is_subsequence(query, norm_name):
        return 4
    return -1


def _is_subsequence(query: str, text: str) -> bool:
    """'메가커피' 처럼 띄어 쓴 기대 표기와 실제 등록명('메가엠지씨커피')이 다를 때를 잡는다."""
    index = 0
    for char in query:
        index = text.find(char, index)
        if index < 0:
            return False
        index += 1
    return True


def search(query: str = "", code: str = "", path: Optional[str] = None,
           limit: int = MAX_MATCHES) -> List[Dict[str, Any]]:
    """색인에서 이름(부분 일치)·관리번호로 찾는다. 최신 연도 행을 먼저 돌려준다.

    정렬: 일치도 → 여러 해 실린 브랜드(`k`) → 최신 연도 → 짧은 이름.
    """
    payload = load(path)
    if payload is None:
        return []
    target_name = _norm(query)
    target_code = _norm(code)
    if not target_name and not target_code:
        return []
    scored: List[Tuple[Tuple[int, int, int, int, str], Dict[str, Any]]] = []
    seen = set()
    fallback: List[Tuple[Tuple[int, int, int, int, str], Dict[str, Any]]] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        row_name = _norm(row.get("n"))
        row_code = _norm(row.get("c"))
        key = row_code or row_name
        if target_code and row_code == target_code:
            if key in seen:
                continue
            seen.add(key)
            scored.append(((0, 0, 0, 0, row_name), row))
            continue
        if not target_name:
            continue
        rank = _rank(row_name, target_name)
        if rank < 0 or key in seen:
            continue
        seen.add(key)
        year = _int(row.get("y")) or 0
        presence = _int(row.get("k")) or 1
        item = ((rank, -presence, -year, len(row_name), row_name), row)
        # 글자 순서만 맞는 후보(rank 4)는 **부분 일치가 하나도 없을 때만** 쓴다.
        # ('메가커피' → '메가엠지씨커피'는 살리고, 'BHC' → 'BS Chicken' 같은 소음은 막는다.)
        (scored if rank < 4 else fallback).append(item)
    if not scored:
        scored = fallback
    scored.sort(key=lambda item: item[0])
    return [_expand(row) for _score, row in scored[:max(1, int(limit))]]


def contains(name: str, path: Optional[str] = None) -> bool:
    return bool(search(name, path=path, limit=1))
