# pinpoint-updater

The host-side updater for self-hosted Pinpoint 311 instances (Phase 2 of
[docs/design/secure-upgrades.md](../docs/design/secure-upgrades.md)). It is the
only component on a town server that pulls images and restarts an instance's
containers. It runs as a systemd unit with no listening port, and it moves
**one** instance at a time to a **signed** release, by digest.

Each upgrade runs these steps under a per-instance lock:

1. **preflight**: resolve the tag to backend/frontend digests, run `cosign verify`
   on both (and `verify-attestation` if required), check the instance's
   `db_revision` sits inside the release's `[min_db_revision, db_revision]` window,
   check disk space. Any failure stops the run with nothing changed.
2. **backup**: `python -m app.cli.backup --verify` in a one-off container from
   the *current* image. It runs the encrypted off-site backup, restores it into a
   scratch database and compares table counts.
3. **pull**: both images, by digest.
4. **migrate**: `python -m app.db.migrate` in a one-off container from the *new*
   image. If the migration is destructive, the run stops with `needs_approval`
   and the old version keeps serving.
5. **recreate**: `backend`, `worker` and `frontend` of this compose project only.
6. **health**: `/api/health/quick` must report the release's version and
   `db_revision`, the worker must answer a ping, and `/` and `/api/services/` must
   return 200. Retried for up to 2 minutes.
7. **commit or roll back**: `release.lock` is rewritten atomically. If anything
   fails, the previous digests are recreated. The database is never restored
   automatically. The report names the step-2 backup instead.
8. **report**: every step and outcome is appended as JSONL to
   `/var/log/pinpoint-updater/<instance>.jsonl`, and, for console requests,
   posted back to the instance (see "The console channel" below).

## Install

```bash
# 1. a dedicated user whose only privilege is the docker group
sudo useradd --system --home /var/lib/pinpoint-updater --shell /usr/sbin/nologin pinpoint-updater
sudo usermod -aG docker pinpoint-updater

# 2. the package (Python ≥ 3.11) and cosign
sudo python3 -m venv /opt/pinpoint-updater/venv
sudo /opt/pinpoint-updater/venv/bin/pip install /path/to/Pinpoint-311/updater
sudo cp /path/to/Pinpoint-311/updater/README.md /opt/pinpoint-updater/
# cosign: install a pinned release binary from github.com/sigstore/cosign/releases
# and check its checksum, e.g. into /usr/local/bin/cosign

# 3. configuration
sudo install -d -m 0750 -o root -g pinpoint-updater /etc/pinpoint-updater
sudo install -m 0640 -o root -g pinpoint-updater deploy/instances.example.yml /etc/pinpoint-updater/instances.yml
sudo -e /etc/pinpoint-updater/instances.yml

# 4. each managed instance directory must be writable by the updater
#    (it writes release.lock and .pinpoint-updater.lock there, nothing else)
sudo setfacl -m u:pinpoint-updater:rwx /home/ubuntu/pinpoint-staffordnjpilot
sudo setfacl -m u:pinpoint-updater:rw  /home/ubuntu/pinpoint-staffordnjpilot/release.lock

# 5. systemd: edit ReadWritePaths= to list every instance dir, then
sudo cp deploy/pinpoint-updater.service deploy/pinpoint-updater.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pinpoint-updater.timer
```

The updater refuses to act on an instance until its `release.lock` and env
file exist. Phase 1's rollout writes the first lock (see the design doc).

## Usage

```bash
pinpoint-updater releases --instance staffordnjpilot   # list + schema compatibility
pinpoint-updater verify   staffordnjpilot v1.8.0       # signatures only
pinpoint-updater plan     staffordnjpilot v1.8.0       # dry run: every check, every command; changes nothing
pinpoint-updater upgrade  staffordnjpilot v1.8.0       # prompts after preflight; --yes to skip
pinpoint-updater upgrade  staffordnjpilot v1.8.0 --yes --allow-destructive   # after a needs_approval
pinpoint-updater rollback staffordnjpilot              # to PREVIOUS_* in release.lock
pinpoint-updater status   staffordnjpilot              # lock, health, containers, drift, last run
```

Global flags: `--config` (default `/etc/pinpoint-updater/instances.yml` or
`$PINPOINT_UPDATER_CONFIG`), `--json` (one JSON document on stdout),
`--log-dir`. Run it as the service user (`sudo -u pinpoint-updater …`) so file
ownership stays right.

| exit | meaning |
|---|---|
| 0 | success, nothing to do, or plan/verify passed |
| 1 | unexpected error |
| 2 | usage or config error, or the instance's `release.lock`/env file is missing |
| 3 | refused: resolve, signature, schema window, disk, backup or pull failed. Nothing changed |
| 4 | needs approval: a destructive migration is pending. Nothing applied, the current version is serving |
| 5 | rolled back: the new release was unhealthy, the previous digests are serving (database not restored) |
| 6 | **rollback failed**: unhealthy, and the rollback did not come back healthy. Act now |
| 7 | locked: another run holds this instance |
| 8 | not confirmed: no `--yes`, and the prompt was declined or there is no TTY |
| 9 | migration failed: containers were not recreated, the current version is serving. Check the schema |

`--insecure-skip-verify` skips cosign entirely. It is refused unless
`PINPOINT_UPDATER_ALLOW_INSECURE=1` is set, prints a banner, and the run is
logged as insecure. It exists for throwaway test stacks (the end-to-end test).

### release.lock

```dotenv
PINPOINT_VERSION=v1.8.0
BACKEND_IMAGE=ghcr.io/pinpoint-311/pinpoint-311-backend@sha256:…
FRONTEND_IMAGE=ghcr.io/pinpoint-311/pinpoint-311-frontend@sha256:…
PINPOINT_APP_VERSION=1.8.0          # what the image label / health endpoint reports
PREVIOUS_PINPOINT_VERSION=v1.7.2
PREVIOUS_BACKEND_IMAGE=…
PREVIOUS_FRONTEND_IMAGE=…
```

Compose reads it as the last `--env-file`. A candidate release is passed as
environment variables, which compose ranks above env files, so the lock only
changes once the candidate is healthy.

## Trust policy

Keyless (Sigstore) is the default. Both `issuer` and `identity` are required.
`identity` is a regexp over the signing certificate's SAN and must be anchored
with `^`, or it would match any identity that merely contains the expected URL.

| Release host | `issuer` | `identity` |
|---|---|---|
| GitHub Actions | `https://token.actions.githubusercontent.com` | `^https://github\.com/Pinpoint-311/Pinpoint-311/\.github/workflows/build-publish\.yml@refs/tags/v` |
| GitLab.com CI | `https://gitlab.com` | `^https://gitlab\.com/<group>/<project>//\.gitlab-ci\.yml@refs/tags/v` (note the `//`) |
| Self-managed GitLab | the instance URL, e.g. `https://gitlab.example.gov` | `^https://gitlab\.example\.gov/<group>/<project>//\.gitlab-ci\.yml@refs/tags/v` |

Self-managed GitLab: the public Sigstore Fulcio only issues certificates for
OIDC issuers it federates with, and that list includes gitlab.com but not
arbitrary self-managed instances. Keyless signing from self-managed GitLab
therefore needs a private Sigstore deployment. Otherwise use key-based
verification.

Key-based: `trust: {key: /etc/pinpoint-updater/cosign.pub}`, or any reference
cosign's `--key` accepts (`awskms://…`, `azurekms://…`, `gcpkms://…`,
`hashivault://…`).

Attestations: an instance with `require_attestations: true` also runs `cosign
verify-attestation --type <t>` for each `trust.attestation_types` entry
(default `spdxjson`, the SBOM that CI attests).

Registry credentials are only needed for private images: a GitHub token with
`read:packages`, or a GitLab deploy token with `read_registry` (set
`registry_username` to the token's username). Each goes in its own file
(`registry_token_file`, `api_token_file`), is never written inline, and is
masked in every log line and report.

## Threat model (short)

- **The web app is not trusted with the host.** The updater has no listening
  port and the app never calls it. `poll` calls the app over loopback with a
  per-instance token. A compromised backend can at most file a request for a
  signed release.
- **The registry is not trusted.** Images are pinned by the digest the registry
  returns. The digest is checked against the manifest body, cosign verifies it
  against a pinned identity and issuer (or key), and the updater pulls and runs
  that digest. A signature covers a digest, not a tag, so the version label
  inside the signed image must also name the requested tag: pointing `1.8.0`
  at the signed `1.7.0` digest is refused.
- **The console is not trusted with the host.** A console request cannot
  "upgrade" to a release older than the one running (rollback goes to the
  previous release only; an older one needs an operator on the host). Its
  answers are capped at 1 MiB and about 30 s, at most three requests run per
  instance per pass, and the unit caps the process at `MemoryMax=1G`.
  Credential files any user on the host can read are refused.
- **The schema is not assumed.** The compatibility window and the app's own
  migration gate stop code from starting on a schema it cannot serve, and
  destructive changes need a human.
- **Scope.** Every docker call names `-p <project>`, `--project-directory`,
  every compose file and both env files. Inherited `COMPOSE_*` variables are
  scrubbed. There is no shell (argv lists only) and one flock per instance.
- **The updater itself is root-equivalent** through the docker group. That is
  why it is small, has no network listener, runs under a strict systemd
  sandbox, and only reads its config and credentials from root-owned files.

## The console channel (Phase 3)

With `token_file` (and usually `api_url`) set on an instance, `poll` talks to
that instance's backend over loopback (`/api/internal/updater/*`,
`HttpRequestSource` in `pinpoint_updater/request_source.py`). Each pass, per
instance:

1. publish the release list: the newest releases resolved to digests, `cosign
   verify` (and `verify-attestation` for `trust.attestation_types`), and the
   schema window against the live `db_revision`, plus what `release.lock` says
   runs. Positive verdicts are cached per digest in `<log_dir>/<instance>.verified.json`.
   The list is rebuilt at most every `release_refresh_seconds` (default 3600) or
   right after a run. In between, the cached list in
   `<log_dir>/<instance>.releases.json` is republished with only the schema
   check redone, so the one-minute timer stays cheap.
   `gate_passed` is reported only as the consequence of a valid signature (CI
   signs after the gate), never as a separate claim. With
   `--insecure-skip-verify` nothing is reported as verified;
2. fetch approved requests, claim each (one claim wins), run it
   (`upgrade`, `rollback`, or `restart`: `docker compose -p <project> restart
   backend worker frontend` followed by the health check), and post every step
   and the outcome back (the outcome is retried). While a run is in progress
   a daemon thread posts a heartbeat every 60 s, so steps longer than the
   console's lease (45 minutes) are not taken for a dead updater. A `409`
   (the console already failed the request) is logged loudly, the run is
   finished, nothing more is posted, and the local outcome says "console lost
   track";
3. record the instance's status. An unreachable console is reported in the
   summary and never blocks the other instances.

Approval: the updater re-checks what the console says. Upgrades and rollbacks
use `TwoPersonApproval` while the console's setting is on, or always when the
instance sets `require_two_person_approval: true`; restarts need one
approval (`ConsoleApproval`). The token is read from its file, registered for
redaction, sent only as a bearer header, and redirects are never followed.

Setup: [docs/RELEASES.md, "Connecting the host updater"](../docs/RELEASES.md#connecting-the-host-updater).

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest                                   # unit tests (fakes for docker/cosign/registry/http)
PINPOINT_UPDATER_E2E=1 .venv/bin/pytest tests/test_e2e.py   # real compose, throwaway project; cleans up after itself
# the console flow: a throwaway PostGIS + this checkout's backend + the same throwaway project
PINPOINT_UPDATER_E2E=1 PINPOINT_UPDATER_E2E_BACKEND_IMAGE=pinpoint-311-backend:latest .venv/bin/pytest tests/test_e2e_console.py
```

The end-to-end test builds tiny images from `tests/e2e_app`, tagged as four
"releases". It starts a uniquely named compose project on a free loopback port
and drives the real CLI through four runs: a good upgrade, a failed-health
rollback, a gated migration and an operator rollback. Then it removes the
project, its volume and its images.

Ported from `centralizedhosting/orchestrator`:

- cosign policy (`supply_chain.py`);
- digest and label resolution (`upstream.py`);
- the compatibility window, the migrate-or-not decision and the health
  expectations (`rollout.py`);
- backup → pull → migrate → recreate and the migrator exit codes
  (`migrator.py`);
- `up` but never `down`/`--volumes` (`stack.py`).

The design doc plans to extract a shared package so the two cannot drift.
