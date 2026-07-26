"""Tests for proactive-health threshold logic (the leading-indicator classifier
that decides when to warn admins before something fails). Pure, no I/O."""

from app.services.proactive_health import (
    classify_metric,
    rollup_status,
    clerk_summary,
    is_worse,
)


# ---- classify_metric (higher is worse: disk, memory, connections) ----------

def test_classify_ok_below_warn():
    assert classify_metric(50, warn=80, crit=92) == "ok"


def test_classify_warning_between_thresholds():
    assert classify_metric(85, warn=80, crit=92) == "warning"


def test_classify_critical_at_or_above_crit():
    assert classify_metric(92, warn=80, crit=92) == "critical"
    assert classify_metric(99, warn=80, crit=92) == "critical"


def test_classify_unknown_when_none():
    assert classify_metric(None, warn=80, crit=92) == "unknown"


def test_classify_boundary_is_inclusive_at_warn():
    assert classify_metric(80, warn=80, crit=92) == "warning"


# ---- rollup: overall = worst check -----------------------------------------

def test_rollup_takes_worst():
    checks = [{"status": "ok"}, {"status": "warning"}, {"status": "ok"}]
    assert rollup_status(checks) == "warning"
    checks.append({"status": "critical"})
    assert rollup_status(checks) == "critical"


def test_rollup_unknown_does_not_escalate():
    # A probe we couldn't run must not drive the overall status.
    checks = [{"status": "ok"}, {"status": "unknown"}]
    assert rollup_status(checks) == "ok"


def test_rollup_all_ok():
    assert rollup_status([{"status": "ok"}, {"status": "ok"}]) == "ok"


# ---- is_worse (alert de-dup transitions) -----------------------------------

def test_is_worse_transitions():
    assert is_worse("warning", "ok") is True
    assert is_worse("critical", "warning") is True
    assert is_worse("critical", None) is True


def test_is_not_worse_same_or_better():
    assert is_worse("warning", "warning") is False
    assert is_worse("ok", "critical") is False
    assert is_worse("warning", "critical") is False


# ---- clerk summary is plain-language and always resolves --------------------

def test_clerk_summary_levels():
    assert clerk_summary("ok")["label"] == "All systems normal"
    assert clerk_summary("warning")["level"] == "warning"
    assert clerk_summary("critical")["level"] == "critical"
    # Unknown/garbage falls back to the safe "all normal" rather than raising.
    assert clerk_summary("garbage")["level"] == "ok"
