"""MCP 구현 — Streamable HTTP(JSON-RPC 2.0) 처리와 stdio 진입점.

`mcp.handle`·`mcp.batch` 는 `POST /mcp` 가 쓰고, `python -m franchise_kr.mcp_stdio` 가
같은 함수를 stdio 로 감쌉니다.

`POST /mcp` · `POST /v1/mcp` 로 들어온 JSON-RPC 2.0 한 건(또는 배치)을 처리합니다.
지원: `initialize`, `notifications/initialized`, `notifications/cancelled`, `ping`,
`tools/list`, `tools/call`, `resources/list`, `prompts/list`.

정직한 한계
-----------
- 응답은 `application/json` 한 덩어리입니다(SSE 스트리밍 없음). MCP 스펙은 스트리밍을
  강제하지 않으므로 대부분의 클라이언트가 그대로 동작합니다.
- 세션·인증이 없습니다. 툴 호출에 키도 필요 없습니다(공개 읽기 전용 판정).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .api import call_tool, mcp_tools, text_summary
from .version import __version__

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "frnc"
SERVER_VERSION = __version__

INSTRUCTIONS_KO = (
    "FRNC — 한국 프랜차이즈 정보공개서·계약 조건 리스크 체크. 브랜드·업종·가맹비·인테리어 "
    "비용과 본부가 제시한 조건(정보공개서 수령 후 경과일, 예상매출 서면, 가맹금 예치·납부 방식, "
    "인테리어 지정, 영업지역, 폐점률, 법 위반 이력 등)을 가맹사업법·시행령 조문과 대조해 "
    "위험 신호·체크리스트·질문·근거를 돌려줍니다. 판정은 check_likely(확인 필요 신호 있음) / "
    "info_needed(정보 부족) / low_risk(뚜렷한 위험 신호 없음) 세 가지이며 확정 판정이 아닙니다. "
    "info_needed 이면 결과의 questions_ko 를 사용자에게 그대로 물어보세요. "
    "브랜드 조회는 공정위 가맹정보 API 승인 전까지 data_state=sample 로 응답하며 apply_urls 를 "
    "함께 줍니다. 창업 지원금은 startup_support 의 GRNT 링크로 안내하세요. "
    "응답의 disclaimer_ko 와 scope_limits_ko 를 사용자에게 함께 전달하세요."
)


def _ok(msg_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def error_response(msg_id: Any, code: int, message: str,
                   data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": error}


def _text_result(result: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
    summary = text_summary(result)
    body = (summary + "\n\n" if summary else "") + json.dumps(result, ensure_ascii=False)
    return {
        "content": [{"type": "text", "text": body}],
        "structuredContent": result,
        "isError": is_error,
    }


def handle(payload: Any, *, store: Any = None, client_id: str = "anonymous") -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return error_response(None, -32600, "invalid_request")

    method = payload.get("method")
    msg_id = payload.get("id")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _ok(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS_KO,
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return _ok(msg_id, {})

    if method == "tools/list":
        return _ok(msg_id, {"tools": mcp_tools()})

    if method == "resources/list":
        return _ok(msg_id, {"resources": []})

    if method == "prompts/list":
        return _ok(msg_id, {"prompts": []})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return error_response(msg_id, -32602, "invalid_params")
        result = call_tool(name, arguments, store=store, client_id=client_id)
        if isinstance(result, dict) and result.get("ok") is False:
            if result.get("error") == "unknown_tool":
                return error_response(msg_id, -32602, "unknown_tool", data={"tool": name})
            return _ok(msg_id, _text_result(result, is_error=True))
        return _ok(msg_id, _text_result(result))

    if msg_id is None:
        return None
    return error_response(msg_id, -32601, "method_not_found", data={"method": method})


def batch(payloads: List[Any], **kwargs: Any) -> List[Dict[str, Any]]:
    out = []
    for item in payloads:
        response = handle(item, **kwargs)
        if response is not None:
            out.append(response)
    return out
