"""Fuzz target: log and path sanitizers (backend/app/core/sanitize.py).

sanitize_for_log must leave no control character in what reaches a log line
(CWE-117). sanitize_path_component must either refuse a name with ValueError or
return a single, safe path component: no separator, never "." or "..", and so
never a path that leaves the directory it is joined to. Names that merely
contain two dots ("a..b", "...") are ordinary file names, not traversal.
"""
import os
import re

import _harness
from app.core.sanitize import sanitize_for_log, sanitize_path_component

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_COMPONENT = re.compile(r"[A-Za-z0-9._-]+")


def fuzz(buf: bytes) -> None:
    s = _harness.text(buf)

    limit = buf[0] if buf else 200
    for value, max_length in ((s, 200), (s, limit), (buf, 200)):
        out = sanitize_for_log(value, max_length)
        assert isinstance(out, str)
        assert not _CONTROL.search(out), out
        assert len(out) <= max_length + len("..."), (len(out), max_length)
    assert sanitize_for_log(None) == "<none>"

    for name in (s, s.replace("\x00", "/")):
        try:
            out = sanitize_path_component(name)
        except ValueError:
            continue
        assert _COMPONENT.fullmatch(out), out
        assert "/" not in out and "\\" not in out and "\x00" not in out, out
        assert out not in (".", ".."), out
        joined = os.path.normpath(os.path.join("/base", out))
        assert os.path.dirname(joined) == "/base", (out, joined)


if __name__ == "__main__":
    _harness.run(fuzz, "sanitize")
