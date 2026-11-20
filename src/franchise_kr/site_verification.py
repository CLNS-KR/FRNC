"""검색엔진 소유확인(구글 서치콘솔·네이버 서치어드바이저) 지원.

두 기관 모두 "메타태그를 첫 페이지 head 에 넣기" 또는 "루트에 HTML 확인 파일 올리기"
둘 중 하나로 소유를 확인합니다. 이 모듈은 **환경변수만으로** 그 두 가지를 모두 열어 줍니다.

환경변수
--------
- `GOOGLE_SITE_VERIFICATION`  → `<meta name="google-site-verification" content="...">`
- `NAVER_SITE_VERIFICATION`   → `<meta name="naver-site-verification" content="...">`
- `SITE_VERIFICATION_FILES`   → JSON. 예: `{"google1a2b3c.html": "google-site-verification: ..."}`

원칙
----
1. 익명: 확인 토큰은 검색엔진이 발급한 값 그대로이고, 사람 이름·이메일을 받지 않습니다.
2. 값은 화이트리스트 문자만 남겨 새니타이즈합니다(HTML 주입·경로 이탈 차단).
3. 환경변수가 없으면 아무 것도 내보내지 않습니다.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Optional

ENV_GOOGLE = "GOOGLE_SITE_VERIFICATION"
ENV_NAVER = "NAVER_SITE_VERIFICATION"
ENV_FILES = "SITE_VERIFICATION_FILES"

META_NAMES = (
    ("google-site-verification", ENV_GOOGLE),
    ("naver-site-verification", ENV_NAVER),
)

_TOKEN_UNSAFE = re.compile(r"[^0-9A-Za-z._:-]")
_FILE_NAME_RE = re.compile(r"^[0-9A-Za-z._-]{1,120}\.html$")


def token(value: Optional[str]) -> str:
    return _TOKEN_UNSAFE.sub("", str(value or ""))[:200]


def meta_tags(env: Optional[Dict[str, str]] = None) -> str:
    source = os.environ if env is None else env
    lines = []
    for name, key in META_NAMES:
        value = token(source.get(key))
        if value:
            lines.append(f'<meta name="{name}" content="{value}">')
    return "\n".join(lines)


def _files(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    source = os.environ if env is None else env
    raw = str(source.get(ENV_FILES) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: Dict[str, str] = {}
    for name, body in parsed.items():
        clean = str(name or "").strip().lstrip("/")
        if _FILE_NAME_RE.match(clean):
            out["/" + clean] = str(body or "")[:400]
    return out


def file_body(path: str, env: Optional[Dict[str, str]] = None) -> Optional[str]:
    return _files(env).get(str(path or "").split("?", 1)[0])
