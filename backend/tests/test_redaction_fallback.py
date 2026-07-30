"""A detector that cannot answer must not look like a photo with nobody in it.

Every cloud detector returns an empty result when it has no credentials, and so
does a photo of an empty street. `vision_annotate` says as much in its own
docstring -- "callers can treat 'no credentials' the same as 'nothing
detected'." For content moderation that conflation is tolerable. For redaction
it is the difference between an empty street and somebody's face on a municipal
website.

`redact_image` had already named this: "a town whose Vision credentials quietly
expired will publish unblurred faces and only find out from the admin console",
and concluded the fix was to surface it loudly. Surfacing is not the best
available answer. Falling back to the detector that needs no credentials is --
it blurs less well than the cloud, but it blurs, and the choice is no longer
between publishing a face and refusing the resident's report.
"""

import asyncio

import pytest

pytest.importorskip("cryptography")

from app.services import image_redaction as ir


def _effective(usable):
    """effective_provider() with a given set of working detectors."""
    async def _fake(provider):
        return provider in usable

    original = ir._usable
    ir._usable = _fake
    try:
        return asyncio.run(ir.effective_provider(_effective.selected))
    finally:
        ir._usable = original


def _run(selected, usable):
    _effective.selected = selected
    return _effective(usable)


def test_a_cloud_detector_without_credentials_degrades_rather_than_disappearing():
    """The bug. Azure selected, no keys entered -- previously every photo was
    stored unblurred and the card stayed green."""
    provider, degraded_from = _run("azure", usable={"local"})
    assert provider == "local"
    assert degraded_from == "azure"


@pytest.mark.parametrize("cloud", ["google", "aws", "azure"])
def test_every_cloud_detector_degrades_the_same_way(cloud):
    provider, degraded_from = _run(cloud, usable={"local"})
    assert (provider, degraded_from) == ("local", cloud)


def test_a_working_detector_is_left_alone():
    """The fallback must not shadow a correctly configured cloud detector --
    it finds more than OpenCV does, which is why a town paid for it."""
    provider, degraded_from = _run("google", usable={"google", "local"})
    assert provider == "google"
    assert degraded_from is None


def test_local_selected_and_working_is_not_a_degradation():
    provider, degraded_from = _run("local", usable={"local"})
    assert provider == "local"
    assert degraded_from is None


def test_when_nothing_can_blur_it_is_reported_as_such():
    """OpenCV missing from the image too. The photo is still kept -- dropping it
    punishes the resident for the town's problem -- but this must not be
    reported as "we looked and there was nobody there"."""
    provider, degraded_from = _run("azure", usable=set())
    assert degraded_from == provider, "caller detects total failure by this equality"


def test_redact_image_distinguishes_no_detector_from_no_detections():
    """Everything downstream reads skipped_reason. `no-detections` means we
    looked; `no-detector` means we could not. Collapsing them is how the
    original bug stayed invisible."""
    import inspect
    source = inspect.getsource(ir.redact_image)
    assert '"no-detector"' in source
    assert '"no-detections"' in source


def test_the_fallback_is_actually_used_by_the_redaction_path():
    """A helper nothing calls is a comment."""
    import inspect
    assert "effective_provider(" in inspect.getsource(ir.redact_image)


def test_the_health_check_reports_a_degraded_detector():
    """Degrading contains the harm; it does not make it fine. A town paying for
    Azure and silently running on OpenCV is getting worse detection than it
    thinks, and should be told."""
    from app.services import proactive_health as ph
    import inspect

    source = inspect.getsource(ph._redaction_check)
    assert "degraded_from" in source
    assert '"warning"' in source
    assert '"critical"' in source
    assert "_redaction_check()" in inspect.getsource(ph.collect_checks)
