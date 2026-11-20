"""stdio MCP — 한 줄에 JSON-RPC 2.0 한 건을 stdin 으로 받고 stdout 으로 응답한다.

로컬 MCP 디렉터리(예: Claude Desktop)에서 `python -m franchise_kr.mcp_stdio` 로 실행합니다.
로그는 stderr 로만 보내 stdout 을 JSON-RPC 전용으로 유지합니다.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from . import mcp
from .store import Store


def main(argv: Optional[list] = None) -> int:
    store = Store(":memory:")
    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                print(json.dumps(mcp.error_response(None, -32700, "parse_error"),
                                 ensure_ascii=False), flush=True)
                continue
            try:
                if isinstance(payload, list):
                    out: Optional[Any] = mcp.batch(payload, store=store)
                else:
                    out = mcp.handle(payload, store=store)
            except Exception:  # noqa: BLE001
                print(json.dumps(mcp.error_response(None, -32603, "internal_error"),
                                 ensure_ascii=False), flush=True)
                continue
            if out is None:
                continue
            print(json.dumps(out, ensure_ascii=False), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
