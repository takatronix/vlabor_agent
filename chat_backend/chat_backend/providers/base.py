"""Provider abstraction for the chat-loop.

Each implementation drives one full Anthropic-or-OpenAI tool-use
turn — text streaming + ``tool_use`` block emission — and yields the
same envelope events ``run_chat`` already produces:

  * ``{"type": "assistant_text_delta", "text": "..."}``
  * ``{"type": "assistant_text", "text": "..."}``
  * ``{"type": "tool_uses", "tool_uses": [...], "assistant_blocks": [...]}``
  * ``{"type": "stop", "stop_reason": "..."}``
  * ``{"type": "error", "message": "..."}``

The third event is **NOT** forwarded to the WS client directly — the
chat_loop captures it and dispatches the tool calls via
:class:`McpPool` itself. That keeps tool dispatch in one place across
providers (so a tool with ``__`` in its qualified name works the same
way no matter which model called it).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class ChatProvider(Protocol):
    """Provider interface — one method per turn.

    Implementations should treat ``messages`` as input-only (no in-place
    mutation). The chat-loop appends the assistant block + tool results
    after the turn completes, using the data carried in the
    ``tool_uses`` event.
    """

    name: str
    """Stable identifier used in settings and conversation meta."""

    default_model: str
    """Fallback model name if settings doesn't override."""

    async def stream_turn(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        anthropic_tools: list[dict[str, Any]],
        openai_tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> AsyncIterator[dict[str, Any]]:
        """Drive one assistant turn, yielding events as they happen."""
        ...


def get_provider(name: str) -> ChatProvider:
    """Resolve a provider implementation by name. Imports lazily so
    the OpenAI SDK isn't loaded for an Anthropic-only deployment (and
    vice-versa)."""
    from .anthropic_provider import AnthropicProvider
    from .openai_provider import OpenAIProvider

    name = (name or "").lower().strip() or "anthropic"
    if name == "anthropic":
        return AnthropicProvider()
    if name == "openai":
        return OpenAIProvider()
    raise ValueError(f"unknown chat provider: {name!r}")


__all__ = ["ChatProvider", "get_provider"]
