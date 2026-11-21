"""`.env` 로더 — 표준 라이브러리만 씁니다(pip 의존성 0 원칙 유지).

왜 필요한가
-----------
인증키는 **배포 환경변수**로 넣는 것이 원칙이고, 로컬에서만 `.env`(gitignore)로 씁니다.
라이브러리 모듈은 import 시점에 `.env` 를 읽지 않습니다. 테스트가 실제 API 를 부르지 않도록
`.env` 는 **실행 진입점**(서버·CLI·도구 스크립트)에서만 읽습니다.

사용
----
    from .config import load_dotenv
    load_dotenv()          # 프로젝트 루트의 .env → os.environ (없으면 조용히 넘어감)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_DIR / ".env"
SENSITIVE_KEYS = ("DATA_GO_KR_SERVICE_KEY", "LAW_GO_KR_OC")


def parse_dotenv(text: str) -> Dict[str, str]:
    """`KEY=VALUE` 줄만 읽는다. 주석·빈 줄·따옴표를 처리하고 값은 절대 출력하지 않는다."""
    values: Dict[str, str] = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def load_dotenv(path: Optional[str] = None, env: Optional[Dict[str, str]] = None,
                override: bool = False) -> Dict[str, str]:
    """`.env` 값을 `env`(기본 `os.environ`)에 채우고, 실제로 채운 키만 돌려준다."""
    target = os.environ if env is None else env
    file_path = Path(path) if path else DEFAULT_ENV_FILE
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    loaded: Dict[str, str] = {}
    for key, value in parse_dotenv(text).items():
        # 이미 있는 키는 (값이 빈 문자열이어도) 건드리지 않는다 — 빈 값은 "일부러 끔"으로 읽는다.
        if not override and key in target:
            continue
        target[key] = value
        loaded[key] = value
    return loaded


def mask(value: str) -> str:
    """로그·상태 출력용 마스킹(앞 4자만 남긴다)."""
    text = str(value or "")
    return (text[:4] + "…") if len(text) > 4 else ("설정됨" if text else "")
