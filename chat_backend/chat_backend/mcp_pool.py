"""Connect to one or more MCP servers, expose their tools as a flat
list ready to drop into Anthropic's ``tools=`` parameter.

Phase 0 supports the ``sse`` transport only — that's what
vlabor-obs ships with (FastMCP). ``stdio`` and ``http`` will follow
once we have something to test against.

Tool names are exposed to the LLM as ``<server>__<tool>`` so two
MCP servers can each define a ``get_state`` without colliding.
The dispatcher splits on ``__`` to route a tool_use back to the
right server.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

from .config import McpServerConfig

log = logging.getLogger(__name__)

_NAME_SEP = "__"


@dataclass
class _ServerHandle:
    name: str
    session: ClientSession
    tool_names: list[str]


class McpPool:
    """Owns the live MCP client sessions for the lifetime of the chat
    backend process.

    Lifecycle:
      * ``await pool.start()`` — connects to every configured server,
        fetches its tool list once, builds the Anthropic tools array.
      * ``pool.tools_for_anthropic()`` — current tool spec to pass to
        ``messages.create(tools=...)``.
      * ``await pool.call(name, args)`` — dispatch a tool_use back to
        the right server. Result comes back as the raw MCP content
        list; the chat loop is responsible for converting that into
        Anthropic ``tool_result`` content blocks.
      * ``await pool.aclose()`` — clean shutdown.
    """

    def __init__(self, configs: list[McpServerConfig]) -> None:
        self._configs = configs
        self._stack = AsyncExitStack()
        self._servers: dict[str, _ServerHandle] = {}
        self._tools_anthropic: list[dict[str, Any]] = []

    async def start(self) -> None:
        for cfg in self._configs:
            try:
                await self._connect_one(cfg)
            except Exception as exc:  # pragma: no cover - logged for ops
                log.exception("[mcp] failed to connect %s (%s): %s", cfg.name, cfg.transport, exc)

    async def aclose(self) -> None:
        await self._stack.aclose()
        self._servers.clear()
        self._tools_anthropic.clear()

    def server_names(self) -> list[str]:
        return list(self._servers.keys())

    def mcp_status(self) -> list[dict[str, Any]]:
        """Per-server snapshot for the UI: connection state, configured
        URL, tool count, tool names. Includes servers that failed to
        connect so the operator can tell what's missing vs. just empty."""
        out: list[dict[str, Any]] = []
        connected = self._servers
        for cfg in self._configs:
            handle = connected.get(cfg.name)
            out.append({
                "name": cfg.name,
                "url": cfg.url,
                "transport": cfg.transport,
                "connected": handle is not None,
                "tool_count": len(handle.tool_names) if handle else 0,
                "tools": list(handle.tool_names) if handle else [],
            })
        return out

    def tools_for_anthropic(self) -> list[dict[str, Any]]:
        return list(self._tools_anthropic)

    def tools_for_openai(self) -> list[dict[str, Any]]:
        """Return the same tools repacked into OpenAI's function-calling
        spec. Names stay qualified (``<server>__<tool>``) so the
        dispatcher in :meth:`call` keeps working unchanged for both
        providers."""
        out: list[dict[str, Any]] = []
        for spec in self._tools_anthropic:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec["name"],
                        "description": spec.get("description", ""),
                        "parameters": spec.get("input_schema")
                                      or {"type": "object", "properties": {}},
                    },
                }
            )
        return out

    async def call(self, qualified_name: str, args: dict[str, Any]) -> Any:
        server_name, tool_name = _split_name(qualified_name)
        handle = self._servers.get(server_name)
        if handle is None:
            raise RuntimeError(f"mcp server not connected: {server_name}")
        if tool_name not in handle.tool_names:
            raise RuntimeError(f"unknown tool {tool_name} on {server_name}")
        return await handle.session.call_tool(tool_name, args or {})

    async def _connect_one(self, cfg: McpServerConfig) -> None:
        if cfg.transport != "sse":
            log.warning("[mcp] transport %s not supported in Phase 0 (server=%s)",
                        cfg.transport, cfg.name)
            return
        if not cfg.url:
            log.warning("[mcp] sse server %s has no url; skipping", cfg.name)
            return

        # The async context managers from the SDK have to live as long
        # as the session — push them onto the exit stack so aclose()
        # tears them down in reverse order.
        read, write = await self._stack.enter_async_context(sse_client(cfg.url))
        session: ClientSession = await self._stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        listed = await session.list_tools()
        names: list[str] = []
        for tool in listed.tools:
            qualified = f"{cfg.name}{_NAME_SEP}{tool.name}"
            self._tools_anthropic.append(
                {
                    "name": qualified,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
                }
            )
            names.append(tool.name)
        self._servers[cfg.name] = _ServerHandle(name=cfg.name, session=session, tool_names=names)
        log.info("[mcp] connected %s — %d tools", cfg.name, len(names))


def _split_name(qualified: str) -> tuple[str, str]:
    if _NAME_SEP not in qualified:
        # Tolerate single-server shorthand by routing to the first
        # connected server; Phase 0 mostly hits this path for the
        # single vlabor-obs default.
        return ("", qualified)
    server, tool = qualified.split(_NAME_SEP, 1)
    return (server, tool)


__all__ = ["McpPool"]
