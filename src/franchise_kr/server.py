"""표준 라이브러리만으로 동작하는 HTTP 서버 — 웹 UI + JSON API + MCP.

환경변수
--------
- `HOST`(기본 0.0.0.0) · `PORT`(기본 8787)
- `FRNC_DB`   익명 카운터·문의 접수 SQLite(기본 `data/app.sqlite`)
- `FRNC_STATS_PATH` 카운터만 따로 둘 경로(영속 디스크·백업용, 선택)
- `PUBLIC_BASE_URL` robots/llms/sitemap 의 공개 주소
- `DATA_GO_KR_SERVICE_KEY` 가맹정보 API 인증키(선택 — 없으면 내장 색인·샘플)
- `GOOGLE_SITE_VERIFICATION`·`NAVER_SITE_VERIFICATION`·`SITE_VERIFICATION_FILES` 소유확인(선택)
- `FRNC_RATE_LIMIT_PER_MINUTE`(기본 240) · `FRNC_RATE_WRITE_PER_MINUTE`(기본 30) ·
  `FRNC_RATE_WINDOW_SECONDS`(기본 60) — 0이면 그 축은 끔
- `FRNC_INQUIRY_WEBHOOK_URL` 문의 접수 웹훅(선택) · `FRNC_INQUIRY_WEBHOOK_CONTACT`(기본 꺼짐)
- `FRNC_INQUIRY_MIRROR` 문의 JSONL 미러 파일(영구 볼륨, 선택 — 재시작 시 DB 로 복구)
- `FRNC_ADMIN_TOKEN` 문의 조회(`GET /v1/inquiries`) 토큰(없으면 그 경로는 404)

경로
----
`GET /` 웹 UI · `/guides/`(질문형 17종) · `/guides/{slug}` · `/healthz` · `/v1/meta` ·
`/v1/stats` · `/v1/mcp`(매니페스트) · `/v1/inquiries`(문의 조회, 토큰)
`/robots.txt` · `/llms.txt` · `/sitemap.xml` · `/.well-known/mcp/server-card.json` ·
`POST /v1/tools/{tool}` · `/mcp`·`/v1/mcp`(JSON-RPC) · `/v1/inquiry`(문의)

보안
----
- 서버가 비밀값을 요구하지 않습니다(공개 읽기 전용 판정). 인증키는 아웃바운드 호출에만 쓰고
  응답·페이지·로그에 남기지 않습니다.
- 페이지는 인라인 CSS/JS 만 쓰고 CSP 로 외부 로드를 막습니다.
- 처리되지 않은 예외는 스택트레이스 없이 `internal_error`.
- 요청 제한은 IP 를 저장하지 않고 프로세스 난수로 해시한 메모리 키만 씁니다(재배포 시 초기화).
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import (engine, guides, legal, live_api, mcp, notify, rate_limit, site_verification,
               static_files, usage)
from .config import load_dotenv
from .api import call_tool, mcp_manifest, submit_inquiry
from .store import Store
from .version import __version__
from .web_ui import render_not_found, render_page

MAX_BODY = 64 * 1024
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
MCP_PATHS = ("/mcp", "/v1/mcp")
INQUIRY_PATH = "/v1/inquiry"
INQUIRIES_PATH = "/v1/inquiries"
INQUIRY_ERROR_STATUS = {"daily_cap_reached": 429, "store_unavailable": 503}
RATE_EXEMPT_PATHS = ("/healthz",)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'"
    ),
}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": (
        "Content-Type, Accept, X-Client-Id, MCP-Protocol-Version, Last-Event-ID"
    ),
    "Access-Control-Expose-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


def project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def default_db_path() -> str:
    return os.path.join(project_root(), "data", "app.sqlite")


def _int_env(value: Optional[str], fallback: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if 0 <= parsed <= 65535 else fallback


def _guide_slug(path: str) -> Optional[str]:
    """/guides/{slug} 경로에서 슬러그만 꺼낸다(다른 경로면 None)."""
    raw = str(path or "")
    if not raw.startswith("/guides/"):
        return None
    remainder = raw[len("/guides/"):].strip("/")
    if not remainder or "/" in remainder:
        return None
    return remainder


def config_from_env(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = os.environ if env is None else env
    db_path = (env.get("FRNC_DB") or "").strip() or default_db_path()
    stats_path = (env.get("FRNC_STATS_PATH") or "").strip() or db_path
    limits = rate_limit.limits_from_env(env)
    return {
        "host": (env.get("HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST,
        "port": _int_env(env.get("PORT"), DEFAULT_PORT),
        "db_path": db_path,
        "stats_path": stats_path,
        "rate_limit_per_minute": limits["per_minute"],
        "rate_write_per_minute": limits["write_per_minute"],
        "rate_window_seconds": limits["window_seconds"],
        "admin_token": (env.get("FRNC_ADMIN_TOKEN") or "").strip(),
        "env": dict(env),
    }


def _days_param(query: str) -> int:
    try:
        return int((parse_qs(query or "").get("days") or [""])[0])
    except (TypeError, ValueError):
        return usage.DEFAULT_DAYS


def health_payload(store: Optional[Store] = None,
                   config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    live = live_api.health_block()
    law = engine.law_meta()
    cfg = config or {}
    return {
        "ok": True,
        "service": "frnc",
        "version": __version__,
        "data_state": "sample" if live["approval"]["approved"] == 0 else "live",
        "trap_cases": len(engine.trap_cases()),
        "guides": len(guides.GUIDES),
        "law_articles": law.get("article_count", 0),
        "law_effective": [law_ for law_ in (law.get("laws") or [])],
        "live_api": live,
        "inquiries": usage.inquiry_summary(store, include_cohort=False),
        "alerts": notify.status(cfg.get("env")),
        "rate_limit": {
            "per_minute": int(cfg.get("rate_limit_per_minute") or 0),
            "write_per_minute": int(cfg.get("rate_write_per_minute") or 0),
            "window_seconds": int(cfg.get("rate_window_seconds") or 0),
            "stores_ip": False,
        },
    }


def make_handler(store: Optional[Store] = None, config: Optional[Dict[str, Any]] = None,
                 limiter: Optional[rate_limit.RateLimiter] = None,
                 inquiry_limiter: Optional[rate_limit.RateLimiter] = None):
    """요청 핸들러 팩토리 — 테스트에서는 `limiter` 를 직접 줘 한도를 낮출 수 있다."""
    cfg = dict(config or config_from_env())
    window = float(cfg.get("rate_window_seconds") or rate_limit.DEFAULT_WINDOW_SECONDS)
    if limiter is None and int(cfg.get("rate_limit_per_minute") or 0) > 0:
        limiter = rate_limit.RateLimiter(int(cfg["rate_limit_per_minute"]), window)
    if inquiry_limiter is None and int(cfg.get("rate_write_per_minute") or 0) > 0:
        inquiry_limiter = rate_limit.RateLimiter(int(cfg["rate_write_per_minute"]), window)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"frnc/{__version__}"
        sys_version = ""
        admin_token = str(cfg.get("admin_token") or "")
        app_config = cfg
        general_limiter = limiter
        write_limiter = inquiry_limiter

        def version_string(self) -> str:
            return self.server_version

        # --- 헬퍼 ------------------------------------------------------------
        def _common_headers(self) -> None:
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)
            info = getattr(self, "_rate_info", None)
            if info:
                self.send_header("X-RateLimit-Limit", str(info["limit"]))
                self.send_header("X-RateLimit-Remaining", str(info["remaining"]))
                self.send_header("X-RateLimit-Window", str(info["window_seconds"]))

        def _send_json(self, status: int, payload: Any, cache: str = "no-store",
                       extra_headers: Optional[Dict[str, str]] = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, status: int, text: str, content_type: str,
                       cache: str = "public, max-age=3600") -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status: int, html: str, cache: str = "no-cache") -> None:
            self._send_text(status, html, "text/html; charset=utf-8", cache)

        def _send_bytes(self, status: int, body: bytes, content_type: str,
                        cache: str = "public, max-age=86400") -> None:
            """바이너리 응답(PNG 등) — 텍스트 경로와 같은 헤더 구성을 쓴다."""
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_empty(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:  # 조용한 로그
            return

        def _read_body(self) -> Optional[bytes]:
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._send_json(400, {"ok": False, "error": "invalid_content_length"})
                return None
            if length > MAX_BODY:
                self._send_json(413, {"ok": False, "error": "payload_too_large"})
                return None
            return self.rfile.read(length) if length else b""

        def _client_rate_key(self) -> str:
            """클라이언트 식별 키 — 원문 IP 는 해시해 메모리에서만 쓰고 저장하지 않는다.

            배포 환경(Render 등)은 프록시 뒤라 소켓 주소가 모두 같습니다. 그래서
            `X-Forwarded-For` 의 **마지막 값**(프록시가 붙인 실제 클라이언트)을 쓰고, 없으면
            소켓 주소를 씁니다. 실제 클라이언트를 쓰지 않으면 전 사이트가 한 버킷을 나눠 쓰게
            됩니다.
            """
            raw = ""
            forwarded = str(self.headers.get("X-Forwarded-For") or "")
            if forwarded:
                parts = [part.strip() for part in forwarded.split(",") if part.strip()]
                if parts:
                    raw = parts[-1]
            if not raw:
                raw = self.client_address[0] if self.client_address else "anonymous"
            return rate_limit.client_key(raw)

        def _enforce_rate(self, active: Optional[rate_limit.RateLimiter]) -> bool:
            """한도를 넘으면 429 + Retry-After 로 끊는다(통과하면 True)."""
            if active is None:
                return True
            verdict = active.check(self._client_rate_key())
            self._rate_info = verdict
            if verdict["allowed"]:
                return True
            usage.record_rate_limited(store)
            retry = max(1, int(verdict["retry_after"] or 1))
            self._send_json(429, {
                "ok": False,
                "error": "rate_limited",
                "message_ko": ("요청이 너무 많습니다. 잠시 뒤 다시 시도해 주세요. "
                               "(클라이언트당 분당 요청 수 제한) 지금은 통계·판정을 저장하지 "
                               "않았습니다."),
                "retry_after_s": retry,
                "limit": verdict["limit"],
            }, extra_headers={"Retry-After": str(retry)})
            return False

        def _handle_admin_inquiries(self) -> None:
            """`GET /v1/inquiries` — 관리자 토큰이 있을 때만 접수 요약·최근 접수를 돌려준다."""
            if not self.admin_token:
                # 토큰이 설정되지 않았으면 경로의 존재 자체를 드러내지 않는다.
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            supplied = str(self.headers.get("X-Admin-Token") or "").strip()
            if not supplied:
                supplied = (parse_qs(urlparse(self.path).query).get("token") or [""])[0].strip()
            if not supplied or not hmac.compare_digest(supplied, self.admin_token):
                self._send_json(401, {"ok": False, "error": "unauthorized",
                                      "message_ko": "관리자 토큰이 필요합니다."})
                return
            try:
                limit = int((parse_qs(urlparse(self.path).query).get("limit") or ["50"])[0])
            except (TypeError, ValueError):
                limit = 50
            recent = store.recent_inquiries(limit) if store is not None else []
            last_alert = None
            if store is not None:
                try:
                    last_alert = store.get_state("inquiry_alert_last")
                except Exception:  # noqa: BLE001 - 상태 읽기 실패는 빈 값으로
                    last_alert = None
            self._send_json(200, {
                "ok": True,
                "summary": usage.inquiry_summary(store),
                "recent": recent,
                "last_alert": last_alert,
                "alerts": notify.status(self.app_config.get("env")),
                "privacy": {
                    "contact_used_for": "reply_only",
                    "in_usage_stats": False,
                    "keep_days": usage.INQUIRY_KEEP_DAYS,
                    "note_ko": ("연락처는 회신 목적으로만 이 응답에 실립니다. 통계·화면에는 "
                                "나가지 않습니다."),
                },
                "checked_at": engine.now_iso(),
            }, cache="no-store")

        # --- 라우팅 ----------------------------------------------------------
        def do_HEAD(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._head(200, "text/html; charset=utf-8")
            elif path in ("/guides", "/guides/index.html"):
                self._head(301, "text/html; charset=utf-8")
            elif _guide_slug(path) is not None:
                self._head(200 if guides.by_slug(_guide_slug(path)) else 404,
                           "text/html; charset=utf-8")
            elif path in ("/healthz", "/v1/stats", "/v1/meta", "/v1/mcp",
                          "/.well-known/mcp/server-card.json", "/v1/tools"):
                self._head(200, "application/json; charset=utf-8")
            elif path in ("/robots.txt", "/llms.txt"):
                self._head(200, "text/plain; charset=utf-8")
            elif legal.is_page(path):
                self._head(200, "text/html; charset=utf-8")
            elif path == "/static/og.png":
                self._head(200, "image/png")
            elif path == "/sitemap.xml":
                self._head(200, "application/xml; charset=utf-8")
            elif site_verification.file_body(path) is not None:
                self._head(200, "text/html; charset=utf-8")
            elif path.startswith("/v1/") or path.startswith("/mcp"):
                self._head(404, "application/json; charset=utf-8")
            else:
                self._head(404, "text/html; charset=utf-8")

        def _head(self, status: int, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", "0")
            if status == 301:
                self.send_header("Location", "/guides/")
            self._common_headers()
            self.end_headers()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Allow", "GET, POST, HEAD, OPTIONS")
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in RATE_EXEMPT_PATHS and not self._enforce_rate(self.general_limiter):
                return
            usage.record_request(store, "GET", path,
                                 client=usage.client_class(self.headers.get("User-Agent")))
            try:
                if path in ("/", "/index.html"):
                    meta = call_tool("get_service_meta", {}, store=store)["result"]["meta"]
                    self._send_html(200, render_page(meta))
                elif path in ("/guides", "/guides/index.html"):
                    self.send_response(301)
                    self.send_header("Location", "/guides/")
                    self.send_header("Content-Length", "0")
                    self._common_headers()
                    self.end_headers()
                elif path == "/guides/":
                    self._send_html(200, guides.render_index(), cache="public, max-age=600")
                elif _guide_slug(path) is not None:
                    html = guides.render_item(_guide_slug(path) or "")
                    if html is None:
                        self._send_json(404, {"ok": False, "error": "not_found"})
                    else:
                        self._send_html(200, html, cache="public, max-age=600")
                elif path == "/favicon.ico":
                    self._send_empty(204)
                elif path == "/static/og.png":
                    # 공유 미리보기 — 이미지 파일이 없으면 표준 라이브러리로 만든 PNG 를 준다.
                    self._send_bytes(200, static_files.load_og_image(), "image/png",
                                     "public, max-age=86400")
                elif legal.is_page(path):
                    # /privacy · /terms · /about — 서버 렌더 정적 HTML(JS·외부 CDN 없음).
                    self._send_html(200, legal.render(path) or "", cache="public, max-age=3600")
                elif path == "/healthz":
                    self._send_json(200, health_payload(store, self.app_config))
                elif path == "/robots.txt":
                    self._send_text(200, static_files.robots_txt(), "text/plain; charset=utf-8")
                elif path == "/llms.txt":
                    self._send_text(200, static_files.llms_txt(), "text/plain; charset=utf-8")
                elif path == "/sitemap.xml":
                    self._send_text(200, static_files.sitemap_xml(),
                                    "application/xml; charset=utf-8")
                elif path == "/.well-known/mcp/server-card.json":
                    self._send_json(200, static_files.server_card(), cache="public, max-age=300")
                elif path == "/v1/mcp":
                    self._send_json(200, mcp_manifest())
                elif path == "/v1/meta":
                    self._send_json(200, call_tool("get_service_meta", {}, store=store))
                elif path == "/v1/tools":
                    self._send_json(200, mcp_manifest())
                elif path == "/v1/stats":
                    query = urlparse(self.path).query
                    self._send_json(200, usage.statistics(store, _days_param(query)),
                                    cache="public, max-age=300")
                elif path == INQUIRIES_PATH:
                    self._handle_admin_inquiries()
                elif path == INQUIRY_PATH:
                    self._send_method_not_allowed()
                elif site_verification.file_body(path) is not None:
                    self._send_text(200, site_verification.file_body(path) or "",
                                    "text/html; charset=utf-8")
                elif path.rstrip("/") == "/mcp":
                    self._send_method_not_allowed()
                elif path.startswith("/v1/") or path.startswith("/mcp") or path in (
                        "/healthz", "/v1", "/v1/"):
                    self._send_json(404, {"ok": False, "error": "not_found"})
                else:
                    # 사람이 주소를 잘못 친 경우 — JSON 대신 다음에 할 일을 안내한다.
                    self._send_html(404, render_not_found(path), cache="no-store")
            except Exception:  # noqa: BLE001 - 내부 정보를 노출하지 않는다
                self._send_json(500, {"ok": False, "error": "internal_error"})

        def _send_method_not_allowed(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "POST, OPTIONS")
            self.send_header("Content-Length", "0")
            self._common_headers()
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if not self._enforce_rate(self.general_limiter):
                return
            if path == INQUIRY_PATH and not self._enforce_rate(self.write_limiter):
                return
            usage.record_request(store, "POST", path,
                                 client=usage.client_class(self.headers.get("User-Agent")))
            if path == INQUIRY_PATH:
                self._handle_inquiry()
                return
            if path.rstrip("/") in MCP_PATHS:
                self._handle_mcp()
                return
            if not path.startswith("/v1/tools/"):
                self._send_json(404, {"ok": False, "error": "not_found"})
                return
            name = path.rsplit("/", 1)[-1]
            raw = self._read_body()
            if raw is None:
                return
            try:
                args = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            if not isinstance(args, dict):
                self._send_json(400, {"ok": False, "error": "invalid_argument",
                                      "message": "request_body_must_be_object"})
                return
            try:
                result = call_tool(name, args, store=store, client_id=self._client())
            except Exception:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": "internal_error", "tool": name})
                return
            status = 200 if result.get("ok") is not False else (
                404 if result.get("error") == "unknown_tool" else 400)
            self._send_json(status, result)

        def _handle_inquiry(self) -> None:
            raw = self._read_body()
            if raw is None:
                return
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"ok": False, "error": "invalid_argument"})
                return
            try:
                result = submit_inquiry(payload, store)
            except Exception:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": "internal_error"})
                return
            if result.get("ok"):
                self._send_json(200, result)
                return
            status = INQUIRY_ERROR_STATUS.get(str(result.get("error") or ""), 400)
            self._send_json(status, result)

        def _handle_mcp(self) -> None:
            raw = self._read_body()
            if raw is None:
                return
            try:
                payload = json.loads(raw.decode("utf-8")) if raw.strip() else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(200, mcp.error_response(None, -32700, "parse_error"))
                return
            options = {"store": store, "client_id": self._client()}
            try:
                if isinstance(payload, list):
                    if not payload:
                        self._send_json(200, mcp.error_response(None, -32600, "invalid_request"))
                        return
                    out = mcp.batch(payload, **options)
                    if not out:
                        self._send_empty(202)
                        return
                    self._send_json(200, out)
                    return
                out = mcp.handle(payload, **options)
            except Exception:  # noqa: BLE001
                self._send_json(500, mcp.error_response(None, -32603, "internal_error"))
                return
            if out is None:
                self._send_empty(202)
                return
            self._send_json(200, out)

        def _client(self) -> str:
            raw = str(self.headers.get("X-Client-Id") or "anonymous")
            safe = "".join(ch for ch in raw if ch.isalnum() or ch in "._:-")[:64]
            return safe or "anonymous"

    return Handler


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, db_path: str = "",
          stats_path: str = "", config: Optional[Dict[str, Any]] = None) -> None:
    cfg = dict(config or config_from_env())
    db_path = stats_path or db_path or str(cfg.get("db_path") or "") or default_db_path()
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    store = Store(db_path)
    usage.purge_inquiries(store)
    # 미러 파일(FRNC_INQUIRY_MIRROR)이 있으면 재시작으로 비워진 DB 에 되돌려 놓는다.
    restored = notify.restore(store, cfg.get("env"))
    httpd = ThreadingHTTPServer((host, port), make_handler(store, config=cfg))
    live = live_api.health_block()
    print(f"FRNC listening on http://{host}:{port} "
          f"(trap_cases={len(engine.trap_cases())}, "
          f"law_articles={engine.law_meta().get('article_count')}, "
          f"ftc_approved={live['approval']['approved']}/{live['approval']['total']}, "
          f"db={db_path}, rate={cfg.get('rate_limit_per_minute')}/min, "
          f"inquiry_restored={restored.get('imported', 0)})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        store.close()


def main(argv: Optional[list] = None) -> int:
    load_dotenv()  # 로컬 .env(있을 때만) — 배포에서는 플랫폼 환경변수를 쓴다.
    parser = argparse.ArgumentParser(
        prog="python -m franchise_kr.server",
        description="FRNC 서버 — 프랜차이즈 정보공개서·리스크 체크 (웹 UI + JSON API + MCP)")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    cfg = config_from_env()
    serve(host=args.host or cfg["host"],
          port=args.port if args.port is not None else cfg["port"],
          db_path=args.db or cfg["db_path"], stats_path=cfg["stats_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
