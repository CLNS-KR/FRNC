"""사람용 단일 페이지 웹 UI (`GET /`) — 로그인 없이 10초 체크.

원칙
----
1. **외부 의존 0**: CSS·JS·아이콘 전부 인라인(CDN·폰트·트래커 없음). CSP 가 외부 로드를 막는다.
2. **개인정보 최소**: 판정 폼에서 이름·연락처·주민등록번호를 받지 않는다. 입력값은 요청 1회로만
   쓰고 서버에 저장하지 않는다(카운터에도 남기지 않음). 예외는 맨 아래 **문의 카드** 하나로,
   거기 직접 적은 연락처만 `POST /v1/inquiry` 로 보내 회신 목적으로 보관한다.
3. **단정 금지**: 판정 문구는 "확인 필요 신호 있음 / 정보 부족 / 뚜렷한 위험 신호 없음" 세 가지.
4. **근거 우선**: 위험 신호마다 이유·법 조문·되돌리기 어려운 점·확인 질문을 접어서 보여 준다.
5. **1초 프리셋**: 실제로 자주 오는 네 가지 상황을 버튼 하나로 채우고 바로 판정한다.
6. **문구 스캔**: 판정 폼과 따로 된 카드에서 계약서·특약 문구만 받아 대조한다. 문구는
   저장하지 않고, 입·출력 어디에도 '안전·문제없음'을 쓰지 않는다.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from . import engine, models, site_verification
from .version import (DISCLOSURE_PORTAL, GRANT_URL, SERVICE_NAME, SERVICE_SUBTITLE_EN,
                      SERVICE_TAGLINE, SERVICE_TITLE_KO, SERVICE_URL, __version__)

BASE_CSS = """
:root{
  --bg:#f4f6fb; --card:#ffffff; --ink:#111827; --ink-soft:#556070; --line:#dbe2ec;
  --surface-2:#f7f9fc; --surface-3:#eceff5; --on-brand:#ffffff;
  --brand:#1f4fd8; --brand-soft:#e8eefc; --brand-ink:#14307d;
  --ok:#0d7a4a; --ok-soft:#e1f5ea; --warn:#8a5300; --warn-soft:#fdf1d9;
  --info:#1e5d91; --info-soft:#e6f0f9; --danger:#a02a24; --danger-soft:#fbe9e7;
  --shadow:0 1px 2px rgba(16,24,40,.05);
  --radius:14px;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0b0f16; --card:#151b24; --ink:#e9eef7; --ink-soft:#a7b2c3; --line:#28313f;
    --surface-2:#1a2230; --surface-3:#212b3a; --on-brand:#0a1020;
    --brand:#84a8ff; --brand-soft:#17233c; --brand-ink:#d3e0ff;
    --ok:#63d69e; --ok-soft:#122a20; --warn:#f2bd66; --warn-soft:#2b2214;
    --info:#8fbbea; --info-soft:#132537; --danger:#f29a90; --danger-soft:#2d1716;
    --shadow:0 1px 2px rgba(0,0,0,.4); --radius:14px;
  }
}
*{box-sizing:border-box}
[hidden]{display:none !important}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-size:16px;line-height:1.55;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif}
a{color:var(--brand);text-underline-offset:2px}
.wrap{max-width:960px;margin:0 auto;padding:0 16px 72px}
header.top{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap;
  padding:22px 0 16px;border-bottom:1px solid var(--line)}
.brand{display:flex;gap:12px;align-items:center;min-width:0}
.mark{width:42px;height:42px;border-radius:12px;background:var(--brand);color:var(--on-brand);
  display:flex;align-items:center;justify-content:center;font-weight:800;font-size:16px;flex:0 0 auto;
  letter-spacing:-.5px}
.brand h1{margin:0;font-size:18px;letter-spacing:-.2px}
.brand p{margin:2px 0 0;font-size:12.5px;color:var(--ink-soft)}
.brand p.en{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase}
.pill{font-size:11.5px;font-weight:700;padding:4px 10px;border-radius:999px;
  background:var(--brand-soft);color:var(--brand-ink);white-space:nowrap}
.pill.ghost{background:transparent;color:var(--ink-soft);border:1px solid var(--line)}
.pill.warn{background:var(--warn-soft);color:var(--warn)}
.notice{margin:16px 0 0;padding:11px 14px;border-radius:11px;background:var(--warn-soft);
  color:var(--warn);font-size:13px;border:1px solid transparent}
.notice.info{background:var(--info-soft);color:var(--info)}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:20px;box-shadow:var(--shadow)}
.card+.card{margin-top:14px}
h2{font-size:17px;margin:0 0 6px;letter-spacing:-.2px}
h3{font-size:14.5px;margin:18px 0 8px}
h4{font-size:14px;margin:0 0 6px}
.sub{margin:0 0 16px;color:var(--ink-soft);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.grid.three{grid-template-columns:repeat(3,minmax(0,1fr))}
.grid .full{grid-column:1/-1}
@media (max-width:700px){.grid,.grid.three{grid-template-columns:1fr}}
.field{display:block}
.field>.lab{display:block;font-size:13px;font-weight:700;margin-bottom:5px}
.field>.lab .opt{font-weight:500;color:var(--ink-soft);font-size:11.5px;margin-left:4px}
input[type=text],input[type=number],select,textarea{width:100%;font:inherit;font-size:15px;color:var(--ink);
  background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:11px 12px;appearance:none}
select{cursor:pointer}
textarea{min-height:88px;resize:vertical}
input:focus,select:focus,textarea:focus{outline:2px solid var(--brand);outline-offset:1px;border-color:transparent}
.hint{display:block;margin-top:5px;font-size:11.5px;color:var(--ink-soft)}
.inline-sum{margin-top:6px;font-size:12.5px;font-weight:700;color:var(--brand-ink)}
.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:18px}
button{font:inherit;cursor:pointer}
button.primary{font-size:15.5px;font-weight:800;color:var(--on-brand);background:var(--brand);
  border:0;border-radius:12px;padding:14px 24px;min-height:48px}
button.primary:disabled{opacity:.6;cursor:progress}
button.ghost{font-size:14px;font-weight:600;color:var(--ink-soft);background:transparent;
  border:1px solid var(--line);border-radius:11px;padding:12px 16px;min-height:44px}
button.ghost:hover{color:var(--ink)}
.presets{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
@media (max-width:760px){.presets{grid-template-columns:repeat(2,minmax(0,1fr))}}
button.preset{text-align:left;background:var(--surface-2);border:1px solid var(--line);border-radius:12px;
  padding:12px 13px;min-height:76px;display:flex;flex-direction:column;gap:4px}
button.preset:hover{border-color:var(--brand)}
button.preset .t{font-size:13px;font-weight:800;color:var(--ink);line-height:1.35}
button.preset .d{font-size:11.5px;color:var(--ink-soft);line-height:1.4}
.verdict{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;
  border:1px solid var(--line);border-radius:12px;padding:16px;background:var(--surface-2)}
.verdict h3{margin:0;font-size:17px}
.verdict .kv{margin:6px 0 0;font-size:13px;color:var(--ink-soft)}
.badge{font-size:12px;font-weight:800;padding:5px 11px;border-radius:999px;white-space:nowrap}
.badge.check_likely{background:var(--danger-soft);color:var(--danger)}
.badge.info_needed{background:var(--warn-soft);color:var(--warn)}
.badge.low_risk{background:var(--ok-soft);color:var(--ok)}
.badge.high{background:var(--danger-soft);color:var(--danger)}
.badge.medium{background:var(--warn-soft);color:var(--warn)}
.badge.low{background:var(--info-soft);color:var(--info)}
.meter{margin-top:14px;height:8px;border-radius:999px;background:var(--surface-3);overflow:hidden}
.meter>span{display:block;height:100%;background:var(--brand)}
.summary{margin:14px 0 0;font-size:14.5px}
.section{margin-top:20px}
.section h3{font-size:14.5px;margin:0 0 10px;display:flex;justify-content:space-between;align-items:baseline}
.section h3 .count{font-size:12px;color:var(--ink-soft);font-weight:600}
.risk{border:1px solid var(--line);border-radius:11px;padding:12px 14px;background:var(--card)}
.risk+.risk{margin-top:9px}
.risk-head{display:flex;gap:8px;align-items:flex-start;justify-content:space-between}
.risk h4{margin:0;font-size:14.5px}
.risk .why{margin:6px 0 0;font-size:13px;color:var(--ink-soft)}
.risk details{margin-top:8px}
.risk summary{cursor:pointer;font-size:12.5px;font-weight:700;color:var(--brand)}
.risk .body{margin:8px 0 0;font-size:13px;line-height:1.6}
.risk .body b{font-weight:800}
.lawbox{margin-top:8px;padding:10px 12px;border-radius:9px;background:var(--bg);border:1px solid var(--line);
  font-size:12.5px;line-height:1.6}
.lawbox .src{display:block;margin-top:5px;font-size:11px;color:var(--ink-soft);word-break:break-all}
.money-table{width:100%;border-collapse:collapse;font-size:13px}
.money-table th,.money-table td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left}
.money-table th{font-size:11.5px;color:var(--ink-soft);font-weight:700;background:var(--bg)}
.money-table td.num{text-align:right;font-variant-numeric:tabular-nums}
ul.clean{margin:8px 0 0;padding-left:18px;font-size:13.5px;line-height:1.75}
ul.clean li{margin:2px 0}
ol.steps{margin:8px 0 0;padding-left:20px;font-size:13.5px;line-height:1.7}
ol.steps li{margin:6px 0}
.linkcard{display:flex;gap:12px;justify-content:space-between;align-items:center;flex-wrap:wrap;
  margin-top:14px;padding:14px 16px;border-radius:12px;background:var(--brand-soft);
  border:1px solid transparent}
.linkcard p{margin:0;font-size:13px;color:var(--brand-ink)}
.linkcard a.btn-link{font-size:13.5px;font-weight:800;padding:10px 14px;border-radius:10px;
  background:var(--brand);color:var(--on-brand);text-decoration:none;white-space:nowrap}
.status{margin-top:12px;font-size:13px;color:var(--ink-soft);min-height:20px}
.status.err{color:var(--danger);font-weight:700}
.copyrow{margin-top:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.foot{margin-top:26px;font-size:12px;color:var(--ink-soft);line-height:1.75}
.foot a{color:var(--ink-soft)}
.kbd{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;background:var(--surface-3);
  padding:1px 5px;border-radius:5px}
.scan-samples{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:14px}
@media (max-width:760px){.scan-samples{grid-template-columns:1fr}}
button.sample{text-align:left;background:var(--surface-2);border:1px solid var(--line);border-radius:12px;
  padding:12px 13px;min-height:64px;display:flex;flex-direction:column;gap:4px}
button.sample:hover{border-color:var(--brand)}
button.sample .t{font-size:13px;font-weight:800;color:var(--ink);line-height:1.35}
button.sample .d{font-size:11.5px;color:var(--ink-soft);line-height:1.4}
.quote{margin:8px 0 0;padding:10px 12px;border-left:3px solid var(--brand);background:var(--surface-2);
  border-radius:0 9px 9px 0;font-size:13px;line-height:1.6;color:var(--ink);word-break:keep-all}
.finding{border:1px solid var(--line);border-radius:11px;padding:12px 14px;background:var(--card)}
.finding+.finding{margin-top:9px}
.finding-head{display:flex;gap:8px;align-items:flex-start;justify-content:space-between}
.finding h4{margin:0;font-size:14.5px}
.finding .why{margin:6px 0 0;font-size:13px;color:var(--ink-soft)}
.finding .req{margin:8px 0 0;font-size:13px;line-height:1.6}
.finding .req b{font-weight:800}
.scan-checks{margin:8px 0 0;padding-left:18px;font-size:13px;line-height:1.7;color:var(--ink-soft)}
"""

PRESETS = [
    {
        "id": "same_day",
        "title": "당일 계약·가맹금 바로 송금",
        "desc": "정보공개서 받은 당일 서명, 본사 계좌로 입금 요구",
        "values": {
            "disclosure_days_before": 0, "contract_doc_days_before": 0,
            "payment_route": "hq_account", "advisor_reviewed": "false",
        },
    },
    {
        "id": "verbal_sales",
        "title": "구두 매출 보장·서면 없음",
        "desc": "'월 5천 보장' 말만 있고 산정서는 없음",
        "values": {
            "revenue_claim_ko": "월 매출 5천만원 보장", "revenue_written": "false",
            "revenue_estimate_doc": "false",
        },
    },
    {
        "id": "interior_forced",
        "title": "본사 인테리어 100% 강제",
        "desc": "지정 업체만 허용, 다른 견적 불가",
        "values": {
            "interior_designated": "forced", "mandatory_purchase": "true",
            "supplier_designated": "true",
        },
    },
    {
        "id": "normal",
        "title": "정상 조건 체크",
        "desc": "14일 숙고, 예치, 자유 인테리어, 독점 영업지역",
        "values": {
            "disclosure_days_before": 21, "contract_doc_days_before": 21,
            "payment_route": "escrow", "revenue_written": "true",
            "revenue_estimate_doc": "true", "interior_designated": "free",
            "territory": "exclusive", "closure_rate_3y_pct": 5,
            "legal_violation": "false", "termination_grace_months": 2,
            "disclosure_registered": "true", "mandatory_purchase": "false",
            "supplier_designated": "false", "price_fixing": "false",
            "ad_cost_burden": "shared", "penalty_ratio_pct": 10,
        },
    },
]

# 문구 스캔 샘플 3종 — 실제로 반복해서 오는 특약 유형만 넣었다.
SCAN_SAMPLES = [
    {
        "id": "purchase",
        "title": "구입강제 특약",
        "desc": "인테리어·원부자재를 지정업체로만",
        "text": (
            "제3조(인테리어) 가맹점사업자는 인테리어와 간판 시공을 당사가 지정한 업체를 통해서만 "
            "하여야 하며, 다른 업체를 이용할 수 없다.\n"
            "제4조(원부자재) 원부자재와 포장재는 당사가 공급하는 물품만 사용하여야 하고, "
            "타사 제품의 사용은 금지한다."
        ),
    },
    {
        "id": "penalty",
        "title": "과중 위약금 특약",
        "desc": "잔여 로열티 전액·보증금 몰수",
        "text": (
            "제12조(중도해지) 가맹점사업자가 계약을 중도해지하는 경우 잔여 계약기간의 로열티 "
            "전액을 위약금으로 지급한다.\n"
            "제13조(보증금) 가맹보증금은 계약 종료 시 전액 몰수하며 반환하지 않는다."
        ),
    },
    {
        "id": "termination",
        "title": "즉시 해지 특약",
        "desc": "최고·유예기간 없이 즉시 해지",
        "text": (
            "제15조(계약해지) 가맹점사업자가 이 계약을 위반한 경우 당사는 최고 없이 즉시 "
            "해지할 수 있으며, 별도의 유예기간은 두지 않는다."
        ),
    },
]

YES_NO_UNKNOWN = [("", "모름"), ("true", "예"), ("false", "아니오")]

SELECTS = [
    ("payment_route", "가맹금 납부 방식", [
        ("", "모름"), ("escrow", "예치기관에 예치"), ("insurance", "피해보상보험계약"),
        ("hq_account", "본사 계좌로 직접 송금"), ("none", "예치·보험 없음")]),
    ("interior_designated", "인테리어·집기 지정", [
        ("", "모름"), ("free", "자유 선택"), ("partial", "일부 품목만 지정"),
        ("forced", "본사 지정 100% 강제")]),
    ("territory", "영업지역", [
        ("", "모름"), ("exclusive", "독점 영업지역 기재"), ("defined", "영업지역만 기재(독점 아님)"),
        ("none", "영업지역 없음")]),
    ("ad_cost_burden", "광고·판촉비 부담", [
        ("", "모름"), ("shared", "본사·점주 분담"), ("franchisee_forced", "점주 의무 부담"),
        ("none", "없음")]),
    ("revenue_written", "매출 정보를 서면으로 받았나", YES_NO_UNKNOWN),
    ("revenue_estimate_doc", "예상매출액 산정서를 받았나", YES_NO_UNKNOWN),
    ("legal_violation", "본부 법 위반·시정조치 이력", YES_NO_UNKNOWN),
    ("disclosure_registered", "등록 정보공개서 확인", YES_NO_UNKNOWN),
    ("mandatory_purchase", "필수품목 구입 의무", YES_NO_UNKNOWN),
    ("price_fixing", "본부가 판매가격을 정하나", YES_NO_UNKNOWN),
]


def _options(rows: list) -> str:
    return "".join(f'<option value="{value}">{label}</option>' for value, label in rows)


def _field(name: str, label: str, *, value: str = "", kind: str = "text",
           hint: str = "", opt: str = "", extra: str = "") -> str:
    opt_html = f'<span class="opt">{opt}</span>' if opt else ""
    hint_html = f'<span class="hint">{hint}</span>' if hint else ""
    return (
        f'<label class="field"><span class="lab">{label}{opt_html}</span>'
        f'<input id="{name}" name="{name}" type="{kind}" value="{value}"{extra}>'
        f'{hint_html}</label>'
    )


def _select_field(name: str, label: str, rows: list, hint: str = "") -> str:
    hint_html = f'<span class="hint">{hint}</span>' if hint else ""
    return (
        f'<label class="field"><span class="lab">{label}</span>'
        f'<select id="{name}" name="{name}">{_options(rows)}</select>{hint_html}</label>'
    )


def _form_html() -> str:
    money_fields = "".join([
        _field("brand_name", "브랜드명", hint="예: 샘플치킨", extra=' autocomplete="off"'),
        _field("industry", "업종", hint="예: 치킨 · 커피 · 편의점", extra=' autocomplete="off"'),
        _field("franchise_fee_krw", "가맹비", hint="예: 1100만원", extra=' inputmode="numeric"'),
        _field("education_fee_krw", "가맹교육비", hint="예: 330만원", extra=' inputmode="numeric"'),
        _field("deposit_krw", "가맹보증금", hint="예: 1000만원", extra=' inputmode="numeric"'),
        _field("interior_krw", "인테리어 비용", hint="예: 5500만원", extra=' inputmode="numeric"'),
        _field("equipment_krw", "설비·집기", hint="예: 2000만원", extra=' inputmode="numeric"'),
        _field("other_krw", "기타 비용", hint="예: 초도물량·간판", extra=' inputmode="numeric"'),
    ])
    selects = "".join(_select_field(name, label, rows) for name, label, rows in SELECTS)
    return f"""
<div class="grid three">
  {money_fields}
  <div class="full"><span class="inline-sum" id="money-sum">총투자: 항목을 넣으면 자동으로 합산합니다.</span></div>

  {_field("disclosure_days_before", "정보공개서 받은 뒤 지난 날", kind="number",
          hint="당일이면 0. 14일(자문 시 7일) 전에 계약·입금하면 위반입니다.", extra=' min="0" step="1"')}
  {_field("contract_doc_days_before", "계약서 초안 받은 뒤 지난 날", kind="number",
          hint="계약서도 같은 숙고기간이 적용됩니다.", extra=' min="0" step="1"')}
  {_select_field("advisor_reviewed", "변호사·가맹거래사 자문", [("", "모름"), ("true", "받음"), ("false", "안 받음")],
                 "자문을 받으면 숙고기간이 7일로 줄어듭니다.")}
  {_select_field("payment_route", "가맹금 납부 방식", SELECTS[0][2],
                 "예치·피해보상보험 없이 본사 계좌로 보내면 회수 장치가 사라집니다.")}
  {_field("revenue_claim_ko", "본부가 한 매출 관련 말", hint="예: 월 매출 5천 보장", extra=' autocomplete="off"')}

  <div class="full"><h3>계약·영업 조건</h3></div>
  {selects}
  {_field("penalty_ratio_pct", "중도해지 위약금(총투자 대비 %)", kind="number",
          hint="모르면 비워 두세요. 20% 이상이면 신호입니다.", extra=' min="0" step="1"')}
  {_field("termination_grace_months", "본부 해지 시 유예기간(개월)", kind="number",
          hint="법은 2개월 이상 유예와 서면 2회 통지를 요구합니다.", extra=' min="0" step="1"')}
  {_field("closure_rate_3y_pct", "최근 3년 폐점률(%)", kind="number",
          hint="모르면 비워 두세요. 15% 이상이면 위험 높음입니다.", extra=' min="0" step="1"')}
  {_field("renewal_years", "최초 포함 전체 계약기간(년)", kind="number",
          hint="갱신 요구권은 전체 10년을 넘지 않습니다.", extra=' min="0" step="1"')}
  {_select_field("sales_target", "판매목표 강제", YES_NO_UNKNOWN,
                 "목표 미달 시 불이익이 있으면 불공정거래행위가 될 수 있습니다.")}
  {_select_field("supplier_designated", "거래처(공급처) 지정", YES_NO_UNKNOWN,
                 "특정 업체와만 거래하도록 강제하면 구입강제가 될 수 있습니다.")}
  {_select_field("essential_price_hidden", "필수품목 단가·산정기준 미공개", YES_NO_UNKNOWN,
                 "단가를 나중에 알려 주겠다고 하면 매입가를 비교할 기준이 없습니다.")}
  {_select_field("essential_items_broad", "일반 공산품까지 필수품목", YES_NO_UNKNOWN,
                 "가맹사업과 무관한 물품을 필수품목으로 묶으면 구입강제가 될 수 있습니다.")}
  {_select_field("margin_raise_unilateral", "차액가맹금 일방 인상", YES_NO_UNKNOWN,
                 "적정 도매가격을 넘는 대가를 본부가 일방적으로 올리는지 확인하세요.")}
  {_select_field("resale_price_bound", "판매가격 유지·변경 제한", YES_NO_UNKNOWN,
                 "본부가 정한 가격을 유지하게 하면 가격 구속 유형을 검토할 수 있습니다.")}
  {_select_field("discount_forbidden", "할인 금지", YES_NO_UNKNOWN,
                 "할인 권한이 점주에게 있는지 계약서에서 확인하세요.")}
</div>
"""


def _presets_html() -> str:
    buttons = []
    for preset in PRESETS:
        buttons.append(
            f'<button type="button" class="preset" data-preset="{preset["id"]}">'
            f'<span class="t">{preset["title"]}</span>'
            f'<span class="d">{preset["desc"]}</span></button>'
        )
    return "".join(buttons)


def _scan_card_html() -> str:
    """특약·계약서 문구 스캔 카드 — 판정 폼과 분리된 별도 입력(문구만 보낸다)."""
    buttons = "".join(
        f'<button type="button" class="sample" data-sample="{row["id"]}">'
        f'<span class="t">{row["title"]}</span><span class="d">{row["desc"]}</span></button>'
        for row in SCAN_SAMPLES
    )
    return f"""
<section class="card" id="scan-card">
  <h2>특약·계약서 문구 1초 스캔</h2>
  <p class="sub">본부가 보낸 계약서·특약·안내 문구를 그대로 붙여 넣으면, 가맹사업법·시행령 별표 2의
    불공정 유형 {len(engine.CONTRACT_RULES)}개와 대조해 <b>확인이 필요한 문구</b>와 본부에 요청할 수정 문구를 짚어 줍니다.
    붙여넣은 문구는 저장하지 않으며, 잡히는 문구가 없어도 '안전'을 뜻하지 않습니다.</p>
  <div class="scan-samples">{buttons}</div>
  <label class="field"><span class="lab">계약서·특약 문구<span class="opt">붙여넣기 · {engine.SCAN_MAX_CHARS:,}자까지</span></span>
    <textarea id="scan-text" rows="7" data-max="{engine.SCAN_MAX_CHARS}" placeholder="예: 인테리어는 당사가 지정한 업체를 통해서만 시공한다."></textarea></label>
  <div class="actions">
    <button type="button" class="primary" id="scan-run">문구 스캔</button>
    <button type="button" class="ghost" id="scan-clear">지우기</button>
    <span class="hint" id="scan-count">0자</span>
  </div>
  <div class="status" id="scan-status" aria-live="polite"></div>
  <div id="scan-result" hidden></div>
</section>
"""


def _inquiry_html() -> str:
    topics = "".join(
        f'<option value="{topic}">{label}</option>'
        for topic, label in [
            ("franchise_review", "브랜드·계약 조건 검토 요청"),
            ("api_mcp", "API·MCP 연동"),
            ("other", "그 밖의 문의"),
        ]
    )
    return f"""
<form id="inquiry" class="card" novalidate>
  <h2>검토 요청·문의</h2>
  <p class="sub">브랜드명과 조건을 적어 주시면 같은 기준으로 다시 확인해 드립니다. 연락처는 회신 목적으로만 쓰고 통계에 넣지 않습니다.</p>
  <div class="grid">
    <label class="field"><span class="lab">연락처<span class="opt">이메일 또는 전화</span></span>
      <input id="inq-contact" name="contact" type="text" autocomplete="off" placeholder="회신받을 연락처"></label>
    <label class="field"><span class="lab">문의 유형</span>
      <select id="inq-topic" name="topic">{topics}</select></label>
    <label class="field full"><span class="lab">내용<span class="opt">선택 · 500자</span></span>
      <textarea id="inq-message" name="message" maxlength="500" placeholder="브랜드명, 궁금한 조항, 확인하고 싶은 점"></textarea></label>
  </div>
  <div class="actions">
    <button type="submit" class="primary" id="inq-send">문의 보내기</button>
    <span class="hint">연락처는 응답에 되돌려 보내지 않습니다.</span>
  </div>
  <div class="status" id="inq-status" aria-live="polite"></div>
</form>
"""


def _guides_teaser_html(limit: int = 6) -> str:
    """홈에서 가이드로 보내는 내부 링크(검색·AI 크롤러가 따라가는 경로).

    카테고리마다 하나씩 먼저 골라 한 곳에 몰리지 않게 한다.
    """
    from . import guides

    picked = []
    for _key, _label, rows, _intro in guides.by_category():
        if rows:
            picked.append(rows[0])
    for row in guides.GUIDES:
        if len(picked) >= limit:
            break
        if row not in picked:
            picked.append(row)
    return "".join(
        f'<li><a href="/guides/{row["slug"]}">{row["topic"]}</a> — {row["question"]}</li>'
        for row in picked[:limit]
    )


def render_page(meta: Optional[Dict[str, Any]] = None) -> str:
    from . import guides

    meta = meta or {}
    data_state = str(meta.get("data_state") or "sample")
    law = engine.law_meta()
    state_note = (
        "브랜드 조회는 공정위 가맹정보 API 활용신청 승인 전이라 내장 샘플로 동작합니다. "
        "판정(리스크 체크)은 입력한 조건과 실조회한 법 조문으로 그대로 계산됩니다."
        if data_state != "live" else
        "공정위 가맹정보 API 실데이터로 동작합니다."
    )
    presets_json = json.dumps({preset["id"]: preset["values"] for preset in PRESETS},
                              ensure_ascii=False)
    scan_samples_json = json.dumps({row["id"]: row["text"] for row in SCAN_SAMPLES},
                                   ensure_ascii=False)
    meta_tags = site_verification.meta_tags()
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{SERVICE_NAME} — {SERVICE_TITLE_KO}</title>
<meta name="description" content="프랜차이즈 창업 전 10초 리스크 체크. 정보공개서 14일 숙고기간, 가맹금 예치, 예상매출 서면, 인테리어 강제, 영업지역을 가맹사업법 조문과 대조합니다. 확정 판정이 아닙니다.">
<meta name="theme-color" content="#1f4fd8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0b0f16" media="(prefers-color-scheme: dark)">
<meta property="og:title" content="{SERVICE_NAME} — {SERVICE_TITLE_KO}">
<meta property="og:description" content="{SERVICE_TAGLINE} 프랜차이즈 계약 전 위험 신호를 법 조문과 대조해 확인합니다.">
<meta property="og:type" content="website">
<meta property="og:url" content="{SERVICE_URL}/">
{meta_tags}
<style>{BASE_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand">
      <div class="mark" aria-hidden="true">FR</div>
      <div>
        <h1>{SERVICE_NAME} · {SERVICE_TITLE_KO}</h1>
        <p>{SERVICE_TAGLINE}</p>
        <p class="en">{SERVICE_SUBTITLE_EN}</p>
      </div>
    </div>
    <div>
      <span class="pill">v{__version__}</span>
      <span class="pill ghost">확정 판정 아님</span>
      <a class="pill ghost" href="/guides/">가이드 {len(guides.GUIDES)}종</a>
    </div>
  </header>

  <p class="notice info" id="data-state-note">{state_note}
    <br>법령 근거: 법제처 OPEN API 실조회 · 조문 {law.get('article_count', 0)}개 · 함정 케이스 {len(engine.trap_cases())}건.
    조회 결과가 0건이어도 '안전'을 뜻하지는 않습니다.</p>

  <section class="card" style="margin-top:14px">
    <h2>1초 프리셋</h2>
    <p class="sub">자주 오는 네 가지 상황입니다. 누르면 조건이 채워지고 바로 판정합니다.</p>
    <div class="presets">{_presets_html()}</div>
  </section>

  <form class="card" id="check" novalidate>
    <h2>조건 입력</h2>
    <p class="sub">모르는 항목은 비워 두세요. 비운 항목은 '괜찮다'가 아니라 <b>되물어볼 질문</b>으로 돌려드립니다.
      이름·연락처·주민등록번호는 받지 않고, 입력값은 서버에 저장하지 않습니다.
      (브랜드 조회 결과가 0건일 때만 조회어를 전화번호·이메일 없이 익명 집계합니다.)</p>
    {_form_html()}
    <div class="actions">
      <button type="submit" class="primary" id="run">10초 체크</button>
      <button type="button" class="ghost" id="reset">입력 지우기</button>
      <span class="hint">Enter 로도 실행됩니다.</span>
    </div>
    <div class="status" id="status" aria-live="polite"></div>
  </form>

  <section class="card" id="result-card" hidden>
    <h2>결과</h2>
    <div id="result"></div>
    <div class="copyrow">
      <button type="button" class="ghost" id="copy">요약 복사</button>
      <button type="button" class="ghost" id="share">공유 링크 복사</button>
      <span class="hint" id="copy-status" aria-live="polite"></span>
    </div>
  </section>

  {_scan_card_html()}

  <section class="card">
    <h2>이 서비스가 보는 8개 축</h2>
    <p class="sub">법이 직접 정한 절차와, 계약서에서 실제로 문제가 되는 조항만 봅니다.</p>
    <ul class="clean">
      <li><b>숙고기간</b> — 정보공개서·계약서를 받은 뒤 14일(자문 시 7일) 전 계약·입금 금지</li>
      <li><b>가맹금</b> — 예치기관 예치 또는 피해보상보험계약</li>
      <li><b>매출 정보</b> — 예상매출액 산정서 서면 교부·산출근거 열람</li>
      <li><b>인테리어</b> — 본사 지정 강제 여부(구입강제)</li>
      <li><b>영업지역</b> — 계약서 기재와 계약 중 침해 금지</li>
      <li><b>폐점률</b> — 최근 3년 가맹점 변동</li>
      <li><b>법 위반 이력</b> — 시정조치·과징금·형벌선고</li>
      <li><b>해지·갱신</b> — 2개월 유예·서면 2회 통지, 갱신 10년 한도</li>
    </ul>
    <p class="hint">각 항목의 조문 기준은 <a href="/guides/">질문형 가이드 {len(guides.GUIDES)}종</a>에서 확인할 수 있습니다.</p>
    <div class="linkcard">
      <p><b>창업비용을 낸 뒤에도 받을 수 있는 지원금이 있습니다.</b><br>
        소상공인 정책자금·청년창업·고용 지원금을 조건으로 확인하세요.</p>
      <a class="btn-link" href="{GRANT_URL}" target="_blank" rel="noopener noreferrer">GRNT에서 확인</a>
    </div>
  </section>

  <section class="card">
    <h2>계약 전 자주 묻는 질문</h2>
    <p class="sub">정보공개서·가맹금·영업지역·해지·갱신을 조문과 함께 정리했습니다.</p>
    <ul class="clean">{_guides_teaser_html()}</ul>
    <p class="hint"><a href="/guides/">가이드 전체 {len(guides.GUIDES)}종 보기</a></p>
  </section>

  {_inquiry_html()}

  <p class="foot">
    {SERVICE_NAME}는 입력한 조건과 공개 법령 조문을 대조하는 참고용 사전 점검 도구입니다.
    위법 여부·계약 효력을 확정하지 않고, 계약서 검토·법률 자문·신고 대행을 하지 않습니다.
    최종 판단은 변호사·가맹거래사 자문으로 하세요. · 정보공개서 원문: <a href="{DISCLOSURE_PORTAL}" target="_blank" rel="noopener noreferrer">가맹사업정보제공시스템</a>
    · <a href="/llms.txt">llms.txt</a> · <a href="/v1/meta">서비스 상태</a>
    · <a href="/guides/">가이드 {len(guides.GUIDES)}종</a>
  </p>
</div>

<script>
(function () {{
  "use strict";
  var PRESETS = {presets_json};
  var SCAN_SAMPLES_TEXT = {scan_samples_json};
  var MONEY = ["franchise_fee_krw","education_fee_krw","deposit_krw","interior_krw",
    "equipment_krw","other_krw"];
  var form = document.getElementById("check");
  var resultCard = document.getElementById("result-card");
  var resultEl = document.getElementById("result");
  var statusEl = document.getElementById("status");
  var lastResult = null;

  function $(id) {{ return document.getElementById(id); }}
  function esc(value) {{
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
      .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  }}
  function won(value) {{
    if (value === null || value === undefined || value === "") return "";
    var n = Number(String(value).replace(/[^0-9.-]/g,""));
    if (!isFinite(n) || n <= 0) return String(value);
    var eok = Math.floor(n / 100000000), man = Math.floor((n % 100000000) / 10000);
    var out = [];
    if (eok) out.push(eok.toLocaleString("ko-KR") + "억");
    if (man) out.push(man.toLocaleString("ko-KR") + "만");
    return out.length ? out.join(" ") + "원" : n.toLocaleString("ko-KR") + "원";
  }}
  function moneySum() {{
    var total = 0, any = false;
    MONEY.forEach(function (name) {{
      var el = $(name); if (!el || !el.value) return;
      var text = String(el.value).replace(/,/g,"");
      var mult = 1;
      if (text.indexOf("억") >= 0) {{ mult = 100000000; text = text.replace("억",""); }}
      else if (text.indexOf("만") >= 0) {{ mult = 10000; text = text.replace(/만원?/,""); }}
      var n = parseFloat(text);
      if (isFinite(n)) {{ total += n * mult; any = true; }}
    }});
    var sumEl = $("money-sum");
    if (!sumEl) return;
    sumEl.textContent = any ? "총투자 합계: " + won(total) + " (입력 항목 단순 합)" :
      "총투자: 항목을 넣으면 자동으로 합산합니다.";
  }}

  function collect() {{
    // 폼에 실제로 있는 name 만 모은다(화면과 요청이 어긋나지 않게).
    var payload = {{}};
    var nodes = form.querySelectorAll("input[name],select[name],textarea[name]");
    Array.prototype.forEach.call(nodes, function (el) {{
      var value = String(el.value || "").trim();
      if (value) payload[el.name] = value;
    }});
    return payload;
  }}

  function fill(values) {{
    Object.keys(values).forEach(function (key) {{
      var el = $(key);
      if (el) el.value = String(values[key]);
    }});
    moneySum();
  }}

  function badge(code, label) {{
    return '<span class="badge ' + esc(code) + '">' + esc(label) + '</span>';
  }}

  function riskItem(row) {{
    var refs = (row.law_refs || []).map(function (key) {{
      return '<span class="kbd">' + esc(key) + '</span>';
    }}).join(" ");
    return '<div class="risk">' +
      '<div class="risk-head"><h4>' + esc(row.title_ko) + '</h4>' +
        badge(row.severity, row.severity_label_ko) + '</div>' +
      '<p class="why">' + esc(row.note_ko || row.category_label_ko) + (row.note_ko && row.category_label_ko ? " · " + esc(row.category_label_ko) : "") + '</p>' +
      '<details><summary>왜 문제인가 · 무엇을 확인하나</summary>' +
        '<div class="body"><b>이유</b><br>' + esc(row.why_ko) +
        '<br><br><b>되돌리기 어려운 점</b><br>' + esc(row.regret_ko) +
        '<br><br><b>지금 할 일</b><br>' + esc(row.fix_ko) +
        '<br><br><b>물어볼 것</b><br>' + esc(row.ask_ko) + '</div>' +
      '</details>' +
      '<div class="lawbox">근거 조문 ' + refs + '</div>' +
    '</div>';
  }}

  function lawBoxes(rows, scope) {{
    if (!rows || !rows.length) return "";
    return '<div class="section"><h3>근거 조문 <span class="count">법제처 OPEN API 실조회</span></h3>' +
      (scope ? '<p class="hint">' + esc(scope) + '</p>' : '') +
      rows.map(function (row) {{
        return '<div class="lawbox"><b>' + esc(row.label_ko || row.key) + '</b>' +
          '<br>' + esc(row.excerpt_ko) +
          '<span class="src">' + esc(row.effective_on || "") + ' 시행 · ' + esc(row.source_url || "") + '</span></div>';
      }}).join("") + '</div>';
  }}

  function moneyBlock(money) {{
    if (!money || !money.components || !money.components.length) return "";
    var rows = money.components.map(function (row) {{
      return '<tr><td>' + esc(row.label_ko) + '</td><td class="num">' + esc(row.amount_ko) + '</td>' +
        '<td class="num">' + (row.share_pct === null || row.share_pct === undefined ? "" : row.share_pct + "%") + '</td></tr>';
    }}).join("");
    return '<div class="section"><h3>비용 구조 <span class="count">' + esc(money.total_ko || "") + '</span></h3>' +
      '<table class="money-table"><thead><tr><th>항목</th><th class="num">금액</th><th class="num">비중</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table>' +
      '<p class="hint">' + esc(money.note_ko) + '</p></div>';
  }}

  function render(result) {{
    lastResult = result;
    var verdict = result.verdict || {{}};
    var counts = result.counts || {{}};
    var coverage = result.coverage || {{}};
    var html = '<div class="verdict"><div><h3>' + esc(verdict.label_ko || "") + '</h3>' +
      '<p class="kv">위험 점수 ' + esc(result.risk_score) + ' · 신호 ' + esc(counts.triggered || 0) +
      '건(높음 ' + esc(counts.high || 0) + ' · 주의 ' + esc(counts.medium || 0) + ') · ' +
      '확인한 축 ' + esc(coverage.answered_axes || 0) + '/' + esc(coverage.total_axes || 8) + '</p></div>' +
      badge(verdict.code, verdict.label_ko) + '</div>' +
      '<div class="meter" aria-hidden="true"><span style="width:' + Math.max(3, Math.min(100, Number(result.risk_score) || 0)) + '%"></span></div>' +
      '<p class="summary">' + esc(result.summary_ko) + '</p>';

    if ((result.risk_points || []).length) {{
      html += '<div class="section"><h3>확인할 위험 신호 <span class="count">' + result.risk_points.length + '건</span></h3>' +
        result.risk_points.map(riskItem).join("") + '</div>';
    }}
    if ((result.unknown_points || []).length) {{
      var shown = result.unknown_points.slice(0, 8);
      var restNote = result.unknown_points.length > shown.length ?
        '<p class="hint">그 밖에 ' + (result.unknown_points.length - shown.length) + '개 항목이 더 있습니다. 위 질문에 답하면 함께 줄어듭니다.</p>' : '';
      html += '<div class="section"><h3>아직 모르는 항목 <span class="count">' + result.unknown_points.length + '건</span></h3>' +
        '<ul class="clean">' + shown.map(function (row) {{
          return '<li><b>' + esc(row.title_ko) + '</b> — ' + esc(row.ask_ko) + '</li>';
        }}).join("") + '</ul>' + restNote + '</div>';
    }}
    if ((result.questions_ko || []).length) {{
      html += '<div class="section"><h3>본부에 물어볼 것</h3><ul class="clean">' +
        result.questions_ko.map(function (q) {{ return '<li>' + esc(q) + '</li>'; }}).join("") + '</ul></div>';
    }}
    if ((result.checklist_ko || []).length) {{
      html += '<div class="section"><h3>계약 전 체크리스트</h3><ul class="clean">' +
        result.checklist_ko.map(function (item) {{ return '<li>' + esc(item) + '</li>'; }}).join("") + '</ul></div>';
    }}
    html += moneyBlock(result.money);
    html += lawBoxes(result.law_basis, result.law_basis_scope_ko);
    if ((result.next_steps || []).length) {{
      html += '<div class="section"><h3>다음 단계</h3><ol class="steps">' +
        result.next_steps.map(function (step) {{
          var link = step.url ? ' <a href="' + esc(step.url) + '" target="_blank" rel="noopener noreferrer">열기</a>' : "";
          return '<li><b>' + esc(step.title_ko) + '</b> — ' + esc(step.detail_ko) + link + '</li>';
        }}).join("") + '</ol></div>';
    }}
    var support = result.startup_support || {{}};
    if (support.url) {{
      html += '<div class="linkcard"><p>' + esc(support.note_ko) + '</p>' +
        '<a class="btn-link" href="' + esc(support.url) + '" target="_blank" rel="noopener noreferrer">' +
        esc(support.name_ko || "지원금 확인") + '</a></div>';
    }}
    html += '<p class="hint">' + esc(result.disclaimer_ko) + '</p>';
    resultEl.innerHTML = html;
    resultCard.hidden = false;
    resultCard.scrollIntoView({{behavior: "smooth", block: "start"}});
  }}

  function run() {{
    var payload = collect();
    statusEl.className = "status";
    statusEl.textContent = "법령 조문과 대조하는 중…";
    var button = $("run");
    button.disabled = true;
    fetch("/v1/tools/check_franchise_risk", {{
      method: "POST", headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify(payload)
    }}).then(function (response) {{
      return response.json().then(function (body) {{ return {{ok: response.ok, body: body}}; }});
    }}).then(function (out) {{
      if (!out.ok || !out.body || out.body.ok === false) {{
        throw new Error((out.body && (out.body.message || out.body.error)) || "판정에 실패했습니다.");
      }}
      render(out.body.result);
      statusEl.textContent = "판정 완료. 확정 판정이 아니므로 서류 원문과 함께 확인하세요.";
    }}).catch(function (error) {{
      statusEl.className = "status err";
      statusEl.textContent = "오류: " + error.message;
    }}).finally(function () {{
      button.disabled = false;
    }});
  }}

  Array.prototype.forEach.call(document.querySelectorAll("button.preset"), function (button) {{
    button.addEventListener("click", function () {{
      var name = button.getAttribute("data-preset");
      fill(PRESETS[name] || {{}});
      statusEl.className = "status";
      statusEl.textContent = "프리셋 적용: " + button.querySelector(".t").textContent;
      run();
    }});
  }});

  form.addEventListener("submit", function (event) {{ event.preventDefault(); run(); }});
  $("reset").addEventListener("click", function () {{
    form.reset(); moneySum(); resultCard.hidden = true; statusEl.textContent = "";
  }});
  MONEY.forEach(function (name) {{
    var el = $(name); if (el) el.addEventListener("input", moneySum);
  }});

  var copyButton = $("copy");
  function copyStatus(message) {{ $("copy-status").textContent = message; }}
  function copyText(text, okMessage) {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(text).then(function () {{ copyStatus(okMessage); }})
        .catch(function () {{ fallback(text, okMessage); }});
    }} else {{ fallback(text, okMessage); }}
    function fallback(value, message) {{
      var area = document.createElement("textarea");
      area.value = value; area.setAttribute("readonly", "readonly");
      area.style.position = "fixed"; area.style.opacity = "0";
      document.body.appendChild(area); area.select();
      try {{ document.execCommand("copy"); copyStatus(message); }}
      catch (error) {{ copyStatus("복사 실패 — 화면의 내용을 직접 선택해 주세요."); }}
      document.body.removeChild(area);
    }}
  }}

  // 비식별 공유 링크 — 브랜드명만 담고 금액·조건·연락처는 담지 않는다.
  function shareLink() {{
    var el = $("brand_name");
    var brand = String((el && el.value) || "").trim().slice(0, 60);
    var base = location.origin + "/";
    return brand ? base + "?brand=" + encodeURIComponent(brand) + "#check" : base + "#check";
  }}

  copyButton.addEventListener("click", function () {{
    if (!lastResult) {{ copyStatus("먼저 10초 체크를 실행해 주세요."); return; }}
    var verdict = lastResult.verdict || {{}};
    var lines = ["FRNC 리스크 체크 — " + (verdict.label_ko || ""),
      "위험 점수 " + lastResult.risk_score + " (신호 " + (lastResult.counts || {{}}).triggered + "건)",
      lastResult.summary_ko || ""];
    (lastResult.risk_points || []).forEach(function (row) {{
      lines.push("- [" + row.severity_label_ko + "] " + row.title_ko + " — " + (row.note_ko || ""));
    }});
    (lastResult.questions_ko || []).slice(0, 5).forEach(function (q) {{ lines.push("? " + q); }});
    lines.push("확정 판정 아님 · " + location.origin);
    copyText(lines.join("\\n"), "복사됨");
  }});

  $("share").addEventListener("click", function () {{
    copyText(shareLink(), "공유 링크 복사됨 — 브랜드명만 담깁니다.");
  }});

  // ?brand=...#check 로 들어오면 브랜드명만 채운다(금액·조건은 손대지 않는다).
  function prefillFromUrl() {{
    var brand = "";
    try {{
      if (window.URLSearchParams) {{
        brand = new URLSearchParams(location.search).get("brand") || "";
      }}
    }} catch (error) {{ brand = ""; }}
    brand = String(brand).trim().slice(0, 60);
    if (!brand) return;
    var el = $("brand_name");
    if (!el) return;
    el.value = brand;
    statusEl.className = "status";
    statusEl.textContent = "공유 링크에서 브랜드명만 채웠습니다. 금액·조건을 넣고 10초 체크를 눌러 주세요.";
  }}

  var inquiry = $("inquiry");
  inquiry.addEventListener("submit", function (event) {{
    event.preventDefault();
    var status = $("inq-status");
    var payload = {{
      contact: $("inq-contact").value,
      topic: $("inq-topic").value,
      message: $("inq-message").value
    }};
    status.className = "status";
    status.textContent = "보내는 중…";
    fetch("/v1/inquiry", {{
      method: "POST", headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify(payload)
    }}).then(function (response) {{
      return response.json().then(function (body) {{ return {{ok: response.ok, body: body}}; }});
    }}).then(function (out) {{
      if (!out.body || !out.body.ok) {{
        status.className = "status err";
        status.textContent = (out.body && out.body.message_ko) || "접수하지 못했습니다.";
        return;
      }}
      status.textContent = (out.body.message_ko || "접수됐습니다.") +
        (out.body.receipt ? " 접수번호 " + out.body.receipt : "");
      $("inq-message").value = "";
    }}).catch(function () {{
      status.className = "status err";
      status.textContent = "네트워크 오류로 접수하지 못했습니다.";
    }});
  }});

  // --- 특약·계약서 문구 스캔 ----------------------------------------------
  var scanText = $("scan-text");
  var scanResultEl = $("scan-result");
  var scanStatusEl = $("scan-status");

  function scanCount() {{
    var el = $("scan-count");
    if (!el || !scanText) return;
    var length = scanText.value.length;
    var max = Number(scanText.getAttribute("data-max")) || 0;
    el.textContent = max && length > max ?
      length.toLocaleString("ko-KR") + "자 — 앞 " + max.toLocaleString("ko-KR") + "자만 스캔합니다" :
      length.toLocaleString("ko-KR") + "자";
  }}

  function scanFinding(row) {{
    var refs = (row.law_refs || []).map(function (key) {{
      return '<span class="kbd">' + esc(key) + '</span>';
    }}).join(" ");
    return '<div class="finding">' +
      '<div class="finding-head"><h4>' + esc(row.title_ko) + '</h4>' +
        badge(row.severity, row.severity_label_ko) + '</div>' +
      '<blockquote class="quote">' + esc(row.matched_text_ko) + '</blockquote>' +
      '<p class="why">' + esc(row.note_ko || row.category_label_ko) + '</p>' +
      '<p class="req"><b>본부에 요청할 문구</b><br>' + esc(row.request_edit_ko) + '</p>' +
      '<details><summary>왜 문제인가 · 물어볼 것</summary>' +
        '<div class="body"><b>이유</b><br>' + esc(row.why_ko) +
        '<br><br><b>물어볼 것</b><br>' + esc(row.ask_ko) + '</div>' +
      '</details>' +
      '<div class="lawbox">근거 조문 ' + refs + '</div>' +
    '</div>';
  }}

  function scanRender(data) {{
    var counts = data.counts || {{}};
    var verdict = data.verdict || {{}};
    var html = '<div class="verdict"><div><h3>' + esc(verdict.label_ko || "") + '</h3>' +
      '<p class="kv">확인 필요 문구 ' + esc(counts.flagged || 0) + '건(높음 ' +
      esc(counts.high || 0) + ' · 주의 ' + esc(counts.medium || 0) + ') · 대조한 유형 ' +
      esc(counts.rules_checked || 0) + '개</p></div>' +
      badge(verdict.code, verdict.label_ko) + '</div>' +
      '<p class="summary">' + esc(data.summary_ko) + '</p>' +
      '<p class="notice" style="margin-top:12px">' + esc(data.not_a_clearance_ko) + '</p>';
    var findings = data.findings || [];
    if (findings.length) {{
      html += '<div class="section"><h3>확인이 필요한 문구 <span class="count">' +
        findings.length + '건</span></h3>' + findings.map(scanFinding).join("") + '</div>';
    }}
    var checks = data.checks_ko || [];
    if (checks.length) {{
      html += '<div class="section"><h3>대조한 유형 <span class="count">' + checks.length +
        '개</span></h3><ul class="scan-checks">' + checks.map(function (row) {{
          return '<li><b>' + esc(row.title_ko) + '</b> — ' + esc(row.result_ko) + '</li>';
        }}).join("") + '</ul></div>';
    }}
    html += lawBoxes(data.law_basis, data.law_basis_scope_ko);
    if ((data.questions_ko || []).length) {{
      html += '<div class="section"><h3>계약 전에 확인할 것</h3><ul class="clean">' +
        data.questions_ko.map(function (q) {{ return '<li>' + esc(q) + '</li>'; }}).join("") +
        '</ul></div>';
    }}
    html += '<p class="hint">' + esc(data.disclaimer_ko) + '</p>';
    scanResultEl.innerHTML = html;
    scanResultEl.hidden = false;
  }}

  function scanRun() {{
    if (!scanText) return;
    var text = String(scanText.value || "").trim();
    if (!text) {{
      scanStatusEl.className = "status err";
      scanStatusEl.textContent = "계약서·특약 문구를 붙여 넣어 주세요.";
      return;
    }}
    var button = $("scan-run");
    scanStatusEl.className = "status";
    scanStatusEl.textContent = "문구를 조문 유형과 대조하는 중…";
    button.disabled = true;
    fetch("/v1/tools/scan_contract_text", {{
      method: "POST", headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{text: text}})
    }}).then(function (response) {{
      return response.json().then(function (body) {{ return {{ok: response.ok, body: body}}; }});
    }}).then(function (out) {{
      if (!out.ok || !out.body || out.body.ok === false) {{
        throw new Error((out.body && (out.body.message || out.body.error)) || "스캔에 실패했습니다.");
      }}
      scanRender(out.body.result);
      scanStatusEl.textContent = "스캔 완료. 잡히는 문구가 없어도 원문 전체 검토는 따로 필요합니다.";
    }}).catch(function (error) {{
      scanStatusEl.className = "status err";
      scanStatusEl.textContent = "오류: " + error.message;
    }}).finally(function () {{
      button.disabled = false;
    }});
  }}

  Array.prototype.forEach.call(document.querySelectorAll("button.sample"), function (button) {{
    button.addEventListener("click", function () {{
      var name = button.getAttribute("data-sample");
      var sample = SCAN_SAMPLES_TEXT[name];
      if (!sample || !scanText) return;
      scanText.value = sample;
      scanCount();
      scanRun();
    }});
  }});

  if (scanText) scanText.addEventListener("input", scanCount);
  $("scan-run").addEventListener("click", scanRun);
  $("scan-clear").addEventListener("click", function () {{
    scanText.value = "";
    scanCount();
    scanResultEl.hidden = true;
    scanStatusEl.textContent = "";
  }});
  scanCount();

  moneySum();
  prefillFromUrl();
}})();
</script>
</body>
</html>
"""
