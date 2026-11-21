"""익명 일별 사용 카운터 + 문의 접수.

남기는 것: `날짜(KST) · 경로 · 툴 이름 · 판정 등급 · 0건/오류 여부`의 **횟수**만.
그리고 **결과가 0건으로 끝난 브랜드 조회어만** 예외적으로 비식별 처리해 남깁니다(`sanitize_query`).
남기지 않는 것: IP, User-Agent, 쿠키, Referer, 세션, 금액·조건 입력, 결과가 있던 조회어.
알 수 없는 경로는 `/404` 한 칸으로 뭉갭니다.

0건 조회어를 남기는 이유
------------------------
"조회가 0건"이라는 사실은 다음 데이터 확충의 유일한 신호입니다. 다만 브랜드명 칸에는
전화번호·이메일이 섞여 들어올 수 있으므로 **결과가 0건일 때만**, 다음을 지운 뒤 최대 30자로
남깁니다: 전화번호·주민등록번호·이메일·URL·@핸들·제어문자, 2자리 이상 숫자.
0건은 '그 브랜드가 없다'도 '문제없다·안전하다'도 아니며, 응답에는 그 고정 안내가 붙습니다
(`live_api.ZERO_RESULT_NOTICE_KO`).

문의 폼(다른 경로)
-------------------
`POST /v1/inquiry` 로 **이용자가 직접 적어 보낸 연락처**만 `inquiries` 표에 두고 회신
목적으로만 씁니다. 응답에 되비추지 않고, 이 통계에도 넣지 않습니다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from . import models

KST = timezone(timedelta(hours=9))
MAX_DAYS = 30
DEFAULT_DAYS = 7

KIND_PATH = "path"
KIND_TOOL = "tool"
KIND_VERDICT = "verdict"
KIND_FLAG = "flag"
KIND_ZERO_QUERY = "zero_query"

FLAG_ZERO = "zero_results"
FLAG_ERROR = "errors"
FLAG_SAMPLE = "sample_data"
FLAG_RATE_LIMIT = "rate_limited"

# 0건 조회어 — 남기는 형태를 여기서만 정한다.
MAX_QUERY_CHARS = 30      # 저장하는 조회어 최대 길이(브리프: 앞 30자)
TOP_ZERO_QUERIES = 20     # 날짜별로 노출하는 상위 개수(전체 개수는 total/distinct 로 따로)

FIXED_PATHS = (
    "/", "/guides/", "/guides", "/healthz", "/robots.txt", "/llms.txt", "/sitemap.xml",
    "/.well-known/mcp/server-card.json", "/v1/meta", "/v1/mcp", "/v1/stats",
    "/v1/tools", "/v1/inquiry", "/v1/inquiries", "/mcp", "/favicon.ico", "/404",
)

KEY_RE = re.compile(r"[^0-9A-Za-z._:/{}-]")
MAX_KEY = 64

_EMAIL_RE = re.compile(r"[0-9A-Za-z._%+\-]+@[0-9A-Za-z.\-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"(?i)(?:https?://|www\.)\S+")
_HANDLE_RE = re.compile(r"@[0-9A-Za-z._\-]+")
_RRN_RE = re.compile(r"\d{6}\s?-?\s?\d{7}")
_PHONE_RE = re.compile(r"0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}")
_DIGITS_RE = re.compile(r"\d{2,}")        # 2자리 이상 숫자는 전화·주민번호·나이 조각일 수 있다
_ALLOWED_RE = re.compile(r"[^0-9A-Za-z가-힣\s·+&-]")
_SPACE_RE = re.compile(r"\s+")
_HAS_HANGUL_RE = re.compile(r"[가-힣]")
_HAS_WORD_RE = re.compile(r"[A-Za-z]{2,}")

INQUIRY_TOPICS = ("franchise_review", "api_mcp", "other")
INQUIRY_TOPIC_LABELS = {
    "franchise_review": "브랜드·계약 조건 검토 요청",
    "api_mcp": "API·MCP 연동",
    "other": "그 밖의 문의",
}
INQUIRY_CONTACT_MIN = 3
INQUIRY_CONTACT_MAX = 120
INQUIRY_MESSAGE_MAX = 500
INQUIRY_DAILY_CAP = 200
INQUIRY_KEEP_DAYS = 180

_CONTACT_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MESSAGE_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")

INQUIRY_ERRORS_KO = {
    "contact_too_short": f"연락처를 {INQUIRY_CONTACT_MIN}자 이상 적어 주세요.",
    "contact_too_long": f"연락처는 {INQUIRY_CONTACT_MAX}자까지 쓸 수 있습니다.",
    "invalid_topic": "문의 유형을 다시 선택해 주세요.",
    "message_too_long": f"문의 내용은 {INQUIRY_MESSAGE_MAX}자까지 쓸 수 있습니다.",
    "daily_cap_reached": "오늘 접수 한도에 닿았습니다. 내일 다시 보내 주세요.",
    "store_unavailable": "지금은 문의를 저장할 수 없습니다. 잠시 뒤 다시 시도해 주세요.",
}


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _shift(day: str, days: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def safe_key(value: Any) -> str:
    return KEY_RE.sub("", str(value or ""))[:MAX_KEY]


def path_key(path: str) -> str:
    raw = str(path or "").split("?", 1)[0]
    if not raw.startswith("/"):
        return "/404"
    trimmed = raw.rstrip("/") or "/"
    if trimmed.startswith("/v1/tools/"):
        return "/v1/tools"
    for candidate in (raw, trimmed):
        if candidate in FIXED_PATHS or candidate in _guide_paths():
            return candidate
    return "/404"


def _guide_paths() -> frozenset:
    """가이드 슬러그 버킷 — 어떤 질문이 유입을 만드는지 센다(임의 문자열은 남기지 않음)."""
    try:
        from . import guides

        return frozenset(guides.paths())
    except Exception:  # noqa: BLE001 - 가이드가 없어도 카운터는 돌아야 한다
        return frozenset()


def sanitize_query(text: Any, limit: int = MAX_QUERY_CHARS) -> str:
    """0건 조회어 → 통계에 남겨도 되는 비식별 형태(최대 `limit`자).

    남는 것이 없으면 빈 문자열을 돌려주고, 호출자는 그때 기록하지 않습니다.
    """
    raw = str(text or "")[:400]
    raw = _URL_RE.sub(" ", raw)
    raw = _EMAIL_RE.sub(" ", raw)
    raw = _HANDLE_RE.sub(" ", raw)
    raw = _RRN_RE.sub(" ", raw)
    raw = _PHONE_RE.sub(" ", raw)
    raw = _ALLOWED_RE.sub(" ", raw)
    raw = _DIGITS_RE.sub("N", raw)
    raw = _SPACE_RE.sub(" ", raw).strip()
    # 숫자만 있던 토큰은 'N' 한 글자로 남는다 — 뜻이 없으니 버린다.
    raw = " ".join(token for token in raw.split() if token.strip("N"))
    if len(raw) > limit:
        raw = raw[:limit].strip()
    if not raw:
        return ""
    if not _HAS_HANGUL_RE.search(raw) and not _HAS_WORD_RE.search(raw):
        return ""
    return raw


def zero_query_key(query: str, reason: str = "not_found") -> str:
    return f"{query}|{reason}"


def _is_zero_result(name: str, result: Any) -> bool:
    """확정된 0건만 참. 승인 전·키 없음·네트워크 실패·해석 실패는 0건이 아니다."""
    data = result if isinstance(result, dict) else {}
    payload = data.get("result") if isinstance(data.get("result"), dict) else {}
    if name == "lookup_brand_disclosure":
        status = str(payload.get("status") or "")
        brands = payload.get("brands") or []
        return bool(payload.get("zero_result")) or status == "not_found" or \
            (status == "live" and not brands)
    return False


def record_zero_query(store: Any, args: Any, result: Any, day: Optional[str] = None) -> None:
    """0건으로 끝난 브랜드 조회어만 비식별 형태로 남긴다(금액·조건 입력은 보지도 않는다)."""
    if store is None or not isinstance(args, dict):
        return
    keyword = str(args.get("brand_name") or args.get("brand") or args.get("query") or "").strip()
    if not keyword:
        return
    query = sanitize_query(keyword)
    if not query:
        return
    data = result if isinstance(result, dict) else {}
    payload = data.get("result") if isinstance(data.get("result"), dict) else {}
    reason = "not_found" if str(payload.get("status") or "") == "not_found" else "empty"
    try:
        store.bump_usage(day or today_kst(), KIND_ZERO_QUERY, zero_query_key(query, reason))
    except Exception:  # noqa: BLE001 - 계측 실패가 응답을 막지 않는다
        pass


def record_request(store: Any, method: str, path: str, day: Optional[str] = None) -> None:
    if store is None or str(method or "").upper() not in ("GET", "POST"):
        return
    try:
        store.bump_usage(day or today_kst(), KIND_PATH, path_key(path))
    except Exception:  # noqa: BLE001 - 계측 실패가 응답을 막지 않는다
        pass


def record_rate_limited(store: Any, day: Optional[str] = None) -> None:
    """429 로 끊은 요청 수만 익명으로 센다(어떤 클라이언트인지는 남기지 않는다)."""
    if store is None:
        return
    try:
        store.bump_usage(day or today_kst(), KIND_FLAG, FLAG_RATE_LIMIT)
    except Exception:  # noqa: BLE001
        pass


def record_tool(store: Any, name: str, result: Any, args: Any = None,
                day: Optional[str] = None) -> None:
    if store is None:
        return
    stamp = day or today_kst()
    key = safe_key(name) or "unknown"
    try:
        store.bump_usage(stamp, KIND_TOOL, key)
        data = result if isinstance(result, dict) else {}
        payload = data.get("result") if isinstance(data.get("result"), dict) else {}
        verdict = payload.get("verdict") if isinstance(payload.get("verdict"), dict) else {}
        code = str(verdict.get("code") or "")
        if code in models.VERDICT_ORDER:
            store.bump_usage(stamp, KIND_VERDICT, code)
        if data.get("ok") is False:
            store.bump_usage(stamp, KIND_FLAG, FLAG_ERROR)
        elif _is_zero_result(key, data):
            store.bump_usage(stamp, KIND_FLAG, FLAG_ZERO)
            record_zero_query(store, args, data, stamp)
        elif data.get("tool") in ("lookup_brand_disclosure", "check_franchise_risk") and \
                str(payload.get("data_state") or payload.get("meta", {}).get("data_state")) == "sample":
            store.bump_usage(stamp, KIND_FLAG, FLAG_SAMPLE)
    except Exception:  # noqa: BLE001
        pass


def statistics(store: Any, days: int = DEFAULT_DAYS, today: Optional[str] = None) -> Dict[str, Any]:
    try:
        window = max(1, min(MAX_DAYS, int(days)))
    except (TypeError, ValueError):
        window = DEFAULT_DAYS
    end = today or today_kst()
    start = _shift(end, -(window - 1))
    empty = [{"date": _shift(start, offset), "requests": 0, "paths": {}, "tools": {},
              "verdicts": {}, "flags": {}, "zero_result_queries": []}
             for offset in range(window)]
    by_day = {row["date"]: row for row in empty}
    zero_by_day: Dict[str, Dict[str, int]] = {}
    zero_all: Dict[str, int] = {}
    if store is not None:
        try:
            rows = store.usage_rows(start, end)
        except Exception:  # noqa: BLE001
            rows = []
        for row in rows:
            target = by_day.get(str(row.get("day") or ""))
            if target is None:
                continue
            kind = str(row.get("kind") or "")
            count = int(row.get("count") or 0)
            if kind == KIND_ZERO_QUERY:
                # 조회어는 서버가 만든 형식(비식별 30자|사유)이라 safe_key 로 훼손하지 않는다.
                raw_key = str(row.get("key") or "")[:MAX_QUERY_CHARS + 12]
                day_bucket = zero_by_day.setdefault(target["date"], {})
                day_bucket[raw_key] = day_bucket.get(raw_key, 0) + count
                zero_all[raw_key] = zero_all.get(raw_key, 0) + count
                continue
            key = safe_key(row.get("key"))
            if kind == KIND_PATH:
                target["paths"][key] = count
                target["requests"] += count
            elif kind == KIND_TOOL:
                target["tools"][key] = count
            elif kind == KIND_VERDICT:
                target["verdicts"][key] = count
            elif kind == KIND_FLAG:
                target["flags"][key] = count

    for day, bucket in zero_by_day.items():
        by_day[day]["zero_result_queries"] = _top_zero_queries(bucket)

    totals: Dict[str, Any] = {"requests": 0, "paths": {}, "tools": {}, "verdicts": {}, "flags": {}}
    for row in empty:
        totals["requests"] += row["requests"]
        for kind in ("paths", "tools", "verdicts", "flags"):
            for key, value in row[kind].items():
                totals[kind][key] = totals[kind].get(key, 0) + value
    return {
        "ok": True,
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "timezone": "Asia/Seoul",
        "window_days": window,
        "from": start,
        "to": end,
        "privacy": {
            "stores_ip": False,
            "stores_user_agent": False,
            "stores_cookies": False,
            "stores_brand_names": "zero_result_only",
            "stores_search_terms": "zero_result_only",
            "stores_inputs": False,
            "zero_result_queries": {
                "what_ko": ("결과가 0건이었던 브랜드 조회어만, 개인식별 요소를 지운 뒤 "
                            "최대 30자로 남깁니다."),
                "removed_ko": ["전화번호", "주민등록번호", "이메일", "URL", "@핸들",
                               "2자리 이상 숫자", "제어문자"],
                "kept_ko": ["조회어(지운 뒤 남은 말)", "0건 사유"],
                "results_are_not_stored": True,
                "max_chars": MAX_QUERY_CHARS,
                "top_per_day": TOP_ZERO_QUERIES,
                "limit_ko": ("사람 이름·상호는 낱말만으로 판별할 수 없어 지우지 못합니다. "
                             "그래서 조회에는 브랜드명만 넣도록 안내합니다."),
            },
            "granularity": ("date (YYYY-MM-DD, Asia/Seoul) · 경로 · 툴 · 판정 등급 · 샘플/0건/오류 · "
                            "0건 조회어(비식별, 최대 30자)"),
            "note_ko": ("금액·조건 입력은 통계에도 저장하지 않습니다. 브랜드 조회어는 결과가 0건이었을 "
                        "때만 전화번호·이메일·숫자를 지운 형태로 남겨 다음 데이터 확충에 씁니다. "
                        "0건은 '문제없음·안전'이라는 뜻이 아닙니다. 알 수 없는 경로는 /404 한 칸으로 "
                        "합산하며, 요청 제한으로 끊은 요청은 flags.rate_limited 횟수로만 남깁니다. "
                        "재배포 시 카운터가 초기화될 수 있습니다."),
            "inquiries": {
                "separate_from_usage": True,
                "in_this_payload": False,
                "keep_days": INQUIRY_KEEP_DAYS,
            },
        },
        "days": empty,
        "zero_result_queries": _top_zero_queries(zero_all),
        "totals": totals,
    }


def _top_zero_queries(bucket: Dict[str, int]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key, count in bucket.items():
        query, _, reason = str(key).partition("|")
        rows.append({"query": query, "reason": reason or "not_found", "count": count})
    rows.sort(key=lambda row: (-int(row["count"]), str(row["query"])))
    return rows[:TOP_ZERO_QUERIES]


def clean_contact(value: Any) -> str:
    text = _CONTACT_CTRL_RE.sub(" ", str(value or "")[:400])
    return _SPACE_RE.sub(" ", text).strip()


def clean_message(value: Any) -> str:
    text = _MESSAGE_CTRL_RE.sub(" ", str(value or "")[:2000])
    return text.strip()


def normalize_inquiry(payload: Any) -> tuple:
    data = payload if isinstance(payload, dict) else {}
    contact = clean_contact(data.get("contact"))
    if len(contact) < INQUIRY_CONTACT_MIN:
        return {}, "contact_too_short"
    if len(contact) > INQUIRY_CONTACT_MAX:
        return {}, "contact_too_long"
    topic = str(data.get("topic") or "").strip()
    if topic not in INQUIRY_TOPICS:
        return {}, "invalid_topic"
    message = clean_message(data.get("message"))
    if len(message) > INQUIRY_MESSAGE_MAX:
        return {}, "message_too_long"
    return {"contact": contact, "topic": topic, "message": message}, None


def save_inquiry(store: Any, data: Dict[str, Any], day: Optional[str] = None) -> Dict[str, Any]:
    stamp = day or today_kst()
    if store is None:
        return {"stored": False, "duplicate": False, "error": "store_unavailable"}
    contact = str(data.get("contact") or "")
    topic = str(data.get("topic") or "")
    message = str(data.get("message") or "")
    try:
        if store.inquiry_exists(stamp, topic, contact, message):
            return {"stored": False, "duplicate": True}
        if store.inquiry_count(stamp) >= INQUIRY_DAILY_CAP:
            return {"stored": False, "duplicate": False, "error": "daily_cap_reached"}
        row_id = store.add_inquiry(stamp, topic, contact, message)
    except Exception:  # noqa: BLE001
        return {"stored": False, "duplicate": False, "error": "store_unavailable"}
    return {"stored": True, "duplicate": False, "receipt": f"F{int(row_id):05d}"}


def inquiry_summary(store: Any) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    try:
        counts = store.inquiry_topic_counts() if store is not None else {}
    except Exception:  # noqa: BLE001
        counts = {}
    return {
        "total": sum(counts.values()),
        "by_topic": [{"topic": topic, "label_ko": INQUIRY_TOPIC_LABELS[topic],
                      "count": int(counts.get(topic, 0))} for topic in INQUIRY_TOPICS],
        "stores_contact": True,
        "in_usage_stats": False,
        "keep_days": INQUIRY_KEEP_DAYS,
    }


def purge_inquiries(store: Any, keep_days: int = INQUIRY_KEEP_DAYS,
                    day: Optional[str] = None) -> int:
    if store is None:
        return 0
    try:
        return store.purge_inquiries(keep_days, day)
    except Exception:  # noqa: BLE001
        return 0


def dump_stats(store: Any) -> str:
    return json.dumps(statistics(store), ensure_ascii=False)
