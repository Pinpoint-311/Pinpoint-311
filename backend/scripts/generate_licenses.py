#!/usr/bin/env python3
"""Emit the third-party license notices that must ship inside the backend image.

The backend is distributed as a prebuilt container image with the whole Python
dependency tree installed into it. That makes Pinpoint 311 a distributor of
those packages, which carries obligations the source tree alone does not
discharge:

  * MIT / BSD / ISC / Apache-2.0 require their notice to accompany the copy.
  * psycopg2-binary is LGPL-3.0-or-later. Distributing a binary that contains
    it requires supplying the license text and identifying corresponding
    source. (Replaceability -- the third LGPL requirement -- is satisfied
    structurally: it is dynamically loaded from site-packages, so a deployer
    can substitute their own build.)
  * certifi is MPL-2.0, which requires the notice.

Run inside the image after `pip install`, so the output reflects what is
actually installed rather than what requirements.txt asked for.
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

# Packages whose license terms need more than a notice. Keyed by the normalized
# distribution name; the note is printed above that package's license text.
EXTRA_OBLIGATIONS = {
    "psycopg2-binary": (
        "LGPL-3.0-or-later (with OpenSSL exception).\n"
        "Corresponding source for this unmodified release is published at\n"
        "https://github.com/psycopg/psycopg2 and on PyPI at\n"
        "https://pypi.org/project/psycopg2-binary/#files\n"
        "This library is dynamically loaded from site-packages and may be\n"
        "replaced by a recipient with their own build."
    ),
    "certifi": (
        "MPL-2.0. Used unmodified; source is published at\n"
        "https://github.com/certifi/python-certifi"
    ),
}


def declared_license(dist: metadata.Distribution) -> str:
    """Best available license string, preferring the modern SPDX expression."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    if classifiers:
        return ", ".join(classifiers)
    declared = (meta.get("License") or "").strip()
    if declared and "\n" not in declared:
        return declared
    if declared:
        return "declared inline (see text below)"
    return "UNDECLARED"


def license_text(dist: metadata.Distribution) -> str | None:
    """The verbatim LICENSE file the distribution shipped, if any."""
    for path in dist.files or []:
        name = Path(path.name)
        stem = name.stem.upper()
        if not (stem.startswith("LICEN") or stem.startswith("COPYING")):
            continue
        # Skip nested licenses belonging to vendored sub-packages.
        if "site-packages" not in str(path.locate()) and len(path.parts) > 3:
            continue
        try:
            # Read through the resolved filesystem path: PackagePath.read_text()
            # takes no errors= argument, and a stray non-UTF-8 byte in one
            # vendored LICENSE should not abort the whole run.
            return (
                Path(str(path.locate()))
                .read_text(encoding="utf-8", errors="replace")
                .strip()
            )
        except (OSError, UnicodeError):
            continue
    return None


def main() -> int:
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "THIRD-PARTY-LICENSES.txt")

    dists = sorted(
        metadata.distributions(),
        key=lambda d: (d.metadata.get("Name") or "").lower(),
    )

    sections: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()

    for dist in dists:
        name = dist.metadata.get("Name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        declared = declared_license(dist)
        text = license_text(dist)
        if not text:
            missing.append(f"{name}=={dist.version} ({declared})")

        note = EXTRA_OBLIGATIONS.get(name.lower())
        sections.append(
            "\n".join(
                filter(
                    None,
                    [
                        "=" * 78,
                        f"{name}=={dist.version}",
                        f"License: {declared}",
                        f"\nNOTE: {note}" if note else None,
                        "=" * 78,
                        "",
                        text
                        or f"[This distribution ships no LICENSE file. "
                        f"Declared license: {declared}.]",
                        "",
                    ],
                )
            )
        )

    header = f"""Pinpoint 311 -- Third-Party Licenses (backend container image)

Pinpoint 311 itself is licensed under the MIT License. This file lists the
third-party Python distributions installed in this image, with their license
texts. It is generated at image build time from the installed environment, so
it describes this exact image.

Distributions: {len(sections)}

Two components carry obligations beyond attribution; both are called out in
their sections below:
  * psycopg2-binary -- LGPL-3.0-or-later
  * certifi -- MPL-2.0

This image derives from python:3.11-slim (Debian), whose base layer includes
GPL- and LGPL-licensed system components. That layer is unmodified upstream;
corresponding source is published by Debian at https://sources.debian.org and
via `apt-get source` against the distribution in this image.

See THIRD-PARTY-NOTICES.md in the project repository for the full analysis,
including runtime data sources and packages with incomplete license metadata.
"""

    if missing:
        header += (
            "\nNo LICENSE file found in the distribution for:\n"
            + "\n".join(f"  - {m}" for m in missing)
            + "\nTheir declared license is recorded in each section below.\n"
        )

    out_path.write_text(header + "\n" + "\n".join(sections), encoding="utf-8")
    print(
        f"{out_path}: {len(sections)} distributions"
        + (f", {len(missing)} without a LICENSE file" if missing else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
