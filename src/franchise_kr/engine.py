"""가맹 조건 → 위험 신호 판정 엔진(결정론, 표준 라이브러리만).

설계 원칙
---------
1. **추측하지 않는다**: 입력하지 않은 항목은 '모름'으로 두고, 그 항목에 해당하는 질문을
   돌려준다. 모름을 '괜찮다'로 바꾸지 않는다.
2. **확정하지 않는다**: 결과는 `check_likely` / `info_needed` / `low_risk` 세 가지뿐이고,
   모든 응답에 면책과 근거 조문이 붙는다.
3. **근거를 붙인다**: 위험 신호마다 법제처 OPEN API 로 받은 가맹사업법·시행령 조문을
   `law-verification.json` 에서 찾아 인용한다. 조문 키가 없으면 판정을 만들지 않는다(테스트로 강제).

함정 코퍼스는 `traps.json`(15건)에 있고, 각 케이스의 판정 함수는 이 파일 아래
`EVALUATORS` 에 1:1로 대응한다.
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


def law_basis(keys: List[str], anchors: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
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
        # 별표는 키 안에 제목이 이미 들어 있어 두 번 쓰지 않는다.
        label = key if (not title or title in key) else f"{key} · {title}"
        out.append({
            "key": key,
            "label_ko": label,
            "law": record.get("law"),
            "article": record.get("article") or record.get("title"),
            "title": record.get("title"),
            # 별표에는 시행일이 따로 없어 그 법령의 시행일을 쓴다(빈 문자열 노출 방지).
            "effective_on": record.get("effective_on") or law_row.get("effective_on"),
            "excerpt_ko": law_excerpt(key, anchor=anchors.get(key, "")),
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
