"""Operator preferences (provider choice, voice mode settings).

Stored at ``~/.vlabor/agent/settings.json`` — separate from the
deployment-time ``config.json`` so changing voice / provider doesn't
require touching the deployment artefact (and `git diff` of the
deploy config stays meaningful).

The settings dict uses a light schema with sensible defaults; missing
fields fall back to defaults rather than raising. This lets the file
evolve without breaking existing operator setups.
"""
from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


_PATH = Path(os.path.expanduser("~/.vlabor/agent/settings.json"))


# Defaults are also the documented schema. Keep keys lower_snake_case
# and grouped by feature so the JSON file stays browse-able by hand.
DEFAULTS: dict[str, Any] = {
    "chat": {
        "provider": "anthropic",     # 'anthropic' | 'openai'
        "model": "",                 # empty → provider's default_model
    },
    "voice": {
        "stt_engine": "openai_whisper",   # only option in v1
        "stt_lang": "ja",
        "tts_voice": "alloy",             # alloy/echo/fable/onyx/nova/shimmer
        "tts_speed": 1.0,
        "tts_model": "tts-1",             # tts-1 (cheap) | tts-1-hd
        "silence_ms": 800,
        "energy_db": -45,
        "barge_in": False,
        # Announce / diagnose. Off by default — operator can flip on
        # in the Settings modal once a TTS provider key is configured
        # and they actually want voice annunciation.
        "notify_enabled": False,
        "notify_severity_min": "critical",  # critical | warning | info
        "notify_diagnose": False,
        "notify_dedupe_window_sec": 60,
    },
}


_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def severity_meets(actual: str, threshold: str) -> bool:
    """True iff ``actual`` is at least as severe as ``threshold``.
    Unknown values default to info for ``actual`` and critical for
    ``threshold`` — fail-safe (don't spam) on bad data."""
    a = _SEVERITY_ORDER.get((actual or "info").lower(), 0)
    t = _SEVERITY_ORDER.get((threshold or "critical").lower(), 2)
    return a >= t


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursive merge — missing keys on overlay keep base values.
    Used to apply file-on-disk over the DEFAULTS template so adding a
    new field in code doesn't require migrating existing operator
    files."""
    out = deepcopy(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict[str, Any]:
    """Read settings, returning ``DEFAULTS`` merged with whatever's on
    disk. Missing file → just defaults. Corrupt file → defaults +
    warning log."""
    if not _PATH.exists():
        return deepcopy(DEFAULTS)
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("settings.json read failed: %s", exc)
        return deepcopy(DEFAULTS)
    if not isinstance(data, dict):
        return deepcopy(DEFAULTS)
    return _merge(DEFAULTS, data)


def save(settings: dict[str, Any]) -> None:
    """Persist settings. Validates only the basic shape (top-level
    ``chat`` / ``voice`` dicts); finer validation happens at use-site
    so a stale field doesn't break the whole file."""
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    merged = _merge(DEFAULTS, settings)
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False),
                     encoding="utf-8")


def patch(partial: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update — top-level groups are deep-merged so the
    UI can PATCH ``{"voice": {"barge_in": true}}`` without echoing back
    the whole tree. Returns the merged result."""
    current = load()
    merged = _merge(current, partial or {})
    save(merged)
    return merged


__all__ = ["DEFAULTS", "load", "save", "patch", "severity_meets"]
