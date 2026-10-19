"""Can this image do its job? A fast, side-effect-free check.

    python -m app.cli.selfcheck [--tools-only]

Run by the release gate inside every freshly built image (with --tools-only:
CI has no database or models) and by pinpoint-updater after an upgrade, inside
the new backend and worker, before it commits release.lock -- a failure there
rolls the upgrade back.

Checks:
  tools     every program in app.services.runtime_tools.REQUIRED_TOOLS is on PATH,
            and gpg can actually encrypt and decrypt (backups depend on it)
  backups   the pre-migration dump directory exists and is writable
  models    when a plate/face model is configured, its file is present and readable

Prints one JSON object as the last line of stdout. Exit 0 when every check
passes, 1 otherwise. Never touches the database or the network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List


def run(tools_only: bool = False) -> Dict[str, object]:
    from app.services import runtime_tools

    problems: List[str] = []
    missing = runtime_tools.missing_tools()
    problems += [f"{t} is not installed ({runtime_tools.REQUIRED_TOOLS[t]})" for t in missing]
    if "gpg" not in missing:
        reason = runtime_tools.gpg_roundtrip()
        if reason:
            problems.append(reason)

    if not tools_only:
        backup_dir = os.environ.get("PRE_RESTORE_SNAPSHOT_DIR", "/backups")
        if os.path.isdir(backup_dir) and not os.access(backup_dir, os.W_OK):
            problems.append(f"backup directory {backup_dir} is not writable")
        # Models are optional (a town without them uses the OCR heuristic), so
        # only a model that was explicitly configured, or that is present but
        # unreadable, is a problem. Paths come from onnx_detectors itself.
        from app.services import onnx_detectors as od
        for env, path in (("PLATE_MODEL_FILE", od.plate_model_path()),
                          ("FACE_MODEL_FILE", od.face_model_path())):
            configured = bool(os.environ.get(env))
            if (configured or os.path.exists(path)) and not os.access(path, os.R_OK):
                problems.append(f"model file {path} is not readable")

    return {"ok": not problems, "problems": problems, "tools_only": tools_only}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.selfcheck")
    parser.add_argument("--tools-only", action="store_true",
                        help="only check programs (for CI, where there is no database or models)")
    args = parser.parse_args(argv)
    result = run(tools_only=args.tools_only)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
