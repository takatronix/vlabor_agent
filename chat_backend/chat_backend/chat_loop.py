"""Provider-agnostic tool-use loop.

The loop runs until the chosen provider's stream emits a stop event
with ``stop_reason != "tool_use"``. Each iteration:

  1. Hand the running ``messages`` list to the provider's
     :meth:`stream_turn`. The provider yields text deltas + a single
     ``tool_uses`` event + a ``stop`` event.
  2. We forward the visible deltas to the WS client unchanged.
  3. If the model wants tools, dispatch them via :class:`McpPool` and
     append ``tool_result`` blocks (preserving image content from MCP
     responses) for the next round.

Image content from MCP tool_result is forwarded verbatim so Claude /
GPT-4o can do their own VLM-style reasoning over camera frames the
robot returns. Block conversion lives in :func:`_mcp_to_anthropic_blocks`
— Anthropic-shape blocks are the canonical history format; the OpenAI
provider translates at the SDK boundary in
:func:`providers.openai_provider._to_openai_messages`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from .mcp_pool import McpPool
from .providers import get_provider

log = logging.getLogger(__name__)


async def run_chat(
    *,
    client: Any | None = None,  # legacy positional kept for caller compat
    model: str,
    messages: list[dict[str, Any]],
    pool: McpPool,
    max_iterations: int = 10,
    provider: str = "anthropic",
    api_key: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Drive one chat turn to completion, yielding events as they happen.

    ``provider`` selects the LLM backend (``"anthropic"`` or
    ``"openai"``); ``api_key`` is the corresponding key. The legacy
    ``client`` argument is accepted but ignored — the provider creates
    its own SDK client per turn so a key rotation is picked up
    immediately.

    Yielded events (envelope shape — caller wraps for transport):
      * ``{"type": "assistant_text_delta", "text": "..."}``
      * ``{"type": "assistant_text", "text": "..."}``
      * ``{"type": "tool_use_start", "name": "...", "input": {...}, "id": "..."}``
      * ``{"type": "tool_use_result", "name": "...", "id": "...",
            "is_error": bool, "summary": "...", "content": [...]}``
      * ``{"type": "done", "stop_reason": "..."}``
      * ``{"type": "error", "message": "..."}``
    """
    impl = get_provider(provider)
    if not model:
        model = impl.default_model

    iteration = 0
    while True:
        iteration += 1
        if iteration > max_iterations:
            yield {"type": "error",
                   "message": f"max iterations ({max_iterations}) hit"}
            return

        tool_uses: list[dict[str, Any]] = []
        assistant_blocks: list[dict[str, Any]] = []
        stop_reason: str | None = None

        async for event in impl.stream_turn(
            api_key=api_key,
            model=model,
            messages=messages,
            anthropic_tools=pool.tools_for_anthropic(),
            openai_tools=pool.tools_for_openai(),
        ):
            etype = event.get("type")
            if etype in ("assistant_text_delta", "assistant_text"):
                yield event
            elif etype == "tool_uses":
                tool_uses = event.get("tool_uses") or []
                assistant_blocks = event.get("assistant_blocks") or []
                # Surface each tool_use as a UI event up front so the
                # operator sees "agent decided to call X" before the
                # tool result lands.
                for use in tool_uses:
                    yield {
                        "type": "tool_use_start",
                        "id": use.get("id"),
                        "name": use.get("name"),
                        "input": use.get("input") or {},
                    }
            elif etype == "stop":
                stop_reason = event.get("stop_reason")
            elif etype == "error":
                yield event
                return

        messages.append({"role": "assistant", "content": assistant_blocks})

        if stop_reason != "tool_use" or not tool_uses:
            yield {"type": "done", "stop_reason": stop_reason or "end_turn"}
            return

        # Dispatch each tool_use; gather tool_result blocks for the next round.
        tool_results: list[dict[str, Any]] = []
        for use in tool_uses:
            name = use["name"]
            args = use["input"] if isinstance(use["input"], dict) else {}
            try:
                result = await pool.call(name, args)
            except Exception as exc:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use["id"],
                        "is_error": True,
                        "content": [{"type": "text", "text": f"tool error: {exc}"}],
                    }
                )
                yield {
                    "type": "tool_use_result",
                    "id": use["id"],
                    "name": name,
                    "is_error": True,
                    "summary": str(exc),
                    "content": [],
                }
                continue

            blocks = _mcp_to_anthropic_blocks(result)
            is_error = bool(getattr(result, "isError", False))
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use["id"],
                    "is_error": is_error,
                    "content": blocks,
                }
            )
            yield {
                "type": "tool_use_result",
                "id": use["id"],
                "name": name,
                "is_error": is_error,
                "summary": _summarise_blocks(blocks),
                "content": blocks,
            }

        messages.append({"role": "user", "content": tool_results})
        # …loop


def _mcp_to_anthropic_blocks(result: Any) -> list[dict[str, Any]]:
    """Convert an MCP ``CallToolResult`` to Anthropic content blocks.

    Preserves both text and image (base64) content so Claude can see
    pictures the robot returns — that's how VLM-style reasoning over
    camera frames lands inside the chat loop. The OpenAI provider
    drops images today (see openai_provider._to_openai_messages); a
    future revision can map them to GPT-4o's image input format.
    """

    blocks: list[dict[str, Any]] = []
    raw_content = getattr(result, "content", None) or []
    for item in raw_content:
        itype = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
        if itype == "text":
            text = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else "")
            blocks.append({"type": "text", "text": text or ""})
        elif itype == "image":
            data = getattr(item, "data", None) or (item.get("data") if isinstance(item, dict) else "")
            mime = getattr(item, "mimeType", None) or (
                item.get("mimeType") if isinstance(item, dict) else "image/png"
            )
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime or "image/png",
                        "data": data or "",
                    },
                }
            )
        else:
            blocks.append({"type": "text", "text": str(item)})

    if not blocks:
        blocks.append({"type": "text", "text": "(empty result)"})
    return blocks


def _summarise_blocks(blocks: list[dict[str, Any]]) -> str:
    """One-line summary suitable for UI status — full content goes in a
    separate field that the panel renders lazily."""
    parts: list[str] = []
    for b in blocks:
        if b.get("type") == "text":
            text = (b.get("text") or "").strip().replace("\n", " ")
            parts.append(text[:80] + ("…" if len(text) > 80 else ""))
        elif b.get("type") == "image":
            parts.append("[image]")
    return " | ".join(p for p in parts if p) or "(no content)"


__all__ = ["run_chat"]
