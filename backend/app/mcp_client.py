from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import httpx

from .models import McpServer
from .secrets import decrypt_secret


PROTOCOL_VERSION = "2025-03-26"


def _json_response(response: httpx.Response) -> dict[str, Any]:
    """Accept the JSON and single-event SSE forms used by streamable HTTP MCP servers."""
    if not response.content:
        return {}
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        value = response.json()
        return value if isinstance(value, dict) else {}
    for line in response.text.splitlines():
        if line.startswith("data:"):
            value = json.loads(line[5:].strip())
            if isinstance(value, dict):
                return value
    raise ValueError("MCP 服务返回了无法识别的响应格式")


def _headers(server: McpServer, session_id: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if server.encrypted_bearer_token:
        headers["Authorization"] = f"Bearer {decrypt_secret(server.encrypted_bearer_token)}"
    return headers


async def _post(client: httpx.AsyncClient, server: McpServer, method: str, params: dict[str, Any] | None, session_id: str | None = None) -> tuple[dict[str, Any], str | None]:
    payload = {"jsonrpc": "2.0", "id": uuid4().hex, "method": method}
    if params is not None:
        payload["params"] = params
    response = await client.post(server.url, headers=_headers(server, session_id), json=payload)
    response.raise_for_status()
    body = _json_response(response)
    if body.get("error"):
        raise ValueError(str(body["error"].get("message") or "MCP 服务返回错误"))
    return body, response.headers.get("Mcp-Session-Id") or session_id


async def _session(client: httpx.AsyncClient, server: McpServer) -> str | None:
    _, session_id = await _post(client, server, "initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "Insight Studio", "version": "2.0"},
    })
    # Notifications intentionally have no request id. Most servers accept a JSON-RPC
    # notification and reply 202 with an empty body.
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    response = await client.post(server.url, headers=_headers(server, session_id), json=notification)
    response.raise_for_status()
    return session_id


async def list_tools(server: McpServer) -> tuple[list[dict[str, Any]], int]:
    started = time.perf_counter()
    # Never route local MCP traffic through desktop/system proxy settings. This is
    # especially important for localhost Superset, where a corporate proxy returns 502.
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        session_id = await _session(client, server)
        body, _ = await _post(client, server, "tools/list", {}, session_id)
    tools = body.get("result", {}).get("tools", [])
    if not isinstance(tools, list):
        raise ValueError("MCP 服务没有返回工具列表")
    return [tool for tool in tools if isinstance(tool, dict)][:200], max(1, round((time.perf_counter() - started) * 1000))


async def call_tool(server: McpServer, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
        session_id = await _session(client, server)
        body, _ = await _post(client, server, "tools/call", {"name": name, "arguments": arguments}, session_id)
    result = body.get("result", {})
    if not isinstance(result, dict):
        raise ValueError("MCP 工具没有返回结构化结果")
    return result, max(1, round((time.perf_counter() - started) * 1000))
