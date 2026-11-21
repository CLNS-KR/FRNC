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

색인 파일에는 공개 API 가 준 식별 정보(브랜드명·관리번호·본부·업종·주요상품·개시일·사업자번호·
기준연도)만 넣습니다. 인증키·개인정보는 넣지 않습니다.
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
    for short, long in ROW_FIELDS:
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


def build(client: Any, endpoint: str, years: Iterable[int], *, page_size: int = PAGE_SIZE,
          max_pages: int = MAX_PAGES) -> Dict[str, Any]:
    """여러 연도를 훑어 색인 페이로드를 만든다(최신 연도 우선).

    `k` = 그 브랜드가 실린 연도 수 — 규모의 거친 대리 지표로 정렬에만 쓴다
    (가맹점 수가 아니라 '몇 년치 목록에 올라 있었는지'다). 정확한 가맹점 수는 조회 시
    승인된 가맹점 데이터셋으로 덧붙인다(`live_api._enrich`).
    """
    year_list = [int(year) for year in years]
    rows: List[Dict[str, Any]] = []
    report = []
    for year in year_list:
        fetched, info = fetch_rows(client, endpoint, year, page_size=page_size,
                                   max_pages=max_pages)
        report.append({"year": year, **info, "rows": len(fetched)})
        rows.extend(_compact(row) for row in fetched)
    presence: Dict[str, int] = {}
    for row in rows:
        key = str(row.get("c") or _norm(row.get("n")))
        presence[key] = presence.get(key, 0) + 1
    for row in rows:
        key = str(row.get("c") or _norm(row.get("n")))
        row["k"] = presence.get(key, 1)
    rows.sort(key=lambda row: (-(_int(row.get("y")) or 0), _norm(row.get("n")), row.get("c") or ""))
    primary = _int(rows[0]["y"]) if rows else (year_list[0] if year_list else None)
    return {
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
        "rows": rows,
    }


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
    """색인 상태 요약(파일이 없으면 available=False)."""
    payload = load(path)
    if payload is None:
        return {"available": False, "count": 0, "year": None, "built_at": None,
                "age_days": None, "fresh": False, "file": index_path(path).name}
    age = age_days(payload.get("built_at"))
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
