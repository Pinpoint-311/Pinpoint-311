"""Nothing on a town's server updates itself.

A Watchtower container shipped in the default compose file, pulling new images
at 3am daily. The README described it as optional; no `profiles:` key made it
so, and `docker compose up -d` started it.

Its scope was also wrong. `WATCHTOWER_LABEL_ENABLE` was unset, so it acted on
every container it could pull rather than on the application. On a source-built
install the app services are `build:` with no registry, so Watchtower could not
touch them -- but PostGIS, Redis and Caddy are pulled by tag, so those upgraded
unattended. Exactly inverted: the database engine changed itself overnight on a
municipal server while the application stayed put.

Removed. Updates are now something a person decides to do, which is also the
answer a state reviewer wants to the question "can anyone outside our
organisation change what is running here".

This test exists because the container is one line to add back, and it would be
added back for a good reason -- unattended security patches are genuinely
valuable for a town with no IT. If that argument wins later, it needs a profile
and a label scope, not a re-paste.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Globbed rather than listed. The list named three files and skipped any that
# did not exist, so deleting one left a dead entry and adding one was never
# checked at all -- demo-orchestrator/docker-compose-demo.yml, which the
# orchestrator hands to every instance it provisions, was never in it.
COMPOSE = sorted(ROOT.glob("docker-compose*.yml")) + sorted(ROOT.glob("*/docker-compose*.yml"))


def test_the_compose_files_were_actually_found():
    """A glob that matches nothing would make the next test quietly vacuous."""
    assert len(COMPOSE) >= 2, f"expected the app's compose files under {ROOT}, found {COMPOSE}"


def test_no_compose_file_ships_an_auto_updater():
    for path in COMPOSE:
        # Comments are prose, not services: one of these files opens by saying
        # "no Watchtower", and a file documenting its own absence must not read
        # as shipping one.
        text = "\n".join(
            line for line in path.read_text().lower().splitlines()
            if not line.strip().startswith("#")
        )
        assert "watchtower" not in text, (
            f"{path.name} ships an auto-updater. If this is deliberate it needs a "
            f"compose profile so it is genuinely opt-in, and WATCHTOWER_LABEL_ENABLE "
            f"with labels on the app services only -- otherwise it upgrades Postgres."
        )


def test_the_readme_tells_a_town_how_to_update_instead():
    """Removing the automatic path without documenting the manual one would
    leave towns on old, vulnerable versions -- worse than what was there."""
    readme = (ROOT / "README.md").read_text()
    assert "docker compose pull" in readme
    assert "Take a backup first" in readme
