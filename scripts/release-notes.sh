#!/usr/bin/env bash
#
# Print the release notes for a tag, as Markdown, on stdout.
#
#   scripts/release-notes.sh v1.8.0
#
# Used by both release pipelines (.github/workflows/build-publish.yml and
# .gitlab-ci.yml) so the two hosts publish the same text.
#
# If CHANGELOG.md has a section for the tag -- a heading such as
# "## v1.8.0", "## 1.8.0", "## [1.8.0]" or "## [1.8.0] - 2026-10-18" -- that
# section is the notes. Otherwise they are the commit subjects since the
# previous v* tag. Either way a reviewer sees what changed before approving the
# upgrade.

set -euo pipefail

TAG="${1:?usage: release-notes.sh <tag>}"
VERSION="${TAG#v}"
ROOT="$(git rev-parse --show-toplevel)"

if [ -f "$ROOT/CHANGELOG.md" ]; then
    SECTION="$(awk -v ver="$VERSION" '
        function is_heading(line) { return line ~ /^##[^#]/ }
        function names_version(line,   v) {
            v = ver; gsub(/\./, "\\.", v)
            return line ~ ("^##[[:space:]]*\\[?v?" v "\\]?([[:space:]]|$)")
        }
        in_section && is_heading($0) { exit }
        in_section { print; next }
        is_heading($0) && names_version($0) { in_section = 1 }
    ' "$ROOT/CHANGELOG.md")"
    if [ -n "$(printf '%s' "$SECTION" | tr -d '[:space:]')" ]; then
        printf '%s\n' "$SECTION"
        exit 0
    fi
fi

PREV="$(git describe --tags --abbrev=0 --match 'v*' "${TAG}^" 2>/dev/null || true)"
if [ -n "$PREV" ]; then
    echo "Changes since ${PREV}:"
    RANGE="${PREV}..${TAG}"
else
    echo "Changes:"
    RANGE="$TAG"
fi
echo
git log --no-merges --pretty='- %s (%h)' "$RANGE"
