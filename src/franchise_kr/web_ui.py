"""사람용 단일 페이지 웹 UI (`GET /`) — 로그인 없이 10초 체크.

원칙 (0.1.12 — 첫 화면 단순화)
------------------------------
1. **한 화면에 하나**: 첫 화면은 "브랜드명(또는 업종) 입력 + [리스크 확인하기]" 하나와
   예시 3개뿐이다. 금액·계약 조건 30여 개는 `상세 조건 입력` 안에 접어 둔다.
2. **외부 의존 0**: CSS·JS·아이콘 전부 인라인(CDN·폰트·트래커 없음). CSP 가 외부 로드를 막는다.
3. **개인정보 최소**: 판정 폼에서 이름·연락처·주민등록번호를 받지 않는다. 입력값은 요청 1회로만
   쓰고 서버에 저장하지 않는다(카운터에도 남기지 않음). 예외는 맨 아래 **문의 카드** 하나로,
   거기 직접 적은 연락처만 `POST /v1/inquiry` 로 보내 회신 목적으로 보관한다.
4. **단정 금지**: 판정 문구는 "확인 필요 신호 있음 / 정보 부족 / 뚜렷한 위험 신호 없음" 세 가지.
5. **결과는 신호등 → 지표 → 질문 순서**: 맨 위 종합 카드 하나로 "어디를 봐야 하는지"를 정하고,
   초기 투자비용·폐점률·법적 분쟁·체크할 질문 네 칸, 그다음 확인할 신호와 물어볼 질문.
   근거 조문·체크리스트·비용 구조는 `자세히 보기` 안에 둔다.
6. **한 번 더 물어보기**: 모르는 항목은 결과 화면에서 한 번에 답할 수 있는 질문 3개로 돌려준다.
7. **문구 스캔**: 계약서·특약 문구만 받아 대조한다. 문구는 저장하지 않고, 입·출력 어디에도
   '안전·문제없음'을 쓰지 않는다.
"""
from __future__ import annotations

import json
import os as _os
from typing import Any, Dict, List, Optional

from . import engine, live_api, site_verification
from .version import (CLNS_URL, DISCLOSURE_PORTAL, GRANT_URL, SERVICE_NAME,
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
  padding:20px 0 16px;border-bottom:1px solid var(--line)}
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
.presets{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
@media (max-width:760px){.presets{grid-template-columns:1fr}}
button.preset{text-align:left;background:var(--surface-2);border:1px solid var(--line);border-radius:12px;
  padding:12px 13px;min-height:64px;display:flex;flex-direction:column;gap:4px}
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

/* ---- 0.1.12 첫 화면 단순화 — 새 구성 요소 -------------------------------- */
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
.hero{padding:26px 22px 22px}
.hero h2{font-size:25px;line-height:1.28;margin:0 0 8px;letter-spacing:-.4px}
.hero .lead{margin:0 0 18px;font-size:14.5px;line-height:1.6;color:var(--ink-soft);max-width:46ch}
.hero .lead b{color:var(--ink)}
.search-row{display:flex;gap:10px;align-items:stretch}
.search-row input{font-size:17px;min-height:56px;border-radius:12px;background:var(--card);padding:13px 15px}
button.primary.big{font-size:16.5px;padding:0 22px;min-height:56px;white-space:nowrap}
@media (max-width:640px){.search-row{flex-direction:column}button.primary.big{width:100%}
  .hero{padding:22px 18px}.hero h2{font-size:22px}}
.chips{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:14px}
.chips-label{font-size:12px;font-weight:700;color:var(--ink-soft)}
button.chip{font-size:13.5px;font-weight:700;color:var(--ink);background:var(--surface-2);
  border:1px solid var(--line);border-radius:999px;padding:9px 14px;min-height:40px}
button.chip:hover{border-color:var(--brand)}
details.more{margin-top:22px;border-top:1px solid var(--line);padding-top:16px}
details.more>summary{cursor:pointer;font-size:14.5px;font-weight:800;color:var(--ink);
  list-style:none;display:flex;gap:8px;align-items:baseline}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::before{content:"+";font-weight:800;color:var(--brand);font-size:16px}
details.more[open]>summary::before{content:"–"}
details.more>summary .note{font-size:12px;font-weight:600;color:var(--ink-soft)}
.more-body{margin-top:14px}
.more-body>h4{margin:20px 0 10px;font-size:13px;font-weight:800;color:var(--ink-soft)}
.group{margin-top:20px}
.group:first-of-type{margin-top:16px}
.group>h4{margin:0 0 10px;font-size:13px;font-weight:800;color:var(--ink-soft)}
.signal{border:2px solid var(--line);border-radius:16px;padding:22px;background:var(--card)}
.signal.check{border-color:var(--danger);background:var(--danger-soft)}
.signal.info{border-color:var(--warn);background:var(--warn-soft)}
.signal.low{border-color:var(--ok);background:var(--ok-soft)}
.signal .state{margin:0;font-size:12px;font-weight:800;letter-spacing:.06em;color:var(--ink-soft)}
.signal .big{margin:6px 0 0;font-size:27px;line-height:1.25;font-weight:800;letter-spacing:-.4px;
  color:var(--ink);word-break:keep-all}
.signal .say{margin:9px 0 0;font-size:14.5px;line-height:1.65;color:var(--ink)}
.signal .meta-line{margin:12px 0 0;font-size:12.5px;color:var(--ink-soft)}
.facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;margin-top:14px;
  background:var(--line);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.facts .cell{background:var(--card);padding:11px 13px}
.facts .k{display:block;font-size:11.5px;font-weight:700;color:var(--ink-soft)}
.facts .v{display:block;margin-top:2px;font-size:14.5px;font-weight:800;color:var(--ink);word-break:keep-all}
.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
@media (max-width:560px){.metrics{grid-template-columns:1fr}}
.metric{border:1px solid var(--line);border-radius:13px;padding:15px 16px;background:var(--card)}
.metric .k{font-size:12.5px;font-weight:700;color:var(--ink-soft)}
.metric .v{margin-top:5px;font-size:20px;font-weight:800;color:var(--ink);letter-spacing:-.2px;
  word-break:keep-all}
.metric .d{margin-top:5px;font-size:12.5px;line-height:1.5;color:var(--ink-soft)}
.quick{margin-top:16px;border:1px solid var(--line);border-radius:13px;padding:16px;background:var(--surface-2)}
.quick h3{margin:0;font-size:14.5px}
.quick .qq{margin-top:14px}
.quick .qq>span{display:block;font-size:13.5px;font-weight:700;color:var(--ink)}
.quick .opts{display:flex;gap:6px;flex-wrap:wrap;margin-top:7px}
button.opt{font-size:13px;font-weight:700;color:var(--ink);background:var(--card);
  border:1px solid var(--line);border-radius:9px;padding:8px 12px;min-height:38px}
button.opt:hover{border-color:var(--brand)}
.result-head{margin:24px 0 10px;font-size:15.5px;font-weight:800;letter-spacing:-.2px}
.morebox{margin-top:18px;border:1px solid var(--line);border-radius:12px;padding:0 16px;
  background:var(--card)}
.morebox>summary{cursor:pointer;font-size:14px;font-weight:800;color:var(--ink);padding:14px 0;
  list-style:none}
.morebox>summary::-webkit-details-marker{display:none}
.morebox>summary::before{content:"＋ ";color:var(--brand)}
.morebox[open]>summary::before{content:"－ "}
.morebox .more-inner{padding:2px 0 18px;border-top:1px solid var(--line)}
.quiet{background:var(--surface-2)}
.quiet h2{font-size:15.5px}
.say{margin:10px 0 0;font-size:14px;line-height:1.6}
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

# 첫 화면 예시 3개 — 브랜드명을 넣고 한 번에 결과를 보는 용도(단일 브랜드로 잡히는 이름만).
QUICK_BRANDS = ["컴포즈커피", "굽네치킨", "파리바게뜨"]

# 결과 화면에서 한 번에 답하는 질문 — 모르는 항목을 3개까지만 물어본다.
QUICK_ANSWERS = [
    {
        "field": "disclosure_days_before",
        "q": "정보공개서를 받고 14일이 지났나요?",
        "match": "며칠이 지났나요",
        "opts": [
            {"l": "14일 넘었어요", "set": {"disclosure_days_before": 21, "contract_doc_days_before": 21}},
            {"l": "아직이에요", "set": {"disclosure_days_before": 0, "contract_doc_days_before": 0}},
        ],
    },
    {
        "field": "payment_route",
        "q": "가맹금은 어디로 내라고 하나요?",
        "match": "어디로 내라고",
        "opts": [
            {"l": "예치기관", "set": {"payment_route": "escrow"}},
            {"l": "피해보상보험", "set": {"payment_route": "insurance"}},
            {"l": "본사 계좌", "set": {"payment_route": "hq_account"}},
            {"l": "정하지 않았어요", "set": {"payment_route": "none"}},
        ],
    },
    {
        "field": "interior_designated",
        "q": "인테리어·집기를 직접 고를 수 있나요?",
        "match": "본사가 지정하나요",
        "opts": [
            {"l": "자유롭게 고를 수 있어요", "set": {"interior_designated": "free"}},
            {"l": "일부만 지정", "set": {"interior_designated": "partial"}},
            {"l": "본부 지정 강제", "set": {"interior_designated": "forced"}},
        ],
    },
    {
        "field": "territory",
        "q": "계약서에 영업지역이 적혀 있나요?",
        "match": "영업지역",
        "opts": [
            {"l": "독점으로 적혀 있음", "set": {"territory": "exclusive"}},
            {"l": "영업지역만 적혀 있음", "set": {"territory": "defined"}},
            {"l": "없어요", "set": {"territory": "none"}},
        ],
    },
    {
        "field": "revenue_written",
        "q": "매출 보장을 서면으로 받았나요?",
        "match": "매출 보장을 서면",
        "opts": [
            {"l": "받았어요", "set": {"revenue_written": "true"}},
            {"l": "못 받았어요", "set": {"revenue_written": "false"}},
        ],
    },
    {
        "field": "legal_violation",
        "q": "본부가 공정위 시정조치·과징금을 받은 적이 있나요?",
        "match": "시정조치",
        "opts": [
            {"l": "있어요", "set": {"legal_violation": "true"}},
            {"l": "없어요", "set": {"legal_violation": "false"}},
        ],
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


# 선택 항목의 도움말 — SELECTS 한 곳에서만 렌더한다(중복 id·중복 필드 방지).
SELECT_HINTS = {
    "payment_route": "예치·피해보상보험 없이 본사 계좌로 보내면 회수 장치가 사라집니다.",
    "interior_designated": "지정 업체 100% 강제는 구입강제 유형으로 봅니다.",
    "territory": "독점 영업지역이 계약서에 적혀 있는지가 기준입니다.",
    "ad_cost_burden": "점주 의무 부담이면 동의 절차·집행 내역 공개 여부를 확인하세요.",
}


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


def _presets_html() -> str:
    buttons = []
    for preset in PRESETS:
        buttons.append(
            f'<button type="button" class="preset" data-preset="{preset["id"]}">'
            f'<span class="t">{preset["title"]}</span>'
            f'<span class="d">{preset["desc"]}</span></button>'
        )
    return "".join(buttons)


def _chips_html() -> str:
    return "".join(
        f'<button type="button" class="chip" data-query="{name}">{name}</button>'
        for name in QUICK_BRANDS
    )


def _detail_form_html() -> str:
    """접어 둔 상세 조건 — 모든 판정 입력은 여기에만 있다(첫 화면에는 없다)."""
    money_fields = "".join([
        _field("franchise_fee_krw", "가맹비", hint="예: 1100만원", extra=' inputmode="numeric"'),
        _field("education_fee_krw", "가맹교육비", hint="예: 330만원", extra=' inputmode="numeric"'),
        _field("deposit_krw", "가맹보증금", hint="예: 1000만원", extra=' inputmode="numeric"'),
        _field("interior_krw", "인테리어 비용", hint="예: 5500만원", extra=' inputmode="numeric"'),
        _field("equipment_krw", "설비·집기", hint="예: 2000만원", extra=' inputmode="numeric"'),
        _field("other_krw", "기타 비용", hint="예: 초도물량·간판", extra=' inputmode="numeric"'),
    ])
    return f"""
<p class="hint">계약 조건을 넣으면 위험 신호를 계산합니다. 모르는 항목은 비워 두세요 — 비운 항목은
  '괜찮다'가 아니라 <b>되물어볼 질문</b>으로 돌려드립니다. 이름·연락처·주민등록번호는 받지 않고,
  입력값은 서버에 저장하지 않습니다.</p>

<h4 class="group-title">자주 오는 상황으로 채우기</h4>
<div class="presets">{_presets_html()}</div>

<div class="group">
  <h4>1. 계약 일정</h4>
  <div class="grid">
    {_field("disclosure_days_before", "정보공개서 받은 뒤 지난 날", kind="number",
            hint="당일이면 0. 14일(자문 시 7일) 전에 계약·입금하면 위반입니다.", extra=' min="0" step="1"')}
    {_field("contract_doc_days_before", "계약서 초안 받은 뒤 지난 날", kind="number",
            hint="계약서도 같은 숙고기간이 적용됩니다.", extra=' min="0" step="1"')}
    {_select_field("advisor_reviewed", "변호사·가맹거래사 자문", [("", "모름"), ("true", "받음"), ("false", "안 받음")],
                   "자문을 받으면 숙고기간이 7일로 줄어듭니다.")}
  </div>
</div>

<div class="group">
  <h4>2. 돈</h4>
  <div class="grid three">
    {money_fields}
    <div class="full"><span class="inline-sum" id="money-sum">총투자: 항목을 넣으면 자동으로 합산합니다.</span></div>
  </div>
  <div class="grid" style="margin-top:14px">
    {_select_field("payment_route", SELECTS[0][1], SELECTS[0][2], SELECT_HINTS["payment_route"])}
    {_field("penalty_ratio_pct", "중도해지 위약금(총투자 대비 %)", kind="number",
            hint="모르면 비워 두세요. 20% 이상이면 신호입니다.", extra=' min="0" step="1"')}
  </div>
</div>

<div class="group">
  <h4>3. 계약 조건</h4>
  <div class="grid">
    {_select_field("interior_designated", SELECTS[1][1], SELECTS[1][2], SELECT_HINTS["interior_designated"])}
    {_select_field("territory", SELECTS[2][1], SELECTS[2][2], SELECT_HINTS["territory"])}
    {_select_field("ad_cost_burden", SELECTS[3][1], SELECTS[3][2], SELECT_HINTS["ad_cost_burden"])}
    {_field("termination_grace_months", "본부 해지 시 유예기간(개월)", kind="number",
            hint="법은 2개월 이상 유예와 서면 2회 통지를 요구합니다.", extra=' min="0" step="1"')}
    {_field("renewal_years", "최초 포함 전체 계약기간(년)", kind="number",
            hint="갱신 요구권은 전체 10년을 넘지 않습니다.", extra=' min="0" step="1"')}
    {_select_field("sales_target", "판매목표 강제", YES_NO_UNKNOWN,
                   "목표 미달 시 불이익이 있으면 불공정거래행위가 될 수 있습니다.")}
    {_select_field("supplier_designated", "거래처(공급처) 지정", YES_NO_UNKNOWN,
                   "특정 업체와만 거래하도록 강제하면 구입강제가 될 수 있습니다.")}
    {_select_field("mandatory_purchase", SELECTS[8][1], SELECTS[8][2],
                   "필수품목으로 묶인 물품이 있는지 확인하세요.")}
    {_select_field("price_fixing", SELECTS[9][1], SELECTS[9][2],
                   "본부가 판매가격을 정하면 가격 구속 유형을 검토할 수 있습니다.")}
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
</div>

<div class="group">
  <h4>4. 본부 이력·매출</h4>
  <div class="grid">
    {_select_field("legal_violation", SELECTS[6][1], SELECTS[6][2],
                   "공정위 시정조치·과징금·형벌선고 이력을 확인했는지 답해 주세요.")}
    {_select_field("disclosure_registered", SELECTS[7][1], SELECTS[7][2],
                   "가맹사업정보제공시스템에서 등록 정보공개서를 봤는지 답해 주세요.")}
    {_field("closure_rate_3y_pct", "최근 3년 폐점률(%)", kind="number",
            hint="모르면 비워 두세요. 15% 이상이면 위험 높음입니다.", extra=' min="0" step="1"')}
    {_select_field("revenue_written", SELECTS[4][1], SELECTS[4][2],
                   "매출을 언급했다면 서면을 요구하세요.")}
    {_select_field("revenue_estimate_doc", SELECTS[5][1], SELECTS[5][2],
                   "예상매출액 산정서와 산출근거를 받았는지 답해 주세요.")}
    {_field("revenue_claim_ko", "본부가 한 매출 관련 말", hint="예: 월 매출 5천 보장",
            extra=' autocomplete="off"')}
  </div>
</div>
"""


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
  <p class="sub">본부가 보낸 계약서·특약 문구를 그대로 붙여 넣으면 불공정 유형 {len(engine.CONTRACT_RULES)}개와
    대조해 <b>확인이 필요한 문구</b>와 본부에 요청할 수정 문구를 짚어 줍니다.
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


def _siblings_html() -> str:
    """같이 쓰는 서비스 — CLNS(수입·유통)·GRNT(정부지원금)로 가는 한 줄 생태계 링크.

    세 서비스 모두 무료ㆍ회원가입 없음이다. 외부 링크는 새 탭 + noopener 로 연다.
    (CLNSㆍGRNT 화면의 '같이 쓰는 서비스' 카드와 같은 문구를 쓴다.)
    """
    return f"""
<section class="card quiet" id="siblings">
  <h2>같이 쓰는 서비스</h2>
  <p class="sub">같은 팀이 무료로 운영하는 두 도구입니다. 세 서비스 모두 회원가입ㆍ결제가 없고,
  판정은 공정위ㆍ정부가 공개한 원본 자료로만 합니다.</p>
  <ul class="clean">
    <li><a href="{CLNS_URL}" target="_blank" rel="noopener noreferrer"><b>CLNS</b></a> — 수입ㆍ유통 규제 체크(세관장확인ㆍKCㆍ식약처ㆍ리콜)</li>
    <li><a href="{GRANT_URL}" target="_blank" rel="noopener noreferrer"><b>GRNT</b></a> — 개인ㆍ창업 정부지원금 판정기(보조금24ㆍK-Startupㆍ기업마당)</li>
  </ul>
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
<form id="inquiry" class="card quiet" novalidate>
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


def home_json_ld(root: str) -> str:
    """홈 구조화 데이터 — Organization · WebSite · WebApplication 을 `@id` 로 연결한다.

    AI 검색·검색엔진이 "이 사이트가 무엇을 하는 곳인지"를 한 덩어리로 읽게 한다.
    판정 문구는 넣지 않고(단정 금지), 서비스 성격·무료 여부·툴 범위만 적는다.
    """
    graph: List[Dict[str, Any]] = [
        {
            "@type": "Organization",
            "@id": root + "/#org",
            "name": SERVICE_NAME,
            "url": root + "/",
        },
        {
            "@type": "WebSite",
            "@id": root + "/#website",
            "name": f"{SERVICE_NAME} — {SERVICE_TITLE_KO}",
            "url": root + "/",
            "inLanguage": "ko-KR",
            "publisher": {"@id": root + "/#org"},
            "potentialAction": {
                "@type": "SearchAction",
                "target": {"@type": "EntryPoint",
                           "urlTemplate": root + "/?brand={search_term_string}"},
                "query-input": "required name=search_term_string",
            },
        },
        {
            "@type": "WebApplication",
            "@id": root + "/#app",
            "name": SERVICE_NAME,
            "url": root + "/",
            "applicationCategory": "BusinessApplication",
            "operatingSystem": "Web",
            "inLanguage": "ko-KR",
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "KRW"},
            "description": (
                "프랜차이즈 가입 전 가맹사업법·시행령 조문과 대조해 확인할 위험 신호·"
                "체크리스트·질문·근거 조문을 정리하는 무료 사전 점검 서비스. 확정 판정이 아니다."
            ),
            "featureList": [
                "가맹금·인테리어·숙고기간·영업지역 등 핵심 축 리스크 체크",
                "계약서·특약 문구 스캔(원문 인용·근거 조문·수정 요청 문구)",
                "브랜드 정보공개서 요약(공정위 가맹정보)",
                "MCP(JSON-RPC 2.0) 툴과 REST JSON 동시 제공",
            ],
            "isPartOf": {"@id": root + "/#website"},
            "publisher": {"@id": root + "/#org"},
        },
    ]
    body = {"@context": "https://schema.org", "@graph": graph}
    return ('<script type="application/ld+json">'
            + json.dumps(body, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
            + "</script>")


SCRIPT = """
(function () {
  "use strict";
  var PRESETS = __PRESETS__;
  var SCAN_SAMPLES_TEXT = __SAMPLES__;
  var QUICK = __QUICK__;
  var MONEY = ["franchise_fee_krw","education_fee_krw","deposit_krw","interior_krw",
    "equipment_krw","other_krw"];
  var form = document.getElementById("check");
  var resultCard = document.getElementById("result-card");
  var resultEl = document.getElementById("result");
  var statusEl = document.getElementById("status");
  var lastResult = null;
  var lastBrand = null;

  function $(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
      .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  }
  function won(value) {
    if (value === null || value === undefined || value === "") return "";
    var n = Number(String(value).replace(/[^0-9.-]/g,""));
    if (!isFinite(n) || n <= 0) return String(value);
    var eok = Math.floor(n / 100000000), man = Math.floor((n % 100000000) / 10000);
    var out = [];
    if (eok) out.push(eok.toLocaleString("ko-KR") + "억");
    if (man) out.push(man.toLocaleString("ko-KR") + "만");
    return out.length ? out.join(" ") + "원" : n.toLocaleString("ko-KR") + "원";
  }
  function moneySum() {
    var total = 0, any = false;
    MONEY.forEach(function (name) {
      var el = $(name); if (!el || !el.value) return;
      var text = String(el.value).replace(/,/g,"");
      var mult = 1;
      if (text.indexOf("억") >= 0) { mult = 100000000; text = text.replace("억",""); }
      else if (text.indexOf("만") >= 0) { mult = 10000; text = text.replace(/만원?/,""); }
      var n = parseFloat(text);
      if (isFinite(n)) { total += n * mult; any = true; }
    });
    var sumEl = $("money-sum");
    if (!sumEl) return;
    sumEl.textContent = any ? "총투자 합계: " + won(total) + " (입력 항목 단순 합)" :
      "총투자: 항목을 넣으면 자동으로 합산합니다.";
  }

  function collect() {
    var payload = {};
    var nodes = form.querySelectorAll("input[name],select[name],textarea[name]");
    Array.prototype.forEach.call(nodes, function (el) {
      var value = String(el.value || "").trim();
      if (value) payload[el.name] = value;
    });
    return payload;
  }

  function fill(values) {
    Object.keys(values).forEach(function (key) {
      var el = $(key);
      if (el) el.value = String(values[key]);
    });
    moneySum();
  }

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (response) {
      return response.json().then(function (data) { return { ok: response.ok, data: data }; });
    }).then(function (out) {
      if (!out.ok || !out.data || out.data.ok === false) {
        throw new Error((out.data && (out.data.message || out.data.error)) || "요청에 실패했습니다.");
      }
      return out.data.result;
    });
  }

  function lookup(query) {
    if (!query) return Promise.resolve(null);
    var body = /^brd_/i.test(query) ? { brand_code: query } : { brand_name: query };
    return post("/v1/tools/lookup_brand_disclosure", body).then(function (data) {
      var brands = data.brands || [];
      return {
        brands: brands,
        count: brands.length,
        zero: Boolean(data.zero_result) || brands.length === 0,
        single: brands.length === 1 ? brands[0] : null
      };
    }).catch(function () { return null; });
  }

  function badge(code, label) {
    return '<span class="badge ' + esc(code) + '">' + esc(label) + '</span>';
  }

  function riskItem(row) {
    var refs = (row.law_refs || []).map(function (key) {
      return '<span class="kbd">' + esc(key) + '</span>';
    }).join(" ");
    var why = row.note_ko || row.why_ko || row.category_label_ko || "";
    return '<div class="risk">' +
      '<div class="risk-head"><h4>' + esc(row.title_ko) + '</h4>' +
        badge(row.severity, row.severity_label_ko) + '</div>' +
      '<p class="why">' + esc(why) + '</p>' +
      '<details><summary>왜 문제인가 · 물어볼 것</summary><div class="body">' +
        '<b>이유</b><br>' + esc(row.why_ko) +
        (row.regret_ko ? '<br><br><b>되돌리기 어려운 점</b><br>' + esc(row.regret_ko) : '') +
        (row.fix_ko ? '<br><br><b>지금 할 일</b><br>' + esc(row.fix_ko) : '') +
        (row.ask_ko ? '<br><br><b>물어볼 것</b><br>' + esc(row.ask_ko) : '') +
      '</div></details>' +
      (refs ? '<div class="lawbox">근거 조문 ' + refs + '</div>' : '') +
    '</div>';
  }

  function lawBoxes(rows, scope) {
    if (!rows || !rows.length) return "";
    return '<div class="section"><h3>근거 조문 <span class="count">법제처 OPEN API 실조회</span></h3>' +
      (scope ? '<p class="hint">' + esc(scope) + '</p>' : '') +
      rows.map(function (row) {
        return '<div class="lawbox"><b>' + esc(row.label_ko || row.key) + '</b>' +
          '<br>' + esc(row.excerpt_ko) +
          '<span class="src">' + esc(row.effective_on || "") + ' 시행 · ' + esc(row.source_url || "") + '</span></div>';
      }).join("") + '</div>';
  }

  function moneyBlock(money) {
    if (!money || !money.components || !money.components.length) return "";
    var rows = money.components.map(function (row) {
      return '<tr><td>' + esc(row.label_ko) + '</td><td class="num">' + esc(row.amount_ko) + '</td>' +
        '<td class="num">' + (row.share_pct === null || row.share_pct === undefined ? "" : row.share_pct + "%") + '</td></tr>';
    }).join("");
    return '<div class="section"><h3>비용 구조 <span class="count">' + esc(money.total_ko || "") + '</span></h3>' +
      '<table class="money-table"><thead><tr><th>항목</th><th class="num">금액</th><th class="num">비중</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table>' +
      (money.note_ko ? '<p class="hint">' + esc(money.note_ko) + '</p>' : '') + '</div>';
  }

  // ---- 결과:① 종합 신호 카드 -------------------------------------------
  function signalBlock(result, risks, brandOne, hasQuick) {
    var code = (result.verdict || {}).code || "info_needed";
    var c = result.counts || {};
    var cov = result.coverage || {};
    var cls = code === "check_likely" ? "check" : (code === "low_risk" ? "low" : "info");
    var big, say;
    if (code === "check_likely") {
      big = "주의 신호 " + (c.triggered || 0) + "건";
      say = (risks[0] ? "가장 먼저 볼 것은 ‘" + risks[0].title_ko + "’입니다. " : "") +
        "아래에서 이유와 본부에 물어볼 것을 확인하세요.";
    } else if (code === "low_risk") {
      big = "뚜렷한 위험 신호 없음";
      say = "입력한 항목에서는 두드러진 신호가 잡히지 않았습니다. 확정 판정이 아니므로 서류 원문과 현장을 따로 확인하세요.";
    } else {
      big = "아직 판단하기 이르다";
      var totalAxes = cov.total_axes || 8;
      var emptyAxes = Math.max(0, totalAxes - (cov.answered_axes || 0));
      say = "핵심 항목 " + totalAxes + "개 중 " + emptyAxes + "개가 아직 비어 있습니다. " +
        (hasQuick ? "아래에서 3개만 답하면 신호가 있는지 좁혀집니다."
                  : "아래 질문에 답하고 상세 조건을 채우면 신호가 있는지 좁혀집니다.");
    }
    var bits = [];
    if (brandOne && brandOne.brand_name) bits.push(String(brandOne.brand_name));
    if (brandOne && brandOne.stores_year_end !== null && brandOne.stores_year_end !== undefined) {
      bits.push("가맹점 " + Number(brandOne.stores_year_end).toLocaleString("ko-KR") + "곳");
    }
    bits.push("확인한 항목 " + (cov.answered_axes || 0) + "/" + (cov.total_axes || 8));
    if (c.high) bits.push("높음 " + c.high + "건");
    if (c.medium) bits.push("주의 " + c.medium + "건");
    if (result.risk_score) bits.push("위험 점수 " + result.risk_score);
    return '<div class="signal ' + cls + '">' +
      '<p class="state">종합 판정</p>' +
      '<p class="big">' + esc(big) + '</p>' +
      '<p class="say">' + esc(say) + '</p>' +
      '<p class="meta-line">' + esc(bits.join(" · ")) + '</p>' +
    '</div>';
  }

  // ---- 결과:② 브랜드 기본 정보 / 비슷한 브랜드 --------------------------
  function fmtDate(value) {
    var text = String(value === null || value === undefined ? "" : value);
    return text.length === 8 ? text.slice(0, 4) + "-" + text.slice(4, 6) + "-" + text.slice(6) : text;
  }

  function cell(key, value) {
    return '<div class="cell"><span class="k">' + esc(key) + '</span>' +
      '<span class="v">' + esc(value || "—") + '</span></div>';
  }

  function factsBlock(brand, query) {
    if (!brand) return "";
    if (brand.count > 1) {
      var picked = brand.brands.slice(0, 5).map(function (b) {
        return '<button type="button" class="chip" data-query="' + esc(b.brand_name) + '">' +
          esc(b.brand_name) + '</button>';
      }).join("");
      return '<p class="say">‘' + esc(query) + '’로 ' + brand.count +
        '개 브랜드가 검색되었습니다. 확인할 브랜드를 눌러 주세요.</p>' +
        '<div class="chips">' + picked + '</div>';
    }
    if (brand.zero) {
      return '<p class="notice info">‘' + esc(query) +
        '’로 등록 브랜드를 찾지 못했습니다. 입력한 조건만으로 확인했습니다. ' +
        '0건은 ‘등록된 브랜드가 없다’는 뜻도, ‘문제없다·안전하다’는 뜻도 아닙니다.</p>';
    }
    var b = brand.single || {};
    var industry = [b.industry_large, b.industry_mid].filter(Boolean).join(" · ");
    var stores = (b.stores_year_end === null || b.stores_year_end === undefined) ? "—" :
      Number(b.stores_year_end).toLocaleString("ko-KR") + "곳";
    var direct = (b.direct_stores === null || b.direct_stores === undefined) ? "—" :
      Number(b.direct_stores).toLocaleString("ko-KR") + "곳";
    var html = '<div class="facts">' +
      cell("브랜드", b.brand_name) +
      cell("본부", b.hq_name) +
      cell("업종", industry) +
      cell("가맹사업 시작", fmtDate(b.started_on)) +
      cell("가맹점", stores) +
      cell("직영점", direct) +
    '</div>';
    if (stores === "—") {
      html += '<p class="hint">가맹점 수·폐점률 같은 일부 항목은 공정위 데이터셋 연동 전이라 비어 있을 수 있습니다. ' +
        '정보공개서 원문에서 확인하세요.</p>';
    }
    html += '<p class="hint"><a href="' +
      esc(b.disclosure_url || "https://franchise.ftc.go.kr") +
      '" target="_blank" rel="noopener noreferrer">가맹사업정보제공시스템에서 정보공개서 원문 보기</a></p>';
    return html;
  }

  // ---- 결과:③ 핵심 지표 4개 --------------------------------------------
  function metric(k, v, d) {
    return '<div class="metric"><div class="k">' + esc(k) + '</div>' +
      '<div class="v">' + esc(v) + '</div><div class="d">' + esc(d) + '</div></div>';
  }

  function metricsBlock(result, brandOne, terms, questions) {
    var money = result.money || {};
    var total = money.total_ko || "";
    var investD = total
      ? (money.total_source === "computed" ? "입력 항목 단순 합 · 견적서로 다시 확인" : "직접 입력한 금액")
      : "가맹비·인테리어·보증금을 넣으면 합산합니다";
    var rate = null, rateSrc = "";
    if (brandOne && brandOne.closure_rate_pct !== null && brandOne.closure_rate_pct !== undefined) {
      rate = brandOne.closure_rate_pct + "%";
      rateSrc = "공정위 공개자료";
    } else if (terms.closure_rate_3y_pct !== undefined && terms.closure_rate_3y_pct !== null) {
      rate = terms.closure_rate_3y_pct + "%";
      rateSrc = "직접 입력값";
    }
    var stores = "";
    if (brandOne && brandOne.stores_year_end !== null && brandOne.stores_year_end !== undefined) {
      stores = "가맹점 " + Number(brandOne.stores_year_end).toLocaleString("ko-KR") + "곳";
      if (brandOne.direct_stores) {
        stores += " · 직영 " + Number(brandOne.direct_stores).toLocaleString("ko-KR") + "곳";
      }
    }
    var legal = "미확인";
    var legalD = "공정위 시정조치·과징금 이력은 정보공개서로 확인하세요";
    if (terms.legal_violation === true) {
      legal = "이력 있음";
      legalD = "시정조치·과징금 이력을 본부에 서면으로 요구하세요";
    } else if (terms.legal_violation === false) {
      legal = "없음(입력 기준)";
      legalD = "입력한 답 기준입니다. 계약 전 정보공개서로 다시 확인하세요";
    }
    var qV = questions.length ? questions.length + "가지" : "—";
    var qD = questions.length ? questions[0] : "확인할 질문이 없습니다";
    return '<div class="metrics">' +
      metric("초기 투자비용", total || "미입력", investD) +
      metric("폐점률", rate || "미확인",
             (stores ? stores + " · " : "") + (rate ? rateSrc : "정보공개서·본부에 문의")) +
      metric("법적 분쟁·행정처분", legal, legalD) +
      metric("체크할 질문", qV, qD) +
    '</div>';
  }

  // ---- 결과:④ 모르는 항목 3개를 그 자리에서 묻기 ------------------------
  function pickQuick(terms, code) {
    if (code === "low_risk") return [];
    var picked = [], index;
    for (index = 0; index < QUICK.length && picked.length < 3; index++) {
      var item = QUICK[index];
      var known = terms && terms[item.field] !== undefined && terms[item.field] !== null;
      if (!known) picked.push(index);
    }
    return picked;
  }

  function quickBlock(picked) {
    if (!picked.length) return "";
    var rows = picked.map(function (idx) {
      var row = QUICK[idx];
      var opts = row.opts.map(function (opt, oi) {
        return '<button type="button" class="opt" data-qi="' + idx + '" data-oi="' + oi + '">' +
          esc(opt.l) + '</button>';
      }).join("");
      return '<div class="qq"><span>' + esc(row.q) + '</span><div class="opts">' + opts + '</div></div>';
    }).join("");
    return '<div class="quick"><h3>' + picked.length + '가지만 답하면 더 정확해집니다</h3>' +
      '<p class="hint">고르면 바로 다시 확인합니다. 나머지 조건은 위 ‘상세 조건 입력’에서 넣을 수 있습니다.</p>' +
      rows + '</div>';
  }

  // ---- 결과:⑤ 접어 둔 자세히 보기 --------------------------------------
  function detailsBlock(result, risks, questions) {
    var html = "";
    var rest = risks.slice(3);
    if (rest.length) {
      html += '<h3>그 밖의 위험 신호 <span class="count">' + rest.length + '건</span></h3>' +
        rest.map(riskItem).join("");
    }
    var unknown = result.unknown_points || [];
    if (unknown.length) {
      html += '<h3>아직 모르는 항목 <span class="count">' + unknown.length + '건</span></h3>' +
        '<ul class="clean">' + unknown.slice(0, 10).map(function (row) {
          return '<li>' + esc(row.title_ko) + '</li>';
        }).join("") + '</ul>';
      if (unknown.length > 10) {
        html += '<p class="hint">그 밖에 ' + (unknown.length - 10) + '개 항목이 더 있습니다.</p>';
      }
    }
    var checklist = result.checklist_ko || [];
    if (checklist.length) {
      html += '<h3>계약 전 체크리스트</h3><ul class="clean">' +
        checklist.map(function (item) { return '<li>' + esc(item) + '</li>'; }).join("") + '</ul>';
    }
    if (questions.length > 5) {
      html += '<h3>물어볼 것이 더 있습니다</h3><ul class="clean">' +
        questions.slice(5).map(function (q) { return '<li>' + esc(q) + '</li>'; }).join("") + '</ul>';
    }
    html += moneyBlock(result.money);
    html += lawBoxes(result.law_basis, result.law_basis_scope_ko);
    var steps = result.next_steps || [];
    if (steps.length) {
      html += '<div class="section"><h3>다음 단계</h3><ol class="steps">' +
        steps.map(function (step) {
          var link = step.url ? ' <a href="' + esc(step.url) + '" target="_blank" rel="noopener noreferrer">열기</a>' : "";
          return '<li><b>' + esc(step.title_ko) + '</b> — ' + esc(step.detail_ko) + link + '</li>';
        }).join("") + '</ol></div>';
    }
    var support = result.startup_support || {};
    if (support.url) {
      html += '<div class="linkcard"><p>' + esc(support.note_ko) + '</p>' +
        '<a class="btn-link" href="' + esc(support.url) + '" target="_blank" rel="noopener noreferrer">' +
        esc(support.name_ko || "지원금 확인") + '</a></div>';
    }
    return '<details class="morebox"><summary>자세히 보기 — 모르는 항목·체크리스트·근거 조문</summary>' +
      '<div class="more-inner">' + html + '</div></details>';
  }

  function render(result, brand) {
    lastResult = result;
    lastBrand = brand;
    var risks = result.risk_points || [];
    var questions = result.questions_ko || [];
    var terms = result.terms_used || {};
    var brandOne = brand && brand.single ? brand.single : null;
    var code = (result.verdict || {}).code || "info_needed";
    var picked = pickQuick(terms, code);
    var quick = quickBlock(picked);
    // 방금 그 자리에서 물은 항목은 '물어볼 질문' 목록에서 빼서 같은 말을 두 번 하지 않는다.
    var asked = picked.map(function (idx) { return QUICK[idx].match || ""; });
    questions = questions.filter(function (q) {
      return !asked.some(function (key) { return key && q.indexOf(key) >= 0; });
    });
    var html = signalBlock(result, risks, brandOne, quick !== "");
    html += factsBlock(brand, (($("brand_name") || {}).value || "").trim());
    html += metricsBlock(result, brandOne, terms, questions);
    if (risks.length) {
      html += '<h3 class="result-head">먼저 확인할 것</h3>' + risks.slice(0, 3).map(riskItem).join("");
    }
    html += quick;
    if (questions.length) {
      html += '<h3 class="result-head">본부에 물어볼 질문</h3><ul class="clean">' +
        questions.slice(0, 5).map(function (q) { return '<li>' + esc(q) + '</li>'; }).join("") + '</ul>';
    }
    html += detailsBlock(result, risks, questions);
    html += '<p class="hint">' + esc(result.disclaimer_ko || "") + '</p>';
    resultEl.innerHTML = html;
    resultCard.hidden = false;
    resultCard.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function run() {
    var payload = collect();
    var query = String(($("brand_name") || {}).value || "").trim().slice(0, 60);
    if (!query && !Object.keys(payload).length) {
      statusEl.className = "status err";
      statusEl.textContent = "브랜드명이나 업종을 넣어 주세요.";
      var empty = $("brand_name");
      if (empty) empty.focus();
      return;
    }
    statusEl.className = "status";
    statusEl.textContent = query ? "공정위 자료와 법 조문을 확인하는 중…" : "법령 조문과 대조하는 중…";
    var button = $("run");
    if (button) button.disabled = true;
    lookup(query).then(function (brand) {
      if (brand && brand.single) {
        if (brand.single.industry_mid) payload.industry = brand.single.industry_mid;
      }
      return post("/v1/tools/check_franchise_risk", payload).then(function (result) {
        return { result: result, brand: brand };
      });
    }).then(function (out) {
      render(out.result, out.brand);
      statusEl.textContent = "확인 완료. 확정 판정이 아니므로 서류 원문과 함께 확인하세요.";
    }).catch(function (error) {
      statusEl.className = "status err";
      statusEl.textContent = "오류: " + error.message;
    }).finally(function () {
      if (button) button.disabled = false;
    });
  }

  function applyQuick(button) {
    var item = QUICK[Number(button.getAttribute("data-qi"))];
    if (!item) return;
    var opt = item.opts[Number(button.getAttribute("data-oi"))];
    if (!opt) return;
    Object.keys(opt.set).forEach(function (field) {
      var el = $(field);
      if (el) el.value = String(opt.set[field]);
    });
    moneySum();
    run();
  }

  // 첫 화면 예시·결과 안의 브랜드 칩·한 번에 답하기 — 한 곳에서 처리한다.
  document.body.addEventListener("click", function (event) {
    var node = event.target;
    while (node && node !== document.body && node.getAttribute &&
           !node.getAttribute("data-query") && !node.getAttribute("data-qi")) {
      node = node.parentNode;
    }
    if (!node || node === document.body || !node.getAttribute) return;
    if (node.getAttribute("data-query")) {
      var input = $("brand_name");
      if (input) input.value = node.getAttribute("data-query");
      run();
      return;
    }
    applyQuick(node);
  });

  Array.prototype.forEach.call(document.querySelectorAll("button.preset"), function (button) {
    button.addEventListener("click", function () {
      var name = button.getAttribute("data-preset");
      fill(PRESETS[name] || {});
      statusEl.className = "status";
      statusEl.textContent = "예시 조건을 채웠습니다: " + button.querySelector(".t").textContent;
      run();
    });
  });

  form.addEventListener("submit", function (event) { event.preventDefault(); run(); });
  MONEY.forEach(function (name) {
    var el = $(name); if (el) el.addEventListener("input", moneySum);
  });

  var copyButton = $("copy");
  function copyStatus(message) { $("copy-status").textContent = message; }
  function copyText(text, okMessage) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { copyStatus(okMessage); })
        .catch(function () { fallback(text, okMessage); });
    } else { fallback(text, okMessage); }
    function fallback(value, message) {
      var area = document.createElement("textarea");
      area.value = value; area.setAttribute("readonly", "readonly");
      area.style.position = "fixed"; area.style.opacity = "0";
      document.body.appendChild(area); area.select();
      try { document.execCommand("copy"); copyStatus(message); }
      catch (error) { copyStatus("복사 실패 — 화면의 내용을 직접 선택해 주세요."); }
      document.body.removeChild(area);
    }
  }

  // 비식별 공유 링크 — 브랜드명만 담고 금액·조건·연락처는 담지 않는다.
  function shareLink() {
    var el = $("brand_name");
    var brand = String((el && el.value) || "").trim().slice(0, 60);
    var base = location.origin + "/";
    return brand ? base + "?brand=" + encodeURIComponent(brand) + "#check" : base + "#check";
  }

  copyButton.addEventListener("click", function () {
    if (!lastResult) { copyStatus("먼저 리스크 확인하기를 눌러 주세요."); return; }
    var verdict = lastResult.verdict || {};
    var lines = ["FRNC 리스크 체크 — " + (verdict.label_ko || ""),
      "위험 점수 " + lastResult.risk_score + " (신호 " + (lastResult.counts || {}).triggered + "건)",
      lastResult.summary_ko || ""];
    (lastResult.risk_points || []).forEach(function (row) {
      lines.push("- [" + row.severity_label_ko + "] " + row.title_ko + " — " + (row.note_ko || ""));
    });
    (lastResult.questions_ko || []).slice(0, 5).forEach(function (q) { lines.push("? " + q); });
    lines.push("확정 판정 아님 · " + location.origin);
    copyText(lines.join("\\n"), "복사됨");
  });

  $("share").addEventListener("click", function () {
    copyText(shareLink(), "공유 링크 복사됨 — 브랜드명만 담깁니다.");
  });

  // ?brand=...#check 로 들어오면 브랜드명만 채운다(금액·조건은 손대지 않는다).
  function prefillFromUrl() {
    var brand = "";
    try {
      if (window.URLSearchParams) {
        brand = new URLSearchParams(location.search).get("brand") || "";
      }
    } catch (error) { brand = ""; }
    brand = String(brand).trim().slice(0, 60);
    if (!brand) return;
    var el = $("brand_name");
    if (!el) return;
    el.value = brand;
    statusEl.className = "status";
    statusEl.textContent = "공유 링크에서 브랜드명만 채웠습니다. 리스크 확인하기를 눌러 주세요.";
  }

  // 무료 베타·소개 글 유입 태그(0.1.7) — ?cohort=beta_pilot 로 들어온 링크만 문의에 붙인다.
  // 서버와 같은 규칙(영문 소문자·숫자와 . _ : -, 40자)을 먼저 확인해 잘못된 값이면 보내지 않는다.
  function cohortTag() {
    try {
      var value = String(new URLSearchParams(location.search).get("cohort") || "").trim().toLowerCase();
      return /^[a-z0-9][a-z0-9._:-]{0,39}$/.test(value) ? value : "";
    } catch (error) { return ""; }
  }

  var inquiry = $("inquiry");
  inquiry.addEventListener("submit", function (event) {
    event.preventDefault();
    var status = $("inq-status");
    var payload = {
      contact: $("inq-contact").value,
      topic: $("inq-topic").value,
      message: $("inq-message").value,
      cohort: cohortTag()
    };
    status.className = "status";
    status.textContent = "보내는 중…";
    fetch("/v1/inquiry", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().then(function (data) { return { ok: response.ok, data: data }; });
    }).then(function (out) {
      if (!out.data || !out.data.ok) {
        status.className = "status err";
        status.textContent = (out.data && out.data.message_ko) || "접수하지 못했습니다.";
        return;
      }
      status.textContent = (out.data.message_ko || "접수됐습니다.") +
        (out.data.receipt ? " 접수번호 " + out.data.receipt : "");
      $("inq-message").value = "";
    }).catch(function () {
      status.className = "status err";
      status.textContent = "네트워크 오류로 접수하지 못했습니다.";
    });
  });

  // --- 특약·계약서 문구 스캔 ----------------------------------------------
  var scanText = $("scan-text");
  var scanResultEl = $("scan-result");
  var scanStatusEl = $("scan-status");

  function scanCount() {
    var el = $("scan-count");
    if (!el || !scanText) return;
    var length = scanText.value.length;
    var max = Number(scanText.getAttribute("data-max")) || 0;
    el.textContent = max && length > max ?
      length.toLocaleString("ko-KR") + "자 — 앞 " + max.toLocaleString("ko-KR") + "자만 스캔합니다" :
      length.toLocaleString("ko-KR") + "자";
  }

  function scanFinding(row) {
    var refs = (row.law_refs || []).map(function (key) {
      return '<span class="kbd">' + esc(key) + '</span>';
    }).join(" ");
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
  }

  function scanRender(data) {
    var counts = data.counts || {};
    var verdict = data.verdict || {};
    var html = '<div class="verdict"><div><h3>' + esc(verdict.label_ko || "") + '</h3>' +
      '<p class="kv">확인 필요 문구 ' + esc(counts.flagged || 0) + '건(높음 ' +
      esc(counts.high || 0) + ' · 주의 ' + esc(counts.medium || 0) + ') · 대조한 유형 ' +
      esc(counts.rules_checked || 0) + '개</p></div>' +
      badge(verdict.code, verdict.label_ko) + '</div>' +
      '<p class="summary">' + esc(data.summary_ko) + '</p>' +
      '<p class="notice" style="margin-top:12px">' + esc(data.not_a_clearance_ko) + '</p>';
    var findings = data.findings || [];
    if (findings.length) {
      html += '<div class="section"><h3>확인이 필요한 문구 <span class="count">' +
        findings.length + '건</span></h3>' + findings.map(scanFinding).join("") + '</div>';
    }
    var checks = data.checks_ko || [];
    if (checks.length) {
      html += '<div class="section"><h3>대조한 유형 <span class="count">' + checks.length +
        '개</span></h3><ul class="scan-checks">' + checks.map(function (row) {
          return '<li><b>' + esc(row.title_ko) + '</b> — ' + esc(row.result_ko) + '</li>';
        }).join("") + '</ul></div>';
    }
    html += lawBoxes(data.law_basis, data.law_basis_scope_ko);
    if ((data.questions_ko || []).length) {
      html += '<div class="section"><h3>계약 전에 확인할 것</h3><ul class="clean">' +
        data.questions_ko.map(function (q) { return '<li>' + esc(q) + '</li>'; }).join("") +
        '</ul></div>';
    }
    html += '<p class="hint">' + esc(data.disclaimer_ko) + '</p>';
    scanResultEl.innerHTML = html;
    scanResultEl.hidden = false;
  }

  function scanRun() {
    if (!scanText) return;
    var text = String(scanText.value || "").trim();
    if (!text) {
      scanStatusEl.className = "status err";
      scanStatusEl.textContent = "계약서·특약 문구를 붙여 넣어 주세요.";
      return;
    }
    var button = $("scan-run");
    scanStatusEl.className = "status";
    scanStatusEl.textContent = "문구를 조문 유형과 대조하는 중…";
    button.disabled = true;
    post("/v1/tools/scan_contract_text", { text: text }).then(function (result) {
      scanRender(result);
      scanStatusEl.textContent = "스캔 완료. 잡히는 문구가 없어도 원문 전체 검토는 따로 필요합니다.";
    }).catch(function (error) {
      scanStatusEl.className = "status err";
      scanStatusEl.textContent = "오류: " + error.message;
    }).finally(function () {
      button.disabled = false;
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll("button.sample"), function (button) {
    button.addEventListener("click", function () {
      var name = button.getAttribute("data-sample");
      var sample = SCAN_SAMPLES_TEXT[name];
      if (!sample || !scanText) return;
      scanText.value = sample;
      scanCount();
      scanRun();
    });
  });

  if (scanText) {
    scanText.addEventListener("input", scanCount);
    scanCount();
  }
  $("scan-run").addEventListener("click", scanRun);
  $("scan-clear").addEventListener("click", function () {
    if (scanText) scanText.value = "";
    scanCount();
    scanResultEl.hidden = true;
    scanStatusEl.textContent = "";
  });

  moneySum();
  prefillFromUrl();
})();
"""


def _script_html() -> str:
    presets_json = json.dumps({preset["id"]: preset["values"] for preset in PRESETS},
                              ensure_ascii=False)
    samples_json = json.dumps({row["id"]: row["text"] for row in SCAN_SAMPLES},
                              ensure_ascii=False)
    quick_json = json.dumps(QUICK_ANSWERS, ensure_ascii=False)
    return (SCRIPT.replace("__PRESETS__", presets_json)
                  .replace("__SAMPLES__", samples_json)
                  .replace("__QUICK__", quick_json))


def render_page(meta: Optional[Dict[str, Any]] = None) -> str:
    from . import guides

    meta = meta or {}
    data_state = str(meta.get("data_state") or live_api.data_state())
    law = engine.law_meta()
    # 실제 동작을 그대로 적는다 — '승인 전이라 샘플' 같은 고정 문구를 쓰지 않는다.
    state_note = live_api.state_note_ko(state=data_state)
    _env = dict(_os.environ)
    _env.setdefault("GOOGLE_SITE_VERIFICATION", "3KG1TCarS7RYxIpCqZ0fv8yIm8S0vBp7k1NNlVlWoxg")
    _env.setdefault("NAVER_SITE_VERIFICATION", "f12b91bab9bab718349e637c8a043e5703a4be35")
    meta_tags = site_verification.meta_tags(_env)
    json_ld = home_json_ld(SERVICE_URL)
    script = _script_html()
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
<meta property="og:image" content="{SERVICE_URL}/static/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="FRNC — 프랜차이즈 계약 전 10초 리스크 체크">
<meta property="og:site_name" content="{SERVICE_NAME}">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="{SERVICE_URL}/">
{meta_tags}
{json_ld}
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
      </div>
    </div>
    <div>
      <span class="pill ghost">v{__version__}</span>
      <a class="pill ghost" href="/guides/">가이드 {len(guides.GUIDES)}종</a>
    </div>
  </header>

  <main>
  <section class="card hero" id="brand-card">
    <h2>어떤 브랜드를 확인할까요?</h2>
    <p class="lead">브랜드명이나 업종을 넣으면 공정위 공개자료와 가맹사업법 조문으로
      <b>계약 전에 확인할 점</b>을 정리해 드립니다. 무료 · 회원가입 없음.</p>
    <form id="check" novalidate>
      <div class="search-row">
        <input id="brand_name" name="brand_name" type="text" autocomplete="off"
               placeholder="예: 메가커피, 굽네치킨, 치킨" aria-label="브랜드명 또는 업종">
        <button type="submit" class="primary big" id="run">리스크 확인하기</button>
      </div>
      <div class="chips">
        <span class="chips-label">예시</span>
        {_chips_html()}
      </div>
      <details class="more" id="more">
        <summary>상세 조건 입력 <span class="note">선택 · 모르면 비워 두세요</span></summary>
        <div class="more-body">
        {_detail_form_html()}
        </div>
      </details>
    </form>
  </section>

  <div class="status" id="status" aria-live="polite"></div>

  <section class="card" id="result-card" hidden aria-label="확인 결과">
    <div id="result"></div>
    <div class="copyrow">
      <button type="button" class="ghost" id="copy">요약 복사</button>
      <button type="button" class="ghost" id="share">공유 링크 복사</button>
      <span class="hint" id="copy-status" aria-live="polite"></span>
    </div>
  </section>

  {_scan_card_html()}

  <section class="card quiet">
    <h2>이 서비스가 보는 것</h2>
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

  <section class="card quiet">
    <h2>계약 전 자주 묻는 질문</h2>
    <p class="sub">정보공개서·가맹금·영업지역·해지·갱신을 조문과 함께 정리했습니다.</p>
    <ul class="clean">{_guides_teaser_html()}</ul>
    <p class="hint"><a href="/guides/">가이드 전체 {len(guides.GUIDES)}종 보기</a></p>
  </section>

  {_siblings_html()}

  {_inquiry_html()}

  <p class="foot">
    <span id="data-state-note">{state_note} 법령 근거: 법제처 OPEN API 실조회 · 조문 {law.get('article_count', 0)}개 · 함정 케이스 {len(engine.trap_cases())}건.</span>
    <br>브랜드 조회 결과가 0건이어도 '등록된 브랜드가 없다'도 '문제없다·안전하다'도 아닙니다.
    <br>{SERVICE_NAME}는 입력한 조건과 공개 법령 조문을 대조하는 참고용 사전 점검 도구입니다. 확정 판정 아님 —
    위법 여부·계약 효력을 확정하지 않고, 계약서 검토·법률 자문·신고 대행을 하지 않습니다.
    최종 판단은 변호사·가맹거래사 자문으로 하세요.
    <br>정보공개서 원문: <a href="{DISCLOSURE_PORTAL}" target="_blank" rel="noopener noreferrer">가맹사업정보제공시스템</a>
    · <a href="/llms.txt">llms.txt</a> · <a href="/v1/meta">서비스 상태</a>
    · <a href="/guides/">가이드 {len(guides.GUIDES)}종</a>
    <br>같이 쓰는 도구 — 수입·유통 규제 체크 <a href="{CLNS_URL}" target="_blank" rel="noopener noreferrer">CLNS</a>
    · 창업·개인 지원금 찾기 <a href="{GRANT_URL}" target="_blank" rel="noopener noreferrer">GRNT</a>
    <br>고지 — <a href="/privacy">개인정보 처리방침</a> · <a href="/terms">이용약관</a>
    · <a href="/about">서비스 소개</a>
  </p>
  </main>
</div>

<script>{script}</script>
</body>
</html>
"""


def render_not_found(path: str = "/", meta: Optional[Dict[str, Any]] = None) -> str:
    """사람이 보는 404 페이지 — JSON 대신 다음에 할 일을 준다(비-`/v1/` 경로 전용)."""
    from . import guides

    safe_path = str(path or "/")[:120]
    safe_path = (safe_path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                 .replace('"', "&quot;"))
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>404 — {SERVICE_NAME} 페이지를 찾지 못했습니다</title>
<meta name="robots" content="noindex">
<meta name="theme-color" content="#1f4fd8" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0b0f16" media="(prefers-color-scheme: dark)">
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
      </div>
    </div>
    <div><span class="pill">v{__version__}</span><span class="pill ghost">404</span></div>
  </header>

  <section class="card" style="margin-top:14px">
    <h2>요청한 페이지를 찾지 못했습니다</h2>
    <p class="sub">주소 <span class="kbd">{safe_path}</span> 는 이 서비스에 없습니다.
      아래에서 원하는 화면으로 이동하세요. 기계용 경로(<span class="kbd">/v1/…</span>)는 JSON 으로 응답합니다.</p>
    <ul class="clean">
      <li><a href="/">브랜드로 리스크 확인</a> — 브랜드명·업종 입력 한 번으로 위험 신호 확인</li>
      <li><a href="/#brand-card">브랜드 정보공개서 조회</a> — 브랜드명(부분 일치)·브랜드관리번호로 조회</li>
      <li><a href="/guides/">질문형 가이드 {len(guides.GUIDES)}종</a> — 숙고기간·가맹금·영업지역·해지·갱신</li>
      <li><a href="/v1/meta">서비스·데이터 상태</a> · <a href="/llms.txt">llms.txt</a> · <a href="/healthz">healthz</a></li>
    </ul>
  </section>

  <p class="foot">
    {SERVICE_NAME}는 입력한 조건과 공개 법령 조문을 대조하는 참고용 사전 점검 도구입니다.
    확정 판정 아님 — 위법 여부·계약 효력을 확정하지 않습니다. · 정보공개서 원문: <a href="{DISCLOSURE_PORTAL}" target="_blank" rel="noopener noreferrer">가맹사업정보제공시스템</a>
    <br>같이 쓰는 도구 — 수입·유통 규제 체크 <a href="{CLNS_URL}" target="_blank" rel="noopener noreferrer">CLNS</a>
    · 창업·개인 지원금 찾기 <a href="{GRANT_URL}" target="_blank" rel="noopener noreferrer">GRNT</a>
    <br>고지 — <a href="/privacy">개인정보 처리방침</a> · <a href="/terms">이용약관</a>
    · <a href="/about">서비스 소개</a>
  </p>
</div>
</body>
</html>
"""
