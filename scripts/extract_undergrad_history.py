#!/usr/bin/env python3
"""Build both coverage benchmarks from pinned upstream Git records.

The command name is retained for existing automation. No observation claims an
exact proof-completion date: it is the state of a curated reference catalog.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from coverage_model import DataError, Revision, SCHEMA_VERSION, Topic, iso
from curriculum_coverage import curriculum_subjects, parse_curriculum
from source_history import (
    GitError,
    clone_source,
    commit_details,
    file_at_commit,
    file_history,
    prefetch_file_blobs,
    resolve_source,
    taxonomy_files,
)

SOURCES = [
    {"name": "mathlib3", "url": "https://github.com/leanprover-community/mathlib.git",
     "ref": "master", "live": False},
    {"name": "mathlib4", "url": "https://github.com/leanprover-community/mathlib4.git",
     "ref": "master", "live": True},
    {"name": "theorem-catalog", "url": "https://github.com/1000-plus/1000-plus.github.io.git",
     "ref": "main", "live": False},
]


def combined_history(sources: list[dict], path: str) -> list[tuple[datetime, str, datetime, dict]]:
    per_source = []
    for source in sources:
        history = file_history(source["repo"], source["head"], path)
        ordered = []
        previous = history[0][1]
        for sha, committed_at in history:
            # Git timestamps need not be monotone. Preserve canonical ancestry
            # and use the earliest consistent mainline observation time.
            observed_at = max(previous, committed_at)
            ordered.append((observed_at, sha, committed_at, source))
            previous = observed_at
        per_source.append(ordered)
    result = []
    for index, history in enumerate(per_source):
        cutoff = per_source[index + 1][0][0] if index + 1 < len(per_source) else None
        result.extend(entry for entry in history if cutoff is None or entry[0] < cutoff)
    return result


def extract_revisions(
    sources: list[dict], path: str, parser: Callable[[str], dict[str, Topic]], now: datetime
) -> list[Revision]:
    revisions = []
    for observed_at, sha, committed_at, source in combined_history(sources, path):
        if observed_at > now:
            continue
        try:
            topics = parser(file_at_commit(source["repo"], sha, path))
        except DataError as exc:
            raise DataError(f"{source['name']}:{sha}:{path}: {exc}") from exc
        summary, context = commit_details(source["repo"], sha)
        revisions.append(Revision(
            at=observed_at, commit=sha, committed_at=committed_at, source=source["name"],
            url=f"{source['url'].removesuffix('.git')}/commit/{sha}",
            summary=summary, context=context, topics=topics,
        ))
    if not revisions:
        raise DataError(f"No observations for {path} at the requested cutoff")
    return revisions


def build_benchmark(
    identifier: str, title: str, description: str, scope: str,
    revisions: list[Revision], subjects: dict[str, str], now: datetime, diagnostics: dict,
) -> dict:
    from coverage_metrics import make_snapshots

    records = []
    interned = {}
    previous = {}
    events = []
    for index, revision in enumerate(revisions):
        current = {}
        for topic in revision.topics.values():
            record = topic.record(revision.source)
            key = json.dumps(record, sort_keys=True, ensure_ascii=True)
            if key not in interned:
                interned[key] = len(records)
                records.append(record)
            current[topic.id] = interned[key]
        changed_ids = sorted(
            key for key in previous.keys() | current.keys() if previous.get(key) != current.get(key)
        )
        events.append({
            "at": iso(revision.at), "committed_at": iso(revision.committed_at),
            "commit": revision.commit, "source": revision.source, "url": revision.url,
            "summary": revision.summary, "context": revision.context, "initial": index == 0,
            "changes": [[key, current.get(key)] for key in changed_ids],
        })
        previous = current
    timeline, latest = make_snapshots(revisions, now)
    if any(topic.subject not in subjects for revision in revisions for topic in revision.topics.values()):
        raise DataError(f"Unlabelled subjects in {identifier}")
    warnings = diagnostics.setdefault("warnings", [])
    if any(revision.at != revision.committed_at for revision in revisions):
        warnings.append("Nonmonotone commit timestamps were ordered by mainline ancestry.")
    return {
        "id": identifier, "title": title, "description": description, "scope": scope,
        "subjects": [{"id": key, "label": label} for key, label in sorted(subjects.items())],
        "records": records, "events": events, "timeline": timeline, "latest": latest,
        "diagnostics": diagnostics,
    }


def generate(sources: list[dict], now: datetime, *, generated_at: datetime | None = None) -> dict:
    from theorem_coverage import parse_taxonomy, parse_theorems, taxonomy_diagnostics

    mathlib3, mathlib4, catalog = sources
    print("Reading the curriculum's mainline history", file=sys.stderr)
    curriculum = extract_revisions([mathlib3, mathlib4], "docs/undergrad.yaml", parse_curriculum, now)
    subjects = {}
    for revision in curriculum:
        subjects.update(curriculum_subjects(revision.topics))
    undergraduate = build_benchmark(
        "undergraduate", "Undergraduate curriculum",
        "A syllabus-derived baseline of undergraduate topics.",
        "Recorded declaration or module references; not a certification of every topic's full scope.",
        curriculum, subjects, now,
        {"warnings": [
            "Checklist edit dates are recording dates, not necessarily formalization dates.",
            "An external or absent reference does not prove the topic is absent from mathlib.",
            "The Lean 3/4 boundary joins checklist records, not independently certified equivalent libraries.",
            "Reviewed legacy duplicate-label repairs preserve distinct Hilbert-space completeness entries. "
            "Only immutable allowlisted Git blobs are repaired; repaired entries carry an evidence note.",
        ]},
    )

    print("Reading the named-theorem catalog and pinned MSC subjects", file=sys.stderr)
    taxonomy = parse_taxonomy(taxonomy_files(catalog["repo"], catalog["head"]))
    theorem_history = extract_revisions(
        [mathlib4], "docs/1000.yaml", lambda text: parse_theorems(text, taxonomy), now,
    )
    diagnostics = taxonomy_diagnostics(theorem_history[-1].topics, taxonomy)
    diagnostics["taxonomy"] = {
        "revision": catalog["head"],
        "url": catalog["url"].removesuffix(".git") + "/tree/" + catalog["head"],
        "note": "All observations use this pinned MSC taxonomy, not historical classifications.",
    }
    diagnostics.setdefault("warnings", []).extend([
        "This catalog began in December 2024. Its initial population/backfills are not new proofs.",
        "The denominator is the mathlib mirror, not a silently substituted canonical catalog.",
        "Named Wikipedia theorems are a benchmark, not a representative sample of all mathematics.",
        "Reviewed immutable historical blobs normalize legacy fields and preserve both references "
        "from a duplicated declaration key. The theorem still counts once; unknown malformed records fail.",
    ])
    used_subjects = {topic.subject for rev in theorem_history for topic in rev.topics.values()}
    subject_names = {key: value for key, value in taxonomy["subjects"].items() if key in used_subjects}
    subject_names["unclassified"] = "Unclassified in the pinned taxonomy"
    named = build_benchmark(
        "named", "1000+ named theorems",
        "A broader benchmark of named theorems, grouped by mathematical subject (MSC).",
        "Recorded declarations in the mathlib repository, including Archive/Counterexamples; "
        "external or unlocated Lean reports and statements are separate.",
        theorem_history, subject_names, now, diagnostics,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "generated_at": iso(generated_at or now), "observed_at": iso(now),
            "sources": [
                {key: (iso(value) if isinstance(value, datetime) else value)
                 for key, value in source.items() if key in ("name", "url", "ref", "head", "head_date")}
                for source in sources
            ],
        },
        "benchmarks": [named, undergraduate],
    }


def write_payload(output: Path, payload: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, prefix=".coverage-", suffix=".json",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="web/data.json")
    parser.add_argument("--cache", default=".mathlib-cache")
    parser.add_argument("--clone", action="store_true", help="create or refresh all upstream caches")
    parser.add_argument("--max-source-age-days", type=int, default=7, help="live source age limit; 0 disables")
    parser.add_argument("--as-of", help="reproducible timezone-qualified observation cutoff (ISO 8601)")
    for name in ("mathlib3", "mathlib4", "catalog"):
        parser.add_argument(f"--{name}-rev", help=f"pin {name} to an existing Git revision")
    args = parser.parse_args()
    try:
        clock = datetime.now(timezone.utc)
        now = datetime.fromisoformat(args.as_of) if args.as_of else clock
        if now.tzinfo is None:
            raise DataError("--as-of must include a timezone")
        now = now.astimezone(timezone.utc)
        if args.max_source_age_days < 0:
            raise DataError("--max-source-age-days cannot be negative")
        sources = []
        for spec, revision in zip(SOURCES, (args.mathlib3_rev, args.mathlib4_rev, args.catalog_rev)):
            source = dict(spec, repo=Path(args.cache) / spec["name"])
            if args.clone:
                print(f"Refreshing {source['name']}", file=sys.stderr)
                clone_source(source["repo"], source["url"], source["ref"], partial=source["name"] != "theorem-catalog")
            if not (source["repo"] / ".git").is_dir():
                raise GitError(f"Missing source cache {source['repo']}; use --clone")
            source["head"], source["head_date"] = resolve_source(source["repo"], revision or source["ref"])
            if source["head_date"] > now:
                raise DataError(f"{source['name']} revision is newer than --as-of; pin an earlier revision")
            if source["live"] and args.max_source_age_days and now - source["head_date"] > timedelta(days=args.max_source_age_days):
                raise DataError(f"{source['name']} revision exceeds the live source age limit")
            sources.append(source)
        if args.clone:
            prefetch_file_blobs(sources[0]["repo"], sources[0]["head"], ["docs/undergrad.yaml"])
            prefetch_file_blobs(sources[1]["repo"], sources[1]["head"], ["docs/undergrad.yaml", "docs/1000.yaml"])
        payload = generate(sources, now, generated_at=clock)
        from validate_coverage import validate_payload

        validate_payload(payload)
        write_payload(Path(args.output), payload)
    except (GitError, DataError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for benchmark in payload["benchmarks"]:
        overall = benchmark["latest"]["overall"]
        print(f"{benchmark['title']}: {overall['covered']}/{overall['total']} "
              f"recorded references ({overall['percentage']:.2f}%)")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
