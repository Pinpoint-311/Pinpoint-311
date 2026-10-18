# Releases: running from signed images

Production Pinpoint 311 runs **built, signed images pinned by digest**. The
containers hold no source checkout and no Docker socket: the code that serves
residents is exactly the code CI tested, scanned and signed. This is Phase 1 of
[docs/design/secure-upgrades.md](design/secure-upgrades.md).

| File | What it is for |
| --- | --- |
| `docker-compose.yml` | Production. `backend`/`worker` run `${BACKEND_IMAGE}`, `frontend` runs `${FRONTEND_IMAGE}`. No `build:`, no source mount, no `/project`, no Docker socket. |
| `release.lock` | Per instance, not in git. Pins the images by digest. Passed with `--env-file`. |
| `docker-compose.prod.yml` | Optional. Changes the default image names to the published GHCR ones (`:latest`). For trying a release, not for pinning one. |
| `docker-compose.dev.yml` | Contributors only. Build contexts, `./backend` mounted, `uvicorn --reload`. Never on a server residents reach. |
| `scripts/build-release.sh` | Builds both images locally with the same stamp CI uses. Unsigned: for testing and for hosts that cannot pull. |

Every image carries the same OCI labels, which the orchestrator, the host
updater and `/api/health/quick` all agree on:

| Label | Env var in the backend | Value |
| --- | --- | --- |
| `org.pinpoint311.app.version` (and `org.opencontainers.image.version`) | `PINPOINT_VERSION` | `1.8.0` for tag `v1.8.0`; `0.0.0-main.<sha7>` for a main build |
| `org.pinpoint311.app.git_sha` (and `org.opencontainers.image.revision`) | `GIT_SHA` | full commit SHA |
| `org.pinpoint311.app.db_revision` | `DB_REVISION` | the single Alembic head the build migrates to |
| `org.pinpoint311.app.min_db_revision` | `MIN_DB_REVISION` | `backend/MIN_DB_REVISION`, or the head's parent when blank |

## Cutting a release

1. Make sure `main` is green and has a single Alembic head.
2. If the release contains a migration, update `backend/MIN_DB_REVISION` by the
   rule written at the top of that file (additive: the previous head;
   destructive: the new head).
3. Optional but recommended: add a `## [1.8.0] - 2026-10-18` section to
   `CHANGELOG.md`. If there is a section for the tag, it becomes the release
   notes; otherwise the notes are the commit subjects since the previous tag
   (`scripts/release-notes.sh`).
4. Tag and push:

   ```bash
   git tag -s v1.8.0 -m "Pinpoint 311 v1.8.0"
   git push origin v1.8.0
   ```

Protect `v*` tags on the code host (GitHub: a tag ruleset restricting who can
create `v*`; GitLab: Settings > Repository > Protected tags), because the
signing identity is "the release workflow running on a `v*` tag".

What the pipeline then does, on GitHub (`.github/workflows/build-publish.yml`)
and GitLab (`.gitlab-ci.yml`) alike:

1. **Gate.** Backend tests, frontend typecheck/tests/build, a Trivy filesystem
   scan and a Trivy scan of each freshly built (not yet pushed) image. Trivy
   fails on any CRITICAL finding that has a fix. Any failure stops the
   pipeline: nothing is pushed, nothing is signed.
2. **Build and push** `linux/amd64` + `linux/arm64`, with BuildKit SLSA
   provenance (`mode=max`) and an SPDX SBOM attached in the registry.
3. **Sign** the multi-arch digest with keyless cosign (the CI OIDC identity; no
   key to manage).
4. **Attest** each platform's SPDX SBOM to the same digest with `cosign attest`.
5. **Release notes** with a ready-to-paste `release.lock` naming both digests.

Images land at `ghcr.io/<owner>/pinpoint-311-backend` / `-frontend` (GitHub) or
`$CI_REGISTRY_IMAGE/backend` / `/frontend` (GitLab).

Every third-party GitHub Action is pinned to a commit SHA with its version in a
comment, and every GitLab CI image is pinned by digest. Update them
deliberately; a moved tag must never change what CI runs.

### Building locally

```bash
scripts/build-release.sh                       # pinpoint-311-backend:<version>, pinpoint-311-frontend:<version>
scripts/build-release.sh --latest              # also :latest, which docker-compose.yml defaults to
scripts/build-release.sh --prefix registry.example.gov/pinpoint-311 --version 1.8.0
```

It refuses a dirty `backend/`, `frontend/` or `deploy/` unless you pass
`--allow-dirty` (the version then ends in `-dirty`), so a label never claims a
commit the image does not match. On a server that runs several stacks, leave
`--latest` off unless you mean every stack defaulting to `:latest` to pick the
build up on its next `up`.

## Pinning a town to a release: `release.lock`

Each instance keeps a lock file next to its own compose override. The host
updater (Phase 2) is its only writer; until then an operator writes it from the
release notes:

```dotenv
# /home/ubuntu/pinpoint-<instance>/release.lock
PINPOINT_VERSION=1.8.0
BACKEND_IMAGE=ghcr.io/pinpoint-311/pinpoint-311-backend@sha256:<64 hex>
FRONTEND_IMAGE=ghcr.io/pinpoint-311/pinpoint-311-frontend@sha256:<64 hex>
```

Pass it **after** the instance's own env file. `--env-file` replaces the default
`.env` lookup, so name both; the later file wins on overlap:

```bash
docker compose -p pinpoint-<instance> \
  --env-file /home/ubuntu/pinpoint-<instance>/.env.<instance> \
  --env-file /home/ubuntu/pinpoint-<instance>/release.lock \
  -f /opt/pinpoint/docker-compose.yml \
  -f /home/ubuntu/pinpoint-<instance>/docker-compose.<instance>.yml \
  up -d db redis backend worker frontend
```

A single-stack install from a checkout is the same with fewer files:

```bash
docker compose --env-file .env --env-file release.lock pull
docker compose --env-file .env --env-file release.lock up -d
```

Rules:

- Pin by `@sha256:` digest, never by tag. A tag can be moved after you verified
  it; a digest cannot.
- An override file that sets `image:` on `backend`, `worker` or `frontend`
  beats the lock. Remove those lines when you adopt `release.lock`.
- `docker compose config | grep image:` shows what will actually run.
- After `up`, `curl -s http://127.0.0.1:<BACKEND_PORT>/api/health/quick` reports
  `version`, `git_sha` and `db_revision`; they must match the lock and the
  release notes.

The entrypoint migrates the database before the API starts (and takes a
`pg_dump` into the `migration_backups` volume first), exactly as before.

## Verifying a release by hand

Install [cosign](https://docs.sigstore.dev/cosign/system_config/installation/)
v2. Verify **both** digests from the lock file before you deploy them.

### GitHub (GHCR)

```bash
IMAGE=ghcr.io/pinpoint-311/pinpoint-311-backend@sha256:<digest>

cosign verify "$IMAGE" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github\.com/Pinpoint-311/Pinpoint-311/\.github/workflows/build-publish\.yml@refs/tags/v'

# The SBOM attestation, same identity:
cosign verify-attestation "$IMAGE" --type spdxjson \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github\.com/Pinpoint-311/Pinpoint-311/\.github/workflows/build-publish\.yml@refs/tags/v' \
  > /dev/null && echo "SBOM attestation OK"
```

### GitLab (gitlab.com or self-managed)

GitLab's keyless certificates name the pipeline config at the tag. For a project
at `https://gitlab.com/<group>/<project>`:

```bash
IMAGE=registry.gitlab.com/<group>/<project>/backend@sha256:<digest>

cosign verify "$IMAGE" \
  --certificate-oidc-issuer https://gitlab.com \
  --certificate-identity-regexp '^https://gitlab\.com/<group>/<project>//\.gitlab-ci\.yml@refs/tags/v'

cosign verify-attestation "$IMAGE" --type spdxjson \
  --certificate-oidc-issuer https://gitlab.com \
  --certificate-identity-regexp '^https://gitlab\.com/<group>/<project>//\.gitlab-ci\.yml@refs/tags/v' \
  > /dev/null && echo "SBOM attestation OK"
```

Self-managed GitLab: use the instance URL (`$CI_SERVER_URL`, e.g.
`https://gitlab.example.gov`) as the issuer and in the identity. The double
slash before `.gitlab-ci.yml` is part of GitLab's identity format.

### GitLab trust policy for the host updater

```yaml
# /etc/pinpoint-updater/instances.yml
release_source:
  provider: gitlab
  registry: registry.gitlab.com/<group>/<project>      # images at .../backend and .../frontend
  api: https://gitlab.com/api/v4                       # or https://gitlab.example.gov/api/v4
  project: <group>/<project>
trust:
  issuer: https://gitlab.com                           # or the self-managed URL
  identity: '^https://gitlab\.com/<group>/<project>//\.gitlab-ci\.yml@refs/tags/v'
```

The GitHub equivalent is `issuer: https://token.actions.githubusercontent.com`
and the identity in the GitHub commands above.

### Labels, provenance and SBOM

```bash
# The stamp, as the orchestrator and updater read it:
docker buildx imagetools inspect "$IMAGE" \
  --format '{{ json (index .Image "linux/amd64").Config.Labels }}'

# BuildKit's SLSA provenance and SBOM (stored next to the image):
docker buildx imagetools inspect "$IMAGE" --format '{{ json (index .Provenance "linux/amd64").SLSA }}'
docker buildx imagetools inspect "$IMAGE" --format '{{ json (index .SBOM "linux/amd64").SPDX }}'
```

## Moving an existing source-mounted stack onto images

Older stacks ran `build: ./backend` with `./backend:/app`, `.:/project` and the
Docker socket mounted. The steps below move one stack; do them **one stack at a
time**, each with a backup first. Each stack is offline for 20–40 seconds.

What changes for a stack:

- The code comes from the image. Editing files in the checkout stops affecting
  it.
- Photos: the same named volume (`<project>_uploads_data`) is mounted at
  `/data/uploads` instead of `/project/uploads`, and `UPLOAD_DIR` says so. No
  data moves.
- The in-console version switcher, git-pull update and restart buttons report
  themselves unavailable (no Docker access is the secure setup). Phase 3
  replaces them with requests to the host updater.

### This server (four stacks sharing `/home/ubuntu/Pinpoint-311`)

`pinpoint-311` (main demo), `pinpoint-a11y`, `pinpoint-passaic` and
`pinpoint-staffordnjpilot` all layer `/home/ubuntu/Pinpoint-311/docker-compose.yml`.

> [!CAUTION]
> The moment the new `docker-compose.yml` is in `/home/ubuntu/Pinpoint-311`, the
> next `up` of **any** of the four stacks recreates it without its source
> mount, running whatever code is in the image it names. Have the release images
> ready (step 1) before the compose change reaches that checkout, and do not run
> `up` on a stack you have not prepared.

1. **Publish a release from the code the stacks run today.** Push a `v*` tag
   from `main` and wait for the pipeline (or, if it cannot run yet, build
   locally with `scripts/build-release.sh --version <x.y.z>` from a clean
   checkout of that commit). Note the backend and frontend digests from the
   release notes and verify both with `cosign verify` (above).
2. **Check the schema window.** For each stack, `curl -s
   http://127.0.0.1:<BACKEND_PORT>/api/health/quick` and confirm its
   `db_revision` is the release's `db_revision` or `min_db_revision`.
3. **Back up the stack** (Admin Console > Backups, or the encrypted off-site
   backup), and confirm it landed.
4. **Write its `release.lock`**:
   - `pinpoint-311`: `/home/ubuntu/Pinpoint-311/release.lock` (ignored by git)
   - the others: `/home/ubuntu/pinpoint-<name>/release.lock`
5. **Remove the `image:` lines** for `backend`, `worker` and `frontend` from
   the stack's override (`docker-compose.a11y.yml`, `docker-compose.passaic.yml`,
   `docker-compose.staffordnjpilot.yml`); they point at the locally built
   `pinpoint-311-backend:latest` / `pinpoint-311-worker:latest` and would beat
   the lock. Keep the `networks:` and `environment:` entries.
6. **Bring the compose change in** (first stack only): update
   `/home/ubuntu/Pinpoint-311` to the commit with the new `docker-compose.yml`.
7. **Preview, then recreate** only that stack's app services:

   ```bash
   # pinpoint-311 (the main demo; it also owns the shared Caddy)
   cd /home/ubuntu/Pinpoint-311
   docker compose -p pinpoint-311 --env-file .env --env-file release.lock \
     -f docker-compose.yml -f docker-compose.caddy-towns.yml config | grep -E 'image:|/project|docker.sock'
   docker compose -p pinpoint-311 --env-file .env --env-file release.lock \
     -f docker-compose.yml -f docker-compose.caddy-towns.yml up -d backend worker frontend

   # pinpoint-a11y / pinpoint-passaic / pinpoint-staffordnjpilot
   N=staffordnjpilot
   docker compose -p pinpoint-$N \
     --env-file /home/ubuntu/pinpoint-$N/.env.$N \
     --env-file /home/ubuntu/pinpoint-$N/release.lock \
     -f /home/ubuntu/Pinpoint-311/docker-compose.yml \
     -f /home/ubuntu/pinpoint-$N/docker-compose.$N.yml \
     up -d backend worker frontend
   ```

   The `config` preview must show the digests and no `/project` or
   `docker.sock`. For a11y the env file is `.env.a11y`, and so on.
8. **Health-check:** `/api/health/quick` reports the release's `version`,
   `git_sha` and `db_revision`; the home page and `/api/services/` return 200;
   `docker inspect pinpoint-$N-backend-1 --format '{{range .Mounts}}{{.Source}} {{end}}'`
   lists no `/home/ubuntu/Pinpoint-311` path and no `docker.sock`; an existing
   photo still loads.
9. **Roll back if needed:** put the previous digests back in `release.lock`
   and repeat step 7. To return to the source-mounted layout, check out the
   previous `docker-compose.yml` in `/home/ubuntu/Pinpoint-311`, restore the
   override's `image:` lines and `up -d` again.

Then move on to the next stack. When all four run from images, the checkout at
`/home/ubuntu/Pinpoint-311` is used by no running container and becomes an
ordinary clone for development and releases. Panel-provisioned towns are
unaffected: the orchestrator already runs them from signed digests.

## Connecting the host updater

Once a stack runs from images and the updater is installed
([updater/README.md](../updater/README.md)), connect it to the instance's
console so admins can request, approve and watch upgrades there
([design, section 4](design/secure-upgrades.md#4-in-the-app)).

1. **Create a token in the console.** Admin Console → Version Control →
   *Updater connection* → *Create token*. The token (`ppu_…`) is shown once;
   the instance stores only its SHA-256 hash. Creating and revoking tokens is
   audited.
2. **Put it in the token file**, readable only by the updater:

   ```bash
   sudo install -m 0600 -o pinpoint-updater -g pinpoint-updater /dev/null \
       /home/ubuntu/pinpoint-staffordnjpilot/updater.token
   sudo -e /home/ubuntu/pinpoint-staffordnjpilot/updater.token   # paste the token, nothing else
   ```

3. **Register the instance** in `/etc/pinpoint-updater/instances.yml`:

   ```yaml
   instances:
     staffordnjpilot:
       # ...project, dir, compose, env_file, app_url as before...
       token_file: updater.token              # relative to dir, or absolute
       api_url: http://127.0.0.1:58004        # the backend's loopback port (BACKEND_PORT)
       # require_two_person_approval: true    # optional host-side floor, see below
   ```

   `api_url` must reach the backend directly. Caddy answers `404` for
   `/api/internal/*`, and the backend refuses any request that carries proxy
   headers, so a URL that goes through Caddy is refused. The backend port is
   bound to `127.0.0.1` in `docker-compose.yml`, so this traffic never leaves
   the host.

4. **Check it.** `sudo -u pinpoint-updater pinpoint-updater --json poll`
   (or wait for the one-minute timer). Version Control now shows when the
   updater last checked in, what `release.lock` says runs (digests included),
   and the signed releases it verified.

What happens next:

- An admin picks a release marked *Signature verified* and *Schema
  compatible*, gives a reason and optionally a time. Every admin is emailed.
- While **two-person approval** is on (the default, in Version Control), a
  different admin approves it. Restarts need one admin: they change no code
  or schema and are the lever used mid-incident. Turning the setting off is
  audited. To make two-person approval non-negotiable for an instance, set
  `require_two_person_approval: true` in `instances.yml`: the updater then
  refuses an upgrade or rollback that only its requester approved, whatever
  the console says.
- On its next poll the updater claims the request (exactly one claim wins),
  runs preflight → backup → pull → migrate → recreate → health → commit or
  rollback, posts each step back, and the console shows the live step list.
  The outcome is audited and emailed.
- A destructive migration stops the run as *On hold: destructive migration*
  with the old version still serving. After checking the backup, file a new
  request with *Allow a destructive migration* checked.

**If the updater stops reporting** (the host rebooted mid-run, the service
was killed), the request becomes *Failed: the updater stopped reporting* once
it has been silent for `UPGRADE_LEASE_MINUTES` (backend env, default 45;
restarts `UPGRADE_RESTART_LEASE_MINUTES`, default 10). Every admin is emailed,
and a late report from that run is refused. An admin can also press *Mark
failed* in Version Control. Either way, check the server (`pinpoint-updater
status <instance>` and `/var/log/pinpoint-updater/<instance>.jsonl`) before
retrying. Heartbeats keep long steps alive: while a run is in progress the
updater renews the lease every minute, so an hour-long backup is fine. If the
console has already given up on a run, the updater finishes it anyway and its
local log (`pinpoint-updater status`, the JSONL file) says "console lost
track".

**Rotating or revoking the token:** create a new one, replace the file's
contents, then revoke the old one in the console. A revoked token is refused
on the updater's next call (`401`, reported in `poll`'s output).

**Without the updater** the console shows *No updater connected* and the
command-line steps instead of request buttons; `pinpoint-updater upgrade`
from the host works exactly as before.
