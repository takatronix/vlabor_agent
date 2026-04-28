"""Anthropic Messages API + MCP tool-use loop.

The loop runs until Claude produces a ``stop_reason`` other than
``tool_use``. On each iteration we:

  1. Send the running ``messages`` list (plus the MCP tool spec)
     to Anthropic.
  2. If the response is a final answer, stream it back to the caller
     and exit.
  3. If the response contains ``tool_use`` blocks, dispatch each one
     to the MCP pool, append ``tool_result`` blocks (text + image
     content preserved), and loop.

Image content from MCP tool_result is forwarded verbatim so Claude
can do its own VLM-style reasoning over camera frames the robot
returns. The conversion lives in :func:`_mcp_to_anthropic_blocks`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from .mcp_pool import McpPool

log = logging.getLogger(__name__)


async def run_chat(
    *,
    client: AsyncAnthropic,
    model: str,
    messages: list[dict[str, Any]],
    pool: McpPool,
    max_iterations: int = 10,
) -> AsyncIterator[dict[str, Any]]:
    """Drive one chat turn to completion, yielding events as they happen.

    Yielded events (envelope shape — caller wraps for transport):
      * ``{"type": "assistant_text", "text": "..."}``
      * ``{"type": "tool_use_start", "name": "...", "input": {...}, "id": "..."}``
      * ``{"type": "tool_use_result", "name": "...", "id": "...",
            "is_error": bool, "summary": "...", "content": [...]}``
      * ``{"type": "done", "stop_reason": "..."}``
      * ``{"type": "error", "message": "..."}``
    """

    tools = pool.tools_for_anthropic()
    iteration = 0
    while True:
        iteration += 1
        if iteration > max_iterations:
            yield {"type": "error", "message": f"max iterations ({max_iterations}) hit"}
            return

        # Stream the assistant turn so the UI shows incremental text
        # rather than a single dump at the end. Anthropic's streaming
        # API yields text deltas during generation; tool_use blocks
        # arrive complete in the final message.
        try:
            text_so_far = ""
            async with client.messages.stream(
                model=model,
                max_tokens=1024,
                tools=tools or None,  # don't send empty array — confuses the API
                messages=messages,
            ) as stream:
                async for chunk in stream.text_stream:
                    if not chunk:
                        continue
                    text_so_far += chunk
                    yield {"type": "assistant_text_delta", "text": chunk}
                resp = await stream.get_final_message()
        except Exception as exc:  # pragma: no cover - surfaced to caller
            log.exception("anthropic call failed")
            yield {"type": "error", "message": f"anthropic call failed: {exc}"}
            return

        # Convert the SDK response into the messages-list shape we'll send
        # back next round.
        assistant_blocks: list[dict[str, Any]] = []
        tool_uses: list[dict[str, Any]] = []

        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text = getattr(block, "text", "") or ""
                if text:
                    # Emit a final "full text" event AFTER the deltas so
                    # frontends that only handle the legacy event shape
                    # still get one consolidated message per text block.
                    # Frontends that handle deltas use this as a "this
                    # block is complete" signal and drop their delta
                    # buffer.
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
                yield {
                    "type": "tool_use_start",
                    "id": use["id"],
                    "name": use["name"],
                    "input": use["input"],
                }
            else:
                # Unknown block type — preserve verbatim if possible so
                # we don't lose anything Claude wanted to say.
                if isinstance(block, dict):
                    assistant_blocks.append(block)

        messages.append({"role": "assistant", "content": assistant_blocks})

        if resp.stop_reason != "tool_use":
            yield {"type": "done", "stop_reason": resp.stop_reason}
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
    camera frames lands inside the chat loop.
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
            # Unknown content type — fall back to text representation so
            # Claude at least gets *something*.
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
