"""Regression coverage for evidence, identity, source safety, and publication."""

from __future__ import annotations

import json
import copy
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import curriculum_legacy
import extract_undergrad_history as extractor
import source_history
from coverage_model import DataError, Revision, Topic, load_yaml, summarise_topics
from curriculum_coverage import classify, curriculum_subjects, parse_curriculum
from source_history import GitError, clone_source, file_history, run_git


def utc(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc)


@pytest.mark.parametrize("value,status", [
    ("Module", "declaration"), ("  Submodule.span  ", "declaration"),
    ("Mathlib/FieldTheory/Finite/Basic.html", "module"),
    ("field_theory/finite.html", "module"),
    ("https://leanprover-community.github.io/mathlib4_docs/Mathlib/Order/Basic.html", "module"),
    ("https://en.wikipedia.org/wiki/Jordan_normal_form", "external"),
    (None, "unlinked"), ("", "unlinked"), ("   ", "unlinked"),
])
def test_classification(value, status):
    assert classify(value) == status


@pytest.mark.parametrize("value", [
    True, False, 0, 1, 3.14, ["Module"], ["https://example.com/x"], [],
    "../escape.html", "unrecognized/path", "mailto:somebody@example.com", "not a declaration",
])
def test_unsupported_leaf_fails(value):
    with pytest.raises(DataError):
        classify(value)


def test_four_classes_and_no_reference_is_not_absence():
    topics = parse_curriculum("""
Algebra:
  Basics:
    definition: Module
    module: Mathlib/Algebra/Basic.html
    external: https://example.com/reference
    missing:
    explicitly empty: {}
""")
    result = summarise_topics(topics.values())
    assert result["total"] == 5
    assert result["covered"] == 2
    assert result["percentage"] == 40
    assert result["statuses"]["unlinked"] == 2
    assert result["statuses"]["module"] == result["statuses"]["declaration"] == 1


def test_audited_current_distribution():
    rows = {"declaration": 396, "module": 3, "external": 37, "unlinked": 130}
    values = {"declaration": "Module", "module": "Mathlib/Test.html",
              "external": "https://example.com/x", "unlinked": ""}
    content = "Algebra:\n  Section:\n" + "".join(
        f"    {status}{i}: '{values[status]}'\n" for status, n in rows.items() for i in range(n)
    )
    summary = summarise_topics(parse_curriculum(content).values())
    assert (summary["covered"], summary["total"]) == (399, 566)
    assert summary["percentage"] == pytest.approx(70.4946996466)


def test_empty_population_is_unknown_not_zero_percent():
    assert summarise_topics([])["percentage"] is None


@pytest.mark.parametrize("text", ["", "[]", "a: b:\n  - [unclosed", "Subject:\n  x: Module",
                                "Subject:\n  Part:\n    topic: Module\n    topic: null\n"])
def test_invalid_or_duplicate_document_fails(text):
    with pytest.raises(DataError):
        parse_curriculum(text)


@pytest.mark.parametrize("old_name,new_name", [
    ("Measures and integral Calculus", "Measures and integral calculus"),
    ("Affine and Euclidian Geometry", "Affine and Euclidean Geometry"),
])
def test_subject_alias_is_continuous_but_preserves_source_label(old_name, new_name):
    template = "{}:\n  Section:\n    topic: Module\n"
    old = parse_curriculum(template.format(old_name))
    new = parse_curriculum(template.format(new_name))
    assert old.keys() == new.keys()
    assert curriculum_subjects(old) == curriculum_subjects(new)
    assert next(iter(old.values())).path[0] != next(iter(new.values())).path[0]


def test_alias_collision_fails_instead_of_dropping_topics():
    with pytest.raises(DataError, match="collision"):
        parse_curriculum("""
Measures and integral Calculus:
  Part:
    x: Module
Measures and integral calculus:
  Part:
    x: Module
""")


def test_repeated_reference_is_not_a_repeated_topic():
    result = summarise_topics(parse_curriculum("Cat:\n  Part:\n    a: Module\n    b: Module").values())
    assert result["covered"] == result["total"] == 2


def test_unknown_duplicate_legacy_shape_still_fails():
    with pytest.raises(DataError, match="Duplicate"):
        parse_curriculum("Topology:\n  Hilbert spaces:\n    its completeness: lp.complete_space\n"
                         "    its completeness: measure_theory.Lp.complete_space\n")


def test_reviewed_legacy_completeness_entries_are_preserved(monkeypatch):
    content = ("Topology:\n  Hilbert spaces:\n    its completeness: lp.complete_space\n"
               "    its completeness: measure_theory.Lp.complete_space\n"
               "    its completeness: span_fourier_Lp_closure_eq_top\n")
    monkeypatch.setattr(curriculum_legacy, "REVIEWED_BLOBS", {curriculum_legacy.blob_hash(content)})
    topics = parse_curriculum(content)
    assert len(topics) == 3
    assert len({topic.id for topic in topics.values()}) == 3
    assert all(topic.note and topic.covered for topic in topics.values())
    later = parse_curriculum("Topology:\n  Hilbert spaces:\n    completeness of $l^2$: lp.completeSpace\n"
                             "    completeness of $L^2$: MeasureTheory.Lp.instCompleteSpace\n")
    assert later.keys() <= topics.keys()


def test_reviewed_identical_empty_duplicate_is_one_topic(monkeypatch):
    content = ("Single Variable Complex Analysis:\n  Functions on one complex variable:\n"
               "    Cauchy formulas:\n    Cauchy formulas:\n")
    monkeypatch.setattr(curriculum_legacy, "REVIEWED_BLOBS", {curriculum_legacy.blob_hash(content)})
    topics = parse_curriculum(content)
    assert len(topics) == 1
    assert next(iter(topics.values())).note


def test_strict_yaml_rejects_duplicate_nonnested_keys():
    with pytest.raises(DataError, match="Duplicate"):
        load_yaml("Q1: {title: one}\nQ1: {title: two}")


def test_failed_git_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(source_history.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr="fetch failed", stdout=""))
    with pytest.raises(GitError, match="fetch failed"):
        run_git(tmp_path, ["fetch", "origin"])


def test_refresh_does_not_update_a_ref_after_failed_fetch(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    calls = []

    def git(repo, args):
        calls.append(args)
        if args[0] == "remote":
            return "https://example.com/source.git\n"
        raise GitError("offline")

    monkeypatch.setattr(source_history, "run_git", git)
    with pytest.raises(GitError, match="offline"):
        clone_source(tmp_path, "https://example.com/source.git", "master")
    assert not any(args[0] == "update-ref" for args in calls)


def test_clone_never_deletes_an_existing_nonrepository(tmp_path):
    file = tmp_path / "important"
    file.write_text("preserve", encoding="utf-8")
    with pytest.raises(GitError, match="Refusing"):
        clone_source(tmp_path, "https://example.com/source.git", "master")
    assert file.read_text(encoding="utf-8") == "preserve"


def test_failed_serialization_keeps_published_data_and_cleans_temp(tmp_path):
    output = tmp_path / "data.json"
    output.write_text('{"old":true}', encoding="utf-8")
    with pytest.raises(ValueError):
        extractor.write_payload(output, {"bad": float("nan")})
    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["data.json"]


def test_atomic_publication(tmp_path):
    output = tmp_path / "web" / "data.json"
    extractor.write_payload(output, {"schema_version": 2})
    assert json.loads(output.read_text(encoding="utf-8")) == {"schema_version": 2}


def test_source_cutoff_and_mainline_timestamp_order(monkeypatch):
    histories = {
        "old": [("a", utc(2020, 1, 1)), ("b", utc(2021, 1, 1)), ("late", utc(2024, 1, 1))],
        "new": [("c", utc(2023, 7, 1)), ("d", utc(2023, 8, 1)), ("e", utc(2023, 7, 15))],
    }
    monkeypatch.setattr(extractor, "file_history", lambda repo, *_: histories[repo])
    sources = [{"repo": name, "head": "pinned", "name": name} for name in histories]
    result = extractor.combined_history(sources, "docs/undergrad.yaml")
    assert [entry[1] for entry in result] == ["a", "b", "c", "d", "e"]
    assert result[-1][0] == utc(2023, 8, 1)
    assert result[-1][2] == utc(2023, 7, 15)


def test_mainline_history_uses_merge_date_not_feature_branch_date(tmp_path):
    def git(*args, day=None):
        env = dict(os.environ)
        if day:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"2025-01-{day:02}T12:00:00+00:00"
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com",
             *args], capture_output=True, encoding="utf-8", env=env,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    git("init", "-b", "main")
    path = tmp_path / "catalog.yaml"
    path.write_text("initial\n", encoding="utf-8")
    git("add", "catalog.yaml")
    git("commit", "-qm", "initial", day=1)
    git("switch", "-c", "feature")
    path.write_text("changed\n", encoding="utf-8")
    git("commit", "-qam", "feature work", day=2)
    git("switch", "main")
    git("merge", "--no-ff", "feature", "-m", "integrate feature", day=9)
    history = file_history(tmp_path, "main", "catalog.yaml")
    assert [when.day for _, when in history] == [1, 9]
    assert history[-1][0] == git("rev-parse", "HEAD")


def test_schema_v2_producer_replays_and_reconciles():
    from validate_coverage import validate_payload

    before = Topic("t", "Topic", "s", ("Subject", "Part", "Topic"), "unlinked")
    after = Topic("t", "Topic", "s", ("Subject", "Part", "Topic"), "declaration", ("Module",))
    revisions = [
        Revision(utc(2024, 1, 1), "a" * 40, utc(2024, 1, 1), "mathlib4",
                 "https://example.com/commit/a", "Baseline", "documentation_only", {"t": before}),
        Revision(utc(2024, 8, 2), "b" * 40, utc(2024, 8, 2), "mathlib4",
                 "https://example.com/commit/b", "Record a reference", "documentation_only", {"t": after}),
    ]
    now = utc(2025, 2, 8)
    benchmarks = [
        extractor.build_benchmark(key, key, "Description", "Scope", revisions, {"s": "Subject"}, now, {})
        for key in ("named", "undergraduate")
    ]
    data = {"schema_version": 2, "meta": {"generated_at": now.isoformat(), "observed_at": now.isoformat()},
            "benchmarks": benchmarks}
    validate_payload(data)
    wrong = copy.deepcopy(data)
    wrong["benchmarks"][0]["latest"]["overall"]["covered"] += 1
    with pytest.raises(DataError, match="Covered count"):
        validate_payload(wrong)
    wrong = copy.deepcopy(data)
    wrong["benchmarks"][0]["events"][0]["changes"][0][1] = 99
    with pytest.raises(DataError, match="record index"):
        validate_payload(wrong)
