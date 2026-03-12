"""
Log sanitization utilities to prevent log injection attacks.

Strips newlines and control characters from user-provided values
before they are written to log output.
"""
import re
from typing import Optional


def sanitize_for_log(value: Optional[str], max_length: int = 200) -> str:
    """Sanitize a string for safe inclusion in log messages.
    
    Strips newlines, carriage returns, and control characters to prevent
    log injection/forging attacks (CWE-117).
    """
    if value is None:
        return "<none>"
    if not isinstance(value, str):
        value = str(value)
    # Strip control characters including \r \n \t and others
    sanitized = re.sub(r'[\r\n\t\x00-\x1f\x7f]', ' ', value)
    if len(sanitized) > max_length:
        return sanitized[:max_length] + "..."
    return sanitized


def mask_secret(value: Optional[str]) -> str:
    """Mask a secret value for logging — shows only length/presence, never content."""
    if not value:
        return "<empty>"
    return f"<set, {len(value)} chars>"


def sanitize_path_component(name: str) -> str:
    """Validate and sanitize a filename to prevent path traversal.
    
    Strips directory separators and traversal sequences.
    Returns only the basename with allowed characters.
    """
    import os
    # Get basename to strip any directory components
    name = os.path.basename(name)
    # Only allow alphanumeric, hyphens, underscores, dots
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '', name)
    # Explicitly reject traversal-like components
    if sanitized in (".", "..") or not sanitized:
        raise ValueError("Invalid path component")
    return sanitized
