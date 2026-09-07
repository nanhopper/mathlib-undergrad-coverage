#!/usr/bin/env python3
"""Extract the historical undergraduate coverage of mathlib from Git history.

The script reads `docs/undergrad.yaml` out of the *upstream* mathlib4
repository, samples its Git history at monthly intervals, and writes a JSON
file describing, for every snapshot, how many topics are formalised.

Classification
--------------
Each leaf of `undergrad.yaml` is one topic, and its value is classified the
same way mathlib's own `scripts/yaml_check.py` classifies it:

    if entry and "/" not in entry:   # a real Lean declaration

* ``implemented`` -- a Lean declaration name (no ``/``).
* ``external``    -- a URL or path (contains ``/``). These mark topics that are
  *not* formalised in mathlib and merely link to an outside reference.
* ``todo``        -- an empty or missing value.

Counting ``external`` as implemented overstates coverage *and* hides progress:
when a topic is finally formalised its value flips from a URL to a declaration,
which is real work that would otherwise register as no change at all.

Source of truth
---------------
Coverage is always read from upstream mathlib4, never from a local fork, so the
numbers cannot silently freeze because a fork fell behind.

Usage
-----
    # clone upstream into a cache directory and extract
    python3 scripts/extract_undergrad_history.py --clone --output web/data.json

    # reuse an existing checkout
    python3 scripts/extract_undergrad_history.py --repo /path/to/mathlib4
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

UPSTREAM_URL = "https://github.com/leanprover-community/mathlib4.git"
UPSTREAM_REF = "master"
TOPIC_FILE = "docs/undergrad.yaml"

IMPLEMENTED = "implemented"
EXTERNAL = "external"
TODO = "todo"


class GitError(RuntimeError):
    """A git command failed."""


def run_git(repo: Path, args: list[str], *, check: bool = True) -> str:
    """Run git inside `repo` and return stdout."""
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


def clone_upstream(dest: Path, url: str, ref: str) -> None:
    """Create (or refresh) a blobless partial clone of upstream mathlib4.

    A partial clone gives the complete commit history -- which is all that is
    needed to walk `undergrad.yaml` -- while downloading file contents lazily,
    so the whole checkout of mathlib is never transferred.
    """
    if (dest / ".git").exists():
        print(f"refreshing existing clone at {dest}", file=sys.stderr)
        run_git(dest, ["fetch", "--quiet", "origin", ref])
        run_git(dest, ["update-ref", f"refs/heads/{ref}", f"refs/remotes/origin/{ref}"], check=False)
        return

    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"cloning {url} ({ref}) into {dest}", file=sys.stderr)
    result = subprocess.run(
        [
            "git", "clone", "--quiet",
            "--filter=blob:none",  # fetch file contents on demand
            "--no-checkout",       # we only ever read via `git show`
            "--single-branch", "--branch", ref,
            url, str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError(f"clone failed: {result.stderr.strip()}")


def file_history(repo: Path, ref: str, path: str) -> list[tuple[str, datetime]]:
    """Return every commit touching `path`, oldest first, as (sha, date)."""
    output = run_git(
        repo,
        ["log", "--reverse", "--format=%H %ct", ref, "--", path],
    )
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
        # Lean declaration names never contain "/", so a "/" means the value is
        # a URL or file path pointing outside mathlib.
        return EXTERNAL if "/" in text else IMPLEMENTED
    if isinstance(value, (list, tuple)):
        seen = {classify(item) for item in value}
        if IMPLEMENTED in seen:
            return IMPLEMENTED
        return EXTERNAL if EXTERNAL in seen else TODO
    # Any other scalar is an unexpected but non-empty value; treat it as a name.
    return IMPLEMENTED


def count_topics(node: object) -> dict[str, int]:
    """Return topic counts for a subtree of the topic list."""
    # An empty dict is a leaf with nothing in it, not a category with no topics;
    # treating it as a category would silently drop the topic from the totals.
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
    """Parse YAML content into overall and per-category summaries."""
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


def build_timeline(repo: Path, ref: str, path: str) -> list[dict]:
    """Sample the history of `path` at monthly boundaries."""
    history = file_history(repo, ref, path)
    if not history:
        raise GitError(f"no commits touch {path} in {ref}")

    now = datetime.now(timezone.utc)
    snapshots: dict[str, dict | None] = {}
    timeline: list[dict] = []

    for boundary in month_starts(history[0][1], now):
        # The state of the file at `boundary` is set by the last commit before it.
        commit, commit_date = next(
            ((sha, date) for sha, date in reversed(history) if date < boundary),
            (None, None),
        )
        if commit is None:
            continue
        if commit not in snapshots:
            try:
                snapshots[commit] = parse_snapshot(file_at_commit(repo, commit, path))
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
    left as null rather than 0, which would invent a data point and show up as a
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
    parser.add_argument("--repo", default=".mathlib-cache", help="path of the mathlib4 checkout to read")
    parser.add_argument("--clone", action="store_true", help="create or refresh the checkout at --repo")
    parser.add_argument("--url", default=UPSTREAM_URL, help="upstream repository URL")
    parser.add_argument("--ref", default=UPSTREAM_REF, help="ref to read the history from")
    parser.add_argument("--path", default=TOPIC_FILE, help="topic list within the repository")
    parser.add_argument(
        "--max-source-age-days",
        type=int,
        default=7,
        help="fail if the source ref's newest commit is older than this (0 disables)",
    )
    args = parser.parse_args()

    repo = Path(args.repo)
    try:
        if args.clone:
            clone_upstream(repo, args.url, args.ref)
        if not (repo / ".git").exists():
            print(f"error: {repo} is not a git repository (use --clone)", file=sys.stderr)
            return 1

        head = run_git(repo, ["rev-parse", args.ref]).strip()
        head_ts = int(run_git(repo, ["log", "-1", "--format=%ct", args.ref]).strip())
        head_date = datetime.fromtimestamp(head_ts, tz=timezone.utc)

        # Guard against silently publishing stale data: if the source has not
        # moved in a week, we are almost certainly not reading live upstream.
        age = datetime.now(timezone.utc) - head_date
        if args.max_source_age_days and age > timedelta(days=args.max_source_age_days):
            print(
                f"error: source ref {args.ref} is {age.days} days old "
                f"(newest commit {head[:8]} at {head_date.isoformat()}); refusing to publish stale data",
                file=sys.stderr,
            )
            return 1

        timeline = build_timeline(repo, args.ref, args.path)
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
            "source": {
                "repository": args.url,
                "ref": args.ref,
                "head": head[:7],
                "head_date": head_date.strftime("%Y-%m-%d"),
                "path": args.path,
            },
            "history_starts": timeline[0]["date"],
            "total_snapshots": len(timeline),
            "categories": categories,
        },
        "timeline": timeline,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")

    overall = latest["overall"]
    print(
        f"wrote {len(timeline)} snapshots to {output}\n"
        f"latest ({latest['date']}): {overall['implemented']}/{overall['total']} "
        f"= {overall['percentage']}% implemented, "
        f"{overall['external']} external references, {overall['todo']} todo"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
