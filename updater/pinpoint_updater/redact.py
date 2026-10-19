"""Keep credentials out of logs, reports and terminal output.

Two layers: every secret the updater itself loaded (registry and API tokens
read from files) is registered here and replaced verbatim wherever it appears,
and a set of patterns catches the shapes credentials usually take in command
output we did not produce (an Authorization header echoed by a registry, a
token in a URL query string, a userinfo part of a URL).
"""

from __future__ import annotations

import re
import threading
from typing import Any

MASK = "***"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization: Bearer xxx / Basic xxx
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    # GitHub tokens (classic, fine-grained, app/oauth), GitLab PAT / deploy / CI tokens
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), MASK),
    (re.compile(r"\b(glpat|gldt|glcbt|glrt|glptt|gloas)-[A-Za-z0-9_-]{16,}"), MASK),
    # ?token=…, &access_token=…, password=…, private_token=…
    (re.compile(r"(?i)\b((?:access_|private_|refresh_|id_)?token|password|secret)=([^\s&\"']+)"),
     r"\1=" + MASK),
    # https://user:secret@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):([^@\s/]+)@"), r"\1:" + MASK + "@"),
    # PRIVATE-TOKEN: xxx header
    (re.compile(r"(?i)\b(private-token|job-token|deploy-token)\s*[:=]\s*\S+"), r"\1: " + MASK),
)

_lock = threading.Lock()
_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a credential so it is masked wherever it shows up later."""
    if value and len(value.strip()) >= 4:
        with _lock:
            _secrets.add(value.strip())


def clear_registered_secrets() -> None:  # tests
    with _lock:
        _secrets.clear()


def redact(text: Any) -> Any:
    """Mask credentials in a string; recurse into dicts/lists; leave the rest."""
    if isinstance(text, str):
        out = text
        with _lock:
            known = sorted(_secrets, key=len, reverse=True)
        for secret in known:
            out = out.replace(secret, MASK)
        for pattern, repl in _PATTERNS:
            out = pattern.sub(repl, out)
        return out
    if isinstance(text, dict):
        return {k: redact(v) for k, v in text.items()}
    if isinstance(text, (list, tuple)):
        return type(text)(redact(v) for v in text)
    return text
