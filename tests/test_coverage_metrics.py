"""Calendar, inventory, common-cohort, and recording-context regressions."""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from coverage_metrics import changes_between, make_snapshots, month_starts
from coverage_model import COVERED, STATUSES, DataError, Revision, Topic, subject_summaries, summarise_topics

FLOW_KEYS = {
    "gains", "losses", "added", "removed", "covered_added", "covered_removed",
    "net_covered", "net_total", "documentation_gains", "source_gains", "unknown_gains",
}
SNAPSHOT_KEYS = {
    "date", "as_of", "kind", "event_index", "source", "commit", "commit_date",
    "overall", "subjects", "flow", "windows",
}
WINDOW_KEYS = {
    "available", "reason", "months", "start", "end", "prior_start", "overall", "subjects", "flow",
}
COMPARISON_KEYS = {"cohort_size", "excluded", "recent", "prior", "pace_change"}
RATE_KEYS = {"gains", "losses", "net", "per_month", "percentage_points"}


def utc(year, month, day=1, hour=0, minute=0, second=0, microsecond=0):
    return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=timezone.utc)


def topic(identifier, status="unlinked", subject="s"):
    references = (f"Reference.{identifier}",) if status in COVERED else ()
    return Topic(identifier, identifier, subject, (subject, identifier), status, references)


def revision(at, *topics, context="unknown", source="mathlib4", commit=None, committed_at=None):
    return Revision(
        at=at, commit=commit or "a" * 40, committed_at=committed_at or at, source=source,
        url="https://example.com/commit", summary="Catalog recording", context=context,
        topics={value.id: value for value in topics},
    )


def assert_flow(flow):
    assert set(flow) == FLOW_KEYS
    assert all(type(value) is int for value in flow.values())
    assert all(flow[key] >= 0 for key in FLOW_KEYS - {"net_covered", "net_total"})
    assert flow["net_covered"] == (
        flow["gains"] - flow["losses"] + flow["covered_added"] - flow["covered_removed"]
    )
    assert flow["net_total"] == flow["added"] - flow["removed"]
    assert flow["gains"] == flow["documentation_gains"] + flow["source_gains"] + flow["unknown_gains"]


def assert_unavailable(window, reason):
    assert not window["available"]
    assert reason.lower() in window["reason"].lower()
    assert window["overall"] is window["flow"] is None
    assert window["subjects"] == {}


@pytest.mark.parametrize("first,last,expected", [
    (utc(2023, 11, 15), utc(2024, 2, 10), [utc(2023, 12), utc(2024, 1), utc(2024, 2)]),
    (utc(2024, 1), utc(2024, 3), [utc(2024, 2), utc(2024, 3)]),
    (utc(2024, 2, 29, 23, 59, 59), utc(2024, 3), [utc(2024, 3)]),
    (utc(2024, 1), utc(2024, 1, 31), []),
    (utc(2024, 3), utc(2024, 1), []),
    (utc(9999, 12), utc(9999, 12, 31), []),
])
def test_month_starts_are_strict_utc_boundaries(first, last, expected):
    assert month_starts(first, last) == expected
    assert all(boundary.tzinfo is timezone.utc for boundary in month_starts(first, last))


def test_month_starts_normalize_offsets_before_finding_calendar_month():
    offset = timezone(timedelta(hours=2))
    assert month_starts(
        datetime(2024, 1, 1, tzinfo=offset), datetime(2024, 2, 1, tzinfo=offset),
    ) == [utc(2024, 1)]


class NoOffset(tzinfo):
    def utcoffset(self, value):
        return None


@pytest.mark.parametrize("invalid", [datetime(2024, 1, 1), datetime(2024, 1, 1, tzinfo=NoOffset()), None])
def test_missing_timezone_is_not_assumed_utc(invalid):
    with pytest.raises(DataError, match="timezone"):
        month_starts(invalid, utc(2024, 2))
    with pytest.raises(DataError, match="timezone"):
        month_starts(utc(2024, 1), invalid)
    with pytest.raises(DataError, match="timezone"):
        make_snapshots([revision(utc(2023, 12), topic("x"))], invalid)


@pytest.mark.parametrize("before_status", STATUSES)
@pytest.mark.parametrize("after_status", STATUSES)
def test_every_status_pair_uses_declarations_and_modules_as_covered(before_status, after_status):
    result = changes_between(
        {"x": topic("x", before_status)}, {"x": topic("x", after_status)},
    )
    assert_flow(result)
    assert result["gains"] == int(before_status not in COVERED and after_status in COVERED)
    assert result["losses"] == int(before_status in COVERED and after_status not in COVERED)
    assert result["added"] == result["removed"] == 0
    assert result["unknown_gains"] == result["gains"]


def test_status_and_inventory_flows_reconcile_separately():
    before = {
        value.id: value for value in (
            topic("gain", "external"), topic("loss", "module"), topic("format", "module"),
            topic("removed-covered", "declaration"), topic("removed-uncovered"),
        )
    }
    after = {
        value.id: value for value in (
            topic("gain", "declaration"), topic("loss", "reported"), topic("format", "declaration"),
            topic("added-covered", "module"), topic("added-uncovered"),
        )
    }
    result = changes_between(before, after)
    assert result == {
        "gains": 1, "losses": 1, "added": 2, "removed": 2, "covered_added": 1,
        "covered_removed": 1, "net_covered": 0, "net_total": 0,
        "documentation_gains": 0, "source_gains": 0, "unknown_gains": 1,
    }
    assert_flow(result)


def test_initial_and_removed_catalogs_are_inventory_not_shared_topic_gains():
    catalog = {"x": topic("x", "declaration"), "y": topic("y")}
    added = changes_between({}, catalog)
    removed = changes_between(catalog, {})
    assert added["gains"] == removed["losses"] == 0
    assert added["added"] == removed["removed"] == 2
    assert added["covered_added"] == removed["covered_removed"] == 1
    assert added["net_covered"] == -removed["net_covered"] == 1
    assert_flow(added)
    assert_flow(removed)
    assert changes_between({}, {}) == dict.fromkeys(FLOW_KEYS, 0)


@pytest.mark.parametrize("invalid", [None, [], {"x": None}, {"different": topic("x")}])
def test_invalid_topic_states_fail_explicitly(invalid):
    with pytest.raises(DataError):
        changes_between(invalid, {"x": topic("x")})
    with pytest.raises(DataError):
        changes_between({"x": topic("x")}, invalid)


def test_catalog_begins_with_observed_baseline_not_zero_history():
    revisions = [revision(utc(2024, 12, 9), topic("x", "module"), context="documentation_only")]
    timeline, latest = make_snapshots(revisions, utc(2025, 2, 15))
    assert [snapshot["date"] for snapshot in timeline] == ["2025-01-01", "2025-02-01"]
    assert timeline[0]["flow"] is None
    assert all(snapshot["overall"]["covered"] == 1 for snapshot in [*timeline, latest])
    assert latest["date"] == "2025-02-15"
    assert latest["kind"] == "latest"
    assert latest["flow"] == dict.fromkeys(FLOW_KEYS, 0)
    for snapshot in [*timeline, latest]:
        assert_unavailable(snapshot["windows"]["12"], "insufficient history")


def test_latest_is_first_baseline_when_no_month_has_closed():
    revisions = [
        revision(utc(2024, 12, 9), topic("x")),
        revision(utc(2024, 12, 10), topic("x", "module")),
    ]
    timeline, latest = make_snapshots(revisions, utc(2024, 12, 20))
    assert timeline == []
    assert latest["event_index"] == 1
    assert latest["overall"]["covered"] == 1
    assert latest["flow"] is None
    for window in latest["windows"].values():
        assert_unavailable(window, "no closed monthly")
        assert window["end"] == "2024-12-01"
        assert window["start"] is window["prior_start"] is None


def test_exact_boundary_excludes_all_coincident_events_but_latest_includes_them_in_input_order():
    revisions = [
        revision(utc(2023, 12, 20), topic("x"), commit="d" * 40),
        revision(utc(2024, 1), topic("x", "module"), context="documentation_only", commit="c" * 40),
        revision(utc(2024, 1), topic("x"), commit="b" * 40),
        revision(utc(2024, 1), topic("x", "declaration"), context="source_accompanied", commit="a" * 40),
    ]
    timeline, latest = make_snapshots(revisions, utc(2024, 1))
    assert len(timeline) == 1
    assert timeline[0]["event_index"] == 0
    assert timeline[0]["commit"] == "d" * 40
    assert timeline[0]["overall"]["covered"] == 0
    assert latest["event_index"] == 3
    assert latest["commit"] == "a" * 40
    assert latest["overall"]["covered"] == 1
    assert latest["flow"]["gains"] == 2
    assert latest["flow"]["losses"] == 1
    assert latest["flow"]["documentation_gains"] == latest["flow"]["source_gains"] == 1
    assert_flow(latest["flow"])
    assert latest["windows"] == timeline[-1]["windows"]


def test_effective_observation_time_not_actual_commit_time_selects_revision():
    revisions = [
        revision(utc(2024, 1, 10), topic("x")),
        revision(
            utc(2024, 3, 10), topic("x", "module"), committed_at=utc(2024, 1, 5), commit="b" * 40,
        ),
    ]
    timeline, latest = make_snapshots(revisions, utc(2024, 3, 15))
    assert [snapshot["event_index"] for snapshot in timeline] == [0, 0]
    assert latest["event_index"] == 1
    assert latest["commit_date"] == utc(2024, 1, 5).isoformat()
    assert latest["as_of"] == utc(2024, 3, 15).isoformat()


def test_snapshot_clock_normalizes_to_utc_and_never_includes_future_events():
    offset = timezone(timedelta(hours=-4))
    revisions = [
        revision(utc(2023, 12, 20), topic("x")),
        revision(utc(2024, 1, 1, 3), topic("x", "module"), commit="b" * 40),
        revision(utc(2024, 1, 1, 5), topic("x"), commit="c" * 40),
    ]
    now = datetime(2023, 12, 31, 23, tzinfo=offset)
    timeline, latest = make_snapshots(revisions, now)
    assert timeline[-1]["date"] == "2024-01-01"
    assert timeline[-1]["event_index"] == 0
    assert latest["date"] == "2024-01-01"
    assert latest["as_of"] == utc(2024, 1, 1, 3).isoformat()
    assert latest["event_index"] == 1
    assert latest["overall"]["covered"] == 1


def test_monthly_flow_counts_reversals_and_transient_inventory_not_only_endpoints():
    revisions = [
        revision(utc(2023, 12, 20), topic("x")),
        revision(utc(2024, 1, 5), topic("x", "module"), topic("new", "module"),
                 context="documentation_only"),
        revision(utc(2024, 1, 6), topic("x")),
        revision(utc(2024, 1, 7), topic("x", "declaration"), context="source_accompanied"),
        revision(utc(2024, 1, 8), topic("x")),
    ]
    timeline, _ = make_snapshots(revisions, utc(2024, 2))
    flow = timeline[-1]["flow"]
    assert flow["gains"] == flow["losses"] == 2
    assert flow["added"] == flow["removed"] == 1
    assert flow["covered_added"] == flow["covered_removed"] == 1
    assert flow["net_total"] == flow["net_covered"] == 0
    assert flow["documentation_gains"] == flow["source_gains"] == 1
    assert_flow(flow)


def test_source_splice_and_reference_rename_preserve_coverage_and_cohort():
    before = replace(topic("x", "module"), label="Old label", references=("Old/Module.html",))
    after = replace(topic("x", "declaration"), label="New label", references=("New.reference",))
    revisions = [
        revision(utc(2023, 12, 20), before, source="mathlib3"),
        revision(utc(2024, 4), after, source="mathlib4", commit="b" * 40),
    ]
    timeline, latest = make_snapshots(revisions, utc(2024, 7, 2))
    assert next(row for row in timeline if row["date"] == "2024-04-01")["source"] == "mathlib3"
    assert next(row for row in timeline if row["date"] == "2024-05-01")["source"] == "mathlib4"
    assert all(row["flow"] == dict.fromkeys(FLOW_KEYS, 0) for row in timeline[1:])
    window = latest["windows"]["3"]
    assert window["available"]
    assert window["overall"]["cohort_size"] == 1
    assert window["overall"]["excluded"] == 0
    assert window["overall"]["recent"]["net"] == window["overall"]["prior"]["net"] == 0


@pytest.mark.parametrize("context,key", [
    ("documentation_only", "documentation_gains"),
    ("source_accompanied", "source_gains"),
    ("unknown", "unknown_gains"),
])
def test_commit_context_counts_shared_gains_not_covered_catalog_additions(context, key):
    revisions = [
        revision(utc(2023, 12, 20), topic("x")),
        revision(utc(2024, 1, 10), topic("x", "declaration"), topic("new", "module"), context=context),
    ]
    timeline, _ = make_snapshots(revisions, utc(2024, 2))
    flow = timeline[-1]["flow"]
    assert flow["gains"] == flow["covered_added"] == flow[key] == 1
    assert flow["net_covered"] == 2
    assert_flow(flow)


@pytest.mark.parametrize("months,start,prior_start", [
    (3, "2024-10-01", "2024-07-01"),
    (6, "2024-07-01", "2024-01-01"),
    (12, "2024-01-01", "2023-01-01"),
])
def test_complete_calendar_windows_and_long_unchanged_states(months, start, prior_start):
    revisions = [revision(utc(2022, 12, 20), topic("x"), topic("y", "module"))]
    _, latest = make_snapshots(revisions, utc(2025, 1, 15))
    window = latest["windows"][str(months)]
    assert window["available"]
    assert window["reason"] is None
    assert (window["start"], window["end"], window["prior_start"]) == (start, "2025-01-01", prior_start)
    assert window["overall"]["cohort_size"] == 2
    assert window["overall"]["recent"] == {
        "gains": 0, "losses": 0, "net": 0, "per_month": 0.0, "percentage_points": 0.0,
    }
    assert window["overall"]["prior"] == window["overall"]["recent"]
    assert window["flow"] == dict.fromkeys(FLOW_KEYS, 0)


def test_paired_windows_require_baseline_strictly_before_prior_boundary():
    revisions = [revision(utc(2024, 1), topic("x"))]
    timeline, _ = make_snapshots(revisions, utc(2024, 8))
    july = next(row for row in timeline if row["date"] == "2024-07-01")
    assert_unavailable(july["windows"]["3"], "before 2024-01-01")
    assert timeline[-1]["windows"]["3"]["available"]
    assert_unavailable(timeline[-1]["windows"]["6"], "insufficient history")
    assert_unavailable(timeline[-1]["windows"]["12"], "insufficient history")


def test_empty_common_cohort_is_unavailable_not_a_zero_rate():
    revisions = [
        revision(utc(2023, 12, 20), topic("old")),
        revision(utc(2024, 2, 10), topic("new", "module")),
    ]
    _, latest = make_snapshots(revisions, utc(2024, 7))
    assert_unavailable(latest["windows"]["3"], "no common cohort")
    assert latest["windows"]["3"]["start"] == "2024-04-01"
    assert latest["windows"]["3"]["prior_start"] == "2024-01-01"


def test_adjacent_windows_use_the_same_continuous_cohort_and_expose_recent_catalog_flow():
    revisions = [
        revision(utc(2023, 12, 20), topic("a"), topic("b"), topic("old", "module")),
        revision(utc(2024, 1, 10), topic("a", "module"), topic("b"), topic("old", "module")),
        revision(utc(2024, 3, 10), topic("a", "module"), topic("b"),
                 topic("old", "module"), topic("prior-extra", "module")),
        revision(utc(2024, 4, 10), topic("a"), topic("b", "declaration"),
                 topic("old", "module"), topic("prior-extra", "module"), topic("new", "module")),
        revision(utc(2024, 5, 10), topic("a"), topic("b", "declaration"), topic("new", "module")),
    ]
    _, latest = make_snapshots(revisions, utc(2024, 7))
    window = latest["windows"]["3"]
    comparison = window["overall"]
    assert comparison["cohort_size"] == 2
    assert comparison["excluded"] == 3
    assert comparison["prior"] == {
        "gains": 1, "losses": 0, "net": 1, "per_month": 1 / 3, "percentage_points": 50,
    }
    assert comparison["recent"] == {
        "gains": 1, "losses": 1, "net": 0, "per_month": 0, "percentage_points": 0,
    }
    assert comparison["pace_change"] == -1 / 3
    assert window["subjects"]["s"] == comparison
    assert window["flow"] == {
        "gains": 1, "losses": 1, "added": 1, "removed": 2, "covered_added": 1,
        "covered_removed": 2, "net_covered": -1, "net_total": -1,
        "documentation_gains": 0, "source_gains": 0, "unknown_gains": 1,
    }
    assert_flow(window["flow"])


def test_readded_identity_is_excluded_even_when_absence_is_between_monthly_observations():
    revisions = [
        revision(utc(2023, 12, 20), topic("anchor"), topic("returning")),
        revision(utc(2024, 1, 5), topic("anchor"), topic("returning", "module")),
        revision(utc(2024, 2, 10), topic("anchor")),
        revision(utc(2024, 2, 11), topic("anchor"), topic("returning")),
        revision(utc(2024, 5, 10), topic("anchor"), topic("returning", "module")),
    ]
    timeline, latest = make_snapshots(revisions, utc(2024, 7))
    comparison = latest["windows"]["3"]["overall"]
    assert comparison["cohort_size"] == comparison["excluded"] == 1
    assert comparison["recent"]["gains"] == comparison["prior"]["gains"] == 0
    assert latest["windows"]["3"]["flow"]["gains"] == 1
    march = next(row for row in timeline if row["date"] == "2024-03-01")
    assert march["flow"]["added"] == march["flow"]["removed"] == 1


def test_temporary_taxonomy_moves_preserve_overall_identity_but_exclude_subject_cohorts():
    revisions = [
        revision(utc(2023, 12, 20), topic("a", subject="A"), topic("b", subject="A"),
                 topic("c", subject="B")),
        revision(utc(2024, 2, 10), topic("a", subject="A"), topic("b", subject="B"),
                 topic("c", subject="B")),
        revision(utc(2024, 2, 11), topic("a", subject="A"), topic("b", "module", "B"),
                 topic("c", subject="B")),
        revision(utc(2024, 2, 12), topic("a", subject="A"), topic("b", "module", "A"),
                 topic("c", subject="B")),
    ]
    _, latest = make_snapshots(revisions, utc(2024, 7))
    window = latest["windows"]["3"]
    assert window["overall"]["cohort_size"] == 3
    assert window["overall"]["excluded"] == 0
    assert window["overall"]["prior"]["gains"] == 1
    for subject in ("A", "B"):
        assert window["subjects"][subject]["cohort_size"] == 1
        assert window["subjects"][subject]["excluded"] == 1
        assert window["subjects"][subject]["prior"]["gains"] == 0
    assert latest["subjects"]["A"]["total"] == 2
    assert latest["subjects"]["A"]["covered"] == 1


def test_subject_without_continuously_classified_members_has_no_comparison():
    revisions = [
        revision(utc(2023, 12, 20), topic("x", subject="old")),
        revision(utc(2024, 3), topic("x", "module", "new")),
    ]
    _, latest = make_snapshots(revisions, utc(2024, 7))
    window = latest["windows"]["3"]
    assert window["available"]
    assert window["overall"]["cohort_size"] == 1
    assert window["subjects"] == {}
    assert set(latest["subjects"]) == {"new"}


def test_ratios_use_integer_net_counts_without_rounding_coverage_percentages():
    revisions = [
        revision(utc(2023, 12, 20), topic("a", "module"), topic("b"), topic("c")),
        revision(utc(2024, 2, 10), topic("a", "module"), topic("b", "module"), topic("c")),
        revision(utc(2024, 5, 10), topic("a", "module"), topic("b", "module"), topic("c", "module")),
    ]
    _, latest = make_snapshots(revisions, utc(2024, 7))
    comparison = latest["windows"]["3"]["overall"]
    for period in ("prior", "recent"):
        assert comparison[period]["percentage_points"] == 100 / 3
        assert comparison[period]["per_month"] == 1 / 3
        assert comparison[period]["percentage_points"] != round(100 / 3, 2)
    assert comparison["pace_change"] == 0


@pytest.mark.parametrize("partial_at,now", [
    (utc(2024, 7), utc(2024, 7)),
    (utc(2024, 7, 10), utc(2024, 7, 15)),
])
def test_latest_partial_month_is_excluded_from_windows_but_included_in_latest_flow(partial_at, now):
    revisions = [
        revision(utc(2023, 12, 20), topic("a"), topic("b")),
        revision(utc(2024, 2, 10), topic("a", "module"), topic("b")),
        revision(utc(2024, 5, 10), topic("a", "module"), topic("b", "module")),
        revision(partial_at, topic("a"), topic("b", "module"), topic("new", "module")),
    ]
    timeline, latest = make_snapshots(revisions, now)
    assert timeline[-1]["date"] == "2024-07-01"
    assert timeline[-1]["event_index"] == 2
    assert latest["event_index"] == 3
    assert latest["flow"]["losses"] == latest["flow"]["covered_added"] == 1
    assert latest["flow"]["net_covered"] == 0
    assert latest["flow"]["net_total"] == 1
    assert latest["windows"] == timeline[-1]["windows"]
    window = latest["windows"]["3"]
    assert (window["prior_start"], window["start"], window["end"]) == (
        "2024-01-01", "2024-04-01", "2024-07-01",
    )
    assert window["overall"]["excluded"] == 0
    assert window["overall"]["cohort_size"] == 2
    assert window["overall"]["recent"]["net"] == 1
    assert window["flow"]["losses"] == window["flow"]["added"] == 0


def test_window_rates_sum_all_covered_transitions_and_boundary_events_use_half_open_periods():
    revisions = [
        revision(utc(2023, 12, 20), topic("x"), topic("anchor")),
        revision(utc(2024, 1), topic("x", "module"), topic("anchor")),
        revision(utc(2024, 2), topic("x"), topic("anchor")),
        revision(utc(2024, 4), topic("x", "module"), topic("anchor"), context="documentation_only"),
        revision(utc(2024, 5), topic("x"), topic("anchor")),
        revision(utc(2024, 6), topic("x", "declaration"), topic("anchor"), context="documentation_only"),
        revision(utc(2024, 7), topic("x"), topic("anchor")),
    ]
    _, latest = make_snapshots(revisions, utc(2024, 7))
    window = latest["windows"]["3"]
    assert window["overall"]["prior"] == {
        "gains": 1, "losses": 1, "net": 0, "per_month": 0, "percentage_points": 0,
    }
    assert window["overall"]["recent"] == {
        "gains": 2, "losses": 1, "net": 1, "per_month": 1 / 3, "percentage_points": 50,
    }
    assert window["flow"]["documentation_gains"] == window["flow"]["gains"] == 2
    assert latest["flow"]["losses"] == 1
    assert_flow(window["flow"])


def test_missing_history_or_future_only_history_never_becomes_zero_observations():
    with pytest.raises(DataError, match="No catalog history"):
        make_snapshots([], utc(2024, 1))
    with pytest.raises(DataError, match="No catalog observation"):
        make_snapshots([revision(utc(2024, 2), topic("x"))], utc(2024, 1))


def test_out_of_order_mainline_states_fail_instead_of_being_sorted_and_reindexed():
    revisions = [
        revision(utc(2024, 2), topic("x")),
        revision(utc(2024, 1), topic("x", "module")),
    ]
    with pytest.raises(DataError, match="chronological"):
        make_snapshots(revisions, utc(2024, 3))


@pytest.mark.parametrize("field,value,reason", [
    ("at", datetime(2024, 1, 1), "timezone"),
    ("committed_at", datetime(2024, 1, 1), "timezone"),
    ("committed_at", utc(2025, 1), "after its observation"),
    ("topics", {}, "gap"),
    ("topics", None, "gap"),
    ("topics", {"x": None}, "identity"),
    ("topics", {"wrong": topic("x")}, "identity"),
    ("commit", "abcd", "full commit SHA"),
    ("commit", "g" * 40, "full commit SHA"),
    ("source", "", "source identity"),
    ("context", "proof_date", "recording context"),
])
def test_mutated_invalid_revision_is_rejected_at_metrics_boundary(field, value, reason):
    invalid = revision(utc(2024, 1), topic("x"))
    setattr(invalid, field, value)
    with pytest.raises(DataError, match=reason):
        make_snapshots([invalid], utc(2024, 8))


def test_explicit_missing_midstream_state_is_an_error_not_an_unchanged_month():
    revisions = [
        revision(utc(2023, 12, 20), topic("x")),
        None,
        revision(utc(2024, 4), topic("x", "module")),
    ]
    with pytest.raises(DataError, match="history has a gap"):
        make_snapshots(revisions, utc(2024, 7))


def test_calendar_underflow_is_an_explicit_unavailable_window():
    _, latest = make_snapshots([revision(utc(1, 1), topic("x"))], utc(1, 2))
    for window in latest["windows"].values():
        assert_unavailable(window, "insufficient calendar history")


def test_exact_schema_reconciliation_and_determinism_without_input_mutation():
    revisions = [
        revision(utc(2022, 12, 20), topic("a"), topic("b", "module", "other")),
        revision(utc(2023, 2, 10), topic("a", "declaration"), topic("b", "module", "other"),
                 context="documentation_only"),
        revision(utc(2024, 8, 10), topic("a"), topic("b", "declaration", "other")),
        revision(utc(2025, 1, 10), topic("a", "module"), topic("b", "declaration", "other")),
    ]
    original = copy.deepcopy(revisions)
    now = utc(2025, 1, 20, 12, 13, 14, 123456)
    timeline, latest = make_snapshots(revisions, now)
    assert revisions == original
    assert (timeline, latest) == make_snapshots(revisions, now)
    json.dumps([timeline, latest], allow_nan=False)
    previous = None
    for snapshot in [*timeline, latest]:
        assert set(snapshot) == SNAPSHOT_KEYS
        assert snapshot["kind"] == ("latest" if snapshot is latest else "monthly")
        state = revisions[snapshot["event_index"]].topics
        assert snapshot["overall"] == summarise_topics(state.values())
        assert snapshot["subjects"] == subject_summaries(state)
        assert set(snapshot["overall"]) == {"total", "covered", "percentage", "statuses"}
        assert set(snapshot["windows"]) == {"3", "6", "12"}
        if previous is None:
            assert snapshot["flow"] is None
        else:
            assert_flow(snapshot["flow"])
            assert snapshot["flow"]["net_covered"] == (
                snapshot["overall"]["covered"] - previous["overall"]["covered"]
            )
            assert snapshot["flow"]["net_total"] == (
                snapshot["overall"]["total"] - previous["overall"]["total"]
            )
        for months, window in snapshot["windows"].items():
            assert set(window) == WINDOW_KEYS
            assert window["months"] == int(months)
            if not window["available"]:
                assert window["reason"]
                assert window["overall"] is window["flow"] is None
                assert window["subjects"] == {}
                continue
            assert window["reason"] is None
            assert_flow(window["flow"])
            for comparison in [window["overall"], *window["subjects"].values()]:
                assert set(comparison) == COMPARISON_KEYS
                assert comparison["cohort_size"] > 0
                assert comparison["excluded"] >= 0
                for rate in (comparison["prior"], comparison["recent"]):
                    assert set(rate) == RATE_KEYS
                    assert type(rate["gains"]) is type(rate["losses"]) is type(rate["net"]) is int
                    assert rate["net"] == rate["gains"] - rate["losses"]
                    assert rate["per_month"] == rate["net"] / int(months)
                    assert rate["percentage_points"] == 100 * rate["net"] / comparison["cohort_size"]
                assert comparison["pace_change"] == (
                    comparison["recent"]["per_month"] - comparison["prior"]["per_month"]
                )
        previous = snapshot
    latest["windows"]["3"]["overall"]["cohort_size"] = -1
    assert timeline[-1]["windows"]["3"]["overall"]["cohort_size"] == 2
