"""검색·AI 크롤러용 정적 파일과 MCP 서버 카드.

- `GET /robots.txt` → `robots_txt()`
- `GET /llms.txt` → `llms_txt()`
- `GET /sitemap.xml` → `sitemap_xml()`
- `GET /.well-known/mcp/server-card.json` → `server_card()`

툴 목록은 `api.TOOL_DEFS` 한 곳만 고치면 되도록 여기서 생성합니다.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from . import engine, live_api
from .api import mcp_tools
from .version import (DISCLOSURE_PORTAL, GRANT_URL, SERVICE_NAME, SERVICE_SUBTITLE_EN,
                      SERVICE_TAGLINE, SERVICE_TITLE_KO, SERVICE_URL, __version__)

DEFAULT_BASE_URL = SERVICE_URL


def base_url(value: Optional[str] = None) -> str:
    raw = (value or os.environ.get("PUBLIC_BASE_URL") or "").strip()
    return (raw or DEFAULT_BASE_URL).rstrip("/")


def robots_txt(base: Optional[str] = None) -> str:
    root = base_url(base)
    return f"""# {SERVICE_NAME} robots.txt
# 사람용 페이지는 공개, API 경로는 색인 제외.

User-agent: *
Allow: /
Disallow: /v1/

User-agent: Yeti
Allow: /

User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

Sitemap: {root}/sitemap.xml
"""


def llms_txt(base: Optional[str] = None) -> str:
    root = base_url(base)
    summary = live_api.dataset_summary()
    counts = summary["counts"]
    law = engine.law_meta()
    from . import guides

    state_line = (
        f"> 데이터: 공정위 가맹정보 API 승인 {counts['approved']}/{counts['total']} · "
        f"미등록 {counts['not_registered']} — 지금은 브랜드 조회가 **내장 샘플**로 동작합니다. "
        "실제 값은 가맹사업정보제공시스템에서 확인하세요."
        if counts["approved"] == 0 else
        f"> 데이터: 공정위 가맹정보 API 승인 {counts['approved']}/{counts['total']} — 실데이터로 동작합니다."
    )
    return f"""# {SERVICE_NAME} — {SERVICE_TITLE_KO}

> {SERVICE_TAGLINE} ({SERVICE_SUBTITLE_EN})
> 브랜드·업종·가맹비·인테리어 비용과 본부가 제시한 조건을 가맹사업법·시행령 조문과 대조해
> **위험 신호·확인 체크리스트·질문·근거 조문**을 돌려주는 무료 서비스입니다.
> 확정 판정이 아니며, 판정은 `check_likely` / `info_needed` / `low_risk` 세 가지뿐입니다.
{state_line}
> 법령: {law.get('source')} · 조문 {law.get('article_count', 0)}개 실조회 저장 · 함정 케이스 {len(engine.trap_cases())}건

## 사람용
- [내 조건으로 10초 체크]({root}/): 로그인·회원가입·개인정보 입력 없이 브랜드·금액·조건만 고릅니다.
  원클릭 프리셋 4개(당일 계약·본사 계좌 송금 / 구두 매출 보장 / 인테리어 100% 강제 / 정상 조건).
- [계약서·특약 문구 스캔]({root}/): 본부가 보낸 특약 문구를 붙여넣으면 확인이 필요한 문구와
  본부에 요청할 수정 문구를 짚어 줍니다. 샘플 3종(구입강제·과중 위약금·즉시 해지) 버튼.
- [질문형 가이드 {len(guides.GUIDES)}종]({root}/guides/): 정보공개서 14일 숙고기간, 예상매출액 산정서,
  가맹금 예치, 인테리어 강제, 영업지역, 폐점률, 위약금, 해지·갱신, 필수품목·차액가맹금,
  판매가격 구속, 점주 단체, 분쟁조정을 조문과 함께 정리.
- [서비스·데이터 상태]({root}/v1/meta): 판정 등급, 핵심 8개 축, 법령 실조회 상태, 공정위 API 승인 상태,
  가이드 {len(guides.GUIDES)}종 메타.
- [익명 사용 통계]({root}/v1/stats): IP·쿠키·금액·조건을 저장하지 않은 일별 호출 수와
  0건 조회어(비식별 30자) 집계.
- [소스 저장소](https://github.com/CLNS-KR/FRNC): MIT.

## 기계용 (MCP · JSON-RPC 2.0)
- [MCP 엔드포인트]({root}/mcp): POST. `initialize` → `tools/list` → `tools/call`. 인증 불필요,
  응답은 `application/json` 한 덩어리(SSE 스트리밍 없음).
- [MCP 서버 카드]({root}/.well-known/mcp/server-card.json): 서버 정보·툴 {len(mcp_tools())}종 스키마.
- [툴 매니페스트]({root}/v1/mcp): GET.

## 기계용 (REST JSON)
- [리스크 체크]({root}/v1/tools/check_franchise_risk): POST.
  `{{"brand_name": "샘플치킨", "industry": "치킨", "franchise_fee_krw": "1100만원", "interior_krw": "5500만원", "disclosure_days_before": 0, "payment_route": "hq_account", "revenue_claim_ko": "월 5천 보장", "revenue_written": false}}`
- [계약서·특약 문구 스캔]({root}/v1/tools/scan_contract_text): POST. `{{"text": "인테리어는 당사가 지정한 업체를 통해서만 시공한다"}}`
  — 확인이 필요한 문구·원문 인용·근거 조문·수정 요청 문구. 0건이어도 '안전'을 뜻하지 않습니다.
- [브랜드 정보공개서 요약]({root}/v1/tools/lookup_brand_disclosure): POST. `{{"brand_name": "샘플치킨"}}`
- [두 조건 비교]({root}/v1/tools/compare_franchise_terms): POST. `{{"a": {{...}}, "b": {{...}}}}`
- [리스크 케이스 목록]({root}/v1/tools/list_risk_cases): POST. `{{"severity": "high"}}`
- [조문 조회]({root}/v1/tools/get_law_article): POST. `{{"article": "제7조"}}`
- [문의]({root}/v1/inquiry): POST. `{{"contact": "...", "topic": "franchise_review|api_mcp|other", "message": "선택 500자"}}`

## 읽는 법
- `check_likely`: 계약·입금 전에 확인해야 할 위험 신호가 있음. 확정 판정 아님.
- `info_needed`: 핵심 항목이 비어 있음. `questions_ko` 를 그대로 사용자에게 물어보세요.
- `low_risk`: 8개 핵심 축이 모두 채워졌고 그 안에서 위험 신호가 없음. **확정 아님** —
  서류 원문·현장 확인은 따로 필요합니다.
- 0건·미발견 응답에는 고정 안내가 붙습니다: 0건은 '그 브랜드가 없다'도 '문제없다·안전하다'도 아닙니다.
- 브랜드 조회는 공정위 가맹정보 API 활용신청 승인 전까지 내장 샘플(`data_state=sample`)로 응답합니다.
  응답의 `apply_urls` 가 활용신청 주소입니다.
- 창업비용을 낸 뒤 받을 수 있는 지원금은 GRNT({GRANT_URL})에서 확인하세요.
- 이 서비스는 계약서 검토·법률 자문·신고 대행을 하지 않습니다. 최종 판단은 변호사·가맹거래사 자문으로.
- 정보공개서 원문: {DISCLOSURE_PORTAL}
{guides.llms_section(root)}"""


def sitemap_xml(base: Optional[str] = None) -> str:
    root = base_url(base)
    lastmod = engine.law_meta().get("generated_at") or "2026-11-21"
    lastmod = str(lastmod)[:10]
    from . import guides

    entries = [f"""  <url>
    <loc>{root}/</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>""", f"""  <url>
    <loc>{root}{guides.INDEX_PATH}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>"""]
    for guide in guides.GUIDES:
        entries.append(f"""  <url>
    <loc>{root}/guides/{guide['slug']}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>""")
    body = "\n".join(entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>
"""


def server_card() -> Dict[str, Any]:
    return {
        "serverInfo": {"name": SERVICE_NAME.lower(), "version": __version__},
        "title": f"{SERVICE_NAME} — {SERVICE_TITLE_KO}",
        "description": (
            f"{SERVICE_NAME} — 한국 프랜차이즈 정보공개서·계약 조건 리스크 체크 MCP. "
            "가맹사업법·시행령 조문(법제처 OPEN API 실조회)과 대조해 위험 신호·체크리스트·"
            "질문·근거를 돌려준다. 확정 판정이 아니다."
        ),
        "authentication": {"required": False, "schemes": []},
        "transport": {
            "type": "streamable-http",
            "endpoint": "/mcp",
            "protocolVersion": "2025-06-18",
            "contentType": "application/json",
        },
        "transports": {
            "http": {"endpoint": "/mcp", "protocolVersion": "2025-06-18"},
            "stdio": {
                "command": "python",
                "args": ["-m", "franchise_kr.mcp_stdio"],
                "note_ko": "로컬 실행형 MCP. 한 줄에 JSON-RPC 2.0 한 건을 stdin 으로 받습니다.",
            },
        },
        "tools": mcp_tools(),
        "resources": [],
        "prompts": [],
        "attribution_ko": (
            "법령: 법제처 국가법령정보 공동활용 OPEN API · "
            "가맹정보: 공정거래위원회 가맹정보 오픈API(data.go.kr) · "
            "정보공개서 원문: 가맹사업정보제공시스템(franchise.ftc.go.kr)"
        ),
    }
