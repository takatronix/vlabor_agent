"""Connect to one or more MCP servers, expose their tools as a flat
list ready to drop into Anthropic's ``tools=`` parameter.

Connection management is **self-healing**: each configured server gets
a supervisor coroutine that connects on startup, monitors liveness via
periodic ``send_ping``, and reconnects with exponential backoff if the
session drops or the server starts up later than the agent. This means
the agent does not depend on the MCP servers being ready at the moment
it boots, and recovers automatically from MCP server restarts.

Tool names are exposed to the LLM as ``<server>__<tool>`` so two MCP
servers can each define a ``get_state`` without colliding. The
dispatcher splits on ``__`` to route a tool_use back to the right
server.

Phase 0 supports the ``sse`` transport only — that's what vlabor-obs
ships with (FastMCP). ``stdio`` and ``http`` will follow once we have
something to test against.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.sse import sse_client

from .config import McpServerConfig

log = logging.getLogger(__name__)

_NAME_SEP = "__"

_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 30.0
_BACKOFF_FACTOR = 2.0
_PING_INTERVAL = 15.0
_PING_TIMEOUT = 5.0
_INITIAL_GRACE = 3.0


@dataclass
class _ServerState:
    cfg: McpServerConfig
    stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    session: Optional[ClientSession] = None
    tool_names: list[str] = field(default_factory=list)
    tool_specs: list[dict[str, Any]] = field(default_factory=list)
    connected: bool = False
    last_error: Optional[str] = None
    next_retry_at: Optional[float] = None
    backoff: float = _BACKOFF_INITIAL
    wake_event: Optional[asyncio.Event] = None
    supervisor: Optional[asyncio.Task] = None
    first_attempt_done: asyncio.Event = field(default_factory=asyncio.Event)


class McpPool:
    """Owns the live MCP client sessions for the lifetime of the chat
    backend process.

    Lifecycle:
      * ``await pool.start()`` — launches one supervisor coroutine per
        configured server. Returns after a short grace period so the
        common happy-path startup log is accurate, but the pool is
        usable even if servers come up later.
      * ``pool.tools_for_anthropic()`` — current tool spec, rebuilt on
        every call from the live set of connected servers.
      * ``await pool.call(name, args)`` — dispatch a tool_use back to
        the right server.
      * ``await pool.reload()`` — wake disconnected supervisors so they
        retry immediately instead of waiting out their backoff.
      * ``await pool.aclose()`` — clean shutdown.
    """

    def __init__(self, configs: list[McpServerConfig]) -> None:
        self._configs = configs
        self._states: dict[str, _ServerState] = {}
        self._closing = False

    async def start(self) -> None:
        for cfg in self._configs:
            state = _ServerState(cfg=cfg)
            state.wake_event = asyncio.Event()
            self._states[cfg.name] = state
            state.supervisor = asyncio.create_task(
                self._supervise(state), name=f"mcp-supervise-{cfg.name}"
            )
        if self._states and _INITIAL_GRACE > 0:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(s.first_attempt_done.wait() for s in self._states.values())
                    ),
                    timeout=_INITIAL_GRACE,
                )
            except asyncio.TimeoutError:
                pass

    async def aclose(self) -> None:
        self._closing = True
        for st in self._states.values():
            if st.wake_event is not None:
                st.wake_event.set()
            if st.supervisor is not None:
                st.supervisor.cancel()
        for st in self._states.values():
            if st.supervisor is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await st.supervisor
        for st in self._states.values():
            with contextlib.suppress(Exception):
                await st.stack.aclose()
        self._states.clear()

    def server_names(self) -> list[str]:
        return [name for name, st in self._states.items() if st.connected]

    def mcp_status(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for cfg in self._configs:
            st = self._states.get(cfg.name)
            if st is None:
                out.append({
                    "name": cfg.name,
                    "url": cfg.url,
                    "transport": cfg.transport,
                    "connected": False,
                    "tool_count": 0,
                    "tools": [],
                    "last_error": None,
                    "next_retry_at": None,
                })
                continue
            out.append({
                "name": cfg.name,
                "url": cfg.url,
                "transport": cfg.transport,
                "connected": st.connected,
                "tool_count": len(st.tool_names),
                "tools": list(st.tool_names),
                "last_error": st.last_error,
                "next_retry_at": st.next_retry_at,
            })
        return out

    def tools_for_anthropic(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for st in self._states.values():
            if st.connected:
                out.extend(st.tool_specs)
        return out

    def tools_for_openai(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in self.tools_for_anthropic():
            out.append({
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": spec.get("input_schema")
                                  or {"type": "object", "properties": {}},
                },
            })
        return out

    async def call(self, qualified_name: str, args: dict[str, Any]) -> Any:
        server_name, tool_name = _split_name(qualified_name)
        st = self._states.get(server_name)
        if st is None or not st.connected or st.session is None:
            raise RuntimeError(f"mcp server not connected: {server_name}")
        if tool_name not in st.tool_names:
            raise RuntimeError(f"unknown tool {tool_name} on {server_name}")
        return await st.session.call_tool(tool_name, args or {})

    async def reload(self) -> list[str]:
        """Wake every disconnected supervisor so it retries immediately
        with a fresh backoff. Returns the server names that were woken."""
        woken: list[str] = []
        for st in self._states.values():
            if not st.connected and st.wake_event is not None:
                st.backoff = _BACKOFF_INITIAL
                st.wake_event.set()
                woken.append(st.cfg.name)
        if woken:
            log.info("[mcp] reload triggered for: %s", woken)
        return woken

    # --- internal -----------------------------------------------------------

    async def _supervise(self, st: _ServerState) -> None:
        cfg = st.cfg
        if cfg.transport != "sse":
            st.last_error = f"unsupported transport {cfg.transport}"
            log.warning("[mcp] transport %s not supported (server=%s)",
                        cfg.transport, cfg.name)
            st.first_attempt_done.set()
            return
        if not cfg.url:
            st.last_error = "no url"
            log.warning("[mcp] sse server %s has no url; skipping", cfg.name)
            st.first_attempt_done.set()
            return

        first = True
        while not self._closing:
            try:
                await self._connect(st)
                st.backoff = _BACKOFF_INITIAL
                if first:
                    st.first_attempt_done.set()
                    first = False
                await self._monitor(st)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                st.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("[mcp] %s connect failed: %s",
                            st.cfg.name, st.last_error)
            await self._teardown(st)
            if first:
                st.first_attempt_done.set()
                first = False
            if self._closing:
                return
            delay = st.backoff
            st.next_retry_at = time.time() + delay
            woken_by_reload = False
            try:
                await asyncio.wait_for(st.wake_event.wait(), timeout=delay)
                woken_by_reload = True
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise
            finally:
                st.wake_event.clear()
                st.next_retry_at = None
            if woken_by_reload:
                st.backoff = _BACKOFF_INITIAL
            else:
                st.backoff = min(st.backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)

    async def _connect(self, st: _ServerState) -> None:
        cfg = st.cfg
        log.info("[mcp] %s connecting to %s", cfg.name, cfg.url)
        read, write = await st.stack.enter_async_context(sse_client(cfg.url))
        session: ClientSession = await st.stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        listed = await session.list_tools()
        names: list[str] = []
        specs: list[dict[str, Any]] = []
        for tool in listed.tools:
            qualified = f"{cfg.name}{_NAME_SEP}{tool.name}"
            specs.append({
                "name": qualified,
                "description": tool.description or "",
                "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
            })
            names.append(tool.name)
        st.session = session
        st.tool_names = names
        st.tool_specs = specs
        st.connected = True
        st.last_error = None
        log.info("[mcp] %s connected — %d tools", cfg.name, len(names))

    async def _monitor(self, st: _ServerState) -> None:
        """Ping the session at a fixed interval. Returns when the session
        becomes unresponsive — the supervisor will then reconnect."""
        assert st.session is not None
        while not self._closing and st.connected:
            try:
                await asyncio.sleep(_PING_INTERVAL)
            except asyncio.CancelledError:
                raise
            if self._closing or not st.connected:
                return
            try:
                await asyncio.wait_for(st.session.send_ping(), timeout=_PING_TIMEOUT)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                st.last_error = f"ping failed: {type(exc).__name__}: {exc}"
                log.warning("[mcp] %s ping failed, will reconnect: %s",
                            st.cfg.name, exc)
                return

    async def _teardown(self, st: _ServerState) -> None:
        st.connected = False
        st.session = None
        st.tool_names = []
        st.tool_specs = []
        with contextlib.suppress(Exception):
            await st.stack.aclose()
        st.stack = AsyncExitStack()


def _split_name(qualified: str) -> tuple[str, str]:
    if _NAME_SEP not in qualified:
        return ("", qualified)
    server, tool = qualified.split(_NAME_SEP, 1)
    return (server, tool)


__all__ = ["McpPool"]
