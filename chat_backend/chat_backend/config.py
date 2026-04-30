"""Runtime config for the chat backend.

Sources, in priority order:
  1. environment variables (VLABOR_AGENT_*)
  2. ~/.vlabor/agent/config.json (per-user, deployment-time)
  3. baked-in defaults below

API keys are *not* read here — they live on disk under
``profile_dir`` (default: ``~/.vlabor/profiles/piper_single_teleop/``)
as ``<provider>_api_key.txt`` files. Reading happens on demand via
:mod:`.keys` so a key rotation doesn't need a restart.

Per-operator preferences (provider choice, voice settings) live in
``~/.vlabor/agent/settings.json`` and are managed by
:mod:`.user_settings` — separate from ``config.json`` because operator
preferences change often (UI), while ``config.json`` is a deployment
artefact (host/port/MCP wiring).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import keys


@dataclass
class McpServerConfig:
    """One MCP server the chat backend will connect to."""

    name: str
    """Stable identifier; surfaced as the tool name prefix to the LLM."""

    transport: str
    """``sse`` / ``http`` / ``stdio``. Phase 0: only ``sse`` is wired."""

    url: str | None = None
    """SSE / HTTP endpoint. Required when transport != ``stdio``."""

    command: list[str] | None = None
    """Process argv when transport == ``stdio``."""

    env: dict[str, str] = field(default_factory=dict)
    """Extra env for stdio transport."""


@dataclass
class ChatBackendConfig:
    host: str = "0.0.0.0"
    port: int = 8888
    """Web service port. Default 8888 collides with vlabor_dashboard, so
    we expect a different port to be set via ``VLABOR_AGENT_PORT`` when
    running side-by-side."""

    anthropic_model: str = "claude-sonnet-4-6"
    """Default model when settings.json doesn't specify one."""

    profile_dir: str = "~/.vlabor/profiles/piper_single_teleop"
    """Directory holding ``<provider>_api_key.txt`` files. Each profile
    gets its own dir so dev / prod keys don't co-mingle."""

    # Backwards-compatibility shim — the original code passed a single
    # ``api_key_path`` pointing at the Anthropic key file. Old callers
    # of ``read_api_key(cfg.api_key_path)`` still work; new code should
    # use ``keys.read_key(cfg.profile_dir, 'anthropic')`` directly.
    api_key_path: str = "~/.vlabor/profiles/piper_single_teleop/anthropic_api_key.txt"

    mcp_servers: list[McpServerConfig] = field(default_factory=list)

    def anthropic_key(self) -> str | None:
        return keys.read_key(self.profile_dir, "anthropic")

    def openai_key(self) -> str | None:
        return keys.read_key(self.profile_dir, "openai")

    @classmethod
    def load(cls) -> "ChatBackendConfig":
        cfg = cls()
        # File overrides (json) — keep the structure obvious so an operator
        # can hand-edit it without reading the dataclasses.
        cfg_path = Path(os.path.expanduser("~/.vlabor/agent/config.json"))
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg = _apply_overrides(cfg, data)
            except (OSError, json.JSONDecodeError) as exc:
                # Don't crash on a corrupt config — log and fall back to defaults.
                # The server's startup banner will print which config it used.
                print(f"[chat_backend] failed to read {cfg_path}: {exc}")

        # Env overrides (last word).
        if env_port := os.environ.get("VLABOR_AGENT_PORT"):
            try:
                cfg.port = int(env_port)
            except ValueError:
                pass
        if env_host := os.environ.get("VLABOR_AGENT_HOST"):
            cfg.host = env_host
        if env_model := os.environ.get("VLABOR_AGENT_MODEL"):
            cfg.anthropic_model = env_model
        if env_key_path := os.environ.get("VLABOR_AGENT_API_KEY_PATH"):
            cfg.api_key_path = env_key_path
            # Derive profile_dir from the key path so the OpenAI key and
            # other per-provider files end up next to it.
            cfg.profile_dir = str(Path(os.path.expanduser(env_key_path)).parent)
        if env_profile_dir := os.environ.get("VLABOR_AGENT_PROFILE_DIR"):
            cfg.profile_dir = env_profile_dir

        # Phase 0 default: connect to the full vlabor MCP set if no
        # servers were configured. ``./run`` then has immediate utility
        # on a vlabor host without any extra config. Operators on
        # other robots will set ``mcp_servers`` in
        # ~/.vlabor/agent/config.json instead.
        if not cfg.mcp_servers:
            cfg.mcp_servers = [
                McpServerConfig(name="vlabor-obs",        transport="sse", url="http://127.0.0.1:9100/sse"),
                McpServerConfig(name="vlabor-ros",        transport="sse", url="http://127.0.0.1:9101/sse"),
                McpServerConfig(name="vlabor-perception", transport="sse", url="http://127.0.0.1:9102/sse"),
                McpServerConfig(name="vlabor-moveit",     transport="sse", url="http://127.0.0.1:9103/sse"),
                McpServerConfig(name="vlabor-arm",        transport="sse", url="http://127.0.0.1:9104/sse"),
                McpServerConfig(name="vlabor-visual",     transport="sse", url="http://127.0.0.1:9105/sse"),
                McpServerConfig(name="vlabor-diagnostics", transport="sse", url="http://127.0.0.1:9106/sse"),
                McpServerConfig(name="vlabor-canvas",     transport="sse", url="http://127.0.0.1:9107/sse"),
            ]
        return cfg


def _apply_overrides(cfg: ChatBackendConfig, data: dict) -> ChatBackendConfig:
    if isinstance(data.get("host"), str):
        cfg.host = data["host"]
    if isinstance(data.get("port"), int):
        cfg.port = data["port"]
    if isinstance(data.get("anthropic_model"), str):
        cfg.anthropic_model = data["anthropic_model"]
    if isinstance(data.get("api_key_path"), str):
        cfg.api_key_path = data["api_key_path"]
        cfg.profile_dir = str(Path(os.path.expanduser(data["api_key_path"])).parent)
    if isinstance(data.get("profile_dir"), str):
        cfg.profile_dir = data["profile_dir"]
    servers = data.get("mcp_servers")
    if isinstance(servers, list):
        cfg.mcp_servers = []
        for entry in servers:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            transport = entry.get("transport")
            if not isinstance(name, str) or not isinstance(transport, str):
                continue
            cfg.mcp_servers.append(
                McpServerConfig(
                    name=name,
                    transport=transport,
                    url=entry.get("url"),
                    command=entry.get("command"),
                    env=entry.get("env") or {},
                )
            )
    return cfg


def read_api_key(path: str) -> str | None:
    """Backwards-compat helper. Prefer :meth:`ChatBackendConfig.anthropic_key`
    or :func:`.keys.read_key` for new code."""
    expanded = Path(os.path.expanduser(path))
    if not expanded.exists():
        return None
    try:
        text = expanded.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None
