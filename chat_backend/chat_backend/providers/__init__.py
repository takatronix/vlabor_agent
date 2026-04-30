"""LLM provider implementations for the chat-loop.

Each provider exposes the same async generator interface so
``chat_loop.run_chat`` doesn't have to know which backend is in use.
The shared protocol lives in :mod:`.base`; individual implementations
in :mod:`.anthropic_provider` and :mod:`.openai_provider`.
"""
from __future__ import annotations

from .base import ChatProvider, get_provider

__all__ = ["ChatProvider", "get_provider"]
