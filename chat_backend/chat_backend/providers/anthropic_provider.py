"""Anthropic provider — preserves the existing behaviour of
:func:`chat_backend.chat_loop.run_chat` from before the provider
abstraction landed.

Uses ``messages.stream`` so the dev page can render assistant tokens
incrementally. Tool-use blocks come back as a complete list at the
final message; we forward them to the chat-loop in one
``tool_uses`` event.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic


log = logging.getLogger(__name__)


class AnthropicProvider:
    name = "anthropic"
    default_model = "claude-sonnet-4-6"

    async def stream_turn(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        anthropic_tools: list[dict[str, Any]],
        openai_tools: list[dict[str, Any]],  # unused here
        max_tokens: int = 1024,
    ) -> AsyncIterator[dict[str, Any]]:
        client = AsyncAnthropic(api_key=api_key)
        # Anthropic rejects empty list AND null for the tools field —
        # omit the kwarg entirely when no MCP tool is wired up.
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for chunk in stream.text_stream:
                    if chunk:
                        yield {"type": "assistant_text_delta", "text": chunk}
                resp = await stream.get_final_message()
        except Exception as exc:
            log.exception("anthropic stream failed")
            yield {"type": "error", "message": f"anthropic call failed: {exc}"}
            return

        assistant_blocks: list[dict[str, Any]] = []
        tool_uses: list[dict[str, Any]] = []

        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text = getattr(block, "text", "") or ""
                if text:
                    yield {"type": "assistant_text", "text": text}
                assistant_blocks.append({"type": "text", "text": text})
            elif btype == "tool_use":
                use = {
                    "type": "tool_use",
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                }
                tool_uses.append(use)
                assistant_blocks.append(use)
            elif isinstance(block, dict):
                assistant_blocks.append(block)

        yield {
            "type": "tool_uses",
            "tool_uses": tool_uses,
            "assistant_blocks": assistant_blocks,
        }
        yield {"type": "stop", "stop_reason": resp.stop_reason}
