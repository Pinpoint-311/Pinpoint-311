# Development

Running Pinpoint 311 from source, the test suites, schema changes, and CI.

- [Code layout](#code-layout)
- [Running locally](#running-locally)
- [Backend tests](#backend-tests)
- [Frontend checks](#frontend-checks)
- [Host updater tests](#host-updater-tests)
- [Schema changes](#schema-changes)
- [CI](#ci)

## Code layout

| Path | Contents |
| --- | --- |
| `backend/app/main.py` | App assembly, middleware, router registration |
| `backend/app/api/` | Route modules (auth, open311, services, system, setup, integrations, upgrades, updater_internal, research, resident_history, health, and others) |
| `backend/app/services/` | Business logic and provider adapters: `ai/` (Vertex, Azure OpenAI, Bedrock), `image_redaction.py` and `onnx_detectors.py` (photo privacy), `gis_layers.py`, `translation_budget.py`, `open311_keys.py`, `upgrades.py` |
| `backend/app/core/` | Config, auth and session revocation, encryption and KMS, `audit_chain.py`, Celery app and Beat schedule |
| `backend/app/integrations/` | Connector framework and connectors (Accela, ArcGIS, Open311, Tyler, generic REST) |
| `backend/app/tasks/` | Background tasks (triage, notifications, integrations, backups, retention, upgrade lease sweep) |
| `backend/app/db/migrate.py`, `backend/alembic/` | Startup migrator and Alembic revisions |
| `backend/tests/` | Pytest suite |
| `frontend/src/pages/`, `frontend/src/components/` | React pages and components, with Vitest tests alongside |
| `updater/` | The host updater (`pinpoint-updater`), its systemd units and tests |
| `deploy/templates/` | Azure ARM and AWS CloudFormation templates for the cloud resources a town needs |
| `redactor/` | Experimental, opt-in EgoBlur sidecar (`--profile redactor`) |

## Running locally

Layer `docker-compose.dev.yml` on top of the default file. It builds from
source, bind-mounts `./backend` into the `backend` and `worker` containers, and
runs uvicorn with `--reload`. Never use it on a server residents reach.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

For frontend work with hot reload, run Vite on the host. Its dev server proxies
`/api` to `http://backend:8000`, so either run it inside the compose network or
change the proxy target in `frontend/vite.config.ts` to `http://localhost:8000`
for your local session.

```bash
cd frontend
npm ci
npm run dev
```

`scripts/build-release.sh --latest` builds both production images locally with
the same version stamp CI uses (unsigned).

## Backend tests

CI (`.github/workflows/backend-tests.yml`) runs Python 3.11 with the full
`requirements.txt` plus `pytest`, `pytest-asyncio`, and `aiosqlite`. The tests
do not need a running database.

```bash
cd backend
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio aiosqlite
python -m pytest tests/ -q
```

Or inside the backend image, without installing anything on the host:

```bash
docker compose run --rm --no-deps --entrypoint bash backend \
  -c "pip install -q pytest pytest-asyncio aiosqlite && python -m pytest tests/ -q"
```

A few tests that exercise cloud provider SDKs can fail in an environment without
those providers' credentials. Some tests check the documentation itself: for
example, `tests/test_no_auto_update.py` requires the README to explain manual
upgrades.

## Frontend checks

CI (`.github/workflows/frontend-checks.yml`) runs on Node 20:

```bash
cd frontend
npm ci
npx tsc --noEmit -p tsconfig.json   # type check (also: npm run typecheck)
npx vitest run                      # unit, keyboard, and accessibility tests (also: npm test)
npx vite build
```

`npm run build` runs the type check before `vite build`, so the frontend Docker
image will not build with type errors. CI tolerates a small known baseline of
type errors in `src/maps/providers/azure/renderer.ts`; new errors elsewhere fail
the job.

## Host updater tests

```bash
cd updater
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

The end-to-end tests (real compose, throwaway project) are opt-in; see
[updater/README.md](../updater/README.md#development).

## Schema changes

Add an Alembic revision under `backend/alembic/versions/`:

```bash
docker compose exec backend alembic revision --autogenerate -m "describe the change"
```

Additive changes apply automatically on the next start. Anything that drops or
rewrites data stops the container until an operator allows it, so write
destructive changes as a separate, deliberate revision. Each image records the
oldest schema it can run on (`backend/MIN_DB_REVISION`), which the host updater
checks before an upgrade; see [RELEASES.md](RELEASES.md).

## CI

- `backend-tests.yml` and `frontend-checks.yml`, as above.
- `build-publish.yml` builds the multi-architecture images, attaches SLSA provenance and an SBOM, and signs each pushed image digest with cosign (keyless, using the workflow's OIDC identity), after the tests and scans pass.
- `accessibility.yml` runs axe-core against a live deployment weekly and on pushes to `main`.
- `codeql.yml` and `security-scan.yml` run CodeQL, an OWASP ZAP baseline scan, and Trivy.
- `.gitlab-ci.yml` includes GitLab's SAST template and a release job.
