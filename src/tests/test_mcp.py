"""MCP JSON-RPC 단위 테스트 + stdio 실행 테스트."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path.insert(0, SRC)

from franchise_kr import mcp  # noqa: E402


def rpc(method, params=None, msg_id=1):
    payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


class ProtocolTest(unittest.TestCase):
    def test_initialize_negotiates_version(self):
        out = mcp.handle(rpc("initialize", {"protocolVersion": "2025-03-26"}))
        self.assertEqual(out["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(out["result"]["serverInfo"]["name"], "frnc")
        self.assertIn("tools", out["result"]["capabilities"])

    def test_initialize_unknown_version_falls_back(self):
        out = mcp.handle(rpc("initialize", {"protocolVersion": "1999-01-01"}))
        self.assertEqual(out["result"]["protocolVersion"], mcp.PROTOCOL_VERSIONS[0])

    def test_tools_list(self):
        out = mcp.handle(rpc("tools/list"))
        names = [tool["name"] for tool in out["result"]["tools"]]
        self.assertEqual(len(names), 7)
        self.assertIn("check_franchise_risk", names)

    def test_tools_call_returns_text_and_structured(self):
        out = mcp.handle(rpc("tools/call", {
            "name": "check_franchise_risk",
            "arguments": {"brand_name": "샘플치킨", "disclosure_days_before": 0,
                          "payment_route": "hq_account"},
        }))
        result = out["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertIn("확인 필요 신호", result["content"][0]["text"])
        self.assertTrue(result["structuredContent"]["ok"])
        self.assertEqual(result["structuredContent"]["result"]["verdict"]["code"],
                         "check_likely")

    def test_tool_invalid_argument_is_error_result(self):
        out = mcp.handle(rpc("tools/call", {
            "name": "compare_franchise_terms", "arguments": {"a": {}}}))
        self.assertTrue(out["result"]["isError"])
        self.assertEqual(out["result"]["structuredContent"]["error"], "invalid_argument")

    def test_unknown_tool_is_protocol_error(self):
        out = mcp.handle(rpc("tools/call", {"name": "nope", "arguments": {}}))
        self.assertEqual(out["error"]["code"], -32602)
        self.assertEqual(out["error"]["data"]["tool"], "nope")

    def test_unknown_method_and_invalid_request(self):
        self.assertEqual(mcp.handle(rpc("nope"))["error"]["code"], -32601)
        self.assertEqual(mcp.handle({"id": 1})["error"]["code"], -32600)
        self.assertEqual(mcp.handle("text")["error"]["code"], -32600)

    def test_notifications_return_none(self):
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0",
                                           "method": "notifications/initialized"}))
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0",
                                           "method": "notifications/cancelled"}))

    def test_ping_and_empty_lists(self):
        self.assertEqual(mcp.handle(rpc("ping"))["result"], {})
        self.assertEqual(mcp.handle(rpc("resources/list"))["result"]["resources"], [])
        self.assertEqual(mcp.handle(rpc("prompts/list"))["result"]["prompts"], [])

    def test_batch_drops_notifications(self):
        out = mcp.batch([
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            rpc("ping", msg_id=2),
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], 2)

    def test_invalid_params_shape(self):
        out = mcp.handle(rpc("tools/call", {"name": "ping", "arguments": []}))
        self.assertEqual(out["error"]["code"], -32602)


class StdioTest(unittest.TestCase):
    def test_stdio_roundtrip(self):
        payloads = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "get_law_article", "arguments": {"article": "제7조"}}},
        ]
        env = dict(os.environ, PYTHONPATH=SRC)
        process = subprocess.run(
            [sys.executable, "-m", "franchise_kr.mcp_stdio"],
            input="\n".join(json.dumps(item) for item in payloads) + "\n",
            capture_output=True, text=True, timeout=60, env=env, cwd=os.path.dirname(SRC))
        self.assertEqual(process.returncode, 0, process.stderr[-400:])
        lines = [line for line in process.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        first, second = json.loads(lines[0]), json.loads(lines[1])
        self.assertEqual(first["result"]["serverInfo"]["name"], "frnc")
        self.assertIn("14일", second["result"]["structuredContent"]["result"]["text"])

    def test_stdio_handles_bad_json(self):
        env = dict(os.environ, PYTHONPATH=SRC)
        process = subprocess.run(
            [sys.executable, "-m", "franchise_kr.mcp_stdio"],
            input="{bad json\n", capture_output=True, text=True, timeout=60, env=env,
            cwd=os.path.dirname(SRC))
        self.assertEqual(process.returncode, 0)
        out = json.loads(process.stdout.strip())
        self.assertEqual(out["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
