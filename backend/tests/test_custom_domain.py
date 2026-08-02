"""Setting the town's domain must not take the site down with it.

Saving a custom domain regenerated the whole Caddyfile from a template inside
the request handler. It never worked -- and that was the good news. If the
reload it attempted had ever succeeded, the generated file would have:

  * proxied the frontend to `frontend:5173`, the Vite dev server, so every page
    returned 502 while the domain looked correctly configured
  * dropped the entire header block: Content-Security-Policy, HSTS,
    X-Content-Type-Options, the `-Server` suppression
  * dropped `import /etc/caddy/tenants/*.caddy`, removing every provisioned
    town tenancy from the reverse proxy
  * dropped the orchestrator panel block

It did not work because the file was written to `PROJECT_ROOT/Caddyfile`
(default `/project/Caddyfile`), which is not the path compose mounts into the
caddy container, and because the reload POST went to `http://caddy:2019` while
Caddy's admin endpoint listens on `localhost:2019` inside its own container
unless told otherwise -- which the shipped Caddyfile never did.

A domain is now one small snippet in the directory Caddy already imports. The
base file keeps owning the routes, the headers and the tenants.
"""

from pathlib import Path

import pytest

from app.services.caddy_config import (
    InvalidDomain, SNIPPET_NAME, describe_reload, normalise_domain, render_snippet,
)

ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "Caddyfile"


# ---- what we will write into a server's config ----

@pytest.mark.parametrize("given,expected", [
    ("township.nj.gov", "township.nj.gov"),
    ("  Township.NJ.gov  ", "township.nj.gov"),
    ("https://township.nj.gov", "township.nj.gov"),
    ("http://township.nj.gov/portal", "township.nj.gov"),
    ("township.nj.gov:8443", "township.nj.gov"),
])
def test_what_an_admin_pastes_is_accepted(given, expected):
    """They paste what is in the address bar. Rejecting a scheme would be
    pedantry aimed at the one person who cannot debug it."""
    assert normalise_domain(given) == expected


@pytest.mark.parametrize("hostile", [
    'town.gov {\n\treverse_proxy evil.example.com\n}\n#',
    "town.gov\n}\n:80 {",
    "town.gov reverse_proxy evil",
    "town.gov{",
    "../../etc/caddy/Caddyfile",
])
def test_a_value_that_is_not_a_hostname_is_refused(hostile):
    """This string goes into a file a web server parses and acts on. A brace or
    a newline is not a domain; it is a directive somebody is trying to add, and
    `reverse_proxy` to a host of their choosing is the obvious one.

    Refused rather than escaped -- there is no legitimate domain containing a
    brace, so there is nothing to preserve.
    """
    with pytest.raises(InvalidDomain):
        normalise_domain(hostile)


@pytest.mark.parametrize("bad", ["", None, "localhost", "notadomain", "-lead.gov"])
def test_values_that_cannot_get_a_certificate_are_refused(bad):
    with pytest.raises(InvalidDomain):
        normalise_domain(bad)


# ---- what the snippet contains ----

def test_the_snippet_is_one_site_block_and_nothing_else():
    snippet = render_snippet("township.nj.gov")
    assert snippet.count("{") == snippet.count("}")
    assert snippet.count("township.nj.gov {") == 1


def test_the_snippet_reuses_the_shared_site_definition():
    """Routes and headers are defined once, in the base file. If this rendered
    its own copy, a town on a custom domain would drift to a different
    Content-Security-Policy than the same town on the default one."""
    snippet = render_snippet("township.nj.gov")
    assert "import pinpoint_site" in snippet
    assert "Content-Security-Policy" not in snippet


def test_the_frontend_is_not_pointed_at_the_dev_server():
    """`frontend:5173` is Vite. Production is nginx on 80, and getting this
    wrong turns a domain change into a site-wide 502 that reads as a DNS
    problem for as long as it takes somebody to check."""
    snippet = render_snippet("township.nj.gov")
    assert "5173" not in snippet
    assert "frontend:80" in snippet


# ---- the base file still has what the generated one threw away ----

@pytest.fixture(scope="module")
def caddyfile() -> str:
    if not CADDYFILE.exists():
        pytest.skip("Caddyfile not in this checkout")
    return CADDYFILE.read_text()


def test_the_shared_snippet_carries_the_security_headers(caddyfile):
    block = caddyfile[caddyfile.index("(pinpoint_site)"):]
    block = block[:block.index("\n}\n")]
    for header in ("Content-Security-Policy", "Strict-Transport-Security",
                   "X-Content-Type-Options", "-Server"):
        assert header in block, f"{header} is no longer applied to every site"


def test_the_tenants_import_survives(caddyfile):
    """Every provisioned town lives behind this line."""
    assert "import /etc/caddy/tenants/*.caddy" in caddyfile


def test_the_custom_domain_snippet_is_imported_exactly_once(caddyfile):
    """The `*.caddy` glob already matches it. Importing it a second time by
    name defines the site block twice, and Caddy refuses to start on that --
    so the "safe" belt-and-braces import is an outage."""
    assert caddyfile.count(f"import /etc/caddy/tenants/{SNIPPET_NAME}") == 0
    assert caddyfile.count("import /etc/caddy/tenants/") == 1


def test_the_admin_endpoint_is_reachable_from_the_backend(caddyfile):
    """Without this the reload is refused every time, which is exactly the
    symptom: "Caddyfile saved but could not reload Caddy automatically"."""
    assert "admin 0.0.0.0:2019" in caddyfile


def test_the_backend_can_write_where_caddy_reads():
    """The old code wrote to /project/Caddyfile, which nothing mounts into the
    backend container, so the write failed or landed nowhere."""
    compose = (ROOT / "docker-compose.yml").read_text()
    backend = compose[compose.index("\n  backend:"):]
    backend = backend[:backend.index("\n  ", backend.index("environment:"))]
    assert "/etc/caddy/tenants" in backend, (
        "the backend has no mount for the directory Caddy imports"
    )


def test_the_handler_no_longer_rewrites_the_whole_config():
    """The invariant is what the handler *writes*, not what it reads.

    An earlier version of this test asserted the name `caddyfile_content` was
    absent, which was a proxy for "builds a Caddyfile from a template". The
    handler now legitimately reads the base file into that same variable to
    POST it to Caddy's admin API -- so the assertion failed on a correct
    change. Reading the config is fine. Overwriting it is not.
    """
    source = (ROOT / "backend/app/api/system.py").read_text()
    handler = source[source.index('@router.post("/domain/configure")'):]
    handler = handler[:handler.index("\n@router.")]

    # The only thing written is the snippet, into the tenants directory.
    assert "render_snippet(" in handler
    assert 'open(snippet_path, "w")' in handler

    # And nothing opens the base Caddyfile for writing.
    assert 'caddyfile_path, "w"' not in handler, "the base Caddyfile is being overwritten again"
    assert "reverse_proxy" not in handler, "a site block is being built in the handler again"


def test_no_machines_ip_is_baked_into_the_product():
    """`/domain/status` returned a hardcoded IP of one particular server, which
    is the address a town is told to point its DNS at -- and wrong for every
    self-hosted deployment."""
    source = (ROOT / "backend/app/api/system.py").read_text()
    assert "132.226.32.116" not in source


# ---- what the administrator is told ----

def test_a_failed_reload_says_so_and_names_the_command():
    told = describe_reload(False, "the proxy could not be reached (ConnectError)")
    assert told["reloaded"] is False
    assert "not serving that name yet" in told["message"]
    assert told["next_step"] == "docker compose restart caddy"


def test_a_successful_reload_does_not_ask_for_a_restart():
    """The old response ended with "Please run: docker-compose restart caddy"
    whether or not that was the problem, and reported `partial` for a change
    that had in fact done nothing."""
    told = describe_reload(True)
    assert told["reloaded"] is True and told["next_step"] is None
