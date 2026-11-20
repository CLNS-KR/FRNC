"""MCP/JSON API 툴 6종.

| 툴 | 하는 일 |
|---|---|
| `check_franchise_risk` | 가맹 조건 → 위험 신호·판정·체크리스트·법 조문·지원금 연결 |
| `lookup_brand_disclosure` | 브랜드 1건 정보공개서 요약(공정위 API 실시간 또는 내장 샘플) |
| `compare_franchise_terms` | 두 프랜차이즈(또는 두 제안 조건) 비교 |
| `list_risk_cases` | 함정 코퍼스 15건 목록(조문 대조 여부 포함) |
| `get_law_article` | 실조회한 가맹사업법·시행령 조문 원문 |
| `get_service_meta` | 판정 등급·축·법령·실시간 API 승인 상태·개인정보 설계 |

공통 원칙
---------
- 모든 응답에 `checked_at`, `schema_version`, `disclaimer_ko` 가 붙습니다.
- 판정은 세 가지(`check_likely`/`info_needed`/`low_risk`)이고 확정 판정이 아닙니다.
- 입력값(브랜드·금액)은 응답의 `terms_used` 에만 되비추고 **서버에 저장하지 않습니다**.
  예외는 결과가 0건인 브랜드 조회어뿐이며, 개인식별 요소를 지운 뒤 익명 횟수로만 남깁니다
  (`usage.sanitize_query`, 0건은 '문제없음·안전'이 아닙니다).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import engine, live_api, models, usage
from .version import (DISCLOSURE_PORTAL, GRANT_URL, SERVICE_NAME, SERVICE_SUBTITLE_EN,
                      SERVICE_TAGLINE, SERVICE_TITLE_KO, SERVICE_URL, __version__)

SCHEMA_VERSION = models.SCHEMA_VERSION
VERDICT_DEFINITIONS = [
    {"code": models.VERDICT_CHECK, "label_ko": models.VERDICT_LABELS_KO[models.VERDICT_CHECK],
     "definition_ko": "입력한 조건에서 법이 금지하는 전형적 패턴(숙고기간 미준수, 본사 계좌 송금, "
                      "인테리어 강제 등)이 하나라도 확인됨. 확정 판정이 아님."},
    {"code": models.VERDICT_INFO, "label_ko": models.VERDICT_LABELS_KO[models.VERDICT_INFO],
     "definition_ko": "위험 신호는 없지만 핵심 항목이 비어 있음. 비어 있는 항목을 '괜찮다'로 "
                      "바꾸지 않고 질문을 돌려줌."},
    {"code": models.VERDICT_LOW, "label_ko": models.VERDICT_LABELS_KO[models.VERDICT_LOW],
     "definition_ko": "8개 핵심 항목이 모두 채워졌고 그 안에서 위험 신호가 없음. 확정 아님."},
]


def _envelope(tool: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload.setdefault("checked_at", engine.now_iso())
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("disclaimer_ko", models.DISCLAIMER_KO)
    payload.setdefault("scope_limits_ko", models.SCOPE_LIMITS_KO)
    return {"tool": tool, "ok": True, "result": payload}


def _meta_block() -> Dict[str, Any]:
    from . import guides

    summary = live_api.dataset_summary()
    return {
        "service": SERVICE_NAME,
        "version": __version__,
        "brand": {
            "name": SERVICE_NAME,
            "title_ko": SERVICE_TITLE_KO,
            "tagline": SERVICE_TAGLINE,
            "subtitle_en": SERVICE_SUBTITLE_EN,
            "url": SERVICE_URL,
        },
        "data_state": "sample" if summary["counts"]["approved"] == 0 else "live",
        "live_api": live_api.health_block(),
        "law": engine.law_meta(),
        "trap_cases": len(engine.trap_cases()),
        "privacy": {
            "stores_inputs": False,
            "stores_ip": False,
            "stores_user_agent": False,
            "stores_cookies": False,
            "stores_brand_names": "zero_result_only",
            "identity_fields": [],
            "note_ko": ("브랜드명·금액·조건은 요청 처리 중에만 쓰고 저장하지 않습니다. "
                        "다만 결과가 0건인 브랜드 조회어는 전화번호·이메일·숫자를 지운 뒤 "
                        "익명 횟수로만 남깁니다(0건은 '문제없음·안전'이 아닙니다). "
                        "문의 폼에 직접 적은 연락처만 회신 목적으로 별도 보관합니다."),
        },
        "disclosure_portal": DISCLOSURE_PORTAL,
        "grant_link": GRANT_URL,
        "python": "표준 라이브러리만 사용(pip 의존성 0)",
        "guides": {
            "index": "/guides/",
            "count": len(guides.GUIDES),
            "items": [
                {"slug": guide["slug"], "topic": guide["topic"],
                 "question": guide["question"], "path": f"/guides/{guide['slug']}"}
                for guide in guides.GUIDES
            ],
        },
        "endpoints": {
            "web": "/",
            "guides": "/guides/",
            "healthz": "/healthz",
            "meta": "/v1/meta",
            "stats": "/v1/stats",
            "tools": "/v1/tools/{tool}",
            "mcp": "/mcp",
            "inquiry": "/v1/inquiry",
            "llms": "/llms.txt",
            "server_card": "/.well-known/mcp/server-card.json",
        },
    }


# ---------------------------------------------------------------------------
# 툴 1 — check_franchise_risk
# ---------------------------------------------------------------------------
def tool_check_franchise_risk(args: Dict[str, Any], store: Any = None) -> Dict[str, Any]:
    result = engine.check_franchise_risk(args)
    result["meta"] = _meta_block()
    return _envelope("check_franchise_risk", result)


# ---------------------------------------------------------------------------
# 툴 2 — lookup_brand_disclosure
# ---------------------------------------------------------------------------
def tool_lookup_brand_disclosure(args: Dict[str, Any], store: Any = None) -> Dict[str, Any]:
    brand = str(args.get("brand_name") or args.get("brand") or args.get("query") or "").strip()
    code = str(args.get("brand_code") or args.get("brandMnno") or "").strip()
    year = args.get("year")
    try:
        year_value: Optional[int] = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("year 는 연도 숫자(예: 2024)로 주세요.")
    if not brand and not code:
        raise ValueError("brand_name 또는 brand_code 중 하나가 필요합니다.")
    result = live_api.lookup(brand, code, year_value)
    result["meta"] = _meta_block()
    result["next_questions"] = _lookup_questions(result)
    return _envelope("lookup_brand_disclosure", result)


def _lookup_questions(result: Dict[str, Any]) -> List[str]:
    status = result.get("status")
    if status == "not_approved":
        return [
            "공공데이터포털에서 가맹정보 API 활용신청을 승인받았나요?",
            "가맹사업정보제공시스템(franchise.ftc.go.kr)에서 정보공개서 등록번호를 확인했나요?",
        ]
    if status == "not_found":
        return ["브랜드명을 더 짧게 넣거나 브랜드관리번호(BRD_...)로 조회해 보세요."]
    if status in ("live", "sample"):
        return [
            "최근 3년 가맹점 변동(신규·계약종료·계약해지)을 확인했나요?",
            "인근 가맹점 2~3곳에서 실제 매출 상황을 들었나요?",
        ]
    return ["공정거래위원회 API 승인 상태를 확인했나요?"]


# ---------------------------------------------------------------------------
# 툴 3 — compare_franchise_terms
# ---------------------------------------------------------------------------
def tool_compare_franchise_terms(args: Dict[str, Any], store: Any = None) -> Dict[str, Any]:
    result = engine.compare_franchise_terms(args)
    result["meta"] = _meta_block()
    return _envelope("compare_franchise_terms", result)


# ---------------------------------------------------------------------------
# 툴 4 — list_risk_cases
# ---------------------------------------------------------------------------
def tool_list_risk_cases(args: Dict[str, Any], store: Any = None) -> Dict[str, Any]:
    result = engine.list_risk_cases()
    severity = str(args.get("severity") or "").strip()
    category = str(args.get("category") or "").strip()
    keyword = str(args.get("keyword") or "").strip()
    cases = result["cases"]
    if severity in models.SEVERITY_ORDER:
        cases = [case for case in cases if case["severity"] == severity]
    if category:
        cases = [case for case in cases if case["category"] == category]
    if keyword:
        cases = [case for case in cases if keyword in case["title_ko"] or keyword in case["ask_ko"]]
    payload = {
        "count": len(cases),
        "cases": cases,
        "filters": {"severity": severity or None, "category": category or None,
                    "keyword": keyword or None},
        "categories": models.CATEGORY_LABELS_KO,
        "severities": models.SEVERITY_LABELS_KO,
        "law": engine.law_meta(),
        "note_ko": result["note_ko"],
        "meta": _meta_block(),
    }
    return _envelope("list_risk_cases", payload)


# ---------------------------------------------------------------------------
# 툴 5 — get_law_article
# ---------------------------------------------------------------------------
def tool_get_law_article(args: Dict[str, Any], store: Any = None) -> Dict[str, Any]:
    result = engine.search_law_article(args.get("article") or args.get("query") or "")
    if not result.get("ok"):
        return {"tool": "get_law_article", "ok": False,
                "error": result.get("error", "not_found"),
                "message": result.get("message_ko") or "조문을 찾지 못했습니다.",
                "available": result.get("available") or []}
    payload = {
        "key": result["key"],
        "law": result["law"],
        "title": result["title"],
        "effective_on": result["effective_on"],
        "text": result["text"],
        "paragraphs": result["paragraphs"],
        "source_url": result["source_url"],
        "law_meta": engine.law_meta(),
        "meta": _meta_block(),
    }
    return _envelope("get_law_article", payload)


# ---------------------------------------------------------------------------
# 툴 6 — get_service_meta
# ---------------------------------------------------------------------------
def tool_get_service_meta(args: Dict[str, Any], store: Any = None) -> Dict[str, Any]:
    meta = _meta_block()
    payload = {
        "meta": meta,
        "verdicts": VERDICT_DEFINITIONS,
        "risk_levels": [
            {"code": code, "label_ko": models.SEVERITY_LABELS_KO[code]} for code in
            models.SEVERITY_ORDER
        ],
        "key_axes": [
            {"axis": axis, "question_ko": engine.MISSING_AXIS_QUESTIONS.get(axis, "")}
            for axis in engine.KEY_AXES
        ],
        "inputs": {
            "money": list(engine.MONEY_FIELDS),
            "numbers": list(engine.NUMBER_FIELDS),
            "booleans": list(engine.BOOL_FIELDS),
            "enums": {field: list(options) for field, options in engine.ENUM_FIELDS.items()},
            "enums_ko": {
                "payment_route": engine.PAYMENT_LABELS_KO,
                "interior_designated": engine.INTERIOR_LABELS_KO,
                "territory": engine.TERRITORY_LABELS_KO,
                "ad_cost_burden": engine.AD_LABELS_KO,
            },
        },
        "trap_cases": len(engine.trap_cases()),
        "law": engine.law_meta(),
        "data_sources": live_api.dataset_summary(),
        "guides": meta["guides"],
        "zero_result_notice_ko": live_api.ZERO_RESULT_NOTICE_KO,
        "grant_link": GRANT_URL,
        "disclosure_portal": DISCLOSURE_PORTAL,
    }
    return _envelope("get_service_meta", payload)


# ---------------------------------------------------------------------------
# 레지스트리
# ---------------------------------------------------------------------------
TOOL_DEFS: List[Dict[str, Any]] = [
    {
        "name": "check_franchise_risk",
        "title_ko": "프랜차이즈 리스크 체크",
        "description_ko": (
            "브랜드·업종·가맹비·인테리어 비용과 본부가 제시한 조건(정보공개서 수령 후 경과일, "
            "예상매출 서면 교부, 가맹금 예치·납부 방식, 인테리어 지정, 영업지역, 폐점률, "
            "법 위반 이력 등)을 받아 위험 신호·확인 체크리스트·가맹사업법 조문 근거를 돌려줍니다. "
            "판정은 `check_likely`(확인 필요 신호 있음) / `info_needed`(정보 부족) / "
            "`low_risk`(뚜렷한 위험 신호 없음) 세 가지이며 확정 판정이 아닙니다. "
            "입력하지 않은 항목은 '모름'으로 두고 `questions_ko` 로 되물어봅니다. "
            "창업비용을 낸 뒤 받을 수 있는 지원금은 GRNT(https://grnt-kr.onrender.com/)에서 확인하도록 "
            "`startup_support` 에 링크를 함께 돌려줍니다."
        ),
        "handler": tool_check_franchise_risk,
        "input_schema": {
            "type": "object",
            "properties": {
                "brand_name": {"type": "string", "description": "브랜드명(예: 샘플치킨)"},
                "brand_code": {"type": "string", "description": "브랜드관리번호(아는 경우)"},
                "industry": {"type": "string", "description": "업종(예: 치킨, 커피, 편의점)"},
                "franchise_fee_krw": {"type": ["integer", "string"],
                                      "description": "가맹비(원 또는 '3,300만원')"},
                "education_fee_krw": {"type": ["integer", "string"], "description": "가맹교육비"},
                "deposit_krw": {"type": ["integer", "string"], "description": "가맹보증금"},
                "interior_krw": {"type": ["integer", "string"], "description": "인테리어 비용"},
                "equipment_krw": {"type": ["integer", "string"], "description": "설비·집기 비용"},
                "other_krw": {"type": ["integer", "string"], "description": "기타 비용"},
                "total_investment_krw": {"type": ["integer", "string"],
                                         "description": "총 창업비용(없으면 항목 합계로 계산)"},
                "royalty_rate_pct": {"type": "number", "description": "월 로열티 비율(%)"},
                "disclosure_days_before": {
                    "type": "integer",
                    "description": "정보공개서를 받은 날부터 계약(예정)일까지 지난 일수. 당일이면 0.",
                },
                "contract_doc_days_before": {
                    "type": "integer", "description": "가맹계약서 초안을 받은 날부터 경과일",
                },
                "advisor_reviewed": {"type": "boolean",
                                     "description": "변호사·가맹거래사 자문 여부(자문 시 숙고기간 7일)"},
                "payment_route": {
                    "type": "string",
                    "enum": list(engine.ENUM_FIELDS["payment_route"]),
                    "description": "가맹금 납부 방식: escrow(예치기관) · insurance(피해보상보험) · "
                                   "hq_account(본사 계좌 직접 송금) · none(예치·보험 없음) · unknown",
                },
                "revenue_claim_ko": {"type": "string",
                                     "description": "본부가 한 매출 관련 말(예: '월 5천 보장')"},
                "revenue_written": {"type": "boolean",
                                    "description": "매출 관련 정보를 서면으로 받았는지"},
                "revenue_estimate_doc": {"type": "boolean",
                                         "description": "예상매출액 산정서(범위·산출근거)를 받았는지"},
                "interior_designated": {
                    "type": "string",
                    "enum": list(engine.ENUM_FIELDS["interior_designated"]),
                    "description": "인테리어 지정: free(자유) · partial(일부 지정) · forced(100% 강제) · unknown",
                },
                "supplier_designated": {"type": "boolean", "description": "거래처(물품 공급처) 지정 여부"},
                "mandatory_purchase": {"type": "boolean", "description": "필수품목 구입 의무 여부"},
                "sales_target": {"type": "boolean", "description": "판매목표 강제 여부"},
                "price_fixing": {"type": "boolean", "description": "본부가 판매가격을 정하고 지키게 하는지"},
                "ad_cost_burden": {
                    "type": "string",
                    "enum": list(engine.ENUM_FIELDS["ad_cost_burden"]),
                    "description": "광고·판촉비 부담: shared(분담) · franchisee_forced(점주 의무) · none · unknown",
                },
                "territory": {
                    "type": "string",
                    "enum": list(engine.ENUM_FIELDS["territory"]),
                    "description": "영업지역: exclusive(독점 기재) · defined(기재만) · none(없음) · unknown",
                },
                "renewal_years": {"type": "number",
                                  "description": "최초 계약을 포함한 전체 계약기간(년)"},
                "renewal_refused": {"type": "boolean", "description": "갱신 거절 사유가 넓은지"},
                "termination_grace_months": {"type": "number",
                                             "description": "본부의 해지 시 유예기간(개월)"},
                "penalty_ratio_pct": {"type": "number",
                                      "description": "중도해지 위약금 비율(총투자 대비 %)"},
                "penalty_krw": {"type": ["integer", "string"],
                                "description": "위약금 액수(비율 대신 줄 때)"},
                "closure_rate_3y_pct": {"type": "number", "description": "최근 3년 폐점률(%)"},
                "legal_violation": {"type": "boolean",
                                    "description": "본부의 공정위 시정조치·과징금·형벌선고 이력 여부"},
                "disclosure_registered": {"type": "boolean",
                                          "description": "등록 정보공개서를 확인했는지"},
                "stores_count": {"type": "integer", "description": "가맹점 수"},
                "avg_sales_krw": {"type": ["integer", "string"], "description": "가맹점 평균매출액"},
            },
            "required": [],
        },
    },
    {
        "name": "lookup_brand_disclosure",
        "title_ko": "브랜드 정보공개서 요약",
        "description_ko": (
            "브랜드명 또는 브랜드관리번호로 공정거래위원회 가맹정보 데이터를 조회해 "
            "가맹본부·업종·가맹사업 개시일·가맹점 수·계약종료/해지·평균매출액·정보공개서 등록번호를 "
            "요약합니다. 이 키는 가맹정보 API 활용신청이 승인되지 않아 지금은 내장 **샘플**로 "
            "응답하며 `data_state` 와 `apply_urls`(활용신청 주소)를 함께 돌려줍니다. "
            "승인 전에는 화면의 구조만 참고하고, 실제 값은 가맹사업정보제공시스템에서 확인하세요."
        ),
        "handler": tool_lookup_brand_disclosure,
        "input_schema": {
            "type": "object",
            "properties": {
                "brand_name": {"type": "string", "description": "브랜드명(부분 일치)"},
                "brand_code": {"type": "string", "description": "브랜드관리번호"},
                "year": {"type": "integer", "description": "가맹사업 기준년도(기본: 최근 3개년 시도)"},
            },
            "required": [],
        },
    },
    {
        "name": "compare_franchise_terms",
        "title_ko": "두 프랜차이즈 조건 비교",
        "description_ko": (
            "두 프랜차이즈(또는 두 제안 조건)를 총투자·가맹비·인테리어·보증금·로열티·숙고기간·"
            "위약금·폐점률·해지 유예기간·가맹금 납부·영업지역으로 나란히 비교하고, 각 조건의 "
            "위험 신호와 차이를 돌려줍니다. `a`·`b` 객체에 `check_franchise_risk` 와 같은 필드를 "
            "넣으면 됩니다. 어느 쪽이 낫다고 단정하지 않고 차이만 정리합니다."
        ),
        "handler": tool_compare_franchise_terms,
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "object", "description": "첫 번째 조건(브랜드명 + 조건 필드)"},
                "b": {"type": "object", "description": "두 번째 조건(브랜드명 + 조건 필드)"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "list_risk_cases",
        "title_ko": "리스크 케이스 목록",
        "description_ko": (
            "가맹사업법 함정 코퍼스 15건을 위험도·분류·키워드로 걸러 봅니다. 각 케이스에 "
            "왜 위험한지, 무엇을 물어야 하는지, 어떤 조문과 대조했는지(`law_verified`)가 붙습니다."
        ),
        "handler": tool_list_risk_cases,
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": list(models.SEVERITY_ORDER)},
                "category": {"type": "string",
                             "enum": sorted(models.CATEGORY_LABELS_KO.keys())},
                "keyword": {"type": "string", "description": "제목·질문에 포함된 말"},
            },
            "required": [],
        },
    },
    {
        "name": "get_law_article",
        "title_ko": "가맹사업법 조문 조회",
        "description_ko": (
            "법제처 OPEN API 로 실조회해 저장한 가맹사업법·시행령 조문 원문을 돌려줍니다. "
            "예: '제7조'(정보공개서 제공·14일 숙고기간), '제6조의5'(가맹금 예치), "
            "'제9조'(허위·과장·예상매출액 산정서), '제12조의4'(영업지역). "
            "시행령은 '시행령 제13조' 처럼 넣습니다."
        ),
        "handler": tool_get_law_article,
        "input_schema": {
            "type": "object",
            "properties": {
                "article": {"type": "string", "description": "조문 번호 또는 키"},
            },
            "required": ["article"],
        },
    },
    {
        "name": "get_service_meta",
        "title_ko": "서비스·데이터 상태",
        "description_ko": (
            "판정 등급 정의, 핵심 8개 축과 질문, 입력 필드, 함정 코퍼스 수, 법령 실조회 상태, "
            "공정위 API 승인 상태와 활용신청 주소, 개인정보 설계를 돌려줍니다."
        ),
        "handler": tool_get_service_meta,
        "input_schema": {"type": "object", "properties": {}},
    },
]

TOOL_INDEX: Dict[str, Dict[str, Any]] = {definition["name"]: definition for definition in TOOL_DEFS}
TOOL_ANNOTATIONS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}


def mcp_tools() -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    for definition in TOOL_DEFS:
        tools.append({
            "name": definition["name"],
            "title": definition["title_ko"],
            "description": definition["description_ko"],
            "inputSchema": definition["input_schema"],
            "annotations": {**TOOL_ANNOTATIONS, "title": definition["title_ko"]},
        })
    return tools


def mcp_manifest() -> Dict[str, Any]:
    return {
        "name": SERVICE_NAME.lower(),
        "version": f"{SERVICE_NAME.lower()}/{__version__}",
        "description": (f"{SERVICE_NAME} — {SERVICE_TITLE_KO}. 가맹 조건을 가맹사업법·시행령 조문과 "
                        "대조해 위험 신호·체크리스트·질문을 돌려주는 MCP. 확정 판정이 아니다."),
        "serverInfo": {"name": SERVICE_NAME.lower(), "version": f"{SERVICE_NAME.lower()}/{__version__}"},
        "tools": [
            {"name": item["name"], "title": item["title_ko"],
             "description": item["description_ko"], "inputSchema": item["input_schema"]}
            for item in TOOL_DEFS
        ],
    }


def call_tool(name: str, arguments: Optional[Dict[str, Any]], store: Any = None,
              client_id: str = "anonymous") -> Dict[str, Any]:
    definition = TOOL_INDEX.get(name)
    if definition is None:
        return {"ok": False, "error": "unknown_tool", "tool": name}
    args = arguments if isinstance(arguments, dict) else {}
    try:
        result = definition["handler"](args, store)
    except ValueError as exc:
        result = {"tool": name, "ok": False, "error": "invalid_argument", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - 공개 배포에서 내부 정보를 노출하지 않는다
        result = {"tool": name, "ok": False, "error": "internal_error",
                  "message": type(exc).__name__}
    usage.record_tool(store, name, result, args)
    return result


def submit_inquiry(payload: Any, store: Any = None, day: Optional[str] = None) -> Dict[str, Any]:
    clean, error = usage.normalize_inquiry(payload)
    if error:
        return {"ok": False, "error": error,
                "message_ko": usage.INQUIRY_ERRORS_KO.get(error, "문의를 접수하지 못했습니다."),
                "topics": inquiry_topics()}
    saved = usage.save_inquiry(store, clean, day)
    if saved.get("error"):
        code = str(saved["error"])
        return {"ok": False, "error": code,
                "message_ko": usage.INQUIRY_ERRORS_KO.get(code, "문의를 접수하지 못했습니다."),
                "topics": inquiry_topics()}
    duplicate = bool(saved.get("duplicate"))
    return {
        "ok": True,
        "stored": bool(saved.get("stored")),
        "duplicate": duplicate,
        "receipt": saved.get("receipt"),
        "topic": clean["topic"],
        "topic_label_ko": usage.INQUIRY_TOPIC_LABELS[clean["topic"]],
        "message_ko": ("같은 내용이 이미 접수되어 있습니다. 회신드리겠습니다." if duplicate else
                       "접수됐습니다. 남겨 주신 연락처로만 회신드립니다."),
        "privacy": {
            "contact_used_for": "reply_only",
            "echoed_back": False,
            "in_usage_stats": False,
            "keep_days": usage.INQUIRY_KEEP_DAYS,
        },
        "topics": inquiry_topics(),
        "checked_at": engine.now_iso(),
    }


def inquiry_topics() -> List[Dict[str, str]]:
    return [{"topic": topic, "label_ko": usage.INQUIRY_TOPIC_LABELS[topic]}
            for topic in usage.INQUIRY_TOPICS]


def text_summary(result: Dict[str, Any]) -> str:
    """MCP content 블록에 넣는 사람이 읽는 요약(JSON 앞에 붙인다)."""
    data = result.get("result") if isinstance(result.get("result"), dict) else {}
    tool = result.get("tool")
    if result.get("ok") is False:
        return f"오류: {result.get('error')} {result.get('message') or ''}".strip()
    if tool == "check_franchise_risk":
        verdict = data.get("verdict") or {}
        lines = [f"[{verdict.get('label_ko')}] 위험 점수 {data.get('risk_score')} · "
                 f"신호 {data.get('counts', {}).get('triggered', 0)}건 "
                 f"(높음 {data.get('counts', {}).get('high', 0)})",
                 str(data.get("summary_ko") or "")]
        for row in (data.get("risk_points") or [])[:4]:
            lines.append(f"· [{row['severity_label_ko']}] {row['title_ko']}")
        if (data.get("questions_ko") or []):
            lines.append("먼저 물어볼 것: " + data["questions_ko"][0])
        support = data.get("startup_support") or {}
        if support.get("url"):
            lines.append(f"창업 지원금 확인: {support['url']}")
        return "\n".join(line for line in lines if line)
    if tool == "lookup_brand_disclosure":
        status = data.get("status")
        brands = data.get("brands") or []
        lines = [f"상태: {status} · 데이터: {data.get('data_state')}"]
        for brand in brands[:3]:
            lines.append(f"· {brand.get('brand_name')} / {brand.get('hq_name')} "
                         f"({brand.get('industry_mid')}) 가맹점 {brand.get('stores_year_end')} · "
                         f"평균매출 {models.format_krw(brand.get('avg_sales_krw'))}")
        if data.get("message_ko"):
            lines.append(data["message_ko"])
        if data.get("zero_result") and data.get("zero_result_notice_ko"):
            lines.append(data["zero_result_notice_ko"])
        return "\n".join(lines)
    if tool == "compare_franchise_terms":
        a, b = data.get("a") or {}, data.get("b") or {}
        lines = [f"A {a.get('label')}: {a.get('verdict', {}).get('label_ko')} (점수 {a.get('risk_score')})",
                 f"B {b.get('label')}: {b.get('verdict', {}).get('label_ko')} (점수 {b.get('risk_score')})"]
        lines.extend(f"· {item}" for item in (data.get("differences_ko") or [])[:5])
        if data.get("recommendation_ko"):
            lines.append(str(data["recommendation_ko"]))
        return "\n".join(lines)
    if tool == "list_risk_cases":
        return f"리스크 케이스 {data.get('count', 0)}건"
    if tool == "get_law_article":
        return f"{data.get('key')} {data.get('title')} — 시행 {data.get('effective_on')}"
    return f"{SERVICE_NAME} 응답"
