"""표준 라이브러리만으로 동작하는 HTTP 서버 — 웹 UI + JSON API + MCP.

환경변수
--------
- `HOST`(기본 0.0.0.0) · `PORT`(기본 8787)
- `FRNC_DB`   익명 카운터·문의 접수 SQLite(기본 `data/app.sqlite`)
- `FRNC_STATS_PATH` 카운터만 따로 둘 경로(영속 디스크·백업용, 선택)
- `PUBLIC_BASE_URL` robots/llms/sitemap 의 공개 주소
- `DATA_GO_KR_SERVICE_KEY` 가맹정보 API 인증키(선택 — 없으면 내장 샘플)
- `GOOGLE_SITE_VERIFICATION`·`NAVER_SITE_VERIFICATION`·`SITE_VERIFICATION_FILES` 소유확인(선택)

경로
----
`GET /` 웹 UI · `/guides/`(질문형 17종) · `/guides/{slug}` · `/healthz` · `/v1/meta` ·
`/v1/stats` · `/v1/mcp`(매니페스트) ·
`/robots.txt` · `/llms.txt` · `/sitemap.xml` · `/.well-known/mcp/server-card.json` ·
`POST /v1/tools/{tool}` · `/mcp`·`/v1/mcp`(JSON-RPC) · `/v1/inquiry`(문의)

보안
----
- 서버가 비밀값을 요구하지 않습니다(공개 읽기 전용 판정). 인증키는 아웃바운드 호출에만 쓰고
  응답·페이지·로그에 남기지 않습니다.
- 페이지는 인라인 CSS/JS 만 쓰고 CSP 로 외부 로드를 막습니다.
- 처리되지 않은 예외는 스택트레이스 없이 `internal_error`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import engine, guides, live_api, mcp, site_verification, static_files, usage
from .api import call_tool, mcp_manifest, submit_inquiry
from .store import Store
from .version import __version__
from .web_ui import render_page

MAX_BODY = 64 * 1024
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
MCP_PATHS = ("/mcp", "/v1/mcp")
INQUIRY_PATH = "/v1/inquiry"
INQUIRY_ERROR_STATUS = {"daily_cap_reached": 429, "store_unavailable": 503}

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
    return {
        "host": (env.get("HOST") or DEFAULT_HOST).strip() or DEFAULT_HOST,
        "port": _int_env(env.get("PORT"), DEFAULT_PORT),
        "db_path": db_path,
        "stats_path": stats_path,
    }


def _days_param(query: str) -> int:
    try:
        return int((parse_qs(query or "").get("days") or [""])[0])
    except (TypeError, ValueError):
        return usage.DEFAULT_DAYS


def health_payload() -> Dict[str, Any]:
    live = live_api.health_block()
    law = engine.law_meta()
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
    }


def make_handler(store: Optional[Store] = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"frnc/{__version__}"
        sys_version = ""

        def version_string(self) -> str:
            return self.server_version

        # --- 헬퍼 ------------------------------------------------------------
        def _common_headers(self) -> None:
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            for key, value in CORS_HEADERS.items():
                self.send_header(key, value)

        def _send_json(self, status: int, payload: Any, cache: str = "no-store") -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
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
            elif path == "/sitemap.xml":
                self._head(200, "application/xml; charset=utf-8")
            elif site_verification.file_body(path) is not None:
                self._head(200, "text/html; charset=utf-8")
            else:
                self._head(404, "application/json; charset=utf-8")

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
            usage.record_request(store, "GET", path)
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
                elif path == "/healthz":
                    self._send_json(200, health_payload())
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
                elif path == INQUIRY_PATH:
                    self._send_method_not_allowed()
                elif site_verification.file_body(path) is not None:
                    self._send_text(200, site_verification.file_body(path) or "",
                                    "text/html; charset=utf-8")
                elif path.rstrip("/") == "/mcp":
                    self._send_method_not_allowed()
                else:
                    self._send_json(404, {"ok": False, "error": "not_found"})
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
            usage.record_request(store, "POST", path)
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
          stats_path: str = "") -> None:
    db_path = stats_path or db_path or default_db_path()
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    store = Store(db_path)
    usage.purge_inquiries(store)
    httpd = ThreadingHTTPServer((host, port), make_handler(store))
    live = live_api.health_block()
    print(f"FRNC listening on http://{host}:{port} "
          f"(trap_cases={len(engine.trap_cases())}, "
          f"law_articles={engine.law_meta().get('article_count')}, "
          f"ftc_approved={live['approval']['approved']}/{live['approval']['total']}, "
          f"db={db_path})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        store.close()


def main(argv: Optional[list] = None) -> int:
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
