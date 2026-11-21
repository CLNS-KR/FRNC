"""HTTP 요청 제한 — 프로세스 메모리 고정 창(fixed window) 카운터.

왜 필요한가
-----------
공개 MCP·JSON API 는 인증이 없어서, 한 클라이언트가 무한정 두드리면 스레드·SQLite 쓰기가
같이 밀립니다(무료 플랜은 CPU·메모리가 작습니다). 그래서 기본 요청 제한을 둡니다.

저장하지 않는 것
---------------
IP·User-Agent·경로별 기록을 **저장하지 않습니다.** 클라이언트 식별자는 프로세스가 시작할 때
만든 난수 salt 로 해시해 메모리 키로만 쓰고(원문 IP 는 어디에도 남기지 않습니다), 창이 지나면
지웁니다. 재배포하면 카운터도 함께 초기화됩니다.

설정
----
- `FRNC_RATE_LIMIT_PER_MINUTE`  일반 GET/POST 분당 허용(기본 240, 0이면 끔)
- `FRNC_RATE_WRITE_PER_MINUTE`  쓰기(POST `/v1/inquiry`) 분당 허용(기본 30, 0이면 끔)
- `FRNC_RATE_WINDOW_SECONDS`    창 길이(기본 60)
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

DEFAULT_PER_MINUTE = 240
DEFAULT_WRITE_PER_MINUTE = 30
DEFAULT_WINDOW_SECONDS = 60.0
MIN_WINDOW_SECONDS = 1.0
MAX_TRACKED_KEYS = 8192

# 프로세스마다 새로 만드는 salt — 메모리 키에만 쓰고 어디에도 남기지 않는다.
_SALT = os.urandom(16)


def client_key(raw: str) -> str:
    """IP 등 원문 식별자 → 메모리에서만 쓰는 해시 키(원문은 저장하지 않는다)."""
    digest = hashlib.sha256(_SALT)
    digest.update(str(raw or "anonymous").encode("utf-8", "replace"))
    return digest.hexdigest()[:24]


def _int_env(env: Dict[str, str], name: str, fallback: int) -> int:
    raw = str(env.get(name, "") or "").strip()
    if not raw:
        return fallback
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return fallback
    return value if value >= 0 else fallback


def _float_env(env: Dict[str, str], name: str, fallback: float) -> float:
    raw = str(env.get(name, "") or "").strip()
    if not raw:
        return fallback
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value >= MIN_WINDOW_SECONDS else fallback


def limits_from_env(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """환경변수 → 요청 제한 설정(0이면 그 축은 끔)."""
    source = os.environ if env is None else env
    return {
        "per_minute": _int_env(source, "FRNC_RATE_LIMIT_PER_MINUTE", DEFAULT_PER_MINUTE),
        "write_per_minute": _int_env(source, "FRNC_RATE_WRITE_PER_MINUTE",
                                     DEFAULT_WRITE_PER_MINUTE),
        "window_seconds": _float_env(source, "FRNC_RATE_WINDOW_SECONDS",
                                     DEFAULT_WINDOW_SECONDS),
    }


class RateLimiter:
    """고정 창 카운터 — (시작 시각, 횟수)만 메모리에 둔다.

    `clock` 을 주면 시간을 갈아 끼울 수 있습니다(테스트·재현용).
    """

    def __init__(self, limit: int, window_seconds: float = DEFAULT_WINDOW_SECONDS, *,
                 clock: Optional[Callable[[], float]] = None,
                 max_keys: int = MAX_TRACKED_KEYS) -> None:
        self.limit = max(1, int(limit))
        self.window = max(MIN_WINDOW_SECONDS, float(window_seconds))
        self._clock = clock or time.monotonic
        self._max_keys = max(16, int(max_keys))
        self._lock = threading.Lock()
        self._buckets: Dict[str, Tuple[float, int]] = {}

    def check(self, key: str) -> Dict[str, Any]:
        """1회 소비 → `{allowed, limit, remaining, retry_after, window_seconds}`."""
        now = self._clock()
        with self._lock:
            start, count = self._buckets.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            count += 1
            self._buckets[key] = (start, count)
            if len(self._buckets) > self._max_keys:
                self._prune(now)
            allowed = count <= self.limit
            remaining = max(0, self.limit - count)
            retry_after = 0 if allowed else max(1, int(round(self.window - (now - start))))
        return {
            "allowed": allowed,
            "limit": self.limit,
            "remaining": remaining,
            "retry_after": retry_after,
            "window_seconds": int(self.window),
        }

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def _prune(self, now: float) -> None:
        stale = [key for key, (start, _count) in self._buckets.items()
                 if now - start >= self.window]
        for key in stale:
            self._buckets.pop(key, None)
        if len(self._buckets) > self._max_keys:
            # 창이 살아 있는 키가 상한을 넘으면 가장 오래된 것부터 버린다(메모리 보호).
            ordered = sorted(self._buckets.items(), key=lambda item: item[1][0])
            for key, _value in ordered[:len(self._buckets) - self._max_keys]:
                self._buckets.pop(key, None)

    def snapshot(self) -> Dict[str, Any]:
        """운영 확인용 — 추적 중인 키 수(키 원문은 돌려주지 않는다)."""
        with self._lock:
            return {"limit": self.limit, "window_seconds": int(self.window),
                    "tracked_clients": len(self._buckets)}
