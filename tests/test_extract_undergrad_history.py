"""Tests for the coverage extractor.

Run with:  python3 -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from extract_undergrad_history import (  # noqa: E402
    EXTERNAL,
    IMPLEMENTED,
    TODO,
    GitError,
    add_metrics,
    classify,
    combined_history,
    count_topics,
    month_starts,
    parse_snapshot,
    summarise,
)


class TestClassify:
    """The classification rule must match mathlib's own `scripts/yaml_check.py`,
    which treats a value containing "/" as an external reference, not a
    declaration:  `if entry and "/" not in entry`."""

    @pytest.mark.parametrize(
        "value",
        ["Module", "LinearMap.range", "Matrix.det", "  Submodule.span  "],
    )
    def test_declarations_are_implemented(self, value):
        assert classify(value) == IMPLEMENTED

    @pytest.mark.parametrize(
        "value",
        [
            "https://en.wikipedia.org/wiki/Diagonalizable_matrix",
            "https://www.math.tamu.edu/~fnarc/psfiles/rank2005.pdf",
            "https://fr.wikipedia.org/wiki/Lemme_des_noyaux",
        ],
    )
    def test_urls_are_external_not_implemented(self, value):
        assert classify(value) == EXTERNAL

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_is_todo(self, value):
        assert classify(value) == TODO

    def test_list_prefers_a_real_declaration(self):
        assert classify(["https://example.com/x", "Module"]) == IMPLEMENTED

    def test_list_of_only_urls_is_external(self):
        assert classify(["https://example.com/x", "https://example.com/y"]) == EXTERNAL

    def test_list_of_empties_is_todo(self):
        assert classify([None, ""]) == TODO


class TestCountTopics:
    def test_counts_each_class(self):
        node = {
            "a": "Module",
            "b": "https://example.com/ref",
            "c": None,
            "d": "LinearMap",
        }
        assert count_topics(node) == {IMPLEMENTED: 2, EXTERNAL: 1, TODO: 1}

    def test_nested_categories_are_flattened(self):
        node = {"outer": {"inner": {"leaf": "Module", "other": None}}}
        assert count_topics(node) == {IMPLEMENTED: 1, EXTERNAL: 0, TODO: 1}

    def test_empty_dict_counts_as_a_todo_leaf(self):
        # An empty mapping is a topic with nothing recorded, not a category with
        # no topics; dropping it would silently shrink the denominator.
        assert count_topics({"a": {}}) == {IMPLEMENTED: 0, EXTERNAL: 0, TODO: 1}


class TestSummarise:
    def test_percentage_excludes_external_references(self):
        result = summarise({IMPLEMENTED: 396, EXTERNAL: 40, TODO: 130})
        assert result["total"] == 566
        assert result["implemented"] == 396
        assert result["external"] == 40
        assert result["percentage"] == 69.96

    def test_zero_total_does_not_divide_by_zero(self):
        assert summarise({IMPLEMENTED: 0, EXTERNAL: 0, TODO: 0})["percentage"] == 0.0


class TestParseSnapshot:
    def test_parses_realistic_yaml(self):
        content = """
        Linear algebra:
          Fundamentals:
            vector space: 'Module'
            elementary row operations: 'https://en.wikipedia.org/wiki/Elementary_matrix'
            some missing topic:
        Topology:
          Basics:
            topological space: 'TopologicalSpace'
        """
        snapshot = parse_snapshot(content)
        assert snapshot["overall"] == {
            "total": 4,
            "implemented": 2,
            "external": 1,
            "todo": 1,
            "percentage": 50.0,
        }
        assert snapshot["categories"]["Linear algebra"]["implemented"] == 1
        assert snapshot["categories"]["Linear algebra"]["external"] == 1
        assert snapshot["categories"]["Topology"]["percentage"] == 100.0

    def test_invalid_yaml_returns_none(self):
        assert parse_snapshot("a: b:\n  - [unclosed") is None

    def test_empty_document_returns_none(self):
        assert parse_snapshot("") is None


class TestMetrics:
    def test_first_two_entries_have_undefined_metrics(self):
        # Reporting 0.0 here would invent data: the first entry has no previous
        # month and the second has no previous velocity.
        timeline = [{"overall": {"implemented": n}, "metrics": {}} for n in (10, 12, 15)]
        add_metrics(timeline)
        assert timeline[0]["metrics"] == {"velocity_per_month": None, "acceleration": None}
        assert timeline[1]["metrics"] == {"velocity_per_month": 2.0, "acceleration": None}
        assert timeline[2]["metrics"] == {"velocity_per_month": 3.0, "acceleration": 1.0}

    def test_velocity_tracks_declarations_only(self):
        timeline = [{"overall": {"implemented": n}, "metrics": {}} for n in (100, 100, 104)]
        add_metrics(timeline)
        assert [e["metrics"]["velocity_per_month"] for e in timeline] == [None, 0.0, 4.0]


class TestMonthStarts:
    def test_starts_the_month_after_the_first_commit(self):
        from datetime import datetime, timezone

        first = datetime(2023, 7, 21, tzinfo=timezone.utc)
        last = datetime(2023, 11, 15, tzinfo=timezone.utc)
        assert [d.strftime("%Y-%m-%d") for d in month_starts(first, last)] == [
            "2023-08-01",
            "2023-09-01",
            "2023-10-01",
            "2023-11-01",
        ]

    def test_rolls_over_the_year(self):
        from datetime import datetime, timezone

        first = datetime(2023, 11, 5, tzinfo=timezone.utc)
        last = datetime(2024, 2, 1, tzinfo=timezone.utc)
        assert [d.strftime("%Y-%m-%d") for d in month_starts(first, last)] == [
            "2023-12-01",
            "2024-01-01",
            "2024-02-01",
        ]


class TestRegressionAgainstMathlibRule:
    """Lock in the behaviour that the previous implementation got wrong."""

    def test_url_topics_do_not_inflate_coverage(self):
        content = yaml.safe_dump(
            {
                "Cat": {
                    "Sub": {
                        "done": "Module",
                        "linked": "https://en.wikipedia.org/wiki/Jordan_normal_form",
                        "missing": None,
                    }
                }
            }
        )
        overall = parse_snapshot(content)["overall"]
        # Counting the URL as implemented would give 66.67%.
        assert overall["percentage"] == pytest.approx(33.33)

    def test_url_becoming_a_declaration_registers_as_progress(self):
        # This is the case the old implementation was blind to: the topic was
        # already counted as done, so formalising it showed up as zero movement.
        before = parse_snapshot(
            yaml.safe_dump({"Cat": {"Sub": {"t": "https://en.wikipedia.org/wiki/X"}}})
        )
        after = parse_snapshot(yaml.safe_dump({"Cat": {"Sub": {"t": "Real.Decl"}}}))
        assert before["overall"]["implemented"] == 0
        assert after["overall"]["implemented"] == 1


def utc(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc)


class TestCombinedHistory:
    """Stitching mathlib3 and mathlib4 into one chronological series.

    `git log --follow` cannot cross the boundary because the file was *ported*
    between two unrelated repositories rather than renamed within one, so the
    two histories are read separately and joined here.
    """

    @staticmethod
    def sources(monkeypatch, histories):
        import extract_undergrad_history as mod

        by_name = {name: history for name, history in histories.items()}
        monkeypatch.setattr(
            mod,
            "file_history",
            lambda repo, ref, path: by_name[repo],
        )
        return [
            {"name": name, "repo": name, "ref": "master", "path": "docs/undergrad.yaml"}
            for name in histories
        ]

    def test_orders_sources_chronologically(self, monkeypatch):
        sources = self.sources(
            monkeypatch,
            {
                "old": [("a", utc(2020, 1, 1)), ("b", utc(2021, 1, 1))],
                "new": [("c", utc(2022, 1, 1))],
            },
        )
        result = combined_history(sources)
        assert [sha for _, sha, _ in result] == ["a", "b", "c"]
        assert [src["name"] for _, _, src in result] == ["old", "old", "new"]

    def test_old_source_is_cut_off_when_the_new_one_starts(self, monkeypatch):
        # mathlib3 kept receiving commits after the port; they must not
        # reappear and overwrite mathlib4's newer state.
        sources = self.sources(
            monkeypatch,
            {
                "old": [
                    ("a", utc(2020, 1, 1)),
                    ("stale", utc(2023, 6, 1)),
                    ("staler", utc(2023, 12, 1)),
                ],
                "new": [("b", utc(2023, 5, 1))],
            },
        )
        result = combined_history(sources)
        assert [sha for _, sha, _ in result] == ["a", "b"]

    def test_a_commit_exactly_at_the_cutoff_belongs_to_the_new_source(self, monkeypatch):
        sources = self.sources(
            monkeypatch,
            {
                "old": [("a", utc(2020, 1, 1)), ("tie", utc(2023, 5, 1))],
                "new": [("b", utc(2023, 5, 1))],
            },
        )
        result = combined_history(sources)
        assert [sha for _, sha, _ in result] == ["a", "b"]

    def test_empty_source_history_is_an_error(self, monkeypatch):
        sources = self.sources(monkeypatch, {"old": [], "new": [("b", utc(2023, 1, 1))]})
        with pytest.raises(GitError):
            combined_history(sources)

    def test_single_source_is_passed_through(self, monkeypatch):
        sources = self.sources(monkeypatch, {"only": [("a", utc(2020, 1, 1))]})
        assert [sha for _, sha, _ in combined_history(sources)] == ["a"]
