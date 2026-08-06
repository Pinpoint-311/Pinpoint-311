"""What the buttons on an integration card actually do.

Four endpoints whose behaviour did not match their label:

  * "Check for updates" enqueued the *global* beat tasks, so pressing it on one
    card polled every vendor the town uses -- and reported 503 in a case where a
    job had already started;
  * "Sync assets now" granted the one-off by permanently setting
    config["sync_assets"], enrolling the integration in the nightly job from one
    click, with nothing on screen saying so and no way back;
  * the inbound webhook matched its token inside a SQL predicate, ignored the
    sync_direction the admin chose, rate-limited per source IP where one vendor
    egress address serves many towns, and could not be rotated at all;
  * generic_rest claimed comments, documents and assets whatever the admin had
    configured, so the beat polled endpoints that were never there.
"""

from pathlib import Path

import pytest

from app.integrations.registry import PLATFORM_CATALOG, build_connector

BACKEND = Path(__file__).resolve().parents[1]


def api_source() -> str:
    return (BACKEND / "app/api/integrations.py").read_text()


def endpoint(name: str) -> str:
    """The body of one endpoint, up to the next route."""
    source = api_source()
    block = source[source.index(f"async def {name}("):]
    marker = "\n@router."
    return block[:block.index(marker)] if marker in block else block


def tasks():
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("celery")
    import app.tasks.integrations as module
    return module


# ---------------------------------------------------------------------------
# 3.1 "Check for updates" means this connection
# ---------------------------------------------------------------------------

def test_the_pull_tasks_accept_one_integration():
    module = tasks()
    import inspect

    for task in (module.pull_integration_updates, module.pull_integration_comments,
                 module.sync_integration_assets):
        # Celery wraps the function; the signature it exposes is the real one.
        params = inspect.signature(task.run if hasattr(task, "run") else task).parameters
        assert "integration_id" in params, task
        assert params["integration_id"].default is None, f"{task} is no longer a beat task"


def test_the_pull_tasks_filter_on_it():
    source = (BACKEND / "app/tasks/integrations.py").read_text()
    for task_name in ("pull_integration_updates", "pull_integration_comments",
                      "sync_integration_assets"):
        block = source[source.index(f"def {task_name}("):]
        block = block[:block.index("@celery_app.task", 1)] if "@celery_app.task" in block[1:] else block
        assert "if integration_id is not None:" in block, task_name
        assert "IntegrationConfig.id == integration_id" in block, task_name


def test_sync_now_passes_the_clicked_integration():
    block = endpoint("trigger_sync")
    assert "enqueue(pull_integration_updates, integration.id)" in block
    assert "enqueue(pull_integration_comments, integration.id)" in block


def test_sync_now_enqueues_both_before_judging_either():
    """`enqueue(a) or enqueue(b)` short-circuited: a first failure never queued
    the second, and a second failure returned 503 -- whose text is "this job did
    not start. Nothing has been changed." -- after the first job had started."""
    block = endpoint("trigger_sync")
    assert "or not enqueue" not in block
    assert 'if not any(started.values()):' in block
    assert 'if all(started.values()):' in block
    # The unqualified claim is the one guarded by every job having gone. Anchored
    # on the returned value: a comment above this endpoint quotes the phrase, and
    # prose about a behaviour is not the behaviour.
    assert block.index('if all(started.values()):') < block.index('"message": "Sync started"')


def test_a_total_queue_failure_is_still_a_503():
    block = endpoint("trigger_sync")
    assert "status_code=503" in block


# ---------------------------------------------------------------------------
# 3.2 A one-off is a one-off
# ---------------------------------------------------------------------------

def test_the_one_off_asset_sync_does_not_rewrite_config():
    """One click used to opt the integration into the nightly beat job forever."""
    block = endpoint("trigger_asset_sync")
    assert '"sync_assets": True' not in block
    assert "integration.config =" not in block
    assert "enqueue(sync_integration_assets, integration.id)" in block


def test_a_named_asset_sync_runs_without_the_nightly_flag():
    """Otherwise removing the config write would just make the button do nothing:
    the task filtered on the same flag the endpoint used to set."""
    source = (BACKEND / "app/tasks/integrations.py").read_text()
    block = source[source.index("def sync_integration_assets("):]
    assert 'if integration_id is None and not _flag(config, "sync_assets"):' in block


@pytest.mark.parametrize("platform", [p for p, meta in PLATFORM_CATALOG.items()
                                      if "assets" in meta.get("capabilities", [])])
def test_every_asset_capable_platform_offers_sync_assets_as_a_field(platform):
    """The opt-in has to be reachable somewhere an admin can see and undo it.
    Removing the implicit one without adding an explicit one would leave nightly
    asset sync switchable only by editing the database."""
    keys = {f["key"] for f in PLATFORM_CATALOG[platform]["config_fields"]}
    assert "sync_assets" in keys, platform


def test_the_endpoint_refuses_when_this_configuration_has_no_asset_endpoint():
    """The catalog says what the platform can do; the connector says what this
    configuration does. Answering "Asset sync started" for a run the task will
    skip is the same lie in a different place."""
    block = endpoint("trigger_asset_sync")
    assert "connector.capabilities" in block


# ---------------------------------------------------------------------------
# 3.3 The inbound webhook
# ---------------------------------------------------------------------------

def test_the_webhook_token_is_not_compared_in_sql():
    """A SQL equality on the token makes the comparison the database's
    byte-by-byte one, on an unauthenticated endpoint anybody can time."""
    block = endpoint("integration_webhook")
    assert "IntegrationConfig.webhook_token == token" not in block
    assert "compare_digest" in block


def test_a_push_only_connection_refuses_inbound_records():
    """Otherwise the sync_direction the admin chose does nothing here, and a
    vendor can open service requests in a town that never asked them to."""
    block = endpoint("integration_webhook")
    assert 'integration.sync_direction == "push"' in block
    assert "status_code=403" in block


class _RateReq:
    """Just what _webhook_rate_key reads: the path and the peer address."""

    def __init__(self, path, host="203.0.113.9"):
        self.url = type("U", (), {"path": path})()
        self.client = type("C", (), {"host": host})()


def test_the_webhook_is_rate_limited_per_connection_not_per_address_alone():
    """One vendor's egress IP serves every town on their platform, so a bucket
    keyed on the IP alone lets a busy neighbour exhaust ours. The token digest
    keeps two connections behind one NAT in separate buckets."""
    source = api_source()
    assert "key_func=_webhook_rate_key" in source

    pytest.importorskip("fastapi")
    from app.api.integrations import _webhook_rate_key

    one = _webhook_rate_key(_RateReq("/api/integrations/webhook/accela/tok-aaa"))
    two = _webhook_rate_key(_RateReq("/api/integrations/webhook/accela/tok-bbb"))
    assert one != two, "two connections share a rate-limit bucket"
    assert one == _webhook_rate_key(_RateReq("/api/integrations/webhook/accela/tok-aaa"))
    assert "accela" in one


def test_the_rate_key_carries_the_source_address():
    """The endpoint is unauthenticated and the token used to be the whole key,
    so the bucket name was entirely attacker-chosen: every wrong guess opened a
    brand-new bucket, invisible to the per-address accounting everything else
    on this API gets. With the address composed in, a guessing source is
    subject to address-keyed limits and attribution like any other client --
    and a real vendor's bucket cannot be exhausted by someone who knows (or
    guesses) the same token from elsewhere."""
    pytest.importorskip("fastapi")
    from app.api.integrations import _webhook_rate_key

    attacker = "198.51.100.7"
    guess = _webhook_rate_key(_RateReq("/api/integrations/webhook/accela/guess-1", attacker))
    assert attacker in guess
    # Same token from a different source is a different bucket: one noisy
    # sender cannot starve the real vendor of its budget.
    other = _webhook_rate_key(_RateReq("/api/integrations/webhook/accela/guess-1", "192.0.2.1"))
    assert other != guess


def test_the_rate_limit_key_does_not_carry_the_token():
    """The key reaches the limiter's store and its log lines."""
    pytest.importorskip("fastapi")
    from app.api.integrations import _webhook_rate_key

    req = _RateReq("/api/integrations/webhook/accela/s3cr3t-token")
    assert "s3cr3t-token" not in _webhook_rate_key(req)


def test_the_webhook_token_can_be_rotated():
    """It travels in a URL path -- proxy access logs, the vendor's own outbound
    logs, any screenshot of the setup page. With no rotation, a token disclosed
    that way was disclosed permanently."""
    source = api_source()
    assert "regenerate-webhook-token" in source
    block = endpoint("regenerate_webhook_token")
    assert "pysecrets.token_urlsafe" in block
    # Recorded, because the vendor's next post will start failing and somebody
    # will need to know why.
    assert "webhook_token_rotated" in block
    # And said out loud, rather than left to be discovered from a silent gap.
    assert "message" in block


# ---------------------------------------------------------------------------
# 3.4 generic_rest claims only what it was configured for
# ---------------------------------------------------------------------------

def generic(**config):
    return build_connector("generic_rest", {"base_url": "https://api.test/v1", **config},
                           {"api_key": "k"})


def test_a_bare_generic_connector_claims_no_optional_endpoints():
    """Unconditional claims made the beat poll paths the vendor never had: a 404
    into integration_sync_logs every fifteen minutes, so the Activity drawer
    showed a working connector as permanently failing."""
    capabilities = generic().capabilities
    assert capabilities == {"test", "push", "push_status", "pull"}
    for absent in ("comments", "documents", "assets", "work_orders"):
        assert absent not in capabilities


@pytest.mark.parametrize("config_key,capability", [
    ("comments_path", "comments"),
    ("documents_path", "documents"),
    ("assets_path", "assets"),
])
def test_configuring_a_path_claims_its_capability(config_key, capability):
    assert capability in generic(**{config_key: "/x"}).capabilities


@pytest.mark.parametrize("config_key,capability", [
    ("comments_path", "comments"),
    ("documents_path", "documents"),
    ("assets_path", "assets"),
])
def test_a_blank_path_is_not_a_configured_one(config_key, capability):
    """The wizard submits empty strings for untouched fields."""
    assert capability not in generic(**{config_key: ""}).capabilities
    assert capability not in generic(**{config_key: "   "}).capabilities


def test_work_orders_is_claimed_when_a_field_is_mapped():
    """Not an endpoint -- the fields ride on records the pull already fetches --
    so the signal is whether the admin mapped any of them."""
    assert "work_orders" not in generic().capabilities
    assert "work_orders" in generic(assigned_to_field="AssignedTo").capabilities
    assert "work_orders" in generic(resolution_field="Resolution").capabilities


def test_the_core_capabilities_never_depend_on_optional_config():
    """Push and pull have real defaults and are the reason to connect at all;
    losing them to a blank optional field would be a worse bug than the one
    being fixed."""
    for capability in ("test", "push", "push_status", "pull"):
        assert capability in generic().capabilities
        assert capability in generic(comments_path="", assets_path="").capabilities


def test_the_paths_are_offered_as_wizard_fields():
    """Deriving capabilities from config that the wizard never asks for would
    make comments and asset sync unreachable rather than honest."""
    keys = {f["key"] for f in PLATFORM_CATALOG["generic_rest"]["config_fields"]}
    for key in ("comments_path", "documents_path", "assets_path"):
        assert key in keys
    help_text = PLATFORM_CATALOG["generic_rest"]["field_help"]
    for key in ("comments_path", "documents_path", "assets_path"):
        assert key in help_text, f"{key} has no plain-language hint"


def test_the_purpose_built_connectors_are_unchanged():
    """Accela and SeeClickFix are written against one documented API each, so
    their capabilities are a fact about that API, not about configuration."""
    accela = build_connector("accela", {"agency_name": "A"}, {})
    assert {"comments", "documents", "assets"} <= accela.capabilities
    scf = build_connector("civicplus", {}, {})
    assert "comments" in scf.capabilities
