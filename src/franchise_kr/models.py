"""판정 등급·표현 상수 — 코드·웹·테스트가 같은 표를 쓴다.

이 서비스는 **확정 판정을 하지 않습니다**. 조건 판정에는 세 가지 표현만 씁니다.
- `check_likely`  확인이 필요한 위험 신호가 뚜렷함 (초록불 아님)
- `info_needed`   입력이 모자라 지금은 판정을 보류함
- `low_risk`      제시된 조건에서는 뚜렷한 위험 신호가 보이지 않음 (확정 아님)

`high`/`medium`/`low` 는 개별 위험 신호의 무게이고, `check_likely` 와 다른 축입니다.

계약서·특약 문구 스캔은 `scan_flagged` / `scan_no_match` / `scan_text_needed` 세 가지를 쓰고,
0건이어도 '안전·문제없음'이라고 쓰지 않습니다(아래 `SCAN_VERDICT_*`).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

VERDICT_CHECK = "check_likely"
VERDICT_INFO = "info_needed"
VERDICT_LOW = "low_risk"
VERDICT_ORDER = (VERDICT_CHECK, VERDICT_INFO, VERDICT_LOW)

VERDICT_LABELS_KO = {
    VERDICT_CHECK: "확인 필요 신호 있음",
    VERDICT_INFO: "정보 부족 — 되물어볼 것 있음",
    VERDICT_LOW: "뚜렷한 위험 신호 없음",
}

VERDICT_ONELINE_KO = {
    VERDICT_CHECK: "계약·입금 전에 반드시 확인해야 할 신호가 있습니다. 확정 판정은 아닙니다.",
    VERDICT_INFO: "지금 가진 정보로는 판정을 보류합니다. 아래 질문에 답하면 판정이 좁혀집니다.",
    VERDICT_LOW: "제시된 조건에서는 법이 금지하는 신호가 보이지 않습니다. 서류 원문 확인은 따로 필요합니다.",
}

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_ORDER = (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)
SEVERITY_LABELS_KO = {
    SEVERITY_HIGH: "위험 높음",
    SEVERITY_MEDIUM: "주의",
    SEVERITY_LOW: "참고",
}

CATEGORY_LABELS_KO = {
    "cooling_off": "숙고기간·계약 절차",
    "revenue": "매출·수익 정보",
    "payment": "가맹금·예치",
    "interior": "인테리어·설비",
    "territory": "영업지역",
    "disclosure": "정보공개서·이력",
    "penalty": "위약금·손해배상",
    "purchase": "구입강제·판매목표",
    "renewal": "계약갱신",
    "termination": "계약해지",
    "advertising": "광고·판촉비",
    "pricing": "가격 결정",
    "registration": "정보공개서 등록",
    "hours": "영업시간 구속",
}

# 계약서·특약 문구 스캔의 세 가지 결론 — '안전'도 '문제없음'도 쓰지 않는다.
SCAN_VERDICT_FLAGGED = "scan_flagged"
SCAN_VERDICT_NO_MATCH = "scan_no_match"
SCAN_VERDICT_TEXT_NEEDED = "scan_text_needed"
SCAN_VERDICT_ORDER = (SCAN_VERDICT_FLAGGED, SCAN_VERDICT_NO_MATCH, SCAN_VERDICT_TEXT_NEEDED)
SCAN_VERDICT_LABELS_KO = {
    SCAN_VERDICT_FLAGGED: "확인이 필요한 문구 있음",
    SCAN_VERDICT_NO_MATCH: "제시된 패턴에서 잡힌 문구 없음",
    SCAN_VERDICT_TEXT_NEEDED: "스캔할 문구가 더 필요함",
}
SCAN_VERDICT_ONELINE_KO = {
    SCAN_VERDICT_FLAGGED: "계약 전에 본부와 문구 수정을 이야기할 항목이 있습니다. 확정 판정은 아닙니다.",
    SCAN_VERDICT_NO_MATCH: "제시된 패턴과 겹치는 문구가 없었습니다. 원문 전체 검토를 대신하지 않습니다.",
    SCAN_VERDICT_TEXT_NEEDED: "스캔할 문구가 너무 짧습니다. 특약·계약서 조항을 그대로 붙여 넣어 주세요.",
}

DISCLAIMER_KO = (
    "본 결과는 확정 판정이 아닙니다. 입력한 조건과 공개 법령 조문을 대조한 참고용 사전 점검이며, "
    "위법 여부나 계약의 효력을 확정하지 않습니다. 계약 전 공정거래위원회 가맹사업정보제공시스템의 "
    "등록 정보공개서 원문과 변호사·가맹거래사 자문으로 확인하세요."
)

SCOPE_LIMITS_KO = [
    "판정은 입력한 항목에 대해서만 합니다. 비어 있는 항목은 '모름'으로 두고 추정하지 않습니다.",
    "법 조문 대조는 법제처 OPEN API 로 받은 가맹사업법·시행령 조문을 근거로 합니다.",
    "브랜드 정보는 공정거래위원회 가맹정보 오픈API 승인 데이터셋으로 답합니다(브랜드 목록 전체 페이지를 "
    "받아 만든 색인 → 실시간 API → 내장 샘플 순). 아직 승인되지 않은 데이터셋 항목은 비워 두고 "
    "apply_urls 로 활용신청 주소를 안내합니다.",
    "표시된 금액은 사용자가 적은 값이며, 실제 창업비용·매출은 본부와 현장에서 다시 확인해야 합니다.",
    "이 서비스는 계약서 검토·법률 자문·신고 대행을 하지 않습니다.",
]

SCHEMA_VERSION = "1.0"


def verdict_block(code: str) -> Dict[str, str]:
    return {
        "code": code,
        "label_ko": VERDICT_LABELS_KO.get(code, code),
        "one_line_ko": VERDICT_ONELINE_KO.get(code, ""),
    }


def scan_verdict_block(code: str) -> Dict[str, str]:
    return {
        "code": code,
        "label_ko": SCAN_VERDICT_LABELS_KO.get(code, code),
        "one_line_ko": SCAN_VERDICT_ONELINE_KO.get(code, ""),
    }


def severity_label(severity: Optional[str]) -> str:
    return SEVERITY_LABELS_KO.get(str(severity or ""), "")


def format_krw(value: Any) -> str:
    """원 단위 숫자를 '1억 2,300만원' 처럼 읽기 쉬운 형태로. 값이 없으면 빈 문자열."""
    try:
        amount = int(round(float(str(value).replace(",", ""))))
    except (TypeError, ValueError):
        return ""
    if amount == 0:
        return "0원"
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    eok, rest = divmod(amount, 100_000_000)
    man, won = divmod(rest, 10_000)
    parts = []
    if eok:
        parts.append(f"{eok:,}억")
    if man:
        parts.append(f"{man:,}만")
    if won and not eok:
        parts.append(f"{won:,}")
    text = " ".join(parts) if parts else f"{amount:,}"
    if won and eok:
        text += f" {won:,}"
    return f"{sign}{text}원"
