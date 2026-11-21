"""정적 고지 페이지 — `/privacy` · `/terms` · `/about`.

왜 서버 렌더 정적 HTML 인가
--------------------------
- 사람·검색 크롤러·AI 크롤러가 같은 내용을 본다(JS 없음, 외부 CDN 없음 → CSP 그대로).
- 계약 전 점검 도구는 "무엇을 판정하지 않는지"를 먼저 밝혀야 오해가 없다. 그 문구를 한 곳에 둔다.

익명 운영 원칙
--------------
실명·직업·개인 연락처·상대 서비스 핸들을 쓰지 않는다. 문의·삭제 요청 경로는 서비스 자체
접수(`POST /v1/inquiry`)와 공개 저장소 Issues 만 쓴다.
"""
from __future__ import annotations

from typing import Dict, Optional

from . import static_files
from .version import (CLNS_URL, GRANT_URL, SERVICE_NAME, SERVICE_TAGLINE, SERVICE_URL,
                      __version__)

SERVICE = SERVICE_NAME
TAGLINE = SERVICE_TAGLINE
REPO_URL = "https://github.com/CLNS-KR/FRNC"
REPO_ISSUES = REPO_URL + "/issues"
DISCLOSURE_PORTAL = "https://franchise.ftc.go.kr"
SIBLINGS = (
    (CLNS_URL, "CLNS", "한국 수입 규제 사전 점검"),
    (GRANT_URL, "GRNT", "개인·창업 통합 지원금 판정기"),
)
EFFECTIVE_DATE = "2026-11-21"

TITLES: Dict[str, str] = {
    "privacy": "개인정보 처리방침",
    "terms": "이용약관",
    "about": "서비스 소개",
}
DESCRIPTIONS: Dict[str, str] = {
    "privacy": "FRNC가 받지 않는 정보, 익명 카운터에 남는 것, 0건 브랜드 조회어 처리, 문의 연락처 180일 보관과 삭제 요청 경로입니다.",
    "terms": "FRNC는 무료 정보 제공 서비스입니다. 위법·계약 효력을 확정하지 않으며 변호사·가맹거래사 자문을 대신하지 않습니다.",
    "about": "프랜차이즈 창업 전 리스크 체크 FRNC의 대상, 공정위 정보공개서 기반 데이터, 판정 3단계를 소개합니다.",
}

_CSS = """
:root{--bg:#0b1019;--card:#121a2b;--line:#243252;--ink:#e8edf5;--soft:#9fb3d9;--brand:#8aa5ff}
@media (prefers-color-scheme:light){:root{--bg:#f6f8fc;--card:#fff;--line:#dbe3f2;--ink:#16213a;--soft:#4c5f80;--brand:#1f4fd8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
.wrap{max-width:780px;margin:0 auto;padding:32px 20px 64px}
.top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.top a.brand{color:var(--ink);text-decoration:none;font-weight:800;font-size:20px;letter-spacing:.02em}
.top span{color:var(--soft);font-size:13px}
h1{font-size:26px;line-height:1.35;margin:18px 0 6px}
h2{font-size:18px;margin:30px 0 8px}
p,li{color:var(--ink)}
.meta{color:var(--soft);font-size:13px;margin:0 0 18px}
ul{padding-left:20px;margin:8px 0}
li{margin:6px 0}
a{color:var(--brand)}
code{font-size:13px;background:rgba(138,165,255,.14);padding:1px 5px;border-radius:5px}
.nav{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--soft)}
.nav a{margin-right:10px}
footer{margin-top:28px;font-size:12px;color:var(--soft)}
"""

_PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {service}</title>
<meta name="description" content="{description}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{service}">
<meta property="og:title" content="{title} · {service}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{canonical}">
<meta property="og:locale" content="ko_KR">
<meta property="og:image" content="{root}/static/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <a class="brand" href="/">{service}</a>
    <span>{tagline} · 프랜차이즈 계약 전 점검</span>
  </div>
  <h1>{title}</h1>
  <p class="meta">시행일 {effective} · 버전 {version} · 무료 베타</p>
  {body}
  <div class="nav">{nav}</div>
  <footer>© 2026 {service} · 익명 운영 무료 베타 · 이 페이지는 사전 점검 서비스의 고지이며 법률 자문이 아닙니다.</footer>
</div>
</body>
</html>
"""


def _page(slug: str, body: str, base: Optional[str] = None) -> str:
    root = static_files.base_url(base)
    canonical = f"{root}/{slug}"
    nav_items = ['<a href="/">리스크 체크</a>', '<a href="/guides/">질문형 가이드</a>']
    for other, title in TITLES.items():
        if other != slug:
            nav_items.append(f'<a href="/{other}">{title}</a>')
    return _PAGE.format(title=TITLES[slug], description=DESCRIPTIONS[slug], canonical=canonical,
                        service=SERVICE, tagline=TAGLINE, css=_CSS, version=__version__,
                        effective=EFFECTIVE_DATE, body=body, nav="".join(nav_items), root=root)


def _privacy(base: Optional[str] = None) -> str:
    body = f"""
<p>FRNC는 회원가입·로그인이 없고, 결제도 받지 않습니다. 브랜드를 조회하거나 계약 조건을 넣어도
<strong>입력값과 금액은 저장하지 않습니다</strong>. 아래에 예외와 보관 기간을 적었습니다.</p>

<h2>받지 않는 정보</h2>
<ul>
  <li>이름·주민등록번호·전화번호·주소: 점검에 쓰지 않고 저장하지 않습니다.</li>
  <li>계약서 원문·사업자등록번호: 붙여넣은 문구는 판정 계산에만 쓰고 저장하지 않습니다.</li>
  <li>회원 계정·비밀번호·소셜 로그인: 만들지 않습니다.</li>
  <li>브라우저 쿠키·광고 식별자·추적 스크립트: 쓰지 않습니다.</li>
</ul>

<h2>점검에 쓰는 입력</h2>
<p>브랜드명, 가맹금·교육비·보증금·인테리어·설비 금액, 계약 기간·영업지역·조항 문구는
<strong>응답을 계산하는 동안에만</strong> 메모리에 있습니다. 금액·조건 입력은 통계에도 저장하지 않습니다.</p>

<h2>익명 카운터에 남는 것</h2>
<ul>
  <li>날짜·경로·툴 이름·판정 등급의 <em>호출 횟수</em>만 남깁니다.</li>
  <li>IP 주소·User-Agent 원문·쿠키·Referer·세션 ID는 저장하지 않습니다. 요청 제한에 쓰는 IP는
  프로세스 난수로 해시해 메모리에만 두고, 재배포하면 사라집니다.</li>
  <li><strong>요청 종류</strong> — 브라우저인지 봇인지의 구분(브라우저·봇·기타 3종)만 셉니다. User-Agent 원문은 남기지 않습니다(봇 판별은 문자열 표식 기준의 참고 수치).</li>
</ul>

<h2>0건으로 끝난 브랜드 조회어만 예외적으로</h2>
<p>"정보공개서에 없는 브랜드"를 찾아 데이터를 보강하는 데만 쓰기 위해, <strong>결과가 0건이었던
조회어</strong>를 비식별 처리해 최대 30자로 남깁니다. 전화번호·주민등록번호·이메일·URL·@핸들·
2자리 이상 숫자·제어문자는 지운 뒤 남깁니다. 사람 이름·상호는 낱말만으로 판별할 수 없어 지우지
못하므로, 조회에는 브랜드명만 넣어 주세요. 점검 결과는 저장하지 않습니다.</p>

<h2>문의할 때 남기는 연락처</h2>
<ul>
  <li>문의(<code>POST /v1/inquiry</code>)에 적은 연락처는 <strong>그 문의에 회신하는 용도로만</strong>
  씁니다.</li>
  <li>보관 기간은 접수일로부터 <strong>180일</strong>이며, 기간이 지나면 지웁니다. 통계·공개 화면에는
  넣지 않습니다.</li>
</ul>

<h2>삭제 요청</h2>
<ul>
  <li>문의로 남긴 연락처나 0건 조회어 기록의 삭제를 원하시면 서비스 내 문의(<code>POST /v1/inquiry</code>)에
  <strong>삭제 요청</strong>이라고 적어 보내 주세요. 확인 후 지체 없이 지웁니다.</li>
  <li>공개 저장소 <a href="{REPO_ISSUES}" target="_blank" rel="noopener noreferrer">이슈</a>로도 요청할 수
  있습니다. 이슈는 공개되므로 개인정보는 적지 마세요.</li>
</ul>

<h2>제3자 제공·처리 위탁</h2>
<ul>
  <li>수집한 정보를 제3자에게 판매·제공하지 않습니다. 국외 이전도 하지 않습니다.</li>
  <li>서비스는 호스팅 사업자 위에서 동작합니다. 호스팅 사업자의 플랫폼 접속 로그는 이 서비스 코드가
  저장하는 정보와 별개로 그 사업자 정책을 따릅니다.</li>
</ul>

<h2>공공데이터에 포함된 정보</h2>
<p>공정위 가맹사업정보제공시스템 정보공개서에는 가맹본부의 상호·연락처·점포 정보가 들어 있습니다.
FRNC는 이를 계약 전 확인 자료로만 보여 주고 별도로 수집하지 않습니다.</p>

<h2>문의</h2>
<p>개인정보 처리에 관한 문의는 서비스 내 문의 접수 또는 공개 저장소
<a href="{REPO_ISSUES}" target="_blank" rel="noopener noreferrer">이슈</a>로 받습니다. 운영자 개인 연락처는
공개하지 않습니다(익명 운영 원칙).</p>
"""
    return _page("privacy", body, base)


def _terms(base: Optional[str] = None) -> str:
    body = f"""
<p>FRNC는 프랜차이즈 계약 전에 위험 신호를 <strong>미리 확인해 보는 무료 사전 점검 도구</strong>입니다.
계약금을 넣기 전에 아래 범위와 한계를 확인해 주세요.</p>

<h2>서비스가 하는 일</h2>
<ul>
  <li>브랜드명으로 공정위 정보공개서의 공개 항목(가맹점 수·평균매출·폐점률·법 위반 이력 등)을 확인합니다.</li>
  <li>가맹금·교육비·보증금·인테리어·설비 금액과 계약 조건을 가맹사업법 조문과 대조해
  <strong>확인해야 할 신호</strong>를 알려 줍니다.</li>
</ul>

<h2>서비스가 하지 않는 일</h2>
<ul>
  <li>위법 여부·계약 효력을 확정하지 않습니다. 판정 등급은 '확인 필요 신호 있음 / 정보 부족 /
  뚜렷한 위험 신호 없음'이며, 확정 판정이 아닙니다.</li>
  <li>계약서 검토, 법률 자문, 정보공개서 열람 대행, 신고·분쟁 대리를 하지 않습니다.</li>
  <li>변호사·가맹거래사 자문을 대신하지 않습니다. 계약 전 전문가 검토를 권합니다.</li>
  <li>'뚜렷한 위험 신호 없음'은 안전하다는 뜻이 아닙니다. 제시된 조건 안에서 법이 금지하는
  신호가 보이지 않았다는 뜻입니다.</li>
</ul>

<h2>데이터와 정확성</h2>
<ul>
  <li>공정위 가맹사업정보제공시스템(<a href="{DISCLOSURE_PORTAL}" target="_blank" rel="noopener noreferrer">franchise.ftc.go.kr</a>)
  정보공개서와 가맹사업법·시행령 조문을 근거로 씁니다.</li>
  <li>정보공개서는 등록 시점 기준입니다. 그 뒤 바뀐 조건·매출·점포 수는 반영되지 않을 수 있습니다.</li>
  <li>원본을 그대로 중계하지 않고 결합·정규화한 판정만 제공하며, 샘플·색인 데이터로 답한 경우
  화면에 사실대로 표시합니다.</li>
</ul>

<h2>이용자의 책임</h2>
<ul>
  <li>입력한 브랜드명·금액·조건의 정확성은 이용자에게 있습니다. 결과는 입력값이 맞다는 전제로 계산됩니다.</li>
  <li>자동화된 과도한 호출, 서비스 우회·부하 유발, 결과를 확정 판정이나 안전 보증처럼 재판매·재게시하는
  행위는 제한될 수 있습니다.</li>
</ul>

<h2>책임의 한계</h2>
<ul>
  <li>서비스는 '있는 그대로' 제공됩니다. 무료 베타이며 중단·변경·오류가 있을 수 있습니다.</li>
  <li>서비스 이용으로 발생한 계약 손실·분쟁·투자 판단의 결과에 대해, 고의 또는 중대한 과실이 없는 한
  책임지지 않습니다.</li>
</ul>

<h2>약관의 변경</h2>
<p>내용이 바뀌면 이 페이지의 시행일과 버전을 갱신합니다. 중요한 변경은 서비스 화면에서 알립니다.</p>

<h2>준거법</h2>
<p>이 약관은 대한민국 법에 따릅니다.</p>
"""
    return _page("terms", body, base)


def _about(base: Optional[str] = None) -> str:
    siblings = "".join(
        f'<li><a href="{url}" target="_blank" rel="noopener noreferrer"><strong>{name}</strong></a> — {desc}</li>'
        for url, name, desc in SIBLINGS
    )
    body = f"""
<p><strong>FRNC</strong>는 프랜차이즈 창업을 결정하기 전에 "무엇을 확인해야 하는지"를 10초 안에
정리해 주는 무료 사전 점검 서비스입니다. {TAGLINE}</p>

<h2>누구를 위한 서비스인가</h2>
<ul>
  <li>프랜차이즈 창업을 검토 중인 예비 창업자</li>
  <li>정보공개서를 받았지만 어디를 봐야 할지 모르는 분</li>
  <li>가맹 계약 조건(가맹금·위약금·영업지역·인테리어 강제)을 조문과 대조하려는 분</li>
</ul>

<h2>무엇을 답하나</h2>
<ul>
  <li>브랜드별 정보공개서 공개 항목: 가맹점 수·신규 개점·계약 해지·평균매출·법 위반 이력</li>
  <li>가맹사업법 조문 대조: 정보공개서 14일 숙고기간, 가맹금 예치, 예상매출의 서면 제공,
  인테리어·설비 강제, 영업지역 침해, 위약금 과다</li>
  <li>계약서 문구 스캔: 금지 조항·필수 기재 사항 누락 신호</li>
</ul>

<h2>판정 3단계</h2>
<p><code>check_likely</code> 확인 필요 신호 있음 · <code>info_needed</code> 정보 부족(되물어볼 것 있음) ·
<code>low_risk</code> 뚜렷한 위험 신호 없음. 셋 다 사전 점검이며, 최종 판단은 전문가 자문과 원문 확인으로
하세요.</p>

<h2>데이터 출처</h2>
<p>공정위 가맹사업정보제공시스템 정보공개서와 가맹사업법·시행령·시행규칙 조문(법제처
국가법령정보센터 현행본)입니다. 조문은 시행일과 원문 링크를 함께 표시합니다.</p>

<h2>쓰는 방법</h2>
<ul>
  <li>사람: <a href="/">리스크 체크</a>에서 브랜드를 찾거나 금액·조건을 넣습니다.</li>
  <li>검색·AI: <a href="/guides/">질문형 가이드</a>가 정적 HTML로 열려 있습니다.</li>
  <li>개발자: MCP(<code>POST /mcp</code>) · REST(<code>POST /v1/tools/&lt;tool&gt;</code>)로 같은 판정을 받습니다.</li>
</ul>

<h2>같이 쓰는 서비스</h2>
<ul>{siblings}</ul>
<p>세 서비스는 같은 원칙으로 운영합니다 — 무료, 로그인 없음, 익명 운영, 근거 조문 표시,
확정 판정 대신 확인 항목 제시.</p>

<h2>만든 방식과 한계</h2>
<p>표준 라이브러리만으로 동작하고, 페이지는 외부 CDN 없이 인라인 자원만 씁니다. 무료 베타라
정보공개서 색인이 모든 브랜드를 담지 못할 수 있고, 그런 경우 '조회되지 않음'으로 사실대로 답합니다.</p>
"""
    return _page("about", body, base)


_RENDERERS = {"privacy": _privacy, "terms": _terms, "about": _about}


def is_page(path: str) -> bool:
    """`/privacy`·`/privacy/` 처럼 이 모듈이 답하는 주소인지."""
    return str(path or "").strip("/").lower() in _RENDERERS


def render(path: str, base: Optional[str] = None) -> Optional[str]:
    """슬러그(`privacy`·`terms`·`about`) 또는 경로로 HTML 을 만든다. 모르는 주소면 None."""
    slug = str(path or "").strip("/").lower()
    renderer = _RENDERERS.get(slug)
    return renderer(base) if renderer else None


def footer_links_html() -> str:
    """홈 푸터에 붙는 고지 링크 묶음."""
    items = " · ".join(f'<a href="/{slug}">{title}</a>' for slug, title in TITLES.items())
    return f'<span class="legal-links">{items}</span>'
