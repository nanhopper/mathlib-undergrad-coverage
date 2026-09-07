#!/usr/bin/env python3
"""Extract the historical undergraduate coverage of mathlib from Git history.

The topic list `docs/undergrad.yaml` lived in mathlib3
(leanprover-community/mathlib) from 2020-09 until it was ported to mathlib4
(leanprover-community/mathlib4) in July 2023 by #6026. The port was a faithful
copy -- both sides of the boundary hold the same 561 topics with the same 345
formalised -- so the two histories are stitched into one continuous series and
the timeline reaches back to 2020 instead of starting in 2023.

Because a port is not a rename, `git log --follow` cannot cross that boundary;
the two repositories have to be read separately.

Classification
--------------
Each leaf of `undergrad.yaml` is one topic, classified the same way mathlib's
own `scripts/yaml_check.py` classifies it:

    if entry and "/" not in entry:   # a real declaration

* ``implemented`` -- a declaration name (no ``/``).
* ``external``    -- a URL or path (contains ``/``). These mark topics that are
  *not* formalised and merely link to an outside reference.
* ``todo``        -- an empty or missing value.

Counting ``external`` as implemented overstates coverage *and* hides progress:
when a topic is finally formalised its value flips from a URL to a declaration,
which is real work that would otherwise register as no change at all.

Usage
-----
    python3 scripts/extract_undergrad_history.py --clone --output web/data.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# Ordered oldest first. Each source covers the period before the next source's
# history begins, so the segments never overlap.
SOURCES = [
    {
        "name": "mathlib3",
        "url": "https://github.com/leanprover-community/mathlib.git",
        "ref": "master",
        "path": "docs/undergrad.yaml",
        "live": False,  # archived; its HEAD is permanently old
    },
    {
        "name": "mathlib4",
        "url": "https://github.com/leanprover-community/mathlib4.git",
        "ref": "master",
        "path": "docs/undergrad.yaml",
        "live": True,
    },
]

IMPLEMENTED = "implemented"
EXTERNAL = "external"
TODO = "todo"


class GitError(RuntimeError):
    """A git command failed."""


def run_git(repo: Path, args: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        if check:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return ""
    return result.stdout


def clone_source(repo: Path, url: str, ref: str) -> None:
    """Create or refresh a blobless partial clone.

    A partial clone carries the complete commit history -- all that is needed to
    walk one file -- while fetching file contents on demand, so a full mathlib
    checkout is never transferred.
    """
    if (repo / ".git").exists():
        print(f"refreshing {repo}", file=sys.stderr)
        run_git(repo, ["fetch", "--quiet", "origin", ref], check=False)
        run_git(repo, ["update-ref", f"refs/heads/{ref}", f"refs/remotes/origin/{ref}"], check=False)
        return

    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    print(f"cloning {url} ({ref}) into {repo}", file=sys.stderr)
    result = subprocess.run(
        [
            "git", "clone", "--quiet",
            "--filter=blob:none", "--no-checkout",
            "--single-branch", "--branch", ref,
            url, str(repo),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError(f"clone of {url} failed: {result.stderr.strip()}")


def file_history(repo: Path, ref: str, path: str) -> list[tuple[str, datetime]]:
    """Every commit touching `path`, oldest first, as (sha, date)."""
    output = run_git(repo, ["log", "--reverse", "--format=%H %ct", ref, "--", path])
    history = []
    for line in output.splitlines():
        sha, _, ts = line.partition(" ")
        if sha and ts.strip().isdigit():
            history.append((sha, datetime.fromtimestamp(int(ts), tz=timezone.utc)))
    return history


def file_at_commit(repo: Path, commit: str, path: str) -> str:
    content = run_git(repo, ["show", f"{commit}:{path}"], check=False)
    if not content.strip():
        raise GitError(f"{path} is empty or missing at {commit[:8]}")
    return content


def classify(value: object) -> str:
    """Classify one YAML leaf, mirroring mathlib's own `yaml_check.py` rule."""
    if value is None:
        return TODO
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return TODO
        # Declaration names never contain "/", so a "/" means the value points
        # at a URL or file path outside the library.
        return EXTERNAL if "/" in text else IMPLEMENTED
    if isinstance(value, (list, tuple)):
        seen = {classify(item) for item in value}
        if IMPLEMENTED in seen:
            return IMPLEMENTED
        return EXTERNAL if EXTERNAL in seen else TODO
    return IMPLEMENTED


def count_topics(node: object) -> dict[str, int]:
    """Topic counts for a subtree of the topic list."""
    # An empty mapping is a topic with nothing recorded, not a category with no
    # topics; treating it as a category would drop it from the denominator.
    if isinstance(node, dict) and node:
        totals = {IMPLEMENTED: 0, EXTERNAL: 0, TODO: 0}
        for value in node.values():
            for key, count in count_topics(value).items():
                totals[key] += count
        return totals
    counts = {IMPLEMENTED: 0, EXTERNAL: 0, TODO: 0}
    counts[classify(node) if not isinstance(node, dict) else TODO] += 1
    return counts


def summarise(counts: dict[str, int]) -> dict[str, float | int]:
    total = counts[IMPLEMENTED] + counts[EXTERNAL] + counts[TODO]
    return {
        "total": total,
        "implemented": counts[IMPLEMENTED],
        "external": counts[EXTERNAL],
        "todo": counts[TODO],
        "percentage": round(100.0 * counts[IMPLEMENTED] / total, 2) if total else 0.0,
    }


def parse_snapshot(content: str) -> dict | None:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        print(f"warning: could not parse a snapshot: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict) or not data:
        return None

    categories = {}
    overall = {IMPLEMENTED: 0, EXTERNAL: 0, TODO: 0}
    for name, node in data.items():
        counts = count_topics(node)
        categories[str(name)] = summarise(counts)
        for key, count in counts.items():
            overall[key] += count
    return {"overall": summarise(overall), "categories": categories}


def month_starts(first: datetime, last: datetime) -> list[datetime]:
    """First day of every month from the month after `first` through `last`."""
    year, month = first.year, first.month
    dates = []
    while True:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        current = datetime(year, month, 1, tzinfo=timezone.utc)
        if current > last:
            return dates
        dates.append(current)


def combined_history(sources: list[dict]) -> list[tuple[datetime, str, dict]]:
    """Stitch the per-source histories into one chronological list.

    Each source is truncated at the point the next one takes over, so an older
    repository that kept receiving commits after the port cannot reappear once
    the newer one has started.
    """
    per_source = []
    for source in sources:
        history = file_history(source["repo"], source["ref"], source["path"])
        if not history:
            raise GitError(f"no commits touch {source['path']} in {source['name']}")
        per_source.append(history)

    combined: list[tuple[datetime, str, dict]] = []
    for index, (source, history) in enumerate(zip(sources, per_source)):
        cutoff = per_source[index + 1][0][1] if index + 1 < len(sources) else None
        for sha, date in history:
            if cutoff is not None and date >= cutoff:
                continue
            combined.append((date, sha, source))
    combined.sort(key=lambda item: item[0])
    return combined


def build_timeline(sources: list[dict]) -> list[dict]:
    history = combined_history(sources)
    now = datetime.now(timezone.utc)
    snapshots: dict[str, dict | None] = {}
    timeline: list[dict] = []

    for boundary in month_starts(history[0][0], now):
        # The state of the file at `boundary` is set by the last commit before it.
        entry = next(((d, s, src) for d, s, src in reversed(history) if d < boundary), None)
        if entry is None:
            continue
        commit_date, commit, source = entry
        if commit not in snapshots:
            try:
                snapshots[commit] = parse_snapshot(
                    file_at_commit(source["repo"], commit, source["path"])
                )
            except GitError as exc:
                print(f"warning: {exc}", file=sys.stderr)
                snapshots[commit] = None
        snapshot = snapshots[commit]
        if snapshot is None:
            continue
        timeline.append(
            {
                "date": boundary.strftime("%Y-%m-%d"),
                "commit": commit[:7],
                "commit_date": commit_date.strftime("%Y-%m-%d"),
                "source": source["name"],
                "overall": snapshot["overall"],
                "metrics": {"velocity_per_month": None, "acceleration": None},
                "categories": snapshot["categories"],
            }
        )

    add_metrics(timeline)
    return timeline


def add_metrics(timeline: list[dict]) -> None:
    """Fill in velocity (topics/month) and acceleration.

    The first entry has no previous month, so its velocity is undefined; the
    second has no previous velocity, so its acceleration is undefined. Both are
    left null rather than 0, which would invent a data point and read as a
    spurious spike on the chart.
    """
    previous_implemented: int | None = None
    previous_velocity: float | None = None
    for entry in timeline:
        implemented = entry["overall"]["implemented"]
        velocity = None if previous_implemented is None else float(implemented - previous_implemented)
        acceleration = (
            None if velocity is None or previous_velocity is None else velocity - previous_velocity
        )
        entry["metrics"] = {
            "velocity_per_month": None if velocity is None else round(velocity, 2),
            "acceleration": None if acceleration is None else round(acceleration, 2),
        }
        previous_implemented = implemented
        previous_velocity = velocity


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract mathlib undergraduate coverage history.")
    parser.add_argument("--output", default="web/data.json", help="path of the generated JSON file")
    parser.add_argument("--cache", default=".mathlib-cache", help="directory holding the clones")
    parser.add_argument("--clone", action="store_true", help="create or refresh the clones")
    parser.add_argument(
        "--max-source-age-days",
        type=int,
        default=7,
        help="fail if the live source's newest commit is older than this (0 disables)",
    )
    args = parser.parse_args()

    cache = Path(args.cache)
    sources = [dict(source, repo=cache / source["name"]) for source in SOURCES]

    try:
        for source in sources:
            if args.clone:
                clone_source(source["repo"], source["url"], source["ref"])
            if not (source["repo"] / ".git").exists():
                print(f"error: {source['repo']} is not a git repository (use --clone)", file=sys.stderr)
                return 1
            source["head"] = run_git(source["repo"], ["rev-parse", source["ref"]]).strip()
            head_ts = int(run_git(source["repo"], ["log", "-1", "--format=%ct", source["ref"]]).strip())
            source["head_date"] = datetime.fromtimestamp(head_ts, tz=timezone.utc)

        # Only the live source can go stale; the archived one never moves again.
        for source in (s for s in sources if s.get("live")):
            age = datetime.now(timezone.utc) - source["head_date"]
            if args.max_source_age_days and age > timedelta(days=args.max_source_age_days):
                print(
                    f"error: {source['name']} ref {source['ref']} is {age.days} days old "
                    f"(newest commit {source['head'][:8]}); refusing to publish stale data",
                    file=sys.stderr,
                )
                return 1

        timeline = build_timeline(sources)
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not timeline:
        print("error: no snapshot could be extracted", file=sys.stderr)
        return 1

    categories: list[str] = []
    for entry in timeline:
        for name in entry["categories"]:
            if name not in categories:
                categories.append(name)

    latest = timeline[-1]
    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": [
                {
                    "name": s["name"],
                    "repository": s["url"],
                    "ref": s["ref"],
                    "path": s["path"],
                    "head": s["head"][:7],
                    "head_date": s["head_date"].strftime("%Y-%m-%d"),
                }
                for s in sources
            ],
            "history_starts": timeline[0]["date"],
            "total_snapshots": len(timeline),
            "categories": categories,
        },
        "timeline": timeline,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")

    counts = {s["name"]: sum(1 for e in timeline if e["source"] == s["name"]) for s in sources}
    overall = latest["overall"]
    print(
        f"wrote {len(timeline)} snapshots to {output} "
        f"({', '.join(f'{k}: {v}' for k, v in counts.items())})\n"
        f"span {timeline[0]['date']} to {latest['date']}\n"
        f"latest: {overall['implemented']}/{overall['total']} = {overall['percentage']}% formalised, "
        f"{overall['external']} external references, {overall['todo']} todo"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
