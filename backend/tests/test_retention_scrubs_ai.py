"""What a retention run removes, and what it is honest to call it.

Three problems, reported together.

The AI summary is the description in different words, so clearing one and
keeping the other is redaction that leaves behind the thing it was meant to
remove -- where a resident put a name or a phone number in the description, the
model repeated it.

The list of what gets removed was fixed in code, deciding for every town what
its own counsel and its state's records law are supposed to decide.

And it was called anonymisation. Anonymising means removing what ties data to a
person; blanking the description of a pothole report is redaction. They are not
interchangeable words when the difference is what a town tells a judge.
"""

import pytest

from app.services import retention_scrub as S


class Rec:
    def __init__(self, **kw):
        self.id = 7
        self.first_name = "John"; self.last_name = "Smith"
        self.email = "john@example.com"; self.phone = "555-0143"
        self.description = "Pothole outside 12 Elm St, call me on 555-0143"
        self.staff_notes = "Spoke to Mr Smith"
        self.media_urls = ["a.jpg"]
        self.address = "12 Elm St"; self.lat = 40.8; self.long = -74.2; self.location = "POINT(...)"
        self.ai_analysis = None; self.vertex_ai_summary = None
        self.vertex_ai_classification = "pothole"
        for k, v in kw.items():
            setattr(self, k, v)


REAL_ANALYSIS = {
    "priority_score": 8.0,
    "priority_justification": "Reported by John Smith, 12 Elm St, reachable on 555-0143.",
    "qualitative_analysis": "The resident says their child cycles past it.",
    "quantitative_metrics": {"estimated_severity": "high"},
    "recommended_response_time": "24h",
    "safety_flags": ["child_safety"],
    "_error": "provider rejected prompt: 'John Smith at 12 Elm St reports...'",
}


class TestTheAiLeak:
    def test_the_free_text_the_model_wrote_is_removed(self):
        r = Rec(ai_analysis=dict(REAL_ANALYSIS))
        S.apply_scrub(r, ["ai_analysis"])
        blob = repr(r.ai_analysis)
        for leaked in ("John Smith", "12 Elm St", "555-0143", "child"):
            assert leaked not in blob, f"{leaked!r} survived"

    def test_the_generated_summary_goes_too(self):
        r = Rec(vertex_ai_summary="John Smith reports a pothole outside 12 Elm St.")
        S.apply_scrub(r, ["ai_analysis"])
        assert r.vertex_ai_summary is None

    def test_the_statistics_survive(self):
        r = Rec(ai_analysis=dict(REAL_ANALYSIS))
        S.apply_scrub(r, ["ai_analysis"])
        assert r.ai_analysis["priority_score"] == 8.0
        assert r.ai_analysis["quantitative_metrics"]["estimated_severity"] == "high"
        assert r.vertex_ai_classification == "pothole"

    def test_it_is_an_allow_list_not_a_strip_list(self):
        r = Rec(ai_analysis={"invented_next_year": "John Smith", "priority_score": 1})
        S.apply_scrub(r, ["ai_analysis"])
        assert "invented_next_year" not in r.ai_analysis

    def test_a_non_dict_analysis_is_discarded_whole(self):
        r = Rec(ai_analysis="John Smith reports a pothole")
        S.apply_scrub(r, ["ai_analysis"])
        assert r.ai_analysis is None


class TestTheTownChooses:
    def test_only_what_was_asked_for_is_cleared(self):
        """Removing "a bit more, to be safe" is how a town loses the
        public-records index it is legally obliged to keep."""
        r = Rec()
        S.apply_scrub(r, ["phone"])
        assert r.phone is None
        assert r.description.startswith("Pothole")
        assert r.first_name == "John"
        assert r.address == "12 Elm St"

    def test_never_configured_means_what_it_did_before(self):
        """A town upgrading into this feature must not have its next run start
        removing more, or less, than yesterday's."""
        r = Rec(ai_analysis=dict(REAL_ANALYSIS))
        done = S.apply_scrub(r, None)
        assert set(done) == {"name", "email", "phone", "description", "staff_notes",
                             "media", "ai_analysis"}
        assert r.address == "12 Elm St"
        assert r.lat == 40.8

    def test_an_empty_choice_is_honoured_rather_than_defaulted(self):
        """Deliberately empty is a real answer -- it goes with a delete-mode
        policy -- and quietly substituting the defaults would destroy data
        somebody had chosen to keep."""
        r = Rec()
        assert S.apply_scrub(r, []) == []
        assert r.first_name == "John"

    def test_location_is_two_choices_not_one(self):
        r = Rec()
        S.apply_scrub(r, ["address"])
        assert r.address is None and r.lat == 40.8

    def test_clearing_the_pin_clears_the_geometry_with_it(self):
        """Leaving PostGIS holding the point after the columns are blank puts
        the record back on a map drawn from geometry."""
        r = Rec()
        S.apply_scrub(r, ["coordinates"])
        assert r.lat is None and r.long is None and r.location is None

    def test_a_made_up_field_is_ignored(self):
        r = Rec()
        assert S.apply_scrub(r, ["not_a_field", "phone"]) == ["phone"]

    def test_duplicates_do_not_double_report(self):
        assert S.normalise_fields(["phone", "phone"]) == ["phone"]

    def test_every_catalog_entry_is_actionable(self):
        """A checkbox that changes nothing when ticked is worse than no
        checkbox: it reads as a promise. `comments` is the one exception --
        another table, handled by the caller."""
        for field in S.SCRUB_FIELDS:
            if field["id"] == "comments":
                continue
            r = Rec(ai_analysis=dict(REAL_ANALYSIS))
            assert S.apply_scrub(r, [field["id"]]) == [field["id"]], field["id"]

    def test_the_defaults_are_what_the_fixed_list_used_to_be(self):
        assert set(S.DEFAULT_FIELDS) == {"name", "email", "phone", "description",
                                         "staff_notes", "media", "ai_analysis"}


class TestTheWord:
    def test_the_mode_is_no_longer_called_anonymising(self):
        assert S.REDACT == "redact"

    def test_what_towns_already_have_stored_still_reads(self):
        assert S.normalise_mode("anonymize") == "redact"

    def test_delete_is_untouched(self):
        assert S.normalise_mode("delete") == "delete"

    def test_nothing_stored_means_redact(self):
        assert S.normalise_mode(None) == "redact"
        assert S.normalise_mode("") == "redact"

    def test_case_and_spacing_do_not_change_the_meaning(self):
        assert S.normalise_mode("  Anonymize ") == "redact"


def test_the_settings_screen_can_show_the_current_choice():
    shown = S.describe_selection(["phone", "address"])
    chosen = {f["id"] for f in shown if f["selected"]}
    assert chosen == {"phone", "address"}
    assert len(shown) == len(S.SCRUB_FIELDS)
    for field in shown:
        assert field["label"] and field["detail"], field["id"]
