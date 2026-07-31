"""An in-process sampler cannot see its own outage, so it must say so.

The failure mode is specific and quiet: the sampler runs inside the backend, so
a backend outage produces *no rows* rather than rows saying "down". Dividing
healthy samples by total samples then returns a higher number the worse the
outage was, and 100% over a day the service spent mostly dead is a figure
somebody will put in front of a council.
"""

from datetime import timedelta


from app.services import uptime as U


class TestTheOutageItCannotSee:
    def test_a_full_day_of_samples_is_trustworthy(self):
        s = U.summarise(total=288, healthy=288, hours=24)
        assert s["uptime_percent"] == 100.0
        assert s["reliable"] is True
        assert s["missed_checks"] == 0

    def test_an_outage_shows_up_as_missing_checks_not_as_downtime(self):
        """Twelve samples in a day means the server was up for about an hour of
        it. The naive figure for that is 100%."""
        s = U.summarise(total=12, healthy=12, hours=24)
        assert s["uptime_percent"] == 100.0      # what the old maths returned
        assert s["reliable"] is False            # and what stops it being quoted
        assert s["missed_checks"] == 276
        assert s["coverage_percent"] < 5

    def test_the_sentence_says_the_server_was_probably_down(self):
        text = U.describe(U.summarise(total=12, healthy=12, hours=24))
        assert "expected" in text
        assert "server itself was down" in text

    def test_a_service_that_really_was_down_still_reads_as_down(self):
        """The caveat must not swallow a genuine failure."""
        s = U.summarise(total=288, healthy=144, hours=24)
        assert s["uptime_percent"] == 50.0
        assert s["reliable"] is True

    def test_nothing_measured_claims_nothing(self):
        s = U.summarise(total=0, healthy=0, hours=24)
        assert s["reliable"] is False
        assert U.describe(s) == "Not measured over this period."

    def test_coverage_cannot_exceed_the_period(self):
        """Two app replicas each run their own sampler, so the row count can
        exceed what one sampler would produce. That is not 200% coverage."""
        s = U.summarise(total=600, healthy=600, hours=24)
        assert s["coverage_percent"] == 100.0


class TestTheStatusMapsThatDisagreed:
    def test_a_switched_off_service_is_not_downtime(self):
        """The background sampler counted "disabled" as healthy and the manual
        "Check now" button did not, so pressing the button on the health page
        recorded a switched-off service as down and dented its uptime. Looking
        at the number made the number worse."""
        assert U.uptime_status("disabled") == "healthy"

    def test_the_other_benign_outcomes_agree_too(self):
        for status in ("healthy", "configured", "fallback"):
            assert U.uptime_status(status) == "healthy"

    def test_a_real_failure_is_still_down(self):
        for status in ("down", "error", "unhealthy", "", "misconfigured"):
            assert U.uptime_status(status) == "down"

    def test_there_is_only_one_such_map_left(self):
        """Two lists in two files is how they diverged in the first place."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "uptime.py":
                continue
            if re.search(r'in \[\s*"healthy",\s*"configured"', path.read_text()):
                offenders.append(str(path.relative_to(root)))
        assert not offenders, f"a second healthy-status list has appeared: {offenders}"


class TestExpectedSamples:
    def test_derived_from_the_interval_rather_than_hardcoded(self):
        assert U.expected_samples(24, timedelta(minutes=5)) == 288
        assert U.expected_samples(1, timedelta(minutes=5)) == 12
        assert U.expected_samples(24, timedelta(minutes=1)) == 1440

    def test_a_nonsense_interval_does_not_divide_by_zero(self):
        assert U.expected_samples(24, timedelta(0)) == 0
        assert U.summarise(total=5, healthy=5, hours=24, interval=timedelta(0))["coverage_percent"] == 0.0


class TestWhatIsSampled:
    """The five-minute sampler and the connector sweep must not overlap.

    They did: the sampler named Auth0, Vertex AI and Google Translate, so an
    Azure town accumulated a month of history for three services it does not
    use. Widening the list is the wrong fix -- the connector sweep is daily
    *because* each external check costs a call to a town's own paid account,
    and eight of them every five minutes is about 2,300 calls a day.
    """

    def _lists(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        out = {}
        for name in ("main.py", "api/health.py"):
            text = (root / name).read_text()
            m = re.search(r"services_to_check = \[(.*?)\]", text, re.S)
            out[name] = set(re.findall(r'\("([a-z_]+)",', m.group(1))) if m else set()
        return out

    def test_no_external_vendor_is_sampled_every_five_minutes(self):
        expensive = {"auth0", "vertex_ai", "translation_api", "kms", "secret_store"}
        for name, sampled in self._lists().items():
            assert not (sampled & expensive), (
                f"{name} samples paid external APIs every five minutes: {sampled & expensive}"
            )

    def test_the_manual_button_records_the_same_series_as_the_sampler(self):
        """When they differed, pressing "Check now" wrote series the sampler
        never maintained, which then aged out of the graph on their own."""
        lists = self._lists()
        assert lists["main.py"] == lists["api/health.py"], lists

    def test_something_is_still_sampled(self):
        assert self._lists()["main.py"], "the uptime series has nothing in it"
