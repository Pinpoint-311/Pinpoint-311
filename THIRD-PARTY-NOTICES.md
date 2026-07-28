# Third-Party Notices

Pinpoint 311 is distributed under the MIT License (see `LICENSE`). It also
incorporates or depends on third-party work, listed below.

A machine-assisted inventory of the full dependency closure for both
ecosystems — 322 npm packages and 104 PyPI packages, with per-package
licenses — is in `SBOM-licenses.md`. That inventory found **no AGPL, GPL,
SSPL, BUSL, Elastic License, CC-BY-NC, or commercially restricted code** in
either tree. Nothing Pinpoint 311 depends on imposes a reciprocal licensing
obligation on Pinpoint 311's own source.

This file records the notices that permissive licenses do require, plus the
two dependencies that carry obligations beyond a simple notice.

---

## 1. Icon artwork embedded directly in source

Most icons come from `lucide-react`, a declared dependency. In a handful of
places an icon's SVG path data is written inline as a string instead — either
because the surrounding code generates a standalone HTML document where a
React component cannot be used, or because the icon predates the project's
standardization on Lucide. Those paths are third-party creative work and are
attributed here.

### Heroicons — MIT License

Copyright (c) Tailwind Labs, Inc.
https://github.com/tailwindlabs/heroicons

Outline path data used inline in:

- `frontend/src/components/ErrorBoundary.tsx` (v2 `exclamation-triangle`)
- `frontend/src/components/TrackRequests.tsx` (v1 `users`, `user-circle`)
- `frontend/src/components/AutoTranslate.tsx` (v1 `refresh`, `translate`)
- `frontend/src/pages/StaffDashboard.tsx` (v1 `flag`)

Heroicons is not currently declared in `frontend/package.json`; only these
individual paths are used.

### Lucide — ISC License, and Feather Icons — MIT License

Lucide: Copyright (c) Lucide Contributors — https://lucide.dev
Feather: Copyright (c) 2013-2022 Cole Bemis — https://feathericons.com

Lucide is a forked and extended Feather, and carries Feather's notice forward.
`lucide-react` is a declared dependency used throughout the application. In
addition, path data is written inline in:

- `frontend/src/components/PrintWorkOrder.tsx` (13 icons; this file emits a
  standalone print document, so React components are unavailable)
- `frontend/src/pages/ResidentPortal.tsx` (a search icon, as a CSS data URI)

### Inter — SIL Open Font License 1.1

Copyright (c) The Inter Project Authors — https://rsms.me/inter/

Loaded at runtime from Google Fonts; no font files are bundled in this
repository.

---

## 2. Dependencies with obligations beyond attribution

### psycopg2-binary — LGPL-3.0-or-later, with an OpenSSL exception

The PostgreSQL driver used for the synchronous engine and for Alembic
migrations (`backend/app/db/session.py`, `backend/alembic/env.py`; the
application's primary async path uses asyncpg).

It is a dynamically imported extension module installed from PyPI, not vendored
into this repository, so **it places no reciprocal obligation on Pinpoint 311's
own MIT-licensed code**.

The LGPL obligations — supplying the license text, offering corresponding
source, and not preventing a recipient from substituting their own build — are
triggered by *distributing a prebuilt binary artifact that contains it*. They
are not triggered by distributing source that installs it at build time, which
is what this repository and its Dockerfile do.

**If you redistribute Pinpoint 311 as a built container image rather than as
source, these obligations apply to that image and must be satisfied.** Deployers
should decide in writing which of the two they are doing. A container image
additionally carries the GPL/LGPL components of its Debian base layer, subject
to the same reasoning.

### certifi — Mozilla Public License 2.0

The CA certificate bundle. MPL-2.0 is file-level weak copyleft: the obligation
attaches only to modified MPL files. certifi is used unmodified, and MPL-2.0 is
explicitly compatible with combination into an MIT-licensed work. Notice only.

---

## 3. Dependencies whose declared license metadata is incomplete

Recorded for transparency; none is believed to be a restriction.

- **`google-crc32c` 1.8.0** — the published artifact declares no license at all
  (empty field, no expression, no classifier). Upstream
  `googleapis/python-crc32c` is Apache-2.0, but the package itself asserts
  nothing. This is the one item a legal reviewer may want to confirm
  independently.
- **`better-profanity`** declares UNKNOWN; the LICENSE file shipped inside the
  distribution is verbatim MIT.
- **`sentry-sdk`** declares MIT in one metadata field and BSD in another.
- **`python-dateutil`** declares the literal string "Dual License" (it is
  Apache-2.0 and BSD-3-Clause).
- **`victory-vendor`** (transitive under recharts) declares "MIT AND ISC" and
  ships no LICENSE file.
- Eight PyPI packages declare a bare "BSD" without a clause count.
- Forty-nine npm packages — the `@esbuild/*` and `@rollup/*` cross-platform
  optional binaries plus `fsevents` — are not installed on this platform and
  were labeled MIT by inference from same-version siblings rather than read
  directly. All are build-time only and none is shipped.

---

## 4. External data sources

Not code, and not bundled — these are queried at runtime — but they are
surfaced to end users through the research portal and map, so they are credited
here as a matter of civic-data practice.

- **U.S. Census Bureau** — TIGERweb boundary and geocoding services, and
  American Community Survey data. Public domain; attribution is customary.
- **CDC/ATSDR Social Vulnerability Index** — retrieved live from CDC OneMap.
  Public domain; cite as CDC/ATSDR SVI.
- **OpenStreetMap / Nominatim** — geocoding. Map *data* is ODbL-1.0 and
  **requires attribution wherever results derived from it are displayed.**
- **Open-Meteo** — weather context. CC-BY-4.0.
- **Google Maps Platform** — a proprietary commercial service used under
  Google's Terms of Service with a deployer-supplied API key. No Google code is
  included in this repository.

---

## 5. Scope of this file

This lists third-party work that is embedded in, or carries obligations for,
this repository. It is not a substitute for the full dependency inventory in
`SBOM-licenses.md`, and it is not legal advice. A deployer distributing built
artifacts rather than source should have counsel review section 2.
