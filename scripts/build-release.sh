#!/usr/bin/env bash
#
# Build the backend and frontend images locally, stamped the way CI stamps them.
#
#   scripts/build-release.sh                 # tag <prefix>-backend:<version>, <prefix>-frontend:<version>
#   scripts/build-release.sh --latest        # ...and :latest (what docker-compose.yml defaults to)
#   scripts/build-release.sh --prefix pp-test/pinpoint-311 --allow-dirty
#
# The stamp (same keys as .github/workflows/build-publish.yml and .gitlab-ci.yml,
# and what the orchestrator / host updater read with `_stamp_from_labels`):
#
#   PINPOINT_VERSION  the tag without its "v" when HEAD is exactly a v* tag,
#                     otherwise 0.0.0-<branch>.<sha7> (CI uses 0.0.0-main.<sha7>);
#                     "-dirty" is appended for an uncommitted tree
#   GIT_SHA           git rev-parse HEAD
#   DB_REVISION       the single Alembic head under backend/alembic/versions
#   MIN_DB_REVISION   backend/MIN_DB_REVISION, or the head's parent when blank
#
# Each becomes an OCI label on both images and an environment variable in the
# backend, which is where /api/health/quick reads its version from.
#
# A local build is for testing and for hosts that cannot pull. It is not a
# release: it is unsigned, and the updater will refuse it. Releases come from a
# pushed tag (docs/RELEASES.md).
#
# Note for shared hosts: --latest retags pinpoint-311-*:latest, which other
# stacks on the same machine may start from on their next `up`. Leave it off
# (the default) unless that is what you mean.

set -euo pipefail

PREFIX="pinpoint-311"
TAG_LATEST=0
ALLOW_DIRTY=0
VERSION_OVERRIDE=""
PLATFORM=""

usage() {
    sed -n '3,30p' "$0" | sed 's/^# \{0,1\}//'
    cat <<'EOF'
Options:
  --prefix P      image name prefix (default: pinpoint-311 -> pinpoint-311-backend)
  --version V     override the derived version (no leading "v")
  --latest        also tag :latest
  --allow-dirty   build from a tree with uncommitted changes (version gets -dirty)
  --platform P    passed to docker build (e.g. linux/arm64)
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="$2"; shift 2 ;;
        --version) VERSION_OVERRIDE="${2#v}"; shift 2 ;;
        --latest) TAG_LATEST=1; shift ;;
        --allow-dirty) ALLOW_DIRTY=1; shift ;;
        --platform) PLATFORM="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 64 ;;
    esac
done

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"

GIT_SHA="$(git rev-parse HEAD)"
SHORT_SHA="${GIT_SHA:0:7}"

DIRTY=""
if [ -n "$(git status --porcelain --untracked-files=normal -- backend frontend deploy)" ]; then
    if [ "$ALLOW_DIRTY" -ne 1 ]; then
        echo "error: backend/, frontend/ or deploy/ has uncommitted changes." >&2
        echo "       The image would not match GIT_SHA ${SHORT_SHA}. Commit first, or pass --allow-dirty." >&2
        exit 1
    fi
    DIRTY="-dirty"
fi

if [ -n "$VERSION_OVERRIDE" ]; then
    VERSION="$VERSION_OVERRIDE"
elif TAG="$(git describe --tags --exact-match --match 'v*' HEAD 2>/dev/null)"; then
    VERSION="${TAG#v}${DIRTY}"
else
    BRANCH="$(git rev-parse --abbrev-ref HEAD | tr '/_' '--' | tr -cd 'A-Za-z0-9.-' | cut -c1-40)"
    VERSION="0.0.0-${BRANCH:-detached}.${SHORT_SHA}${DIRTY}"
fi

# Alembic heads from the files alone (no database, no alembic install): the
# same answer `ScriptDirectory.get_heads()` gives CI, via the AST so a docstring
# that mentions "revision = ..." cannot fool it.
read -r DB_REVISION PREV_REVISION < <(python3 - backend/alembic/versions <<'PY'
import ast, pathlib, sys

revs = {}
for path in pathlib.Path(sys.argv[1]).glob("*.py"):
    tree = ast.parse(path.read_text(), str(path))
    found = {}
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        for name in targets:
            if name in ("revision", "down_revision") and node.value is not None:
                found[name] = ast.literal_eval(node.value)
    if "revision" in found:
        down = found.get("down_revision")
        revs[found["revision"]] = tuple(down) if isinstance(down, (list, tuple)) else ((down,) if down else ())

referenced = {d for downs in revs.values() for d in downs}
heads = sorted(r for r in revs if r not in referenced)
if len(heads) != 1:
    sys.exit(f"expected exactly one alembic head, found {heads}. Merge the branches before building a release.")
head = heads[0]
downs = revs[head]
print(head, downs[0] if len(downs) == 1 else head)
PY
)

if [ -z "${DB_REVISION:-}" ]; then
    echo "error: could not determine the Alembic head (see the message above)." >&2
    exit 1
fi

MIN_DB_REVISION="$(grep -v '^[[:space:]]*#' backend/MIN_DB_REVISION 2>/dev/null | tr -d '[:space:]' || true)"
MIN_DB_REVISION="${MIN_DB_REVISION:-$PREV_REVISION}"

echo "version=${VERSION} git_sha=${GIT_SHA} db_revision=${DB_REVISION} min_db_revision=${MIN_DB_REVISION}"

STAMP_ARGS=(
    --build-arg "PINPOINT_VERSION=${VERSION}"
    --build-arg "GIT_SHA=${GIT_SHA}"
    --build-arg "DB_REVISION=${DB_REVISION}"
    --build-arg "MIN_DB_REVISION=${MIN_DB_REVISION}"
)
[ -n "$PLATFORM" ] && STAMP_ARGS+=(--platform "$PLATFORM")

build() {
    local name="$1"; shift
    local tags=(-t "${PREFIX}-${name}:${VERSION}")
    [ "$TAG_LATEST" -eq 1 ] && tags+=(-t "${PREFIX}-${name}:latest")
    echo "==> building ${PREFIX}-${name}:${VERSION}"
    DOCKER_BUILDKIT=1 docker build "${STAMP_ARGS[@]}" "${tags[@]}" "$@"
}

build backend --build-context "deploy-templates=${ROOT}/deploy/templates" backend
build frontend frontend

echo
echo "Built:"
for name in backend frontend; do
    docker image inspect "${PREFIX}-${name}:${VERSION}" \
        --format "  ${PREFIX}-${name}:${VERSION}  {{.Id}}  version={{index .Config.Labels \"org.pinpoint311.app.version\"}} db_revision={{index .Config.Labels \"org.pinpoint311.app.db_revision\"}}"
done
cat <<EOF

To run this build, put these in the instance's release.lock (local tags; a
published release pins @sha256 digests instead -- see docs/RELEASES.md):

PINPOINT_VERSION=${VERSION}
BACKEND_IMAGE=${PREFIX}-backend:${VERSION}
FRONTEND_IMAGE=${PREFIX}-frontend:${VERSION}
EOF
