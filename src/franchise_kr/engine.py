"""가맹 조건 → 위험 신호 판정 엔진(결정론, 표준 라이브러리만).

설계 원칙
---------
1. **추측하지 않는다**: 입력하지 않은 항목은 '모름'으로 두고, 그 항목에 해당하는 질문을
   돌려준다. 모름을 '괜찮다'로 바꾸지 않는다.
2. **확정하지 않는다**: 결과는 `check_likely` / `info_needed` / `low_risk` 세 가지뿐이고,
   모든 응답에 면책과 근거 조문이 붙는다.
3. **근거를 붙인다**: 위험 신호마다 법제처 OPEN API 로 받은 가맹사업법·시행령 조문을
   `law-verification.json` 에서 찾아 인용한다. 조문 키가 없으면 판정을 만들지 않는다(테스트로 강제).

함정 코퍼스는 `traps.json`(17건)에 있고, 각 케이스의 판정 함수는 이 파일 아래
`EVALUATORS` 에 1:1로 대응한다.

계약서·특약 문구 스캔(`scan_contract_text`)도 같은 원칙을 따른다. 규칙(`CONTRACT_RULES`)은
같은 문구에 항상 같은 결과를 주고, 인용은 사용자가 넣은 글자 그대로이며, 잡히는 문구가
0건이어도 '안전·문제없음'을 쓰지 않는다(`SCAN_NOT_A_CLEARANCE_KO` 고정 문장).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import models
from .version import DISCLOSURE_PORTAL, GRANT_URL

KST = timezone(timedelta(hours=9))
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parents[1]
TRAPS_PATH = PACKAGE_DIR / "traps.json"
LAW_PATH = PROJECT_DIR / "law-verification.json"

# ---------------------------------------------------------------------------
# 입력 별칭 — 한글 키·줄임말을 모두 받는다(에이전트가 그대로 넘겨도 동작하게)
# ---------------------------------------------------------------------------
FIELD_ALIASES: Dict[str, str] = {
    "brand_name": "brand_name", "brand": "brand_name", "brand_nm": "brand_name",
    "브랜드": "brand_name", "브랜드명": "brand_name", "name": "brand_name",
    "brand_code": "brand_code", "브랜드관리번호": "brand_code", "brand_mnno": "brand_code",
    "industry": "industry", "업종": "industry", "업종명": "industry",
    "franchise_fee": "franchise_fee_krw", "franchise_fee_krw": "franchise_fee_krw",
    "가맹비": "franchise_fee_krw", "franchise_fee_amount": "franchise_fee_krw",
    "education_fee": "education_fee_krw", "가맹교육비": "education_fee_krw",
    "교육비": "education_fee_krw", "education_fee_krw": "education_fee_krw",
    "deposit": "deposit_krw", "보증금": "deposit_krw", "가맹보증금": "deposit_krw",
    "deposit_krw": "deposit_krw",
    "interior": "interior_krw", "interior_cost": "interior_krw",
    "인테리어": "interior_krw", "인테리어비용": "interior_krw", "interior_krw": "interior_krw",
    "equipment": "equipment_krw", "설비": "equipment_krw", "집기": "equipment_krw",
    "설비비": "equipment_krw", "equipment_krw": "equipment_krw",
    "other": "other_krw", "기타비용": "other_krw", "other_krw": "other_krw",
    "total_investment": "total_investment_krw", "총투자": "total_investment_krw",
    "총투자금": "total_investment_krw", "창업비용": "total_investment_krw",
    "total_investment_krw": "total_investment_krw",
    "royalty": "royalty_rate_pct", "royalty_rate": "royalty_rate_pct",
    "로열티": "royalty_rate_pct", "royalty_rate_pct": "royalty_rate_pct",
    "disclosure_days_before": "disclosure_days_before",
    "days_before_contract": "disclosure_days_before",
    "disclosure_days": "disclosure_days_before",
    "정보공개서경과일": "disclosure_days_before", "정보공개서_경과일": "disclosure_days_before",
    "contract_doc_days_before": "contract_doc_days_before",
    "계약서경과일": "contract_doc_days_before", "계약서_경과일": "contract_doc_days_before",
    "advisor_reviewed": "advisor_reviewed", "자문": "advisor_reviewed",
    "payment_route": "payment_route", "결제방식": "payment_route", "가맹금납부": "payment_route",
    "escrow": "payment_route", "예치": "payment_route",
    "revenue_claim": "revenue_claim_ko", "revenue_claim_ko": "revenue_claim_ko",
    "매출약속": "revenue_claim_ko", "예상매출": "revenue_claim_ko",
    "revenue_written": "revenue_written", "매출서면": "revenue_written",
    "revenue_estimate_doc": "revenue_estimate_doc", "예상매출액산정서": "revenue_estimate_doc",
    "interior_designated": "interior_designated", "인테리어지정": "interior_designated",
    "supplier_designated": "supplier_designated", "거래처지정": "supplier_designated",
    "mandatory_purchase": "mandatory_purchase", "필수품목": "mandatory_purchase",
    "sales_target": "sales_target", "판매목표": "sales_target",
    "price_fixing": "price_fixing", "가격구속": "price_fixing",
    "essential_price_hidden": "essential_price_hidden",
    "필수품목단가미공개": "essential_price_hidden", "필수품목가격미공개": "essential_price_hidden",
    "essential_items_broad": "essential_items_broad", "필수품목과다": "essential_items_broad",
    "필수품목범위과다": "essential_items_broad", "일반공산품필수품목": "essential_items_broad",
    "margin_raise_unilateral": "margin_raise_unilateral",
    "차액가맹금일방인상": "margin_raise_unilateral", "차액가맹금인상": "margin_raise_unilateral",
    "resale_price_bound": "resale_price_bound", "재판매가격유지": "resale_price_bound",
    "판매가격구속": "resale_price_bound", "가격유지강요": "resale_price_bound",
    "discount_forbidden": "discount_forbidden", "할인금지": "discount_forbidden",
    "ad_cost_burden": "ad_cost_burden", "광고비부담": "ad_cost_burden",
    "territory": "territory", "영업지역": "territory",
    "renewal_years": "renewal_years", "갱신년수": "renewal_years",
    "renewal_refused": "renewal_refused", "갱신거절": "renewal_refused",
    "termination_grace_months": "termination_grace_months",
    "해지유예기간": "termination_grace_months",
    "penalty_ratio_pct": "penalty_ratio_pct", "위약금비율": "penalty_ratio_pct",
    "penalty_krw": "penalty_krw", "위약금": "penalty_krw",
    "closure_rate_3y_pct": "closure_rate_3y_pct", "폐점률": "closure_rate_3y_pct",
    "closure_rate": "closure_rate_3y_pct",
    "legal_violation": "legal_violation", "법위반": "legal_violation",
    "disclosure_registered": "disclosure_registered", "정보공개서등록": "disclosure_registered",
    "stores_count": "stores_count", "가맹점수": "stores_count",
    "avg_sales_krw": "avg_sales_krw", "평균매출": "avg_sales_krw",
}

MONEY_FIELDS = (
    "franchise_fee_krw", "education_fee_krw", "deposit_krw", "interior_krw",
    "equipment_krw", "other_krw", "total_investment_krw", "penalty_krw", "avg_sales_krw",
)
NUMBER_FIELDS = (
    "royalty_rate_pct", "disclosure_days_before", "contract_doc_days_before",
    "renewal_years", "termination_grace_months", "penalty_ratio_pct",
    "closure_rate_3y_pct", "stores_count",
)
BOOL_FIELDS = (
    "advisor_reviewed", "revenue_written", "revenue_estimate_doc", "supplier_designated",
    "mandatory_purchase", "sales_target", "price_fixing", "renewal_refused",
    "legal_violation", "disclosure_registered",
    "essential_price_hidden", "essential_items_broad", "margin_raise_unilateral",
    "resale_price_bound", "discount_forbidden",
)
ENUM_FIELDS = {
    "payment_route": ("escrow", "insurance", "hq_account", "none", "unknown"),
    "interior_designated": ("free", "partial", "forced", "unknown"),
    "territory": ("exclusive", "defined", "none", "unknown"),
    "ad_cost_burden": ("shared", "franchisee_forced", "none", "unknown"),
}

# 입력이 있어야 '안다'고 볼 축 — low_risk 는 이 축들이 모두 채워졌을 때만 나온다.
KEY_AXES = (
    "disclosure_days_before", "payment_route", "revenue", "interior_designated",
    "territory", "closure_rate_3y_pct", "legal_violation", "termination_grace_months",
)

# 위험 신호가 하나도 확인되지 않았을 때 함께 보여 줄 '핵심 8축'의 근거 조문.
CORE_LAW_REFS = (
    "가맹사업법:제7조", "가맹사업법:제6조의5", "가맹사업법:제9조", "가맹사업법:제11조",
    "가맹사업법:제12조의4", "가맹사업법:제14조",
)

# 함정 1건 → (판정 함수, 채우는 축, 법 조문 키)
# 법 조문 키는 traps.json 의 law_refs 와 같아야 하고, law-verification.json 에 실제로 있어야 한다(테스트).

TRUE_WORDS = {"true", "y", "yes", "1", "예", "네", "맞음", "있음", "o", "ㅇ"}
FALSE_WORDS = {"false", "n", "no", "0", "아니오", "아니요", "없음", "아님", "x"}
UNKNOWN_WORDS = {"", "unknown", "모름", "미정", "확인안함", "확인 안 함", "?"}

PAYMENT_LABELS_KO = {
    "escrow": "예치기관에 예치",
    "insurance": "피해보상보험계약",
    "hq_account": "본사 계좌로 직접 송금",
    "none": "예치·보험 없음",
    "unknown": "모름",
}
INTERIOR_LABELS_KO = {
    "free": "자유 선택",
    "partial": "일부 품목만 지정",
    "forced": "본사 지정 100% 강제",
    "unknown": "모름",
}
TERRITORY_LABELS_KO = {
    "exclusive": "독점 영업지역 기재",
    "defined": "영업지역만 기재(독점 아님)",
    "none": "영업지역 없음",
    "unknown": "모름",
}
AD_LABELS_KO = {
    "shared": "본사·점주 분담",
    "franchisee_forced": "점주 의무 부담",
    "none": "없음",
    "unknown": "모름",
}


# ---------------------------------------------------------------------------
# 로드
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_traps() -> Dict[str, Any]:
    with open(TRAPS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_law() -> Dict[str, Any]:
    try:
        with open(LAW_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"laws": [], "articles": {}, "annexes": {}}


def trap_cases() -> List[Dict[str, Any]]:
    return list(load_traps().get("cases") or [])


def trap_index() -> Dict[str, Dict[str, Any]]:
    return {case["id"]: case for case in trap_cases()}


def law_record(key: str) -> Optional[Dict[str, Any]]:
    data = load_law()
    record = (data.get("articles") or {}).get(key)
    if record is None:
        record = (data.get("annexes") or {}).get(key)
    return record


def law_full_text(record: Optional[Dict[str, Any]]) -> str:
    """조문 레코드 → 조문내용 + 항·호·목을 이어 붙인 전문."""
    if not record:
        return ""
    parts: List[str] = []
    head = str(record.get("text") or "").strip()
    if head:
        parts.append(head)
    for paragraph in record.get("paragraphs") or []:
        text = str(paragraph.get("text") or "").strip()
        if text and text not in head:
            parts.append(text)
        for item in paragraph.get("items") or []:
            item_text = str(item.get("text") or "").strip()
            if item_text:
                parts.append(item_text)
            for sub in item.get("subitems") or []:
                sub_text = str(sub.get("text") or "").strip()
                if sub_text:
                    parts.append(sub_text)
    return "\n".join(parts)


def law_excerpt(key: str, limit: int = 420, anchor: str = "") -> str:
    """조문 발췌 — `anchor` 가 있으면 그 문구가 보이도록 창을 옮긴다(별표 2 처럼 긴 문서)."""
    record = law_record(key)
    if not record:
        return ""
    text = re.sub(r"\s+", " ", law_full_text(record)).strip()
    if len(text) <= limit:
        return text
    if anchor:
        position = text.find(anchor)
        if position > 0:
            start = max(0, position - 80)
            window = text[start:start + limit]
            prefix = "…" if start > 0 else ""
            suffix = "…" if start + limit < len(text) else ""
            return prefix + window.strip() + suffix
    return text[:limit].rstrip() + "…"


def law_label(key: str) -> str:
    """조문 키 → 사람이 읽는 라벨('가맹사업법:제12조 · 불공정거래행위의 금지')."""
    record = law_record(key)
    if not record:
        return key
    title = str(record.get("title") or "")
    # 별표는 키 안에 제목이 이미 들어 있어 두 번 쓰지 않는다.
    return key if (not title or title in key) else f"{key} · {title}"


def law_basis(keys: List[str], anchors: Optional[Dict[str, str]] = None,
              limit: int = 420) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    anchors = anchors or {}
    laws = {str(row.get("short") or ""): row for row in load_law().get("laws") or []}
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        record = law_record(key)
        if not record:
            continue
        law_row = laws.get(str(record.get("law") or "")) or {}
        title = str(record.get("title") or "")
        label = law_label(key)
        out.append({
            "key": key,
            "label_ko": label,
            "law": record.get("law"),
            "article": record.get("article") or record.get("title"),
            "title": record.get("title"),
            # 별표에는 시행일이 따로 없어 그 법령의 시행일을 쓴다(빈 문자열 노출 방지).
            "effective_on": record.get("effective_on") or law_row.get("effective_on"),
            "excerpt_ko": law_excerpt(key, limit=limit, anchor=anchors.get(key, "")),
            "source_url": record.get("source_url"),
        })
    return out


# ---------------------------------------------------------------------------
# 입력 정규화
# ---------------------------------------------------------------------------
def _clean_key(key: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(key or "").strip()).lower()


def parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    return None


_MONEY_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(억|천만|백만|만|원)?")
_UNIT = {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000, "원": 1}


def parse_money(value: Any) -> Optional[int]:
    """'3억', '5,000만원', '1억 2,300만' → 원 단위 정수."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text or text.lower() in UNKNOWN_WORDS:
        return None
    if text.isdigit():
        return int(text)
    total = 0.0
    matched = False
    for number, unit in _MONEY_RE.findall(text):
        total += float(number) * _UNIT.get(unit or "원", 1)
        matched = True
    if not matched:
        return None
    return int(round(total))


def parse_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in UNKNOWN_WORDS:
        return None
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", text)
    return float(match.group()) if match else None


def parse_enum(field: str, value: Any) -> Optional[str]:
    options = ENUM_FIELDS[field]
    if value is None:
        return None
    text = str(value).strip().lower()
    korean = {
        "예치": "escrow", "예치기관": "escrow", "보험": "insurance",
        "피해보상보험": "insurance", "본사계좌": "hq_account", "본사": "hq_account",
        "직접송금": "hq_account", "없음": "none", "없다": "none",
        "모름": "unknown", "": "unknown",
        "자유": "free", "자유선택": "free", "일부": "partial", "부분": "partial",
        "강제": "forced", "지정": "forced",
        "독점": "exclusive", "기재": "defined", "없음(미기재)": "none",
        "분담": "shared", "공동": "shared", "점주": "franchisee_forced",
        "의무": "franchisee_forced",
    }
    text = korean.get(text, text)
    return text if text in options else None


def normalize_terms(args: Any) -> Dict[str, Any]:
    """입력(한글·영문 키 혼용, 문자열 금액) → 표준 필드 dict."""
    raw = args if isinstance(args, dict) else {}
    nested = raw.get("terms") if isinstance(raw.get("terms"), dict) else {}
    source: Dict[str, Any] = {}
    for block in (nested, raw):
        for key, value in block.items():
            if isinstance(value, dict):
                continue
            canonical = FIELD_ALIASES.get(_clean_key(key))
            if canonical and value is not None and value != "":
                source[canonical] = value
    terms: Dict[str, Any] = {}
    for field in MONEY_FIELDS:
        if field in source:
            parsed = parse_money(source[field])
            if parsed is not None:
                terms[field] = parsed
    for field in NUMBER_FIELDS:
        if field in source:
            parsed = parse_number(source[field])
            if parsed is not None:
                terms[field] = parsed
    for field in BOOL_FIELDS:
        if field in source:
            parsed = parse_bool(source[field])
            if parsed is not None:
                terms[field] = parsed
    for field in ENUM_FIELDS:
        if field in source:
            parsed = parse_enum(field, source[field])
            if parsed is not None:
                terms[field] = parsed
    for field in ("brand_name", "brand_code", "industry", "revenue_claim_ko"):
        value = source.get(field)
        if value is not None:
            text = str(value).strip()
            if text:
                terms[field] = text[:120]
    # 매출 관련 축: 약속 문구나 서면 여부 중 하나라도 있으면 '안다'로 본다.
    return terms


def known_axes(terms: Dict[str, Any]) -> Dict[str, bool]:
    revenue_known = any(
        terms.get(field) is not None
        for field in ("revenue_claim_ko", "revenue_written", "revenue_estimate_doc")
    )
    return {
        "disclosure_days_before": terms.get("disclosure_days_before") is not None
        or terms.get("contract_doc_days_before") is not None,
        "payment_route": terms.get("payment_route") not in (None, "unknown"),
        "revenue": revenue_known,
        "interior_designated": terms.get("interior_designated") not in (None, "unknown"),
        "territory": terms.get("territory") not in (None, "unknown"),
        "closure_rate_3y_pct": terms.get("closure_rate_3y_pct") is not None,
        "legal_violation": terms.get("legal_violation") is not None,
        "termination_grace_months": terms.get("termination_grace_months") is not None,
    }


# ---------------------------------------------------------------------------
# 함정별 판정
# ---------------------------------------------------------------------------
def _result(status: str, severity: str = "", note_ko: str = "") -> Dict[str, Any]:
    return {"status": status, "severity": severity, "note_ko": note_ko}


def _ev_same_day(terms: Dict[str, Any]) -> Dict[str, Any]:
    days = terms.get("disclosure_days_before")
    doc_days = terms.get("contract_doc_days_before")
    values = [value for value in (days, doc_days) if value is not None]
    if not values:
        return _result("unknown")
    limit = 7 if terms.get("advisor_reviewed") else 14
    worst = min(values)
    if worst < limit:
        return _result("triggered", models.SEVERITY_HIGH,
                       f"경과일 {int(worst)}일 (기준 {limit}일)")
    return _result("clear", note_ko=f"경과일 {int(worst)}일 (기준 {limit}일)")


def _ev_revenue(terms: Dict[str, Any]) -> Dict[str, Any]:
    claim = terms.get("revenue_claim_ko")
    written = terms.get("revenue_written")
    estimate = terms.get("revenue_estimate_doc")
    if estimate is False or written is False:
        reason = "예상매출액 산정서를 받지 못함" if estimate is False else "매출 정보를 서면으로 받지 못함"
        return _result("triggered", models.SEVERITY_HIGH, reason)
    if claim and written is None and estimate is None:
        return _result("unknown", note_ko=f"구두 약속만 있음: {claim}")
    if written is None and estimate is None and not claim:
        return _result("unknown")
    return _result("clear", note_ko="서면으로 받았거나 매출 약속이 없음")


def _ev_payment(terms: Dict[str, Any]) -> Dict[str, Any]:
    route = terms.get("payment_route")
    if route == "hq_account":
        return _result("triggered", models.SEVERITY_HIGH, "본사 계좌 직접 송금 요구")
    if route in ("escrow", "insurance"):
        return _result("clear", note_ko=PAYMENT_LABELS_KO.get(route, ""))
    if route == "none":
        return _result("clear", note_ko="예치 없음 — 예치·보험 항목에서 따로 판정")
    return _result("unknown")


def _ev_interior(terms: Dict[str, Any]) -> Dict[str, Any]:
    value = terms.get("interior_designated")
    if value == "forced":
        return _result("triggered", models.SEVERITY_HIGH, "본사 지정 업체 100% 강제")
    if value == "partial":
        return _result("triggered", models.SEVERITY_MEDIUM, "일부 품목 본사 지정")
    if value == "free":
        return _result("clear", note_ko="자유 선택")
    return _result("unknown")


def _ev_territory(terms: Dict[str, Any]) -> Dict[str, Any]:
    value = terms.get("territory")
    if value == "none":
        return _result("triggered", models.SEVERITY_HIGH, "영업지역 미기재")
    if value == "defined":
        return _result("triggered", models.SEVERITY_MEDIUM, "영업지역은 있으나 독점 아님")
    if value == "exclusive":
        return _result("clear", note_ko="독점 영업지역 기재")
    return _result("unknown")


def _ev_closure(terms: Dict[str, Any]) -> Dict[str, Any]:
    rate = terms.get("closure_rate_3y_pct")
    if rate is None:
        return _result("unknown")
    if rate >= 15:
        return _result("triggered", models.SEVERITY_HIGH, f"최근 3년 폐점률 {rate:.1f}%")
    if rate >= 8:
        return _result("triggered", models.SEVERITY_MEDIUM, f"최근 3년 폐점률 {rate:.1f}%")
    return _result("clear", note_ko=f"최근 3년 폐점률 {rate:.1f}%")


def _ev_violation(terms: Dict[str, Any]) -> Dict[str, Any]:
    value = terms.get("legal_violation")
    if value is True:
        return _result("triggered", models.SEVERITY_HIGH, "법 위반 이력이 있음(고지·확인 필요)")
    if value is False:
        return _result("clear", note_ko="확인한 이력 없음")
    return _result("unknown")


def _ev_escrow(terms: Dict[str, Any]) -> Dict[str, Any]:
    route = terms.get("payment_route")
    if route == "none":
        return _result("triggered", models.SEVERITY_HIGH, "예치·피해보상보험 모두 없음")
    if route in ("escrow", "insurance"):
        return _result("clear", note_ko=PAYMENT_LABELS_KO.get(route, ""))
    if route == "hq_account":
        return _result("clear", note_ko="본사 직접 송금은 '가맹금 본사 계좌 송금' 신호로 판정(중복 계상 안 함)")
    return _result("unknown")


def _ev_penalty(terms: Dict[str, Any]) -> Dict[str, Any]:
    ratio = terms.get("penalty_ratio_pct")
    total = terms.get("total_investment_krw") or _computed_total(terms)
    if terms.get("penalty_krw") and total:
        computed = terms["penalty_krw"] / total * 100.0
        ratio = computed if ratio is None else max(float(ratio), computed)
    if ratio is None:
        return _result("unknown")
    if ratio >= 40:
        return _result("triggered", models.SEVERITY_HIGH, f"위약금이 총투자의 {ratio:.0f}%")
    if ratio >= 20:
        return _result("triggered", models.SEVERITY_MEDIUM, f"위약금이 총투자의 {ratio:.0f}%")
    return _result("clear", note_ko=f"위약금 비율 {ratio:.0f}%")


def _ev_purchase(terms: Dict[str, Any]) -> Dict[str, Any]:
    mandatory = terms.get("mandatory_purchase")
    supplier = terms.get("supplier_designated")
    target = terms.get("sales_target")
    if mandatory is True or supplier is True or target is True:
        note = "필수품목 구입 강제" if mandatory else ("판매목표 강제" if target else "거래처 지정")
        return _result("triggered", models.SEVERITY_MEDIUM, note)
    if mandatory is False and supplier is False and target is False:
        return _result("clear", note_ko="필수품목·거래처·판매목표 강제 없음")
    if mandatory is False and supplier is None and target is None:
        return _result("clear", note_ko="필수품목 없음")
    return _result("unknown")


def _ev_price(terms: Dict[str, Any]) -> Dict[str, Any]:
    value = terms.get("price_fixing")
    if value is True:
        return _result("triggered", models.SEVERITY_MEDIUM, "판매가격 구속")
    if value is False:
        return _result("clear", note_ko="가격 결정권 있음")
    return _result("unknown")


def _ev_essential_margin(terms: Dict[str, Any]) -> Dict[str, Any]:
    """필수품목 단가 미공개·과다 지정·차액가맹금 일방 인상."""
    hidden = terms.get("essential_price_hidden")
    broad = terms.get("essential_items_broad")
    raised = terms.get("margin_raise_unilateral")
    if hidden is True or broad is True or raised is True:
        note = ("필수품목 단가·산정기준 미공개" if hidden else
                "필수품목 범위 과다(일반 공산품 포함)" if broad else
                "차액가맹금 일방 인상")
        return _result("triggered", models.SEVERITY_HIGH, note)
    if hidden is False and broad is False and raised is False:
        return _result("clear", note_ko="필수품목 단가·범위·인상 절차 확인")
    return _result("unknown")


def _ev_resale_price(terms: Dict[str, Any]) -> Dict[str, Any]:
    """재판매가격 유지·할인 금지."""
    bound = terms.get("resale_price_bound")
    discount = terms.get("discount_forbidden")
    if bound is True or discount is True:
        note = "판매가격 유지·변경 제한" if bound else "할인 금지"
        return _result("triggered", models.SEVERITY_MEDIUM, note)
    if bound is False and discount is False:
        return _result("clear", note_ko="가격·할인 결정권 확인")
    return _result("unknown")


def _ev_ad(terms: Dict[str, Any]) -> Dict[str, Any]:
    value = terms.get("ad_cost_burden")
    if value == "franchisee_forced":
        return _result("triggered", models.SEVERITY_LOW, "광고·판촉비 점주 의무 부담")
    if value in ("shared", "none"):
        return _result("clear", note_ko=AD_LABELS_KO.get(value, ""))
    return _result("unknown")


def _ev_renewal(terms: Dict[str, Any]) -> Dict[str, Any]:
    years = terms.get("renewal_years")
    refused = terms.get("renewal_refused")
    if years is not None and years > 10:
        return _result("triggered", models.SEVERITY_MEDIUM, f"전체 계약기간 {years:.0f}년(10년 초과)")
    if refused is True:
        return _result("triggered", models.SEVERITY_MEDIUM, "갱신 거절 사유가 넓음")
    if years is not None or refused is False:
        return _result("clear", note_ko="10년 이내·갱신 가능")
    return _result("unknown")


def _ev_termination(terms: Dict[str, Any]) -> Dict[str, Any]:
    months = terms.get("termination_grace_months")
    if months is None:
        return _result("unknown")
    if months < 2:
        return _result("triggered", models.SEVERITY_MEDIUM, f"유예기간 {months:.0f}개월(2개월 미만)")
    return _result("clear", note_ko=f"유예기간 {months:.0f}개월")


def _ev_registration(terms: Dict[str, Any]) -> Dict[str, Any]:
    value = terms.get("disclosure_registered")
    if value is False:
        return _result("triggered", models.SEVERITY_MEDIUM, "정보공개서 등록 미확인")
    if value is True:
        return _result("clear", note_ko="등록 정보공개서 확인")
    return _result("unknown")


EVALUATORS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "same_day_contract": _ev_same_day,
    "revenue_verbal_guarantee": _ev_revenue,
    "payment_to_hq_account": _ev_payment,
    "interior_forced": _ev_interior,
    "no_territory": _ev_territory,
    "closure_rate_hidden": _ev_closure,
    "legal_violation_hidden": _ev_violation,
    "no_escrow": _ev_escrow,
    "excessive_penalty": _ev_penalty,
    "mandatory_purchase": _ev_purchase,
    "price_fixing": _ev_price,
    "essential_items_margin": _ev_essential_margin,
    "resale_price_maintenance": _ev_resale_price,
    "ad_cost": _ev_ad,
    "renewal_terms": _ev_renewal,
    "termination_no_grace": _ev_termination,
    "disclosure_not_registered": _ev_registration,
}

AXIS_BY_TRAP = {
    "same_day_contract": "disclosure_days_before",
    "revenue_verbal_guarantee": "revenue",
    "payment_to_hq_account": "payment_route",
    "no_escrow": "payment_route",
    "interior_forced": "interior_designated",
    "no_territory": "territory",
    "closure_rate_hidden": "closure_rate_3y_pct",
    "legal_violation_hidden": "legal_violation",
    "termination_no_grace": "termination_grace_months",
}


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------
def _computed_total(terms: Dict[str, Any]) -> Optional[int]:
    parts = [terms.get(field) for field in
             ("franchise_fee_krw", "education_fee_krw", "deposit_krw", "interior_krw",
              "equipment_krw", "other_krw")]
    values = [value for value in parts if isinstance(value, (int, float))]
    return int(sum(values)) if values else None


def _money_block(terms: Dict[str, Any]) -> Dict[str, Any]:
    total = terms.get("total_investment_krw") or _computed_total(terms)
    components = {
        "franchise_fee_krw": terms.get("franchise_fee_krw"),
        "education_fee_krw": terms.get("education_fee_krw"),
        "deposit_krw": terms.get("deposit_krw"),
        "interior_krw": terms.get("interior_krw"),
        "equipment_krw": terms.get("equipment_krw"),
        "other_krw": terms.get("other_krw"),
    }
    labels = {
        "franchise_fee_krw": "가맹비", "education_fee_krw": "교육비", "deposit_krw": "보증금",
        "interior_krw": "인테리어", "equipment_krw": "설비·집기", "other_krw": "기타",
    }
    lines = []
    for field, value in components.items():
        if value is None:
            continue
        share = (value / total * 100.0) if total else None
        lines.append({
            "field": field, "label_ko": labels[field], "amount_krw": int(value),
            "amount_ko": models.format_krw(value),
            "share_pct": round(share, 1) if share is not None else None,
        })
    return {
        "total_krw": int(total) if total else None,
        "total_ko": models.format_krw(total) if total else "",
        "total_source": "input" if terms.get("total_investment_krw") else (
            "computed" if total else "unknown"),
        "components": lines,
        "royalty_rate_pct": terms.get("royalty_rate_pct"),
        "note_ko": ("합계는 입력한 항목의 단순 합입니다. 부가세·보증금 성격·초도물량 등은 "
                    "본부 견적서로 다시 확인하세요."),
    }


def evaluate(terms: Dict[str, Any]) -> Dict[str, Any]:
    """정규화된 조건 → triggered/unknown/clear 세 묶음."""
    triggered: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []
    clear: List[Dict[str, Any]] = []
    for case in trap_cases():
        evaluator = EVALUATORS.get(case["id"])
        if evaluator is None:
            continue
        outcome = evaluator(terms)
        row = {
            "trap_id": case["id"],
            "title_ko": case["title_ko"],
            "category": case["category"],
            "category_label_ko": models.CATEGORY_LABELS_KO.get(case["category"], ""),
            "severity": outcome["severity"] or case["severity"],
            "severity_label_ko": models.severity_label(outcome["severity"] or case["severity"]),
            "why_ko": case["why_ko"],
            "regret_ko": case["regret_ko"],
            "fix_ko": case["fix_ko"],
            "ask_ko": case["ask_ko"],
            "checklist_ko": case["checklist_ko"],
            "law_refs": case["law_refs"],
            "note_ko": outcome["note_ko"],
        }
        if outcome["status"] == "triggered":
            triggered.append(row)
        elif outcome["status"] == "unknown":
            unknown.append(row)
        else:
            clear.append(row)
    order = {severity: index for index, severity in enumerate(models.SEVERITY_ORDER)}
    triggered.sort(key=lambda row: order.get(row["severity"], 9))
    return {"triggered": triggered, "unknown": unknown, "clear": clear}


def decide(terms: Dict[str, Any], evaluated: Dict[str, Any]) -> Dict[str, Any]:
    """위험 신호 수와 채워진 축으로 세 가지 판정 중 하나를 고른다."""
    triggered = evaluated["triggered"]
    high = [row for row in triggered if row["severity"] == models.SEVERITY_HIGH]
    medium = [row for row in triggered if row["severity"] == models.SEVERITY_MEDIUM]
    axes = known_axes(terms)
    missing_axes = [axis for axis in KEY_AXES if not axes.get(axis)]
    if triggered:
        code = models.VERDICT_CHECK
    elif missing_axes:
        code = models.VERDICT_INFO
    else:
        code = models.VERDICT_LOW
    score = min(100, len(high) * 25 + len(medium) * 10
                + sum(1 for row in triggered if row["severity"] == models.SEVERITY_LOW) * 4)
    level = (models.SEVERITY_HIGH if high else
             models.SEVERITY_MEDIUM if medium else
             models.SEVERITY_LOW if triggered else "")
    confidence = round(len(KEY_AXES) - len(missing_axes)) / len(KEY_AXES)
    return {
        "verdict": models.verdict_block(code),
        "risk_score": score,
        "risk_level": level or "none",
        "risk_level_label_ko": models.severity_label(level) if level else "신호 없음",
        "counts": {
            "high": len(high), "medium": len(medium),
            "low": sum(1 for row in triggered if row["severity"] == models.SEVERITY_LOW),
            "triggered": len(triggered), "unknown": len(evaluated["unknown"]),
            "clear": len(evaluated["clear"]),
        },
        "answered_axes": len(KEY_AXES) - len(missing_axes),
        "total_axes": len(KEY_AXES),
        "missing_axes": missing_axes,
        "confidence": confidence,
    }


MISSING_AXIS_QUESTIONS = {
    "disclosure_days_before": "정보공개서를 받은 날부터 계약까지 며칠이 지났나요?",
    "payment_route": "가맹금을 어디로 내라고 했나요? (예치기관·보험·본사 계좌)",
    "revenue": "매출 보장을 서면(예상매출액 산정서)으로 받았나요?",
    "interior_designated": "인테리어·집기를 본사가 지정하나요? 다른 업체도 가능한가요?",
    "territory": "계약서에 영업지역(행정동·반경)이 적혀 있나요?",
    "closure_rate_3y_pct": "최근 3년 폐점률(또는 계약해지 건수)을 알고 있나요?",
    "legal_violation": "본부의 공정위 시정조치·과징금 이력을 확인했나요?",
    "termination_grace_months": "본부가 계약을 해지할 때 유예기간이 몇 개월인가요?",
}


def summary_text(terms: Dict[str, Any], decision: Dict[str, Any],
                 evaluated: Dict[str, Any]) -> str:
    brand = terms.get("brand_name") or "해당 브랜드"
    industry = terms.get("industry")
    head = f"{brand}" + (f"({industry})" if industry else "")
    counts = decision["counts"]
    if decision["verdict"]["code"] == models.VERDICT_CHECK:
        parts = [f"{head} 조건에서 확인이 필요한 신호 {counts['triggered']}건을 찾았습니다."]
        if counts["high"]:
            parts.append(f"그중 위험 높음 {counts['high']}건은 계약·입금 전에 반드시 확인해야 합니다.")
        top = evaluated["triggered"][0]
        parts.append(f"가장 먼저 볼 항목은 '{top['title_ko']}'입니다.")
        return " ".join(parts)
    if decision["verdict"]["code"] == models.VERDICT_INFO:
        return (f"{head} 조건은 아직 판정에 필요한 항목이 남아 있습니다. "
                f"{len(decision['missing_axes'])}개 항목을 더 확인하면 위험 신호 유무가 좁혀집니다.")
    return (f"{head} 조건에서는 제시된 8개 핵심 항목 모두에서 뚜렷한 위험 신호가 보이지 않았습니다. "
            "확정 판정이 아니므로 서류 원문과 현장 확인은 따로 하세요.")


def checklist(triggered: List[Dict[str, Any]], unknown: List[Dict[str, Any]],
              limit: int = 12) -> List[str]:
    """기본 4개 + 확인된 신호의 항목 → 모르는 항목 순으로 채우고 `limit` 에서 자른다."""
    base = [
        "정보공개서 등록번호·등록일을 가맹사업정보제공시스템에서 대조",
        "가맹계약서 초안과 정보공개서를 계약 전에 받아 보관",
        "가맹금은 예치기관 예치 또는 피해보상보험계약으로 납부",
        "변호사·가맹거래사 자문(숙고기간이 7일로 줄어드는 점 유의)",
    ]
    seen = set(base)
    merged = list(base)
    ordered = list(triggered) + list(unknown)
    # 확인된 신호의 체크리스트를 먼저, 그 다음 모르는 항목.
    for row in ordered:
        if len(merged) >= limit:
            break
        for item in row.get("checklist_ko") or []:
            if len(merged) >= limit:
                break
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return merged


def next_steps(terms: Dict[str, Any]) -> List[Dict[str, str]]:
    brand = terms.get("brand_name")
    steps = [
        {"title_ko": "등록 정보공개서 원문 확인",
         "detail_ko": "브랜드명으로 검색해 등록번호·최근 등록일·가맹점 변동 현황을 봅니다.",
         "url": DISCLOSURE_PORTAL},
        {"title_ko": "예상매출액 산정서·산출근거 요구",
         "detail_ko": "매출을 언급했다면 서면과 산출근거 자료 열람을 요구하세요.",
         "url": ""},
        {"title_ko": "가맹거래사·변호사 자문",
         "detail_ko": "계약서 초안을 가지고 숙고기간 안에 자문을 받으면 됩니다.",
         "url": ""},
    ]
    if brand:
        steps.append({
            "title_ko": "창업 지원금 확인",
            "detail_ko": "소상공인 정책자금·청년창업 지원 등 받을 수 있는 지원금을 GRNT에서 확인할 수 있습니다.",
            "url": GRANT_URL,
        })
    return steps


def check_franchise_risk(args: Any) -> Dict[str, Any]:
    terms = normalize_terms(args)
    evaluated = evaluate(terms)
    decision = decide(terms, evaluated)
    missing_axes = set(decision["missing_axes"])
    # 근거 조문은 '확인된 위험 신호'의 것만 붙인다. 신호가 없으면 핵심 축의 근거만 골라 붙인다.
    source_rows = evaluated["triggered"]
    law_scope = "triggered"
    refs: List[str] = []
    anchors: Dict[str, str] = {}
    if not source_rows:
        law_scope = "key_axes"
        refs = list(CORE_LAW_REFS)
    for row in source_rows:
        for key in row.get("law_refs") or []:
            refs.append(key)
        case = trap_index().get(row["trap_id"]) or {}
        for key, anchor in (case.get("law_excerpt_anchors") or {}).items():
            anchors.setdefault(key, anchor)
    questions: List[str] = []
    for axis in decision["missing_axes"]:
        question = MISSING_AXIS_QUESTIONS.get(axis)
        if question and question not in questions:
            questions.append(question)
    for row in evaluated["triggered"]:
        if row["ask_ko"] and row["ask_ko"] not in questions:
            questions.append(row["ask_ko"])
    for row in evaluated["unknown"]:
        if len(questions) >= 8:
            break
        # 이미 같은 축의 질문이 위에 있으면 같은 말을 두 번 묻지 않는다.
        if AXIS_BY_TRAP.get(row["trap_id"]) in missing_axes:
            continue
        if row["ask_ko"] and row["ask_ko"] not in questions:
            questions.append(row["ask_ko"])
    questions = questions[:8]
    payload = {
        "brand": {
            "name": terms.get("brand_name"),
            "code": terms.get("brand_code"),
            "industry": terms.get("industry"),
        },
        "terms_used": {key: value for key, value in terms.items()},
        "verdict": decision["verdict"],
        "risk_score": decision["risk_score"],
        "risk_level": decision["risk_level"],
        "risk_level_label_ko": decision["risk_level_label_ko"],
        "counts": decision["counts"],
        "coverage": {
            "answered_axes": decision["answered_axes"],
            "total_axes": decision["total_axes"],
            "missing_axes": decision["missing_axes"],
            "confidence": decision["confidence"],
        },
        "summary_ko": summary_text(terms, decision, evaluated),
        "risk_points": evaluated["triggered"],
        "unknown_points": evaluated["unknown"],
        "clear_points": [
            {"trap_id": row["trap_id"], "title_ko": row["title_ko"], "note_ko": row["note_ko"]}
            for row in evaluated["clear"]
        ],
        "questions_ko": questions,
        "checklist_ko": checklist(evaluated["triggered"], evaluated["unknown"], limit=12),
        "money": _money_block(terms),
        "law_basis": law_basis(refs, anchors),
        "law_basis_scope_ko": (
            "확인된 위험 신호의 근거 조문입니다."
            if law_scope == "triggered" else
            "위험 신호가 확인되지 않아, 핵심 8축을 확인한 근거 조문을 실었습니다."),
        "next_steps": next_steps(terms),
        "startup_support": {
            "service": "GRNT",
            "name_ko": "개인·창업 통합 지원금 판정기",
            "url": GRANT_URL,
            "note_ko": ("프랜차이즈 창업비용을 낸 뒤에도 소상공인 정책자금·청년창업·고용 지원금을 "
                        "받을 수 있는 경우가 있습니다. 조건을 넣어 후보를 확인하세요."),
        },
        "disclaimer_ko": models.DISCLAIMER_KO,
        "scope_limits_ko": models.SCOPE_LIMITS_KO,
    }
    return payload


# ---------------------------------------------------------------------------
# 두 조건 비교
# ---------------------------------------------------------------------------
COMPARE_ROWS = (
    ("total_investment_krw", "총투자", "money", "lower"),
    ("franchise_fee_krw", "가맹비", "money", "lower"),
    ("interior_krw", "인테리어", "money", "lower"),
    ("deposit_krw", "보증금", "money", "lower"),
    ("royalty_rate_pct", "로열티(%)", "number", "lower"),
    ("disclosure_days_before", "정보공개서 경과일", "number", "higher"),
    ("penalty_ratio_pct", "위약금(총투자 대비 %)", "number", "lower"),
    ("closure_rate_3y_pct", "3년 폐점률(%)", "number", "lower"),
    ("termination_grace_months", "해지 유예기간(개월)", "number", "higher"),
    ("payment_route", "가맹금 납부", "enum", "compliance"),
    ("interior_designated", "인테리어 지정", "enum", "compliance"),
    ("territory", "영업지역", "enum", "compliance"),
)


def _side_label(terms: Dict[str, Any], fallback: str) -> str:
    name = str(terms.get("brand_name") or "").strip()
    if not name:
        return fallback
    industry = str(terms.get("industry") or "").strip()
    return f"{name}({industry})" if industry else name


def _display(field: str, kind: str, value: Any) -> str:
    if value is None:
        return ""
    if kind == "money":
        return models.format_krw(value)
    if kind == "number":
        return f"{value:g}"
    if field == "payment_route":
        return PAYMENT_LABELS_KO.get(str(value), str(value))
    if field == "interior_designated":
        return INTERIOR_LABELS_KO.get(str(value), str(value))
    if field == "territory":
        return TERRITORY_LABELS_KO.get(str(value), str(value))
    return str(value)


def _compliance_score(field: str, value: Any) -> Optional[int]:
    """같은 축에서 어느 쪽이 안전한지 비교하기 위한 서열(높을수록 안전)."""
    tables = {
        "payment_route": {"escrow": 2, "insurance": 2, "none": 0, "hq_account": 0},
        "interior_designated": {"free": 2, "partial": 1, "forced": 0},
        "territory": {"exclusive": 2, "defined": 1, "none": 0},
    }
    return tables.get(field, {}).get(str(value))


def compare_franchise_terms(args: Any) -> Dict[str, Any]:
    raw = args if isinstance(args, dict) else {}
    side_a_input = raw.get("a") or raw.get("terms_a") or raw.get("franchise_a") or {}
    side_b_input = raw.get("b") or raw.get("terms_b") or raw.get("franchise_b") or {}
    if not isinstance(side_a_input, dict) or not isinstance(side_b_input, dict):
        raise ValueError("a·b 두 조건을 객체로 주세요.")
    if not side_a_input or not side_b_input:
        raise ValueError("비교할 두 프랜차이즈 조건(a, b)이 모두 필요합니다.")
    side_a = normalize_terms({**side_a_input, "terms": side_a_input})
    side_b = normalize_terms({**side_b_input, "terms": side_b_input})
    name_a = _side_label(side_a, "A")
    name_b = _side_label(side_b, "B")
    rows: List[Dict[str, Any]] = []
    differences: List[str] = []
    for field, label, kind, better in COMPARE_ROWS:
        value_a, value_b = side_a.get(field), side_b.get(field)
        if field == "total_investment_krw":
            value_a = value_a or _computed_total(side_a)
            value_b = value_b or _computed_total(side_b)
        display_a = _display(field, kind, value_a)
        display_b = _display(field, kind, value_b)
        winner = "unknown"
        gap = None
        if value_a is not None and value_b is not None:
            if kind in ("money", "number"):
                gap = round(float(value_b) - float(value_a), 2)
                if float(value_a) == float(value_b):
                    winner = "tie"
                else:
                    lower_is_a = float(value_a) < float(value_b)
                    winner = ("a" if lower_is_a else "b") if better == "lower" else (
                        "b" if lower_is_a else "a")
            elif kind == "enum":
                score_a, score_b = _compliance_score(field, value_a), _compliance_score(field, value_b)
                if score_a is not None and score_b is not None:
                    winner = "tie" if score_a == score_b else ("a" if score_a > score_b else "b")
        row = {
            "field": field, "label_ko": label, "kind": kind,
            "a_ko": display_a, "b_ko": display_b,
            "a_value": value_a, "b_value": value_b,
            "winner": winner,
        }
        if gap is not None and kind == "money":
            row["gap_krw"] = int(gap)
            row["gap_ko"] = models.format_krw(abs(gap))
        rows.append(row)
        if winner in ("a", "b") and kind in ("money", "number") and gap is not None:
            better_side = name_a if winner == "a" else name_b
            if kind == "money":
                differences.append(f"{label} — {better_side} 유리 (차이 {models.format_krw(abs(gap))})")
            else:
                differences.append(f"{label} — {better_side} 유리 (차이 {abs(gap):g})")
        elif winner in ("a", "b") and kind == "enum":
            safe = name_a if winner == "a" else name_b
            differences.append(f"{label} — {safe} 쪽이 안전")
    evaluated_a = evaluate(side_a)
    evaluated_b = evaluate(side_b)
    decision_a = decide(side_a, evaluated_a)
    decision_b = decide(side_b, evaluated_b)
    payload = {
        "a": {
            "label": name_a,
            "verdict": decision_a["verdict"],
            "risk_score": decision_a["risk_score"],
            "counts": decision_a["counts"],
            "risk_titles_ko": [row["title_ko"] for row in evaluated_a["triggered"]],
        },
        "b": {
            "label": name_b,
            "verdict": decision_b["verdict"],
            "risk_score": decision_b["risk_score"],
            "counts": decision_b["counts"],
            "risk_titles_ko": [row["title_ko"] for row in evaluated_b["triggered"]],
        },
        "rows": rows,
        "differences_ko": differences,
        "recommendation_ko": _compare_advice(name_a, name_b, decision_a, decision_b),
        "law_basis": law_basis([key for row in (evaluated_a["triggered"] + evaluated_b["triggered"])
                                for key in row.get("law_refs") or []]),
        "disclaimer_ko": models.DISCLAIMER_KO,
        "scope_limits_ko": models.SCOPE_LIMITS_KO,
    }
    return payload


def _compare_advice(name_a: str, name_b: str, decision_a: Dict[str, Any],
                    decision_b: Dict[str, Any]) -> str:
    a, b = decision_a["counts"]["triggered"], decision_b["counts"]["triggered"]
    a_high = decision_a["counts"]["high"]
    b_high = decision_b["counts"]["high"]
    if a == 0 and b == 0:
        return ("두 조건 모두 뚜렷한 위험 신호는 없습니다. 비용·상권·본부 지원을 기준으로 비교하세요. "
                "확정 판정이 아닙니다.")
    if a_high and not b_high:
        return (f"위험 높음 신호 — {name_a} {a_high}건 / {name_b} 0건. "
                f"지금 조건만 보면 {name_b} 쪽이 절차 위험이 적습니다. 확정 판정이 아닙니다.")
    if b_high and not a_high:
        return (f"위험 높음 신호 — {name_a} 0건 / {name_b} {b_high}건. "
                f"지금 조건만 보면 {name_a} 쪽이 절차 위험이 적습니다. 확정 판정이 아닙니다.")
    if a == b:
        return (f"두 조건 모두 확인 신호가 {a}건씩입니다. 비용과 상권, 본부 지원을 함께 보세요. "
                "확정 판정이 아닙니다.")
    safer, riskier = (name_a, name_b) if a < b else (name_b, name_a)
    return (f"확인 신호 — {riskier} {max(a, b)}건 / {safer} {min(a, b)}건. "
            f"신호 수만 보면 {safer} 쪽이 적지만, 위험 높음 신호가 남아 있다면 그것부터 확인하세요. "
            "확정 판정이 아닙니다.")


# ---------------------------------------------------------------------------
# 코퍼스·법령 조회
# ---------------------------------------------------------------------------
def list_risk_cases() -> Dict[str, Any]:
    cases = []
    for case in trap_cases():
        keys = [key for key in case.get("law_refs") or [] if law_record(key)]
        cases.append({
            "trap_id": case["id"],
            "title_ko": case["title_ko"],
            "category": case["category"],
            "category_label_ko": models.CATEGORY_LABELS_KO.get(case["category"], ""),
            "severity": case["severity"],
            "severity_label_ko": models.severity_label(case["severity"]),
            "trigger_ko": case["trigger_ko"],
            "ask_ko": case["ask_ko"],
            "law_refs": case["law_refs"],
            "law_verified": len(keys) == len(case.get("law_refs") or []),
        })
    data = load_law()
    return {
        "count": len(cases),
        "cases": cases,
        "law_source": data.get("source"),
        "laws": data.get("laws") or [],
        "note_ko": ("각 케이스는 가맹사업법·시행령 조문과 1:1로 대조되어 있습니다. "
                    "law_verified=false 는 조문 키 확인이 필요하다는 뜻입니다."),
    }


def search_law_article(query: Any) -> Dict[str, Any]:
    """'제7조', '7조', '가맹사업법 제9조' → 실조회한 조문 레코드."""
    text = str(query or "").strip()
    data = load_law()
    articles = data.get("articles") or {}
    annexes = data.get("annexes") or {}
    if not text:
        return {"ok": False, "error": "query_required",
                "message_ko": "조문 번호를 주세요. 예: '제7조', '제9조', '가맹사업법 시행령 별표2'",
                "available": sorted(articles)[:40]}
    for key in (articles, annexes):
        if text in key:
            record = key[text]
            return {"ok": True, "key": text, "law": record.get("law"),
                    "title": record.get("title"), "effective_on": record.get("effective_on"),
                    "text": law_full_text(record),
                    "paragraphs": record.get("paragraphs") or [],
                    "source_url": record.get("source_url")}
    compact = re.sub(r"\s+", "", text)
    match = re.search(r"(?:제)?(\d+)조(?:의(\d+))?", compact)
    if not match:
        return {"ok": False, "error": "not_found", "query": text,
                "available": sorted(articles)[:40]}
    wanted = f"제{match.group(1)}조" + (f"의{match.group(2)}" if match.group(2) else "")
    law_hint = "시행령" if "시행령" in compact else ""
    for key, record in {**articles, **annexes}.items():
        if not key.endswith(":" + wanted):
            continue
        if law_hint and law_hint not in key:
            continue
        return {"ok": True, "key": key, "law": record.get("law"),
                "title": record.get("title"), "effective_on": record.get("effective_on"),
                "text": law_full_text(record), "paragraphs": record.get("paragraphs") or [],
                "source_url": record.get("source_url")}
    return {"ok": False, "error": "not_found", "query": text,
            "available": sorted(articles)[:40]}


def law_meta() -> Dict[str, Any]:
    data = load_law()
    return {
        "source": data.get("source"),
        "generated_at": data.get("generated_at"),
        "laws": data.get("laws") or [],
        "article_count": len(data.get("articles") or {}),
        "annex_count": len(data.get("annexes") or {}),
    }


def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 계약서·특약 문구 스캔 (0.1.2 → 0.1.3)
# ---------------------------------------------------------------------------
# 왜 규칙 엔진인가: 같은 문구는 언제 넣어도 같은 결과가 나와야 하고(결정적), 어떤 문구를
# 어떤 조문과 대조했는지 사용자가 직접 확인할 수 있어야 하기 때문이다. 여기서 하는 일은
# "이 문구는 계약 전에 확인이 필요하다"까지이고, 위법 여부나 계약 효력의 판정이 아니다.
#
# 문구 대조는 공백을 지운 사본에서 한다(계약서는 줄바꿈·띄어쓰기가 제각각이다).
# 대신 인용문은 원문 위치로 되돌려 잘라 내므로, 화면에 보이는 인용은 사용자가 넣은 글자
# 그대로다 — 우리가 문장을 만들어 내지 않는다.
ANNEX_UNFAIR = "가맹사업법 시행령:불공정거래행위의 유형 또는 기준(제13조제1항관련)"
ANNEX_DISCLOSURE = "가맹사업법 시행령:정보공개서의 기재사항(제4조제1항 관련)"

SCAN_MAX_CHARS = 20_000
SCAN_MIN_CHARS = 8
SCAN_MAX_FINDINGS_PER_RULE = 3
SCAN_MAX_FINDINGS = 24
SCAN_QUOTE_PAD = 44

SCAN_TEXT_KEYS = (
    "text", "contract_text", "clause_text", "document_text", "document", "content",
    "body", "special_terms", "special_terms_text", "contract", "특약", "계약서", "문구",
    "본문", "조항",
)

SCAN_NOT_A_CLEARANCE_KO = (
    "제시된 패턴에서 잡히지 않았을 뿐, 다른 특약이나 정보공개서 불일치가 있을 수 있어 "
    "원문 전체와 가맹거래사 확인이 필요합니다."
)

# 매칭 직후에 붙는 부정 표현 — "위약금을 부과하지 않는다" 같은 문장을 위험 신호로 세지 않는다.
SCAN_NEGATION_TAILS = (
    "하지않", "하지아니", "아니한다", "않는다", "않음", "않고", "할수없", "아니다",
)

SCAN_QUESTIONS_KO = [
    "특약 전체(별지·부속합의서 포함)를 정보공개서와 나란히 놓고 같은 내용인지 확인했나요?",
    "이 문구를 빼거나 고쳐 달라고 본부에 서면으로 요청할 수 있나요?",
    "계약서 초안을 가맹거래사나 변호사에게 보여 주고 검토받았나요?",
]


def _p(expr: str, note_ko: str = "", severity: str = "", guard: str = "") -> Dict[str, str]:
    """규칙 안의 문구 패턴 한 줄. 공백은 컴파일할 때 지운다(띄어쓰기 차이를 흡수)."""
    return {"expr": expr, "note_ko": note_ko, "severity": severity, "guard": guard}


CONTRACT_RULES: List[Dict[str, Any]] = [
    {
        "id": "purchase_forced",
        "title_ko": "구입강제·지정업체 강제",
        "category": "purchase",
        "severity": models.SEVERITY_HIGH,
        "why_ko": (
            "본사가 지정한 업체와만 거래하게 하면 비교견적이 막히고, 자재·시공 단가가 본사 "
            "재량에 맡겨집니다. 가맹사업법은 경영에 필요한 양을 넘는 시설·설비·상품·용역·"
            "원재료 구입을 강제하는 행위를 불공정거래행위로 봅니다(법 제12조, 시행령 별표 2 3.가)."
        ),
        "fix_ko": (
            "‘시공·설비·원부자재는 가맹점사업자가 비교견적 후 자유롭게 선정하되, 본사가 정한 "
            "최소 품질기준(시방)을 충족하면 인정한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": (
            "지정 업체 외 거래가 실제로 가능한가요? 지정 업체 단가표와 다른 업체 견적을 함께 "
            "받아 볼 수 있나요?"
        ),
        "law_refs": ["가맹사업법:제12조", "가맹사업법 시행령:제13조", ANNEX_UNFAIR],
        "anchors": {
            "가맹사업법:제12조": "부당하게 구속하거나 제한하는",
            ANNEX_UNFAIR: "가. 구입강제",
        },
        "patterns": [
            _p(r"(당사|본사|회사)가?지정(한|하는|된)(업체|시공사|공급업체|거래처|업자|인테리어업체|설비업체)",
               "지정 업체와만 거래하도록 묶는 문구입니다."),
            _p(r"지정(업체|업자|거래처)(외|외에|외에는)(거래|시공|구매|사용|납품)(할수없|금지|불가|불허)",
               "지정 업체 외 거래를 금지하는 문구입니다."),
            _p(r"(인테리어|간판|시설|설비|집기|비품|원부자재|부자재|식자재|포장재|물품)(일체|전부|모두)?(는|를|은)?(반드시|필히|오직)?(당사|본사)가?(지정|선정|공급)",
               "자재·시공사 선택을 본사가 정하는 문구입니다."),
            _p(r"(당사|본사)가?(공급|지정)하는(물품|자재|원부자재|식자재)(만|외에는)",
               "본사 공급 물품만 쓰도록 묶는 문구입니다."),
            _p(r"(타사|타업체|다른업체)(제품|물품)?(의)?(사용|구매|거래|시공|이용)(을|은)?(금지|할수없|불가|제한)",
               "타사 제품 사용을 막는 문구입니다.", models.SEVERITY_MEDIUM),
            _p(r"(공급처|거래처)(는|를)?(당사|본사)가?(선정|지정)",
               "거래처 선정권을 본사가 갖는 문구입니다.", models.SEVERITY_MEDIUM),
            _p(r"(필수품목|판매목표|최소구매량|구매수량)[^.]{0,16}(강제|의무|이상구매|달성하여야|구매하여야|판매하여야|달성하지못)",
               "필수품목 구매·판매목표 달성을 의무로 두는 문구입니다.",
               models.SEVERITY_MEDIUM),
        ],
    },
    {
        "id": "excessive_penalty",
        "title_ko": "과중 위약금·손해배상 예정",
        "category": "penalty",
        "severity": models.SEVERITY_HIGH,
        "why_ko": (
            "잔여기간 로열티 전액·보증금 몰수·2~3배 배상처럼 실제 손해보다 큰 금액을 미리 "
            "정해 두면, 나갈 때 그 금액을 그대로 물게 됩니다. 법은 계약의 목적·손해 크기·"
            "귀책 정도에 비해 과중한 위약금을 부당한 손해배상 의무로 봅니다"
            "(법 제12조①5, 시행령 제12조의2·별표 2 4.가)."
        ),
        "fix_ko": (
            "‘중도해지 위약금은 해지 사유와 잔여기간을 기준으로 산정한 실제 손해 범위에서 정하고, "
            "보증금은 미지급 가맹금·손해배상 채무를 빼고 반환한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": (
            "위약금 산정 근거(잔여기간·예상 손해액)를 서면으로 받을 수 있나요? 보증금 반환 조건은 "
            "무엇인가요?"
        ),
        "law_refs": [
            "가맹사업법:제12조", "가맹사업법 시행령:제12조의2", ANNEX_UNFAIR,
        ],
        "anchors": {
            "가맹사업법:제12조": "과중한 위약금을 부과하는",
            "가맹사업법 시행령:제12조의2": "계약의 목적과 내용",
            ANNEX_UNFAIR: "가. 과중한 위약금 설정",
        },
        "patterns": [
            _p(r"(잔여|남은)(계약)?기간(의)?(로열티|월회비|관리비|가맹비|수수료)(전액|전부|일시)",
               "남은 기간의 로열티를 전액 위약금으로 잡는 문구입니다."),
            _p(r"(가맹)?보증금[^.]{0,18}(몰수|귀속|상계)",
               "보증금을 돌려주지 않는 문구입니다."),
            _p(r"(보증금|가맹금)(은|을)?(어떠한|어떤|모든)경우에도?(반환하지않|돌려주지않)",
               "어떤 경우에도 반환하지 않는다는 문구입니다."),
            _p(r"손해배상(액|금)?(은|을)?(2|3|두|세)배",
               "손해액의 2~3배를 배상하게 하는 문구입니다."),
            _p(r"(위약금|위약벌|손해배상예정)[^0-9]{0,14}[0-9]{2,3}%",
               "위약금을 총투자 대비 큰 비율로 미리 정한 문구입니다.", "", "pct_ge_20"),
            _p(r"(위약금|손해배상예정)(은|을)?(총투자|총투자금|창업비용|가맹금)(의)?(2|3|두|세)배",
               "총투자의 2~3배를 위약금으로 정한 문구입니다."),
        ],
    },
    {
        "id": "unilateral_termination",
        "title_ko": "일방적 즉시 해지·최고 없는 해지",
        "category": "termination",
        "severity": models.SEVERITY_HIGH,
        "why_ko": (
            "최고와 유예기간 없이 바로 해지할 수 있다는 조항은 법이 정한 절차를 건너뛰게 "
            "만듭니다. 본부는 2개월 이상 유예기간을 두고 위반 사실을 구체적으로 밝혀 서면으로 "
            "2회 이상 통지해야 하고, 그 절차를 거치지 않은 해지는 효력이 없습니다(법 제14조)."
        ),
        "fix_ko": (
            "‘본부는 계약을 해지하려면 2개월 이상의 유예기간을 두고 위반 사실과 시정 요구를 "
            "서면으로 2회 이상 통지한 뒤 해지한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": "해지 전에 시정할 기회를 서면으로 받을 수 있나요? 통지 횟수와 방법이 계약서에 적혀 있나요?",
        "law_refs": ["가맹사업법:제14조", "가맹사업법 시행령:제15조"],
        "anchors": {"가맹사업법:제14조": "2개월 이상의 유예기간"},
        "patterns": [
            _p(r"(즉시|즉각|바로)[^.]{0,8}(해지|해제)", "절차 없이 바로 해지할 수 있게 한 문구입니다."),
            _p(r"(최고|통지|서면통지|시정요구)(를|을)?(거치지않고|받지않고|없이|없는)[^.]{0,10}(해지|해제)",
               "최고·통지 없이 해지할 수 있게 한 문구입니다."),
            _p(r"(당사|본사)(의)?(판단|결정|요청)만으로(해지|해제)",
               "본사 판단만으로 해지할 수 있게 한 문구입니다."),
            _p(r"(유예기간)(을)?(두지않|없이|적용하지않)",
               "유예기간을 두지 않는다는 문구입니다."),
            _p(r"(당사|본사)(는)?(언제든지|임의로|일방적으로)[^.]{0,10}(해지|해제)",
               "본사 마음대로 해지할 수 있게 한 문구입니다."),
            _p(r"(경고|시정요구)(1|한|일)회(로)?(즉시)?(해지|해제)",
               "한 번의 경고로 바로 해지하는 문구입니다.", models.SEVERITY_MEDIUM),
        ],
    },
    {
        "id": "territory_infringement",
        "title_ko": "영업지역 미보장·인근 출점 허용",
        "category": "territory",
        "severity": models.SEVERITY_HIGH,
        "why_ko": (
            "영업지역 보호가 없거나 본사가 인근에 직영점·가맹점을 열 수 있다는 조항이면, 내가 "
            "만든 매출을 옆 점포가 가져갈 수 있습니다. 법은 계약서에 영업지역을 기재하게 하고, "
            "정당한 사유 없이 영업지역 안에 같은 업종의 직영점이나 가맹점을 설치하는 것을 "
            "금지합니다(법 제12조의4)."
        ),
        "fix_ko": (
            "‘본사는 계약기간 중 가맹점사업자의 영업지역(행정동·반경으로 표기) 안에 동일 업종의 "
            "직영점이나 가맹점을 설치하지 않는다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": (
            "영업지역이 계약서에 행정동이나 반경으로 적혀 있나요? 인근 출점 계획이 있는지 서면으로 "
            "확인할 수 있나요?"
        ),
        "law_refs": ["가맹사업법:제12조의4", "가맹사업법 시행령:제13조의4", "가맹사업법:제11조"],
        "anchors": {"가맹사업법:제12조의4": "영업지역 안에서"},
        "patterns": [
            _p(r"영업지역(을|은|를)?(보장하지않|보호하지않|설정하지않|인정하지않|두지않)",
               "영업지역을 보장하지 않는다는 문구입니다."),
            _p(r"영업지역(에)?(대한)?(독점|배타적)(적)?(권리|보호)(는)?(없|부여하지않)",
               "독점·배타적 권리가 없다는 문구입니다."),
            _p(r"(인근|주변|반경[0-9]+(km|미터|m))(에|내)?(직영점|직영매장|가맹점|점포)(을)?(출점|개설|설치)(할수있|가능)",
               "영업지역 주변에 본사가 점포를 열 수 있게 한 문구입니다."),
            _p(r"(당사|본사)(의)?(판단|필요)(에)?(따라|의해)(인근|주변)?(출점|추가출점|가맹점개설|신규출점)",
               "본사 판단으로 추가 출점할 수 있게 한 문구입니다."),
            _p(r"(직영점|직영매장)(을)?(제한없이|자유롭게|언제든지|임의로)(출점|개설|설치)",
               "직영점 출점에 제한이 없다는 문구입니다."),
            _p(r"영업지역(내)?(추가)?출점(을)?(제한하지않|허용)",
               "영업지역 안 추가 출점을 허용한 문구입니다."),
        ],
    },
    {
        "id": "cooling_off_waiver",
        "title_ko": "숙고기간 포기·계약과 동시 입금",
        "category": "cooling_off",
        "severity": models.SEVERITY_HIGH,
        "why_ko": (
            "숙고기간을 포기하게 하거나 계약과 동시에 가맹금을 받는 조항은 조건을 비교할 14일을 "
            "없앱니다. 정보공개서를 받은 날부터 14일(자문을 받은 경우 7일)이 지나기 전에는 "
            "가맹계약 체결이나 가맹금 수령을 할 수 없습니다(법 제7조③)."
        ),
        "fix_ko": (
            "‘가맹희망자는 정보공개서를 받은 날부터 14일(자문 시 7일)이 지난 뒤 계약을 체결하고 "
            "가맹금을 납부한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": (
            "정보공개서를 받은 날짜와 계약 예정일이 어떻게 되나요? 숙고기간을 건너뛰는 별도 합의서를 "
            "요구했나요?"
        ),
        "law_refs": ["가맹사업법:제7조", "가맹사업법 시행령:제6조", "가맹사업법:제11조"],
        "anchors": {"가맹사업법:제7조": "14일"},
        "patterns": [
            _p(r"(14|십사)일(의)?(숙고기간|기간)(을)?(포기|면제|단축|적용하지않|배제)",
               "숙고기간을 포기·단축하게 하는 문구입니다."),
            _p(r"숙고기간(을)?(포기|면제|적용하지않|두지않)",
               "숙고기간을 적용하지 않는다는 문구입니다."),
            _p(r"정보공개서(를)?(받은)?(당일|즉시|바로)(계약|서명|체결)",
               "정보공개서를 받은 당일 계약하게 하는 문구입니다."),
            _p(r"(계약(체결)?(과)?동시에|계약당일|계약즉시)(가맹금|가맹비|보증금|교육비)?[^.]{0,40}(납부|입금|지급)",
               "계약과 동시에 돈을 받는 문구입니다."),
            _p(r"가맹금(은|을)?(계약(체결)?(전|즉시)|협약즉시)(납부|입금|지급)",
               "계약 전·즉시 가맹금을 받는 문구입니다."),
        ],
    },
    {
        "id": "payment_to_hq",
        "title_ko": "가맹금 본사 직접 수령",
        "category": "payment",
        "severity": models.SEVERITY_HIGH,
        "why_ko": (
            "가맹금을 본사 계좌로 직접 받으면 계약이 틀어졌을 때 돈을 돌려받을 장치가 사라집니다. "
            "법은 가맹금을 예치기관에 예치하도록 하거나 가맹점사업자피해보상보험계약을 "
            "체결하도록 정하고 있습니다(법 제6조의5, 제15조의2)."
        ),
        "fix_ko": (
            "‘가맹금은 법이 정한 예치기관에 예치하고, 예치 사실을 확인한 뒤 지급한다’로 바꿔 달라고 "
            "요청하세요."
        ),
        "ask_ko": "예치기관과 예치 계좌를 알려 줄 수 있나요? 피해보상보험계약 증서를 받았나요?",
        "law_refs": ["가맹사업법:제6조의5", "가맹사업법:제15조의2", "가맹사업법 시행령:제5조의8"],
        "anchors": {"가맹사업법:제6조의5": "예치하도록 하여야 한다"},
        "patterns": [
            _p(r"(가맹금|가맹비|보증금|교육비)[^.]{0,16}(당사|본사|회사)(의)?(계좌|명의)(로|에)(직접)?(입금|송금|납부|지급)",
               "가맹금을 본사 계좌로 받는 문구입니다."),
            _p(r"(당사|본사)(의)?계좌(로|에)(직접|바로)(입금|송금|납부)",
               "본사 계좌 입금을 요구하는 문구입니다."),
            _p(r"예치(하지않|없이|생략|대신)", "예치하지 않는다는 문구입니다."),
            _p(r"(예치기관|피해보상보험)(을|은|는)?(거치지않|통하지않|이용하지않)",
               "예치·보험을 거치지 않는다는 문구입니다."),
            _p(r"현금(으로)?(당사|본사)(에)?(직접)?(지급|납부|전달)",
               "현금으로 본사에 내라는 문구입니다.", models.SEVERITY_MEDIUM),
        ],
    },
    {
        "id": "ad_cost_unilateral",
        "title_ko": "광고·판촉비 일방 부담",
        "category": "advertising",
        "severity": models.SEVERITY_MEDIUM,
        "why_ko": (
            "점주에게 광고·판촉비를 일방적으로 청구하고 사전 동의를 받지 않는 조항은 비용 부담을 "
            "떠넘기는 구조입니다. 법은 점주가 비용을 부담하는 광고·판촉행사를 하려면 정해진 비율 "
            "이상의 동의를 받고, 집행 내역을 통보하고 열람하게 해야 한다고 정합니다(법 제12조의6)."
        ),
        "fix_ko": (
            "‘광고·판촉행사는 비용 부담 비율과 집행 내역을 사전에 서면으로 합의하고, 동의한 "
            "가맹점사업자에게만 부과한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": "광고비 부담 비율과 동의 절차가 계약서에 적혀 있나요? 지난 집행 내역을 열람할 수 있나요?",
        "law_refs": ["가맹사업법:제12조의6", "가맹사업법 시행령:제13조의5", "가맹사업법 시행령:제13조의6"],
        "anchors": {"가맹사업법:제12조의6": "동의를 받아야 한다"},
        "patterns": [
            _p(r"(광고|판촉|홍보)[^.]{0,8}(비|비용)[^.]{0,14}(가맹점|가맹점사업자|점주)(이|가|에게)?(부담|청구|지급|납부)",
               "광고·판촉비를 점주가 부담하는 문구입니다."),
            _p(r"(당사|본사)가?(실시한)?(광고|판촉)(비용|비)(을)?(가맹점|점주)(에게)?(청구|부과|전가)",
               "본사 광고비를 점주에게 청구하는 문구입니다."),
            _p(r"(사전동의|협의)(없이|를받지않고)?(광고|판촉)(행사|비용)?(을)?(실시|청구|부과|징수)",
               "사전 동의 없이 광고·판촉비를 매기는 문구입니다."),
            _p(r"(광고비|판촉비)(를)?(매월|매년|정기적)(으로)?(징수|청구|납부)",
               "광고비를 정기적으로 걷는 문구입니다."),
        ],
    },
    {
        "id": "revenue_guarantee",
        "title_ko": "매출·수익 보장·적자 보전",
        "category": "revenue",
        "severity": models.SEVERITY_HIGH,
        "why_ko": (
            "매출·수익을 보장하거나 적자를 보전해 준다는 문구는 계약서에 남는 순간 나중에 책임 "
            "소재가 뒤집힙니다. 법은 예상매출액·수익 정보를 서면으로 주고 산출근거를 열람하게 "
            "하며, 허위·과장된 정보 제공을 금지합니다(법 제9조)."
        ),
        "fix_ko": (
            "‘예상매출액은 산정서와 산출근거를 서면으로 제공하며, 실제 매출을 보장하지는 "
            "않는다’로 명확히 바꿔 달라고 요청하세요."
        ),
        "ask_ko": "매출 보장 문구를 서면으로 남길 수 있나요? 예상매출액 산정서와 산출근거를 받았나요?",
        "law_refs": ["가맹사업법:제9조", "가맹사업법 시행령:제8조", "가맹사업법 시행령:제9조"],
        "anchors": {"가맹사업법:제9조": "서면으로 하여야 한다"},
        "patterns": [
            _p(r"(?<!\()(월|일|연)?(순수익|순이익|수익|매출|영업이익|매출액)[^.]{0,18}(보장|확약|보증해|보증한다)",
               "매출·수익을 보장하는 문구입니다."),
            _p(r"(적자|손실)[^.]{0,12}(당사|본사)(가)?[^.]{0,6}(보전|보상|책임)",
               "적자를 본사가 보전해 준다는 문구입니다."),
            _p(r"(원금|투자금)(을)?(보장|회수해준다|회수보장)",
               "투자금 회수를 보장하는 문구입니다.", models.SEVERITY_MEDIUM),
            _p(r"(수익|매출)(이|을)?(보장된다|확실하다|틀림없다)",
               "수익이 확실하다고 단정하는 문구입니다."),
        ],
    },
    {
        "id": "hours_bound",
        "title_ko": "영업시간 구속·심야 영업 강제",
        "category": "hours",
        "severity": models.SEVERITY_MEDIUM,
        "why_ko": (
            "영업시간을 본사가 정하고 단축을 허용하지 않는 조항은 점주의 시간과 인건비를 "
            "묶습니다. 법은 심야 영업손실이 나는데도 단축을 허용하지 않거나, 질병 같은 "
            "불가피한 사유의 단축 요구를 막는 행위를 부당한 영업시간 구속으로 봅니다"
            "(법 제12조의3, 시행령 제13조의3)."
        ),
        "fix_ko": (
            "‘영업시간은 가맹점사업자가 상권과 인력 사정을 고려해 정하고, 본사는 손실이 나는 "
            "심야 시간대의 단축 요구를 허용한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": "영업시간을 점주가 조정할 수 있나요? 심야 영업 손실이 날 때 단축 요구 절차가 있나요?",
        "law_refs": ["가맹사업법:제12조의3", "가맹사업법 시행령:제13조의3"],
        "anchors": {
            "가맹사업법:제12조의3": "심야 영업시간대",
            "가맹사업법 시행령:제13조의3": "심야 영업시간대",
        },
        "patterns": [
            _p(r"영업(시간|시각)(은|을)?(당사|본사)가?(정한|지정한|정하는|지시한)",
               "영업시간을 본사가 정하는 문구입니다."),
            _p(r"영업시간(을)?(임의로)?(변경|단축)(할수없|금지|불가)",
               "영업시간 변경·단축을 막는 문구입니다."),
            _p(r"(24시간|연중무휴|심야|새벽)영업(을)?(의무|강제|하여야|실시하여야)",
               "심야·24시간 영업을 의무로 하는 문구입니다."),
            _p(r"(영업시간|휴무일)(을)?(당사|본사)가?(지정|결정)",
               "휴무일까지 본사가 정하는 문구입니다."),
            _p(r"영업시간단축(을)?(허용하지않|불허|인정하지않)",
               "영업시간 단축을 허용하지 않는 문구입니다."),
        ],
    },
    {
        "id": "renewal_restraint",
        "title_ko": "갱신 거절 제한·과도한 경업금지",
        "category": "renewal",
        "severity": models.SEVERITY_MEDIUM,
        "why_ko": (
            "계약이 끝난 뒤 오랫동안 같은 업종을 못 하게 하거나, 본사가 사유를 넓게 잡아 갱신을 "
            "거절할 수 있게 한 조항은 다음 계약을 막습니다. 법은 갱신 요구를 정당한 사유 없이 "
            "거절하지 못하게 하고, 거절할 때는 15일 이내에 사유를 서면으로 통지하게 합니다"
            "(법 제13조)."
        ),
        "fix_ko": (
            "‘계약 갱신은 법이 정한 사유가 있을 때만 거절하고, 거절하면 15일 이내에 사유를 서면으로 "
            "통지한다. 경업금지는 계약기간 중 같은 상권으로 한정한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": "갱신 거절 사유가 구체적으로 적혀 있나요? 계약 종료 후 경업금지 기간과 지역은 얼마인가요?",
        "law_refs": ["가맹사업법:제13조", "가맹사업법 시행령:제14조", "가맹사업법:제12조"],
        "anchors": {"가맹사업법:제13조": "거절하지 못한다"},
        "patterns": [
            _p(r"(계약|계약기간)?(종료|만료|해지)(후|이후)[^.]{0,30}(경업|겸업|동일업종|같은업종)[^.]{0,12}(금지|제한|할수없)",
               "계약이 끝난 뒤 같은 업종 영업을 막는 문구입니다."),
            _p(r"(경업|겸업)금지기간(을|은)?[^.]{0,12}(1|2|3|5|십)년",
               "경업금지 기간을 길게 잡은 문구입니다."),
            _p(r"(계약)?(종료|만료)(후)?[^.]{0,20}(1|2|3|5|십|이|삼|오)년(간|동안)?[^.]{0,16}업종[^.]{0,8}(금지|제한|할수없)",
               "계약 종료 뒤 오랫동안 같은 업종을 막는 문구입니다."),
            _p(r"반경[0-9]+(km|킬로미터|미터|m)(이내)?(동일|같은)?업종(창업|영업)(을|를)?(금지|제한)",
               "반경 안 같은 업종 창업을 막는 문구입니다."),
            _p(r"(갱신|재계약)(을)?(거절할수있|하지않을수있|거부할수있)",
               "갱신을 거절할 수 있다는 문구입니다."),
            _p(r"갱신(요구)?(를)?(할수없|금지|불가)",
               "갱신 요구 자체를 막는 문구입니다.", models.SEVERITY_HIGH),
            _p(r"(전체)?계약기간(을)?(10|십)년(초과|이상)",
               "갱신 요구권 10년 한도를 넘기는 문구입니다."),
        ],
    },
    {
        "id": "excessive_essential_items",
        "title_ko": "필수품목 과다 지정·단가 미공개·차액가맹금 일방 인상",
        "category": "purchase",
        "severity": models.SEVERITY_HIGH,
        "why_ko": (
            "필수품목 목록만 길고 품목별 공급가격·산정기준이 없으면, 점주는 단가를 비교할 기준 "
            "없이 본부가 부르는 값에 사게 됩니다. 법은 본부가 거래를 강제하는 품목의 종류와 "
            "공급 가격 산정방식을 가맹계약서에 적게 하고(법 제11조②12), 정보공개서에는 "
            "필수품목 구입대금 추정액의 상·하한과 차액가맹금(적정한 도매가격을 넘는 대가) "
            "지급액·매출 대비 비율, 품목별 차액가맹금 수취 여부와 주요 품목 공급가격의 "
            "상·하한을 적게 합니다(시행령 별표 1 5.나·6.가). 경영과 무관하거나 필요한 양을 "
            "넘는 물품을 사게 하는 행위는 구입강제로, 특정 거래상대방과의 거래를 강제하는 "
            "행위는 정해진 요건을 갖추지 못하면 거래상대방 구속으로 봅니다"
            "(시행령 별표 2 2.나·3.가)."
        ),
        "fix_ko": (
            "‘필수품목은 품목·수량·공급가격(또는 산정기준)·변경 절차를 별지에 적고, 가격을 "
            "올릴 때는 사전 서면 통지와 협의를 거친다. 가맹사업에 필요하지 않은 일반 공산품은 "
            "가맹점사업자가 자유롭게 구매한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": (
            "필수품목 목록과 품목별 공급가격·산정기준을 서면으로 받았나요? 차액가맹금이 붙는 "
            "품목은 무엇이고, 최근 가격 인상은 언제·얼마였나요?"
        ),
        "law_refs": ["가맹사업법:제11조", "가맹사업법:제12조", ANNEX_UNFAIR, ANNEX_DISCLOSURE],
        "anchors": {
            "가맹사업법:제11조": "공급 가격 산정방식",
            "가맹사업법:제12조": "부당하게 구속하거나 제한",
            ANNEX_UNFAIR: "나. 거래상대방의 구속",
            ANNEX_DISCLOSURE: "차액가맹금",
        },
        "patterns": [
            _p(r"(필수품목|필수물품|지정품목|공급품목)[^.]{0,24}(가격|단가|가격표|산정기준)"
               r"(은|는|을|를|이|가)?(별도|추후|협의하여|협의로|고지|통보|정한다|변경할수있"
               r"|미정|미공개|비공개|공개하지않)",
               "필수품목 가격·산정기준을 나중에 정하거나 알려 주기만 하겠다는 문구입니다."),
            _p(r"(필수품목|지정품목)[^.]{0,40}(일반|시중|마트|온라인|인터넷)[^.]{0,10}"
               r"(공산품|생필품|소모품|잡화)",
               "필수품목에 일반 공산품까지 묶는 문구입니다."),
            _p(r"(일반|시중|마트|온라인)[^.]{0,10}(공산품|생필품|소모품|잡화)[^.]{0,14}"
               r"(필수품목|지정품목|본사지정)",
               "일반 공산품을 필수품목으로 지정하는 문구입니다."),
            _p(r"(차액|마진|리베이트)[^.]{0,12}(가맹금)?[^.]{0,10}"
               r"(일방|임의|사전협의없이|사전통보없이|통보만)(으로)?[^.]{0,10}"
               r"(인상|변경|조정|수취|공제)",
               "차액·마진을 본부가 일방적으로 올리거나 조정하는 문구입니다."),
            _p(r"(공급가격|납품가격|공급단가|단가)(은|는|을|를)?(본사|당사|회사)(가|의)?"
               r"[^.]{0,12}(일방|임의|사전통보없이|사전협의없이)(으로)?[^.]{0,10}"
               r"(인상|변경|조정)",
               "공급단가를 본부가 일방적으로 바꾸는 문구입니다.", models.SEVERITY_MEDIUM),
        ],
    },
    {
        "id": "price_fixing",
        "title_ko": "판매가격 구속·재판매가격 유지 강요",
        "category": "pricing",
        "severity": models.SEVERITY_MEDIUM,
        "why_ko": (
            "본부가 판매가격을 정해 그 가격을 유지하도록 하거나 점주의 가격 결정을 부당하게 "
            "구속하는 행위는 구속조건부 거래(가격의 구속)로 봅니다(법 제12조①2, 시행령 별표 2 "
            "2.가). 같은 목은 판매가격을 정해 따르도록 권장하는 행위와, 가격을 결정·변경할 때 "
            "사전에 협의하도록 하는 행위는 제외하되, 사전협의를 통해 판매가격을 강요하는 "
            "행위는 다시 가격 구속으로 봅니다. 본부가 두는 가격 제한은 정보공개서에도 적어야 "
            "합니다(시행령 별표 1 6.라.3)."
        ),
        "fix_ko": (
            "‘판매가격은 가맹점사업자가 상권과 원가를 고려해 정하고, 본부는 권장가격을 "
            "참고자료로 제시한다. 할인과 가격 변경은 점주가 정한다’로 바꿔 달라고 요청하세요."
        ),
        "ask_ko": (
            "가격을 점주가 바꿀 수 있나요? 할인·가격 변경 때 본부 승인이나 사전협의가 필요한가요? "
            "그 조건이 정보공개서에도 적혀 있나요?"
        ),
        "law_refs": ["가맹사업법:제12조", "가맹사업법 시행령:제13조", ANNEX_UNFAIR,
                     ANNEX_DISCLOSURE],
        "anchors": {
            "가맹사업법:제12조": "부당하게 구속하거나 제한",
            "가맹사업법 시행령:제13조": "별표 2와 같다",
            ANNEX_UNFAIR: "가. 가격의 구속",
            ANNEX_DISCLOSURE: "가격을 정하여 이에 따르도록 권장",
        },
        "patterns": [
            _p(r"(본사|당사|회사)(가|는)?(정한|지정한|결정한|제시한)[^.]{0,10}(판매)?"
               r"(?<!공급)(?<!납품)(?<!도매)(가격)(대로|에따라|으로)[^.]{0,6}(판매|청구|결제)",
               "본부가 정한 가격대로 판매하게 하는 문구입니다."),
            _p(r"(판매가격|판매가|가격)(을|를)?(본사|당사)(가)?(정한|지정한|결정한)"
               r"[^.]{0,6}(유지|준수)(하도록|하여야|해야|한다)",
               "본부가 정한 판매가격을 유지·준수하게 하는 문구입니다."),
            _p(r"(판매가격|판매가|(?<!공급)(?<!납품)(?<!도매)가격)(을|를)?(임의로|마음대로|자유롭게|제멋대로)"
               r"(변경|인하|할인|조정|올리|내리)(할수없|금지|불가|하지못)",
               "판매가격 변경·할인을 막는 문구입니다."),
            _p(r"(할인|할인판매|할인행사|가격할인|프로모션)[^.]{0,8}(금지|불허|할수없|불가|제한)",
               "할인 판매를 금지·제한하는 문구입니다."),
            _p(r"(권장소비자가|권장가격|권장가)(격)?(을|를)?(반드시|의무적으로|필히)"
               r"(준수|따라야|유지)(하여야|해야|한다)",
               "권장가격을 의무로 지키게 하는 문구입니다."),
            _p(r"(판매가격|가격|판매가)(을|를)?(지키지않|위반|어길)[^.]{0,16}"
               r"(해지|위약금|공급중단|계약종료|페널티|패널티)",
               "판매가격을 지키지 않으면 제재한다는 문구입니다."),
            _p(r"(판매가격|판매가|(?<!공급)(?<!납품)(?<!도매)가격)(을|를)?(본사|당사)(가)?(일방|사전통보없이|사전협의없이)"
               r"(으로)?(인상|변경|조정)(한다|할수있다)",
               "판매가격을 본부가 일방적으로 바꾸는 문구입니다."),
            _p(r"(판매가격|(?<!공급)(?<!납품)(?<!도매)가격)(을|를)?(본사|당사|회사)(가)?(정한다|결정한다|지정한다)",
               "판매가격 결정권을 본부가 갖는 문구입니다."),
        ],
    },
]

CONTRACT_RULE_INDEX: Dict[str, Dict[str, Any]] = {
    rule["id"]: rule for rule in CONTRACT_RULES
}

_PCT_RE = re.compile(r"([0-9]{1,3}) ?%")


def _guard_pct_ge_20(matched: str) -> bool:
    """'위약금 … 20%' 처럼 비율이 20% 이상일 때만 신호로 센다."""
    return any(int(value) >= 20 for value in _PCT_RE.findall(matched))


SCAN_GUARDS: Dict[str, Callable[[str], bool]] = {"pct_ge_20": _guard_pct_ge_20}


@lru_cache(maxsize=256)
def _scan_pattern(expr: str) -> "re.Pattern[str]":
    """문구 패턴 — 띄어쓰기 차이를 흡수하려고 공백을 지운 뒤 컴파일한다."""
    return re.compile(re.sub(r"\s+", "", expr))


def _compact_map(text: str) -> Tuple[str, List[int]]:
    """공백을 지운 사본과, 사본 글자 → 원문 위치 표."""
    chars: List[str] = []
    mapping: List[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        chars.append(char)
        mapping.append(index)
    return "".join(chars), mapping


def _scan_bounds(text: str, start: int, end: int, pad: int) -> Tuple[int, int]:
    """매칭 위치 → 문장 경계로 다듬은 [시작, 끝) 구간."""
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    head = text[left:start]
    cut = max(head.rfind("\n"), head.rfind(". "))
    if cut >= 0:
        left += cut + 1
    tail = text[end:right]
    stops = [position for position in (tail.find("\n"), tail.find(". ")) if position >= 0]
    if stops:
        right = end + min(stops) + 1
    return left, right


def _scan_sentence_key(text: str, start: int, end: int) -> str:
    """매칭을 둘러싼 문장 전체 — 같은 문장의 중복 매칭을 하나로 줄이는 열쇠."""
    head = text[:start]
    left = max(head.rfind("\n"), head.rfind(". ")) + 1
    tail = text[end:]
    stops = [position for position in (tail.find("\n"), tail.find(". ")) if position >= 0]
    right = end + (min(stops) + 1 if stops else len(text) - end)
    return re.sub(r"\s+", "", text[left:right]).rstrip(".")


def _scan_quote(text: str, start: int, end: int) -> str:
    """매칭 위치 → 원문 그대로의 인용문(문장 경계에서 자른다)."""
    left, right = _scan_bounds(text, start, end, SCAN_QUOTE_PAD)
    quote = re.sub(r"\s+", " ", text[left:right]).strip()
    if left > 0:
        quote = "…" + quote
    if right < len(text):
        quote = quote + "…"
    return quote


def _scan_hits(rule: Dict[str, Any], text: str, compact: str,
               mapping: List[int]) -> List[Dict[str, Any]]:
    """규칙 1건의 매칭 — 겹치는 매칭은 하나로 줄이고, 부정 문장은 건너뛴다."""
    hits: List[Dict[str, Any]] = []
    for entry in rule["patterns"]:
        pattern = _scan_pattern(entry["expr"])
        for match in pattern.finditer(compact):
            if match.end() <= match.start():
                continue
            start = mapping[match.start()]
            end = mapping[match.end() - 1] + 1
            window = re.sub(r"\s+", "", text[end:end + 6])
            # 매칭 바로 뒤에 부정 표현이 붙으면("부과하지 않는다") 위험 신호로 세지 않는다.
            if any(window.startswith(word) for word in SCAN_NEGATION_TAILS):
                continue
            guard = entry.get("guard") or ""
            if guard and not SCAN_GUARDS[guard](match.group(0)):
                continue
            hits.append({
                "start": start,
                "end": end,
                "matched_ko": match.group(0),
                "severity": entry.get("severity") or rule["severity"],
                "note_ko": entry.get("note_ko") or "",
            })
    hits.sort(key=lambda row: (row["start"], -(row["end"] - row["start"])))
    kept: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    seen_sentences = set()

    def overlaps(row: Dict[str, Any], rows: List[Dict[str, Any]]) -> bool:
        return any(row["start"] < other["end"] and other["start"] < row["end"]
                   for other in rows)

    for hit in hits:
        if overlaps(hit, kept) or overlaps(hit, blocked):
            continue
        key = _scan_sentence_key(text, hit["start"], hit["end"])
        # 한 문장에 여러 패턴이 걸리거나 문구가 반복되면 한 번만 보여 준다.
        if key in seen_sentences:
            blocked.append(hit)
            continue
        seen_sentences.add(key)
        hit["quote_ko"] = _scan_quote(text, hit["start"], hit["end"])
        kept.append(hit)
    return kept


def _scan_input_text(args: Any) -> Tuple[str, str]:
    if isinstance(args, str):
        return (args, "text") if args.strip() else ("", "")
    raw = args if isinstance(args, dict) else {}
    nested = raw.get("document") if isinstance(raw.get("document"), dict) else {}
    for block in (raw, nested):
        for key in SCAN_TEXT_KEYS:
            value = block.get(key)
            if isinstance(value, str) and value.strip():
                return value, key
            if isinstance(value, list) and all(isinstance(row, str) for row in value):
                joined = "\n".join(value)
                if joined.strip():
                    return joined, key
    return "", ""


def scan_contract_text(args: Any) -> Dict[str, Any]:
    """계약서·특약 문구 → 확인이 필요한 문구·근거 조문·요청할 수정 문구.

    0건이어도 '안전·문제없음'을 쓰지 않는다. "제시된 패턴에서 잡히지 않았을 뿐"이라는
    고정 문장(`SCAN_NOT_A_CLEARANCE_KO`)을 항상 붙인다.
    """
    raw_text, source_key = _scan_input_text(args)
    if not raw_text.strip():
        raise ValueError(
            "스캔할 계약서·특약 문구를 주세요. 예: {\"text\": \"인테리어는 당사가 지정한 "
            "업체를 통해서만 시공한다\"}")
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    truncated = len(text) > SCAN_MAX_CHARS
    if truncated:
        text = text[:SCAN_MAX_CHARS]
    compact, mapping = _compact_map(text)
    if len(compact) < SCAN_MIN_CHARS:
        payload = {
            "scanned": {"chars": len(text), "non_space_chars": len(compact),
                        "truncated": False, "source_field": source_key or "text"},
            "verdict": models.scan_verdict_block(models.SCAN_VERDICT_TEXT_NEEDED),
            "counts": {"flagged": 0, "high": 0, "medium": 0, "low": 0,
                       "rules_checked": len(CONTRACT_RULES), "rules_matched": 0},
            "summary_ko": ("스캔할 문구가 너무 짧습니다. 계약서·특약 조항을 한 문장 이상 "
                           "그대로 붙여 넣어 주세요."),
            "findings": [],
            "checks_ko": [
                {"rule_id": rule["id"], "title_ko": rule["title_ko"],
                 "result_ko": "확인하지 못함(문구 부족)", "matched_count": 0}
                for rule in CONTRACT_RULES
            ],
            "not_a_clearance_ko": SCAN_NOT_A_CLEARANCE_KO,
            "questions_ko": list(SCAN_QUESTIONS_KO),
            "request_edits_ko": [],
            "law_basis": law_basis(["가맹사업법:제7조", "가맹사업법:제12조", "가맹사업법:제14조"],
                                    limit=200),
            "law_basis_scope_ko": "문구가 모자라 대조하지 못했습니다.",
            "next_steps": _scan_next_steps(),
            "disclaimer_ko": models.DISCLAIMER_KO,
            "scope_limits_ko": models.SCOPE_LIMITS_KO + [
                "문구 스캔은 정규식 규칙으로 표시된 패턴만 찾습니다. 문장의 맥락·예외 조항·"
                "별지 특약 전체를 해석하지 않습니다.",
            ],
        }
        return payload

    findings: List[Dict[str, Any]] = []
    checks: List[Dict[str, Any]] = []
    extra_matches = 0
    matched_rules = 0
    refs: List[str] = []
    anchors: Dict[str, str] = {}
    order = {severity: index for index, severity in enumerate(models.SEVERITY_ORDER)}
    for rule in CONTRACT_RULES:
        hits = _scan_hits(rule, text, compact, mapping)
        shown = hits[:SCAN_MAX_FINDINGS_PER_RULE]
        extra_matches += max(0, len(hits) - len(shown))
        checks.append({
            "rule_id": rule["id"], "title_ko": rule["title_ko"],
            "category": rule["category"],
            "category_label_ko": models.CATEGORY_LABELS_KO.get(rule["category"], ""),
            "result_ko": (f"문구 {len(hits)}건 확인" if hits else "제시된 패턴에서 잡힌 문구 없음"),
            "matched_count": len(hits),
        })
        if not hits:
            continue
        matched_rules += 1
        for key in rule["law_refs"]:
            refs.append(key)
        for key, anchor in (rule.get("anchors") or {}).items():
            anchors.setdefault(key, anchor)
        for hit in shown:
            findings.append({
                "rule_id": rule["id"],
                "title_ko": rule["title_ko"],
                "category": rule["category"],
                "category_label_ko": models.CATEGORY_LABELS_KO.get(rule["category"], ""),
                "severity": hit["severity"],
                "severity_label_ko": models.severity_label(hit["severity"]),
                "matched_text_ko": hit["quote_ko"],
                "matched_exact_ko": hit["matched_ko"],
                "offset": hit["start"],
                "note_ko": hit["note_ko"],
                "why_ko": rule["why_ko"],
                "request_edit_ko": rule["fix_ko"],
                "ask_ko": rule["ask_ko"],
                "law_refs": list(rule["law_refs"]),
                "law_refs_ko": [law_label(key) for key in rule["law_refs"]],
            })
    findings.sort(key=lambda row: (order.get(row["severity"], 9), row["offset"]))
    if len(findings) > SCAN_MAX_FINDINGS:
        extra_matches += len(findings) - SCAN_MAX_FINDINGS
        findings = findings[:SCAN_MAX_FINDINGS]
    high = sum(1 for row in findings if row["severity"] == models.SEVERITY_HIGH)
    medium = sum(1 for row in findings if row["severity"] == models.SEVERITY_MEDIUM)
    low = sum(1 for row in findings if row["severity"] == models.SEVERITY_LOW)
    verdict_code = (models.SCAN_VERDICT_FLAGGED if findings else models.SCAN_VERDICT_NO_MATCH)
    if findings:
        parts = [f"입력한 문구에서 계약 전에 확인이 필요한 문구 {len(findings)}건을 찾았습니다."]
        if high:
            parts.append(f"그중 위험 높음 {high}건은 계약·입금 전에 먼저 확인하세요.")
        parts.append("항목마다 본부에 요청할 수 있는 수정 문구를 함께 적었습니다.")
        summary = " ".join(parts)
    else:
        summary = (f"입력한 문구에서는 제시된 {len(CONTRACT_RULES)}개 유형과 겹치는 문구가 "
                   "없었습니다. 이것은 원문 전체를 검토한 결과가 아닙니다.")
    request_edits = []
    seen_rules = set()
    for row in findings:
        if row["rule_id"] in seen_rules:
            continue
        seen_rules.add(row["rule_id"])
        request_edits.append({"rule_id": row["rule_id"], "title_ko": row["title_ko"],
                              "request_ko": row["request_edit_ko"]})
    if findings:
        basis_refs, basis_limit, basis_scope = refs, 320, "확인된 문구의 근거 조문입니다."
    else:
        basis_refs = [key for rule in CONTRACT_RULES for key in rule["law_refs"]]
        basis_limit = 200
        basis_scope = ("위험 문구가 확인되지 않아, 제시된 유형을 대조한 근거 조문을 실었습니다. "
                       "조문이 있다는 것만으로 이 계약이 적법하다는 뜻이 아닙니다.")
    questions = list(SCAN_QUESTIONS_KO)
    for row in findings:
        if row["ask_ko"] and row["ask_ko"] not in questions:
            questions.append(row["ask_ko"])
    payload = {
        "scanned": {
            "chars": len(text), "non_space_chars": len(compact),
            "truncated": truncated, "source_field": source_key or "text",
            "max_chars": SCAN_MAX_CHARS,
        },
        "verdict": models.scan_verdict_block(verdict_code),
        "counts": {
            "flagged": len(findings), "high": high, "medium": medium, "low": low,
            "rules_checked": len(CONTRACT_RULES), "rules_matched": matched_rules,
            "more_matches": extra_matches,
        },
        "summary_ko": summary,
        "findings": findings,
        "checks_ko": checks,
        "not_a_clearance_ko": SCAN_NOT_A_CLEARANCE_KO,
        "questions_ko": questions[:8],
        "request_edits_ko": request_edits,
        "law_basis": law_basis(basis_refs, anchors if findings else None, limit=basis_limit),
        "law_basis_scope_ko": basis_scope,
        "next_steps": _scan_next_steps(),
        "disclaimer_ko": models.DISCLAIMER_KO,
        "scope_limits_ko": models.SCOPE_LIMITS_KO + [
            "문구 스캔은 정규식 규칙으로 표시된 패턴만 찾습니다. 문장의 맥락·예외 조항·"
            "별지 특약 전체를 해석하지 않습니다.",
        ],
    }
    return payload


def _scan_next_steps() -> List[Dict[str, str]]:
    return [
        {"title_ko": "문구를 본부에 그대로 보내 수정 요청",
         "detail_ko": "결과의 인용 문구와 요청 문구를 복사해 서면(메일)으로 남기세요.",
         "url": ""},
        {"title_ko": "정보공개서와 특약 대조",
         "detail_ko": "등록된 정보공개서와 계약서·특약의 내용이 같은지 항목별로 확인하세요.",
         "url": DISCLOSURE_PORTAL},
        {"title_ko": "가맹거래사·변호사 검토",
         "detail_ko": "특약 전체를 보여 주고 계약 전에 검토받으세요. 스캔은 그 검토를 대신하지 않습니다.",
         "url": ""},
    ]
