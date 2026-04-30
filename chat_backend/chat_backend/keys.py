"""Per-provider API key file management.

Keys live in ``~/.vlabor/profiles/<profile>/<provider>_api_key.txt`` —
one file per provider, plain text, mode 0o600. The file path
convention is the same as the original Anthropic-only implementation
(``anthropic_api_key.txt``); we just generalise it to per-provider.

Key access is on-demand: every chat turn re-reads the file so a key
rotation doesn't need a backend restart. The previous module-level
``read_api_key()`` in ``config.py`` stays callable as a thin wrapper
around :func:`read_key` for backwards compatibility.
"""
from __future__ import annotations

import os
from pathlib import Path

# Providers we recognise. Adding a new entry here is sufficient — UI,
# storage, and chat_loop dispatch all key off of these strings.
KNOWN_PROVIDERS: tuple[str, ...] = ("anthropic", "openai")


def _expand(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.expanduser(str(path)))


def key_path(profile_dir: str | os.PathLike[str], provider: str) -> Path:
    """Resolve the on-disk path for ``provider``'s key under
    ``profile_dir`` (``~/.vlabor/profiles/<profile>/`` typically)."""
    if provider not in KNOWN_PROVIDERS:
        raise ValueError(f"unknown provider: {provider!r}")
    return _expand(profile_dir) / f"{provider}_api_key.txt"


def read_key(profile_dir: str | os.PathLike[str], provider: str) -> str | None:
    """Read the key file. Returns ``None`` if missing / empty / unreadable.

    Returns the trimmed file contents — Anthropic / OpenAI keys are
    short single-line strings, so a leading/trailing newline from the
    operator's editor is tolerated.
    """
    path = key_path(profile_dir, provider)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def write_key(profile_dir: str | os.PathLike[str], provider: str, value: str) -> Path:
    """Write the key, creating the directory tree as needed and forcing
    mode 0o600 on the resulting file.

    The 0o600 chmod is applied AFTER the write because some
    filesystems (notably some bind-mounted hosts) reject ``open(mode=)``
    flags. Returns the resolved path."""
    path = key_path(profile_dir, provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Best-effort. If the underlying FS doesn't support chmod the
        # caller still got the key written; the host should already be
        # operator-only.
        pass
    return path


def delete_key(profile_dir: str | os.PathLike[str], provider: str) -> bool:
    """Remove the key file. Returns ``True`` if a file was deleted."""
    path = key_path(profile_dir, provider)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def status(profile_dir: str | os.PathLike[str]) -> dict[str, bool]:
    """Return ``{provider: is_set}`` without exposing key values.

    Used by the settings UI to render "Anthropic key: configured ✓ /
    not set" without leaking the actual secret to the browser."""
    out: dict[str, bool] = {}
    for provider in KNOWN_PROVIDERS:
        out[provider] = read_key(profile_dir, provider) is not None
    return out


__all__ = [
    "KNOWN_PROVIDERS",
    "key_path",
    "read_key",
    "write_key",
    "delete_key",
    "status",
]
