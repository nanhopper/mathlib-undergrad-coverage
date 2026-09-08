"""Pinned mainline Git observations and checked, non-destructive source refreshes."""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from coverage_model import DataError


class GitError(RuntimeError):
    pass


def run_git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def clone_source(repo: Path, url: str, ref: str, *, partial: bool = True) -> None:
    if (repo / ".git").is_dir():
        origin = run_git(repo, ["remote", "get-url", "origin"]).strip()
        if origin.removesuffix(".git") != url.removesuffix(".git"):
            raise GitError(f"Unexpected origin for {repo}: {origin}")
        run_git(repo, ["fetch", "--quiet", "origin", f"+refs/heads/{ref}:refs/remotes/origin/{ref}"])
        run_git(repo, ["update-ref", f"refs/heads/{ref}", f"refs/remotes/origin/{ref}"])
        return
    if repo.exists():
        raise GitError(f"Refusing to replace a non-repository cache directory: {repo}")
    repo.parent.mkdir(parents=True, exist_ok=True)
    args = ["git", "clone", "--quiet", "--no-checkout", "--single-branch", "--branch", ref]
    if partial:
        args.append("--filter=blob:none")
    result = subprocess.run([*args, url, str(repo)], capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise GitError(f"Clone of {url} failed: {result.stderr.strip()}")


def resolve_source(repo: Path, revision: str) -> tuple[str, datetime]:
    sha = run_git(repo, ["rev-parse", "--verify", f"{revision}^{{commit}}"]).strip()
    timestamp = run_git(repo, ["show", "-s", "--format=%ct", sha]).strip()
    return sha, datetime.fromtimestamp(int(timestamp), timezone.utc)


def file_history(repo: Path, ref: str, path: str) -> list[tuple[str, datetime]]:
    # Only mainline states are observations. A feature branch's earlier commit
    # timestamp is not when its changes became available on the default branch.
    result = run_git(
        repo,
        ["log", "--first-parent", "--diff-merges=first-parent", "--no-patch", "--reverse", "--format=%H %ct",
         ref, "--", path],
    )
    history = []
    for line in result.splitlines():
        sha, timestamp = line.split()
        history.append((sha, datetime.fromtimestamp(int(timestamp), timezone.utc)))
    if not history:
        raise GitError(f"No history for {path} at {ref}")
    return history


def file_at_commit(repo: Path, commit: str, path: str) -> str:
    content = run_git(repo, ["show", f"{commit}:{path}"])
    if not content.strip():
        raise GitError(f"{path} is empty at {commit}")
    return content


def prefetch_file_blobs(repo: Path, sha: str, paths: list[str]) -> None:
    raw = run_git(
        repo, ["log", "--first-parent", "--diff-merges=first-parent", "--raw", "--no-abbrev",
               "--format=", sha, "--", *paths],
    )
    blobs = sorted(set(re.findall(r"^:\d+ \d+ [a-f0-9]{40} ([a-f0-9]{40}) ", raw, re.M)) - {"0" * 40})
    if not blobs:
        raise GitError("No source blobs found for the requested catalog history")
    # Git's lazy-fetch protocol accepts many object IDs at once. Binary input
    # is intentional: Windows text-mode CRLF produces invalid --stdin refspecs.
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "fetch.negotiationAlgorithm=noop", "fetch", "--quiet",
         "origin", "--no-tags", "--no-write-fetch-head", "--recurse-submodules=no",
         "--filter=blob:none", "--stdin"],
        input=("\n".join(blobs) + "\n").encode("ascii"), capture_output=True,
    )
    if result.returncode:
        raise GitError(f"Catalog blob fetch failed: {result.stderr.decode('utf-8')}")


def commit_details(repo: Path, sha: str) -> tuple[str, str]:
    summary = run_git(repo, ["show", "-s", "--format=%s", sha]).strip()
    changed = run_git(
        repo, ["show", "--format=", "--name-only", "--diff-merges=first-parent", sha]
    ).splitlines()
    if any(path.endswith(".lean") and path.startswith(("Mathlib/", "Archive/", "Counterexamples/", "src/"))
           for path in changed):
        context = "source_accompanied"
    elif changed and all(path.startswith("docs/") or path.endswith((".md", ".rst")) for path in changed):
        context = "documentation_only"
    else:
        context = "unknown"
    return summary, context


def taxonomy_files(repo: Path, sha: str) -> dict[str, str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", sha, "_thm", "_data/msc.yml"],
        capture_output=True,
    )
    if result.returncode:
        raise GitError(f"Cannot read taxonomy archive: {result.stderr.decode('utf-8')}")
    files = {}
    # Read the archive in memory; never extract remote paths onto the filesystem.
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        for member in archive.getmembers():
            if member.isfile() and (member.name.endswith(".md") or member.name == "_data/msc.yml"):
                stream = archive.extractfile(member)
                if stream is None:
                    raise DataError(f"Unreadable taxonomy entry: {member.name}")
                files[member.name] = stream.read().decode("utf-8")
    return files
