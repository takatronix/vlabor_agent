"""OpenAI Whisper (STT) + TTS-1 (TTS) async proxy.

Thin wrapper over ``openai`` SDK so the rest of the backend can stay
provider-agnostic. Both helpers raise :class:`VoiceError` on failure
so the HTTP handlers can surface a clean 400/502 instead of the SDK's
deeply nested exceptions.

The OpenAI key is passed in per call rather than read from env. The
caller (settings handler / HTTP endpoint) resolves it from
``keys.read_key(profile_dir, 'openai')`` so a key rotation is picked
up without restart.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover — surfaced at boot time
    AsyncOpenAI = None  # type: ignore[assignment,misc]


log = logging.getLogger(__name__)


class VoiceError(RuntimeError):
    """Anything that prevents STT/TTS from completing — missing key,
    network failure, model error. Caller turns this into an HTTP
    response, so keep the message short and operator-readable."""


def _ensure_sdk() -> None:
    if AsyncOpenAI is None:
        raise VoiceError("openai SDK not installed — pip install openai")


async def whisper_stt(*,
                      api_key: str,
                      audio_bytes: bytes,
                      filename: str = "speech.webm",
                      lang: str = "ja",
                      model: str = "whisper-1") -> str:
    """Transcribe one audio blob via OpenAI Whisper.

    ``filename`` matters because OpenAI infers the codec from the
    extension. The browser sends ``audio/webm;codecs=opus`` from
    MediaRecorder by default, hence ``.webm`` here.
    """
    _ensure_sdk()
    if not api_key:
        raise VoiceError("OpenAI API key not set")
    if not audio_bytes:
        raise VoiceError("empty audio")
    client = AsyncOpenAI(api_key=api_key)
    try:
        # The SDK accepts a (filename, BytesIO, mime) tuple as the
        # ``file`` argument — same shape as ``requests`` multipart.
        result = await client.audio.transcriptions.create(
            model=model,
            file=(filename, io.BytesIO(audio_bytes), "audio/webm"),
            language=lang or None,
        )
    except Exception as exc:  # pragma: no cover — surfaced upstream
        log.exception("whisper failed")
        raise VoiceError(f"whisper failed: {exc}") from exc
    text = getattr(result, "text", "") or ""
    return text.strip()


async def openai_tts(*,
                     api_key: str,
                     text: str,
                     voice: str = "alloy",
                     speed: float = 1.0,
                     model: str = "tts-1",
                     fmt: str = "mp3") -> bytes:
    """Synthesize ``text`` to audio bytes (mp3 by default).

    Returns the raw bytes ready to ship to the browser as ``audio/mpeg``.
    """
    _ensure_sdk()
    if not api_key:
        raise VoiceError("OpenAI API key not set")
    text = (text or "").strip()
    if not text:
        raise VoiceError("empty text")
    # OpenAI TTS-1 caps each call at 4096 chars. Truncate quietly so a
    # long agent reply still gets read aloud (operator can re-request
    # if they need the rest — half-duplex makes that ergonomic).
    text = text[:4096]
    client = AsyncOpenAI(api_key=api_key)
    try:
        # Use the streaming variant so we can return raw bytes without
        # the SDK trying to wrap the payload in its own helper class.
        async with client.audio.speech.with_streaming_response.create(
            model=model, voice=voice, input=text, speed=speed,
            response_format=fmt,
        ) as resp:
            chunks: list[bytes] = []
            async for part in resp.iter_bytes():
                chunks.append(part)
        return b"".join(chunks)
    except Exception as exc:  # pragma: no cover — surfaced upstream
        log.exception("tts failed")
        raise VoiceError(f"tts failed: {exc}") from exc


__all__ = ["VoiceError", "whisper_stt", "openai_tts"]
