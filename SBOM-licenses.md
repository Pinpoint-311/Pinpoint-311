# Pinpoint 311 — Dependency License Inventory (SBOM)

**Project license:** MIT (see `LICENSE`, Copyright 2024-2026 Parth Gupta)
**Inventory generated:** date not recorded here — see git history for this file (`git log -- SBOM-licenses.md`) for the authoritative generation date.

## Scope and method

| Ecosystem | Source of truth | Resolution method |
|---|---|---|
| npm (frontend) | `frontend/package-lock.json` (lockfileVersion 3) + installed `frontend/node_modules` | Every one of the 322 locked packages was enumerated from the lockfile; the `license` field was read from each package's installed `package.json`. `dev` / `optional` flags come from the lockfile. |
| PyPI (backend) | `backend/requirements.txt` | There is **no Python lock file**. The full transitive closure was resolved from the PyPI JSON API against the pinned root versions, for CPython 3.11 / Linux / x86_64, including declared extras (`uvicorn[standard]`, `sqlalchemy[asyncio]`, `PyJWT[crypto]`, `passlib[bcrypt]`, `sentry-sdk[fastapi]`). Licenses come from each release's PyPI metadata (`license_expression`, `license`, or trove classifier). |

Out of scope for this inventory (stated separately at the end): `demo-orchestrator/` (Node service, no lock file and not installed), OS/base-image packages, and runtime third-party web services.

---

## Summary

| Ecosystem | Packages | Production | Dev / build-only |
|---|---|---|---|
| npm (frontend) | 322 | 62 | 260 |
| PyPI (backend) | 104 | 104 (no separate dev requirements file exists) | 0 |
| **Total** | **426** | | |

### npm — production dependencies (62)

| License | Count |
|---|---|
| MIT | 43 |
| ISC | 14 |
| BSD-3-Clause | 2 |
| 0BSD | 1 |
| Apache-2.0 | 1 |
| MIT AND ISC | 1 |

### npm — dev / build-only dependencies (260)

| License | Count |
|---|---|
| MIT | 172 |
| NOT IN METADATA | 49 |
| Apache-2.0 | 15 |
| ISC | 14 |
| BSD-2-Clause | 6 |
| BSD-3-Clause | 2 |
| CC-BY-4.0 | 1 |
| Python-2.0 | 1 |

> The 49 "NOT IN METADATA" entries are all `@esbuild/*`, `@rollup/rollup-*` and `fsevents` platform-specific optional binaries for **other** CPU/OS targets. They are not installed on this machine, so their `package.json` could not be read. Their installed same-version siblings (`@esbuild/linux-x64` 0.25.12, `@rollup/rollup-linux-x64-gnu` 4.59.0) and their parent packages (`esbuild` 0.25.12, `rollup` 4.59.0) all declare **MIT**. Treated as MIT-by-inference, not verified directly.

### PyPI — backend dependencies (104)

| License | Count |
|---|---|
| Apache-2.0 | 36 |
| MIT | 32 |
| BSD-3-Clause | 12 |
| BSD (unversioned) | 5 |
| BSD (unversioned, from classifier) | 3 |
| BSD-2-Clause | 2 |
| PSF-2.0 | 2 |
| Apache-2.0 AND MIT | 1 |
| Apache-2.0 OR BSD-2-Clause | 1 |
| Apache-2.0 OR BSD-3-Clause | 1 |
| CC0-1.0 | 1 |
| Dual License | 1 |
| ISC | 1 |
| LGPL with exceptions | 1 |
| MIT AND PSF-2.0 | 1 |
| MIT OR Apache-2.0 | 1 |
| MIT-0 | 1 |
| MPL-2.0 | 1 |
| NOT DECLARED | 1 |

---

## FLAGGED ITEMS

Nothing in this project is AGPL, GPL, SSPL, BUSL, Elastic License, CC-BY-NC, commercial, or proprietary. The following require a reviewer's attention.

### 1. `psycopg2-binary` 2.9.9 — **LGPL-3.0-or-later with an OpenSSL linking exception** — PRODUCTION

- **Ecosystem:** PyPI. Direct dependency, pinned in `backend/requirements.txt`.
- **Depended on by:** `backend/app/db/session.py` (builds a synchronous SQLAlchemy engine by rewriting `postgresql+asyncpg://` to `postgresql://`) and `backend/alembic/env.py` (migrations require a sync driver). It is a real runtime dependency, not vestigial — the async path uses `asyncpg` (Apache-2.0), but the sync path uses psycopg2.
- **License text verified** from the installed distribution's `LICENSE` file: LGPL v3 "or (at your option) any later version", plus an explicit exception permitting linking against OpenSSL.
- **Exposure:** Low, but non-zero and it is the only copyleft item in the shipped stack. psycopg2 is imported as a separate Python extension module at runtime; it is not statically linked into or derived from Pinpoint 311 code. Under the LGPL this is the "use the library" case, so **the MIT license of Pinpoint 311's own source is unaffected**. The obligations attach to whoever *distributes a binary bundle containing psycopg2* — i.e. if a container image is shipped to an agency, that distribution must carry the LGPL-3.0 text and a written offer for psycopg2's source, and must not prevent the recipient from replacing the psycopg2 component. Shipping source + a `pip install` at build time (which is what `backend/Dockerfile` does) creates no obligation at all; shipping a prebuilt image does.
- **Note:** `psycopg2-binary` also vendors prebuilt libpq/OpenSSL shared objects in its wheels, which is precisely what the OpenSSL exception exists to permit.

### 2. `certifi` — **MPL-2.0** — PRODUCTION

- **Ecosystem:** PyPI, transitive (via `requests`, `httpx`/`httpcore`, `google-*`, `sentry-sdk`).
- **Exposure:** Negligible. MPL-2.0 is file-level weak copyleft: the obligation is to make modified *certifi source files* available. Pinpoint 311 does not modify certifi. MPL-2.0 is explicitly compatible with distributing a larger work under MIT. No action beyond including the MPL-2.0 notice in an attribution file.

### 3. `caniuse-lite` — **CC-BY-4.0** — DEV / BUILD-ONLY

- **Ecosystem:** npm. Transitive under `browserslist` → `autoprefixer`/`postcss`/`@babel/preset-env` toolchain.
- **Exposure:** Effectively none for redistribution. It is a browser-support **data set**, consumed at build time by autoprefixer; it is not bundled into `frontend/dist`. CC-BY-4.0 is not copyleft — it only requires attribution — and there is nothing to attribute in the shipped artifact because nothing from it ships. Some procurement checklists auto-flag any `CC-BY-*` string; the answer is "build-time data, not distributed."

### 4. `google-crc32c` 1.8.0 — **license metadata absent** — PRODUCTION

- **Ecosystem:** PyPI, transitive (`google-cloud-storage` → `google-resumable-media`, pulled in by `google-cloud-aiplatform`).
- The PyPI release metadata has an empty `license` field, no `license_expression`, and **no license trove classifier**.
- The upstream repository (`googleapis/python-crc32c`, linked as the package Homepage) carries an **Apache License 2.0** `LICENSE` file, which was fetched and confirmed.
- **Exposure:** Almost certainly Apache-2.0 and therefore fine. But the *distributed artifact's own metadata* asserts nothing, so an automated SBOM scanner will report UNKNOWN and a reviewer may want the repo-to-artifact link documented. This is the one item where "a lawyer would have to look at it" is a fair statement, and the answer is expected to be short.

### 5. `argparse` 2.0.1 — **Python-2.0 (PSF License)** — DEV-ONLY

- npm package (a JS port), transitive under `js-yaml` → `eslint`. Not a Python package.
- PSF-2.0 is a permissive, GPL-compatible, MIT-compatible license. Flagged only because it is a non-standard string in a JS dependency tree. No exposure.

### 6. Ambiguous / dual / non-obvious license strings (no action expected, listed for completeness)

| Package | Ecosystem | Declared | Read as |
|---|---|---|---|
| `cryptography` 49.0.0 | PyPI, prod, direct | `Apache-2.0 OR BSD-3-Clause` | Dual-licensed, **both permissive**; take either. Not a copyleft option. |
| `python-dateutil` 2.9.0.post0 | PyPI, prod | `"Dual License"` (free-text) | Classifiers say Apache-2.0 **and** BSD-3-Clause. Upstream dual-licenses under both. Permissive either way, but the literal metadata string is uninformative. |
| `sniffio` 1.3.1 | PyPI, prod | `MIT OR Apache-2.0` | Dual, both permissive. |
| `packaging` 26.2 | PyPI, prod | `Apache-2.0 OR BSD-2-Clause` | Dual, both permissive. |
| `aiohttp` 3.14.1 | PyPI, prod, direct | `Apache-2.0 AND MIT` | Conjunctive — comply with both. Both permissive. |
| `greenlet` 3.5.4 | PyPI, prod | `MIT AND PSF-2.0` | Conjunctive, both permissive. |
| `cffi` 2.1.0 | PyPI, prod | `MIT-0` | MIT with the attribution requirement removed. Strictly more permissive. |
| `email-validator` 2.1.0 | PyPI, prod, direct | `CC0-1.0` (copyright waived) | Public-domain dedication. Fine, but CC0 grants no patent license, which a few federal-adjacent policies note. Later releases relabel this as Unlicense. |
| `better-profanity` 0.7.0 | PyPI, prod, direct | PyPI `license` field is empty; installed dist declares `UNKNOWN` | The distribution's own `LICENSE` file was read and is **verbatim MIT text**. Resolved: MIT. |
| `sentry-sdk` 2.54.0 | PyPI, prod, direct | `license` field says MIT, trove classifier says "BSD License" | Internally inconsistent metadata. Both are permissive, so the outcome is the same either way, but the two fields disagree. |
| `victory-vendor` 36.9.2 | npm, **prod** (via `recharts`) | `MIT AND ISC` | Conjunctive; the package re-publishes several `d3-*` modules (ISC) under an MIT wrapper. Both permissive. No `LICENSE` file ships in the package — attribution must be reconstructed from the vendored d3 sources. |
| `tslib` 2.8.1 | npm, prod | `0BSD` | BSD Zero Clause — public-domain-equivalent, no attribution required. |
| `amqp`, `billiard`, `passlib`, `prompt_toolkit`, `pyasn1-modules`, `starlette`, `uvicorn`, `vine` | PyPI, prod | bare `"BSD"` or a BSD trove classifier with no version | The metadata does not say 2-clause vs 3-clause. All are permissive BSD variants; the distinction does not change MIT compatibility, only the exact notice text to reproduce. Upstream `LICENSE` files should be read when assembling the attribution file. |

---

## Full inventory

## npm — `frontend/`

### Production dependencies (62)

#### 0BSD (1)

- `tslib` 2.8.1

#### Apache-2.0 (1)

- `@googlemaps/markerclusterer` 2.6.2

#### BSD-3-Clause (2)

- `d3-ease` 3.0.1
- `react-transition-group` 4.4.5

#### ISC (14)

- `d3-array` 3.2.4
- `d3-color` 3.1.0
- `d3-format` 3.1.0
- `d3-interpolate` 3.0.1
- `d3-path` 3.1.0
- `d3-scale` 4.0.2
- `d3-shape` 3.2.0
- `d3-time` 3.1.0
- `d3-time-format` 4.1.0
- `d3-timer` 3.0.1
- `internmap` 2.0.3
- `kdbush` 4.0.2
- `lucide-react` 0.468.0
- `supercluster` 8.0.1

#### MIT (43)

- `@babel/runtime` 7.28.4
- `@dnd-kit/accessibility` 3.1.1
- `@dnd-kit/core` 6.3.1
- `@dnd-kit/sortable` 10.0.0
- `@dnd-kit/utilities` 3.2.2
- `@types/d3-array` 3.2.2
- `@types/d3-color` 3.1.3
- `@types/d3-ease` 3.0.2
- `@types/d3-interpolate` 3.0.4
- `@types/d3-path` 3.1.1
- `@types/d3-scale` 4.0.9
- `@types/d3-shape` 3.1.7
- `@types/d3-time` 3.0.4
- `@types/d3-timer` 3.0.2
- `@types/geojson` 7946.0.16
- `@types/supercluster` 7.1.3
- `clsx` 2.1.1
- `cookie` 1.1.1
- `csstype` 3.2.3
- `decimal.js-light` 2.5.1
- `dom-helpers` 5.2.1
- `eventemitter3` 4.0.7
- `fast-equals` 5.4.0
- `framer-motion` 12.36.0
- `js-tokens` 4.0.0
- `lodash` 4.18.1
- `loose-envify` 1.4.0
- `motion-dom` 12.36.0
- `motion-utils` 12.36.0
- `object-assign` 4.1.1
- `prop-types` 15.8.1
- `react` 18.3.1
- `react-dom` 18.3.1
- `react-is` 16.13.1
- `react-is` 18.3.1
- `react-router` 7.18.1
- `react-router-dom` 7.18.1
- `react-smooth` 4.0.4
- `recharts` 2.15.4
- `recharts-scale` 0.4.5
- `scheduler` 0.23.2
- `set-cookie-parser` 2.7.2
- `tiny-invariant` 1.3.3

#### MIT AND ISC (1)

- `victory-vendor` 36.9.2

### Dev / build-only dependencies (260)

#### Apache-2.0 (15)

- `@eslint/config-array` 0.21.1
- `@eslint/config-helpers` 0.4.2
- `@eslint/core` 0.17.0
- `@eslint/object-schema` 2.1.7
- `@eslint/plugin-kit` 0.4.1
- `@humanfs/core` 0.19.1
- `@humanfs/node` 0.16.7
- `@humanwhocodes/module-importer` 1.0.1
- `@humanwhocodes/retry` 0.4.3
- `baseline-browser-mapping` 2.9.11
- `didyoumean` 1.2.2
- `eslint-visitor-keys` 3.4.3
- `eslint-visitor-keys` 4.2.1
- `ts-interface-checker` 0.1.13
- `typescript` 5.6.3

#### BSD-2-Clause (6)

- `eslint-scope` 8.4.0
- `espree` 10.4.0
- `esrecurse` 4.3.0
- `estraverse` 5.3.0
- `esutils` 2.0.3
- `uri-js` 4.4.1

#### BSD-3-Clause (2)

- `esquery` 1.6.0
- `source-map-js` 1.2.1

#### CC-BY-4.0 (1)

- `caniuse-lite` 1.0.30001761

#### ISC (14)

- `anymatch` 3.1.3
- `electron-to-chromium` 1.5.267
- `fastq` 1.20.1
- `flatted` 3.4.2
- `glob-parent` 5.1.2
- `glob-parent` 5.1.2
- `glob-parent` 6.0.2
- `isexe` 2.0.0
- `lru-cache` 5.1.1
- `minimatch` 3.1.5
- `picocolors` 1.1.1
- `semver` 6.3.1
- `which` 2.0.2
- `yallist` 3.1.1

#### MIT (172)

- `@alloc/quick-lru` 5.2.0
- `@babel/code-frame` 7.29.7
- `@babel/compat-data` 7.29.7
- `@babel/core` 7.29.7
- `@babel/generator` 7.29.7
- `@babel/helper-compilation-targets` 7.29.7
- `@babel/helper-globals` 7.29.7
- `@babel/helper-module-imports` 7.29.7
- `@babel/helper-module-transforms` 7.29.7
- `@babel/helper-plugin-utils` 7.27.1
- `@babel/helper-string-parser` 7.29.7
- `@babel/helper-validator-identifier` 7.29.7
- `@babel/helper-validator-option` 7.29.7
- `@babel/helpers` 7.29.7
- `@babel/parser` 7.29.7
- `@babel/plugin-transform-react-jsx-self` 7.27.1
- `@babel/plugin-transform-react-jsx-source` 7.27.1
- `@babel/template` 7.29.7
- `@babel/traverse` 7.29.7
- `@babel/types` 7.29.7
- `@esbuild/linux-x64` 0.25.12
- `@eslint-community/eslint-utils` 4.9.0
- `@eslint-community/regexpp` 4.12.2
- `@eslint/eslintrc` 3.3.3
- `@eslint/js` 9.39.2
- `@jridgewell/gen-mapping` 0.3.13
- `@jridgewell/remapping` 2.3.5
- `@jridgewell/resolve-uri` 3.1.2
- `@jridgewell/sourcemap-codec` 1.5.5
- `@jridgewell/trace-mapping` 0.3.31
- `@nodelib/fs.scandir` 2.1.5
- `@nodelib/fs.stat` 2.0.5
- `@nodelib/fs.walk` 1.2.8
- `@rolldown/pluginutils` 1.0.0-beta.27
- `@rollup/rollup-linux-x64-gnu` 4.59.0
- `@rollup/rollup-linux-x64-musl` 4.59.0
- `@types/babel__core` 7.20.5
- `@types/babel__generator` 7.27.0
- `@types/babel__template` 7.4.4
- `@types/babel__traverse` 7.28.0
- `@types/estree` 1.0.8
- `@types/google.maps` 3.58.1
- `@types/json-schema` 7.0.15
- `@types/prop-types` 15.7.15
- `@types/react` 18.3.27
- `@types/react-dom` 18.3.7
- `@vitejs/plugin-react` 4.7.0
- `acorn` 8.15.0
- `acorn-jsx` 5.3.2
- `ajv` 6.14.0
- `ansi-styles` 4.3.0
- `any-promise` 1.3.0
- `arg` 5.0.2
- `autoprefixer` 10.4.23
- `balanced-match` 1.0.2
- `binary-extensions` 2.3.0
- `brace-expansion` 1.1.16
- `braces` 3.0.3
- `browserslist` 4.28.1
- `callsites` 3.1.0
- `camelcase-css` 2.0.1
- `chalk` 4.1.2
- `chokidar` 3.6.0
- `color-convert` 2.0.1
- `color-name` 1.1.4
- `commander` 4.1.1
- `concat-map` 0.0.1
- `convert-source-map` 2.0.0
- `cross-spawn` 7.0.6
- `cssesc` 3.0.0
- `debug` 4.4.3
- `deep-is` 0.1.4
- `dlv` 1.1.3
- `esbuild` 0.25.12
- `escalade` 3.2.0
- `escape-string-regexp` 4.0.0
- `eslint` 9.39.2
- `eslint-plugin-react-hooks` 5.2.0
- `eslint-plugin-react-refresh` 0.4.26
- `fast-deep-equal` 3.1.3
- `fast-glob` 3.3.3
- `fast-json-stable-stringify` 2.1.0
- `fast-levenshtein` 2.0.6
- `fdir` 6.5.0
- `fdir` 6.5.0
- `file-entry-cache` 8.0.0
- `fill-range` 7.1.1
- `find-up` 5.0.0
- `flat-cache` 4.0.1
- `fraction.js` 5.3.4
- `function-bind` 1.1.2
- `gensync` 1.0.0-beta.2
- `globals` 14.0.0
- `has-flag` 4.0.0
- `hasown` 2.0.2
- `ignore` 5.3.2
- `import-fresh` 3.3.1
- `imurmurhash` 0.1.4
- `is-binary-path` 2.1.0
- `is-core-module` 2.16.1
- `is-extglob` 2.1.1
- `is-glob` 4.0.3
- `is-number` 7.0.0
- `jiti` 1.21.7
- `js-yaml` 4.3.0
- `jsesc` 3.1.0
- `json-buffer` 3.0.1
- `json-schema-traverse` 0.4.1
- `json-stable-stringify-without-jsonify` 1.0.1
- `json5` 2.2.3
- `keyv` 4.5.4
- `levn` 0.4.1
- `lilconfig` 3.1.3
- `lines-and-columns` 1.2.4
- `locate-path` 6.0.0
- `lodash.merge` 4.6.2
- `merge2` 1.4.1
- `micromatch` 4.0.8
- `ms` 2.1.3
- `mz` 2.7.0
- `nanoid` 3.3.16
- `natural-compare` 1.4.0
- `node-releases` 2.0.27
- `normalize-path` 3.0.0
- `object-hash` 3.0.0
- `optionator` 0.9.4
- `p-limit` 3.1.0
- `p-locate` 5.0.0
- `parent-module` 1.0.1
- `path-exists` 4.0.0
- `path-key` 3.1.1
- `path-parse` 1.0.7
- `picomatch` 2.3.2
- `picomatch` 4.0.4
- `picomatch` 4.0.4
- `pify` 2.3.0
- `pirates` 4.0.7
- `postcss` 8.5.23
- `postcss-import` 15.1.0
- `postcss-js` 4.1.0
- `postcss-load-config` 6.0.1
- `postcss-nested` 6.2.0
- `postcss-selector-parser` 6.1.2
- `postcss-value-parser` 4.2.0
- `prelude-ls` 1.2.1
- `punycode` 2.3.1
- `queue-microtask` 1.2.3
- `react-refresh` 0.17.0
- `read-cache` 1.0.0
- `readdirp` 3.6.0
- `resolve` 1.22.11
- `resolve-from` 4.0.0
- `reusify` 1.1.0
- `rollup` 4.59.0
- `run-parallel` 1.2.0
- `shebang-command` 2.0.0
- `shebang-regex` 3.0.0
- `strip-json-comments` 3.1.1
- `sucrase` 3.35.1
- `supports-color` 7.2.0
- `supports-preserve-symlinks-flag` 1.0.0
- `tailwindcss` 3.4.19
- `thenify` 3.3.1
- `thenify-all` 1.6.0
- `tinyglobby` 0.2.15
- `to-regex-range` 5.0.1
- `type-check` 0.4.0
- `update-browserslist-db` 1.2.3
- `util-deprecate` 1.0.2
- `vite` 6.4.3
- `word-wrap` 1.2.5
- `yocto-queue` 0.1.0

#### NOT IN METADATA (not installed on this platform) (49)

- `@esbuild/aix-ppc64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/android-arm` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/android-arm64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/android-x64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/darwin-arm64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/darwin-x64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/freebsd-arm64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/freebsd-x64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/linux-arm` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/linux-arm64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/linux-ia32` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/linux-loong64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/linux-mips64el` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/linux-ppc64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/linux-riscv64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/linux-s390x` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/netbsd-arm64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/netbsd-x64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/openbsd-arm64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/openbsd-x64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/openharmony-arm64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/sunos-x64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/win32-arm64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/win32-ia32` 0.25.12 _(optional, platform-specific; not installed here)_
- `@esbuild/win32-x64` 0.25.12 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-android-arm-eabi` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-android-arm64` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-darwin-arm64` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-darwin-x64` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-freebsd-arm64` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-freebsd-x64` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-arm-gnueabihf` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-arm-musleabihf` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-arm64-gnu` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-arm64-musl` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-loong64-gnu` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-loong64-musl` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-ppc64-gnu` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-ppc64-musl` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-riscv64-gnu` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-riscv64-musl` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-linux-s390x-gnu` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-openbsd-x64` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-openharmony-arm64` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-win32-arm64-msvc` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-win32-ia32-msvc` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-win32-x64-gnu` 4.59.0 _(optional, platform-specific; not installed here)_
- `@rollup/rollup-win32-x64-msvc` 4.59.0 _(optional, platform-specific; not installed here)_
- `fsevents` 2.3.3 _(optional, platform-specific; not installed here)_

#### Python-2.0 (1)

- `argparse` 2.0.1

---

## PyPI — `backend/`

`backend/requirements.txt` declares no separate dev/test extras, so every package below is in the production closure. (`pytest` and `ruff` are present in the developer's local environment but are **not** declared in `requirements.txt` and are therefore not part of the shipped dependency set.)

**[direct]** marks a package pinned in `requirements.txt`; everything else is transitive.

#### Apache-2.0 (36)

- `aiofiles` 23.2.1 **[direct]**
- `aiosignal` 1.4.0
- `async-timeout` 5.0.1
- `asyncpg` 0.29.0 **[direct]**
- `bcrypt` 4.0.1 **[direct]**
- `boto3` 1.34.25 **[direct]**
- `botocore` 1.34.162
- `distro` 1.9.0
- `frozenlist` 1.8.0
- `google-api-core` 2.33.0
- `google-auth` 2.47.0 **[direct]**
- `google-cloud-aiplatform` 1.141.0 **[direct]**
- `google-cloud-bigquery` 3.42.2
- `google-cloud-core` 2.6.0
- `google-cloud-iam` 2.14.0 **[direct]**
- `google-cloud-kms` 2.21.0 **[direct]**
- `google-cloud-resource-manager` 1.18.0
- `google-cloud-secret-manager` 2.18.0 **[direct]**
- `google-cloud-storage` 3.13.0
- `google-genai` 1.75.0
- `google-resumable-media` 2.10.0
- `googleapis-common-protos` 1.75.0
- `grpc-google-iam-v1` 0.14.4
- `grpcio` 1.83.0
- `grpcio-status` 1.83.0
- `multidict` 6.7.1
- `propcache` 0.5.2
- `proto-plus` 1.28.2
- `pyOpenSSL` 26.3.0
- `python-multipart` 0.0.32 **[direct]**
- `requests` 2.34.2
- `rsa` 4.9.1
- `s3transfer` 0.10.4
- `tenacity` 9.1.4
- `tzdata` 2026.3
- `yarl` 1.24.5

#### Apache-2.0 AND MIT (1)

- `aiohttp` 3.14.1 **[direct]**

#### Apache-2.0 OR BSD-2-Clause (1)

- `packaging` 26.2

#### Apache-2.0 OR BSD-3-Clause (1)

- `cryptography` 49.0.0 **[direct]**

#### BSD (unversioned) (5)

- `amqp` 5.3.1
- `billiard` 4.2.4
- `passlib` 1.7.4 **[direct]**
- `pyasn1-modules` 0.4.2
- `vine` 5.1.0

#### BSD (unversioned, from classifier) (3)

- `prompt_toolkit` 3.0.53
- `starlette` 0.35.1
- `uvicorn` 0.27.0 **[direct]**

#### BSD-2-Clause (2)

- `pyasn1` 0.6.4
- `wrapt` 2.3.0

#### BSD-3-Clause (12)

- `celery` 5.3.6 **[direct]**
- `click` 8.4.2
- `click-plugins` 1.1.1.2
- `httpcore` 1.0.9
- `httpx` 0.28.1 **[direct]**
- `idna` 3.18
- `kombu` 5.6.2
- `MarkupSafe` 3.0.3
- `protobuf` 6.33.6
- `pycparser` 3.0
- `python-dotenv` 1.2.2
- `websockets` 16.1.1

#### CC0-1.0 (1)

- `email-validator` 2.1.0 **[direct]**

#### Dual License (1)

- `python-dateutil` 2.9.0.post0

#### ISC (1)

- `dnspython` 2.8.0

#### LGPL with exceptions (1)

- `psycopg2-binary` 2.9.9 **[direct]**

#### MIT (32)

- `alembic` 1.13.1 **[direct]**
- `annotated-types` 0.8.0
- `anyio` 4.14.2
- `attrs` 26.1.0
- `better-profanity` 0.7.0 **[direct]**
- `charset-normalizer` 3.4.9
- `click-didyoumean` 0.3.1
- `click-repl` 0.3.0
- `Deprecated` 1.3.1
- `docstring-parser` 0.18.0
- `fastapi` 0.109.0 **[direct]**
- `GeoAlchemy2` 0.14.3 **[direct]**
- `h11` 0.16.0
- `httptools` 0.8.0
- `jmespath` 1.1.0
- `limits` 5.8.0
- `Mako` 1.3.12
- `pydantic` 2.10.6 **[direct]**
- `pydantic-settings` 2.7.1 **[direct]**
- `pydantic_core` 2.27.2
- `PyJWT` 2.13.0 **[direct]**
- `PyYAML` 6.0.3
- `redis` 5.0.1 **[direct]**
- `sentry-sdk` 2.54.0 **[direct]**
- `six` 1.17.0
- `slowapi` 0.1.9 **[direct]**
- `SQLAlchemy` 2.0.25 **[direct]**
- `urllib3` 2.7.0
- `uvloop` 0.22.1
- `vaderSentiment` 3.3.2 **[direct]**
- `watchfiles` 1.2.0
- `wcwidth` 0.8.2

#### MIT AND PSF-2.0 (1)

- `greenlet` 3.5.4

#### MIT OR Apache-2.0 (1)

- `sniffio` 1.3.1

#### MIT-0 (1)

- `cffi` 2.1.0

#### MPL-2.0 (1)

- `certifi` 2026.7.22

#### NOT DECLARED (1)

- `google-crc32c` 1.8.0

#### PSF-2.0 (2)

- `aiohappyeyeballs` 2.7.1
- `typing-extensions` 4.16.0

---

## Items outside the two audited manifests

These are **not** covered by the counts above and should be resolved separately before a procurement submission.

1. **`demo-orchestrator/package.json`** — a Node service (`express` ^4.18.2, `cors` ^2.8.5, `node-cron` ^3.0.3) with **no lock file and no installed `node_modules`**, so its transitive closure could not be resolved. The three direct dependencies were checked against the npm registry: `express` MIT, `cors` MIT, `node-cron` ISC. Their transitive dependencies are **unresolved**. This component spins up ephemeral demo instances and may not be part of a government deployment at all; confirm before including it.

2. **Runtime third-party services (no code redistributed, but procurement-relevant):**
   - **Google Maps JavaScript API** — loaded at runtime from `maps.googleapis.com` (`frontend/src/utils/googleMaps.ts`). Proprietary SaaS under Google Maps Platform Terms of Service. No code is redistributed, so it does not affect MIT redistribution, but it is a commercial terms-of-service dependency and a data-egress consideration for a government tenant.
   - **Google Fonts (Inter)** — loaded at runtime from `fonts.googleapis.com` (`frontend/index.html`). The Inter typeface is SIL OFL 1.1 (permissive). Not redistributed. The remote fetch is a privacy/air-gap consideration rather than a licensing one.
   - **Google Cloud Vertex AI / KMS / Secret Manager / IAM, AWS (boto3), Sentry** — client libraries are Apache-2.0/MIT and counted above; the *services* are commercial and governed by their own terms.

3. **Base container images** — `backend/Dockerfile` uses `python:3.11-slim` and `apt-get install`s `gcc`, `libpq-dev`, `postgresql-client`, `git`, `curl`, `gnupg`, `docker-ce-cli`, `docker-compose-plugin`. Debian base-image packages include GPL and LGPL software (glibc is LGPL; coreutils, gcc, git are GPL). This is normal and does not affect the MIT licensing of Pinpoint 311's own code, but **if a prebuilt container image is delivered as the artifact**, the same GPL/LGPL source-offer obligations described for psycopg2 apply to the base image contents. Distributing a Dockerfile rather than an image avoids this entirely.

---

## Bottom line for redistribution under MIT

Pinpoint 311's own source code can be distributed under the MIT license without conflict. No dependency imposes a reciprocal licensing obligation on this project's code. The only copyleft component in the application dependency set is `psycopg2-binary` (LGPL-3.0+), which is dynamically imported and therefore does not affect the project's license — it creates notice-and-source-offer obligations only for whoever distributes a **prebuilt binary bundle** that contains it.

**Recommended before submission:** ship a `THIRD-PARTY-NOTICES` file reproducing the MIT/BSD/ISC/Apache-2.0 notices, the MPL-2.0 notice for certifi, and the LGPL-3.0 text plus a source offer for psycopg2-binary.
