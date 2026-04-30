"""OpenAI provider — function-calling tool-use loop.

The OpenAI Chat Completions streaming protocol emits ``tool_calls``
in deltas: each chunk may carry one tool call (or partial), and the
final message has the assembled list. We accumulate fragments by
``index`` until the stream ends, then yield the same ``tool_uses``
event the Anthropic provider produces so the chat-loop dispatch can
treat both providers identically.

Conversation shape: OpenAI uses a flat ``messages`` list with roles
``user`` / ``assistant`` / ``tool``. The chat-loop translates
Anthropic-style ``tool_result`` blocks into OpenAI ``tool`` messages
in :func:`_to_openai_messages` so the same ``messages`` history
buffer flows through either provider.

Notes / limitations:
  * Image content blocks (Anthropic image type) are not forwarded to
    OpenAI yet — first cut keeps text + tool only. VLM via OpenAI
    is a follow-up.
  * ``stop_reason`` is normalised to Anthropic's vocabulary
    (``"tool_use"`` when the model wants to call a tool, ``"end_turn"``
    otherwise) so the chat-loop's existing while-condition keeps
    working.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any


log = logging.getLogger(__name__)


def _to_openai_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate an Anthropic-shaped ``messages`` list into the format
    OpenAI's Chat Completions API expects.

    The chat-loop's running history uses Anthropic content blocks. We
    walk each message and map blocks → OpenAI's flat structure:

      * user text → ``{"role":"user","content": <str>}``
      * assistant text → ``{"role":"assistant","content": <str>}``
      * assistant tool_use → ``{"role":"assistant","tool_calls":[...]}``
      * user tool_result → ``{"role":"tool","tool_call_id":...,"content":...}``

    Multiple text blocks in one assistant message get joined; multiple
    tool_use blocks in one message become a list of ``tool_calls``.
    """
    out: list[dict[str, Any]] = []
    for m in history:
        role = m.get("role")
        content = m.get("content")
        if role == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue
            tool_results: list[dict[str, Any]] = []
            text_parts: list[str] = []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text") or "")
                    elif btype == "tool_result":
                        tool_results.append(block)
            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts).strip()})
            for tr in tool_results:
                tr_content = tr.get("content")
                if isinstance(tr_content, list):
                    flat = "\n".join(
                        b.get("text") or ""
                        for b in tr_content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ).strip()
                else:
                    flat = str(tr_content) if tr_content else ""
                out.append({
                    "role": "tool",
                    "tool_call_id": tr.get("tool_use_id") or "",
                    "content": flat or "(empty)",
                })
        elif role == "assistant":
            if isinstance(content, str):
                out.append({"role": "assistant", "content": content})
                continue
            text_parts = []
            tool_calls: list[dict[str, Any]] = []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text") or "")
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id": block.get("id") or "",
                            "type": "function",
                            "function": {
                                "name": block.get("name") or "",
                                "arguments": json.dumps(block.get("input") or {},
                                                       ensure_ascii=False),
                            },
                        })
            entry: dict[str, Any] = {"role": "assistant"}
            joined_text = "\n".join(t for t in text_parts if t).strip()
            entry["content"] = joined_text or None
            if tool_calls:
                entry["tool_calls"] = tool_calls
            # OpenAI rejects assistant messages with neither content nor
            # tool_calls. Skip if both empty (shouldn't happen but
            # cheap guard).
            if entry.get("content") is None and not tool_calls:
                continue
            out.append(entry)
        else:
            # System messages get passed through untouched (currently
            # the chat-loop never emits these for user turns; the
            # diagnose flow includes its prompt as a user message).
            out.append(m)
    return out


class OpenAIProvider:
    name = "openai"
    default_model = "gpt-4o-mini"

    async def stream_turn(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        anthropic_tools: list[dict[str, Any]],  # unused here
        openai_tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            yield {"type": "error", "message": "openai SDK not installed"}
            return

        client = AsyncOpenAI(api_key=api_key)
        oa_messages = _to_openai_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "messages": oa_messages,
            "stream": True,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        text_buf = ""
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None

        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta is None:
                    continue
                if delta.content:
                    text_buf += delta.content
                    yield {"type": "assistant_text_delta", "text": delta.content}
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if tc.index is not None else 0
                        slot = tool_calls_acc.setdefault(idx, {
                            "id": "", "name": "", "arguments": "",
                        })
                        if tc.id:
                            slot["id"] = tc.id
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            if getattr(fn, "name", None):
                                slot["name"] = fn.name
                            if getattr(fn, "arguments", None):
                                slot["arguments"] += fn.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except Exception as exc:
            log.exception("openai stream failed")
            yield {"type": "error", "message": f"openai call failed: {exc}"}
            return

        assistant_blocks: list[dict[str, Any]] = []
        if text_buf:
            yield {"type": "assistant_text", "text": text_buf}
            assistant_blocks.append({"type": "text", "text": text_buf})

        tool_uses: list[dict[str, Any]] = []
        for idx in sorted(tool_calls_acc.keys()):
            slot = tool_calls_acc[idx]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            use = {
                "type": "tool_use",
                "id": slot.get("id") or f"call_{idx}",
                "name": slot.get("name") or "",
                "input": args,
            }
            tool_uses.append(use)
            assistant_blocks.append(use)

        yield {
            "type": "tool_uses",
            "tool_uses": tool_uses,
            "assistant_blocks": assistant_blocks,
        }
        # Map OpenAI finish_reason → Anthropic vocabulary so the
        # chat-loop's loop condition (``stop_reason == 'tool_use'``)
        # works for both providers.
        if finish_reason == "tool_calls" or tool_uses:
            stop = "tool_use"
        elif finish_reason == "length":
            stop = "max_tokens"
        else:
            stop = finish_reason or "end_turn"
        yield {"type": "stop", "stop_reason": stop}
