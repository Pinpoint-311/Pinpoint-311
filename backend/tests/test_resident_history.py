"""Resident history: keyed fingerprints and the safeguards around the lookup.

The feature lets staff see a resident's earlier reports. For a government
deployment the properties that matter are what it does NOT do: store PII in a
searchable form, match scrubbed records, show reports outside a clerk's
departments, return more than the minimum, or run unaudited.
"""
import inspect

import pytest

from app.core import resident_index as ri


@pytest.fixture
def fixed_key(monkeypatch):
    monkeypatch.setattr(ri, "_key", b"k" * 32)
    yield
    ri.reset_key_cache()


# ---- normalisation ----------------------------------------------------------

def test_email_is_normalised_before_fingerprinting():
    assert ri.normalise_email("  Jane.Doe@Example.ORG ") == "jane.doe@example.org"
    assert ri.normalise_email("") is None
    assert ri.normalise_email("not-an-email") is None


def test_full_name_only():
    """One part alone would group every 'John' in town under one fingerprint."""
    assert ri.normalise_name("  Jane ", "Q  Doe") == "jane q doe"
    assert ri.normalise_name("Jane", None) is None
    assert ri.normalise_name(None, None) is None


def test_retention_sentinels_have_no_fingerprint():
    """The scrub rewrites fields to these, so a scrubbed report cannot be linked."""
    assert ri.normalise_email("archived-12@retention.local") is None
    assert ri.normalise_name("[ARCHIVED]", "[ARCHIVED]") is None
    assert ri.normalise_name("Jane", "[ARCHIVED]") is None


# ---- fingerprints -----------------------------------------------------------

def test_same_email_same_fingerprint(fixed_key):
    assert ri.email_index("Jane@Example.org") == ri.email_index(" jane@example.org")
    assert ri.email_index("jane@example.org") != ri.email_index("john@example.org")


def test_fingerprint_is_not_the_value(fixed_key):
    fp = ri.email_index("jane@example.org")
    assert "jane" not in fp and len(fp) == 64


def test_email_and_name_fingerprints_are_domain_separated(fixed_key):
    """A name that happens to equal an email string must not collide with it."""
    assert ri._mac(b"email", "a b") != ri._mac(b"name", "a b")


def test_search_box_name_splits_first_and_rest(fixed_key):
    assert ri.name_index_from_full("Jane  Q Doe") == ri.name_index("Jane", "Q Doe")
    assert ri.name_index_from_full("Jane") is None


def test_the_key_is_random_and_wrapped_not_derived_from_secret_key():
    src = inspect.getsource(ri._load_or_create_key)
    assert "os.urandom(32)" in src
    assert "encrypt_pii(" in src, "the key must be wrapped by the PII envelope / KMS"
    assert "secret_key" not in src.lower()


# ---- the model keeps fingerprints in step -----------------------------------

def test_setting_and_scrubbing_a_record_updates_its_fingerprints(fixed_key):
    from app.models import ServiceRequest
    from app.services.retention_scrub import apply_scrub

    rec = ServiceRequest(first_name="Jane", last_name="Doe", email="jane@example.org")
    assert rec.resident_email_index == ri.email_index("jane@example.org")
    assert rec.resident_name_index == ri.name_index("Jane", "Doe")
    assert rec.pii_index_version == ri.VERSION

    apply_scrub(rec, ["name", "email"])
    assert rec.resident_email_index is None
    assert rec.resident_name_index is None


def test_a_key_service_outage_does_not_fail_the_submission(monkeypatch):
    """An optional staff feature must never stop a resident filing a report."""
    from app.models import ServiceRequest

    def boom():
        raise ri.IndexKeyUnavailable("kms down")

    monkeypatch.setattr(ri, "_get_key", boom)
    rec = ServiceRequest(email="jane@example.org")
    assert rec.resident_email_index is None
    assert rec.pii_index_version is None, "left for the backfill to retry"


# ---- the API's safeguards ---------------------------------------------------

def _src(fn):
    return inspect.getsource(fn)


@pytest.fixture(autouse=True)
def _needs_app_stack(request):
    """CI installs only the crypto and HTTP libraries; tests touching the
    models or the API skip there rather than fail collection."""
    if request.node.name.startswith(("test_setting_and_scrubbing", "test_a_key_service",
                                     "test_the_module_defaults")):
        pytest.importorskip("sqlalchemy")
    if request.node.name.startswith(("test_both_endpoints", "test_results_are", "test_only_minimal",
                                     "test_every_lookup", "test_the_audit_never", "test_search_is_a_post",
                                     "test_the_card_matches")):
        pytest.importorskip("fastapi.routing")


def test_both_endpoints_are_off_unless_the_module_is_on():
    from app.api import resident_history as rh
    for fn in (rh.history_for_request, rh.search_by_resident):
        assert "_module_enabled(db)" in _src(fn) and "_off()" in _src(fn)


def test_the_module_defaults_off():
    from app.models import SystemSettings
    assert SystemSettings.__table__.c.modules.default.arg["resident_history"] is False


def test_results_are_department_scoped():
    from app.api import resident_history as rh
    assert "department_scope_filters(" in _src(rh._matches)
    assert "scoped_request(" in _src(rh.history_for_request)


def test_only_minimal_fields_are_returned():
    from app.api.resident_history import HistoryItem
    assert set(HistoryItem.model_fields) == {
        "service_request_id", "service_name", "status", "requested_datetime"}


def test_every_lookup_is_audited_and_fails_closed():
    from app.api import resident_history as rh
    for fn in (rh.history_for_request, rh.search_by_resident):
        src = _src(fn)
        assert "record_admin_action(" in src
        assert "if not recorded:" in src and "_audit_failed()" in src
        # Audited before anything is returned.
        assert src.index("record_admin_action(") < src.rindex("return ")


def test_the_audit_never_carries_the_searched_value():
    from app.api import resident_history as rh
    src = _src(rh.search_by_resident)
    details = src[src.index("details={"):src.index("}", src.index("details={"))]
    assert "email" not in details.replace('"searched_by"', "")
    assert "name" not in details.replace('"searched_by"', "")


def test_search_is_a_post_so_pii_stays_out_of_urls():
    from app.api.resident_history import router
    methods = {r.path: r.methods for r in router.routes}
    assert methods["/search"] == {"POST"}


def test_the_card_matches_by_email_only():
    """Two residents can share a name; the card must not mix them up."""
    from app.api import resident_history as rh
    src = _src(rh.history_for_request)
    assert "resident_email_index" in src and "resident_name_index" not in src
