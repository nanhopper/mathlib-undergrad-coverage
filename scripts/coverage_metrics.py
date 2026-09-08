"""Calendar observations and comparable rates of recorded catalog coverage.

Monthly states are strictly before their UTC boundary; latest is inclusive of
the supplied, frozen clock. Rates sum every shared-identity covered transition,
including reversals, rather than comparing only endpoint statuses. Their net
therefore reconciles to endpoint counts without discarding intervening edits.

Both adjacent windows use one continuously present cohort. ``excluded`` counts
identities seen anywhere in the paired interval but outside that cohort; subject
cohorts also exclude every identity that changes subject, even temporarily.
Window.flow describes the recent window's full catalog, not just its cohort.
Context labels describe recording commits, never dates of new mathematical proofs.

Input revisions must be a complete sequence of known source states. A long
interval without a catalog edit is not a gap. Missing/unreadable source states
must fail extraction, not be omitted: Revision has no implicit gap sentinel.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from copy import deepcopy
from datetime import datetime, timezone

from coverage_model import DataError, Revision, Topic, iso, subject_summaries, summarise_topics

_MONTHS = (3, 6, 12)
_FLOW_KEYS = (
    "gains", "losses", "added", "removed", "covered_added", "covered_removed",
    "net_covered", "net_total", "documentation_gains", "source_gains", "unknown_gains",
)
_CONTEXT_KEYS = {
    "documentation_only": "documentation_gains",
    "source_accompanied": "source_gains",
    "unknown": "unknown_gains",
}


def _utc(value: datetime, name: str) -> datetime:
    try:
        if isinstance(value, datetime) and value.utcoffset() is not None:
            return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DataError(f"Invalid timezone or timestamp for {name}") from exc
    raise DataError(f"{name} must be a timezone-aware datetime")


def _month_number(value: datetime) -> int:
    return (value.year - 1) * 12 + value.month - 1


def _month_at(number: int) -> datetime | None:
    if not 0 <= number < 9999 * 12:
        return None
    year, month = divmod(number, 12)
    return datetime(year + 1, month + 1, 1, tzinfo=timezone.utc)


def month_starts(first: datetime, last: datetime) -> list[datetime]:
    """Return UTC month boundaries strictly after first and at or before last."""
    first = _utc(first, "First observation")
    last = _utc(last, "Last observation")
    result = []
    for number in range(_month_number(first) + 1, _month_number(last) + 1):
        boundary = _month_at(number)
        if boundary is not None and boundary <= last:
            result.append(boundary)
    return result


def _validate_topics(topics: dict[str, Topic], *, nonempty: bool = False) -> None:
    if not isinstance(topics, dict) or (nonempty and not topics):
        raise DataError("Missing or invalid topic state; history cannot contain an unknown gap")
    for identifier, topic in topics.items():
        if not isinstance(topic, Topic) or not isinstance(identifier, str) or identifier != topic.id:
            raise DataError("Topic state has an invalid or inconsistent identity")
        if any(not isinstance(value, str) or not value.strip()
               for value in (topic.id, topic.label, topic.subject)):
            raise DataError("Topic identity, label, and subject must be nonempty strings")
        try:
            topic.__post_init__()
        except (TypeError, AttributeError) as exc:
            raise DataError(f"Invalid evidence state for {identifier}") from exc


def _empty_flow() -> dict:
    return dict.fromkeys(_FLOW_KEYS, 0)


def _transition(before: dict[str, Topic], after: dict[str, Topic]) -> tuple[dict, set, set]:
    shared = before.keys() & after.keys()
    gained = {key for key in shared if not before[key].covered and after[key].covered}
    lost = {key for key in shared if before[key].covered and not after[key].covered}
    added = after.keys() - before.keys()
    removed = before.keys() - after.keys()
    covered_added = sum(after[key].covered for key in added)
    covered_removed = sum(before[key].covered for key in removed)
    flow = {
        "gains": len(gained),
        "losses": len(lost),
        "added": len(added),
        "removed": len(removed),
        "covered_added": covered_added,
        "covered_removed": covered_removed,
        "net_covered": len(gained) - len(lost) + covered_added - covered_removed,
        "net_total": len(added) - len(removed),
        "documentation_gains": 0,
        "source_gains": 0,
        "unknown_gains": len(gained),
    }
    return flow, gained, lost


def changes_between(before: dict[str, Topic], after: dict[str, Topic]) -> dict:
    """Count status and catalog changes; absent commit context makes gains unknown."""
    _validate_topics(before)
    _validate_topics(after)
    return _transition(before, after)[0]


class _History:
    def __init__(self, revisions: list[Revision]) -> None:
        if not isinstance(revisions, list) or not revisions:
            raise DataError("No catalog history is available")
        self.revisions = revisions
        self.times = []
        for index, revision in enumerate(revisions):
            if not isinstance(revision, Revision):
                raise DataError(f"Missing or invalid revision at index {index}; history has a gap")
            observed = _utc(revision.at, f"Revision {index} observation")
            committed = _utc(revision.committed_at, f"Revision {index} commit")
            if self.times and observed < self.times[-1]:
                raise DataError("Revisions must be in chronological mainline observation order")
            if committed > observed:
                raise DataError(f"Revision {index} commit timestamp is after its observation")
            if not isinstance(revision.commit, str) or not re.fullmatch(
                r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", revision.commit
            ):
                raise DataError(f"Revision {index} must identify a full commit SHA")
            if not isinstance(revision.source, str) or not revision.source.strip():
                raise DataError(f"Revision {index} has no source identity")
            if not isinstance(revision.context, str) or revision.context not in _CONTEXT_KEYS:
                raise DataError(f"Revision {index} has an invalid recording context")
            _validate_topics(revision.topics, nonempty=True)
            self.times.append(observed)

        # Index zero is an observed baseline, not a coverage-production event.
        self.prefix = [_empty_flow()]
        self.gains = [set()]
        self.losses = [set()]
        for before, after in zip(revisions, revisions[1:]):
            flow, gained, lost = _transition(before.topics, after.topics)
            flow["unknown_gains"] = 0
            flow[_CONTEXT_KEYS[after.context]] = flow["gains"]
            self.prefix.append({key: self.prefix[-1][key] + flow[key] for key in _FLOW_KEYS})
            self.gains.append(gained)
            self.losses.append(lost)

    def before(self, boundary: datetime) -> int:
        return bisect_left(self.times, boundary) - 1

    def flow(self, first: int, last: int) -> dict:
        return {key: self.prefix[last][key] - self.prefix[first][key] for key in _FLOW_KEYS}


def _rate(history: _History, first: int, last: int, cohort: set[str], months: int) -> dict:
    gains = sum(len(history.gains[index] & cohort) for index in range(first + 1, last + 1))
    losses = sum(len(history.losses[index] & cohort) for index in range(first + 1, last + 1))
    net = gains - losses
    endpoint_net = sum(
        history.revisions[last].topics[key].covered - history.revisions[first].topics[key].covered
        for key in cohort
    )
    if net != endpoint_net:
        raise DataError("Continuous-cohort transitions do not reconcile to endpoint coverage")
    return {
        "gains": gains,
        "losses": losses,
        "net": net,
        "per_month": net / months,
        "percentage_points": 100 * net / len(cohort),
    }


def _comparison(
    history: _History, first: int, middle: int, last: int,
    cohort: set[str], excluded: int, months: int,
) -> dict:
    recent = _rate(history, middle, last, cohort, months)
    prior = _rate(history, first, middle, cohort, months)
    return {
        "cohort_size": len(cohort),
        "excluded": excluded,
        "recent": recent,
        "prior": prior,
        "pace_change": recent["per_month"] - prior["per_month"],
    }


def _window(history: _History, end: datetime, months: int) -> dict:
    result = {
        "available": False,
        "reason": None,
        "months": months,
        "start": None,
        "end": end.date().isoformat(),
        "prior_start": None,
        "overall": None,
        "subjects": {},
        "flow": None,
    }
    last = history.before(end)
    if last < 0:
        result["reason"] = "No closed monthly observation is available for this catalog yet."
        return result

    start = _month_at(_month_number(end) - months)
    prior_start = _month_at(_month_number(end) - 2 * months)
    result["start"] = start.date().isoformat() if start is not None else None
    result["prior_start"] = prior_start.date().isoformat() if prior_start is not None else None
    if start is None or prior_start is None:
        result["reason"] = f"Insufficient calendar history for two complete {months}-month windows."
        return result
    first = history.before(prior_start)
    if first < 0:
        result["reason"] = (
            f"Insufficient history: two complete {months}-month windows require a baseline "
            f"before {prior_start.date().isoformat()}; catalog history begins {iso(history.times[0])}."
        )
        return result
    middle = history.before(start)

    baseline = history.revisions[first].topics
    cohort = set(baseline)
    stable_subjects = {key: topic.subject for key, topic in baseline.items()}
    seen = set()
    seen_by_subject: dict[str, set[str]] = {}
    for revision in history.revisions[first:last + 1]:
        cohort.intersection_update(revision.topics)
        seen.update(revision.topics)
        for key in list(stable_subjects):
            topic = revision.topics.get(key)
            if topic is None or topic.subject != stable_subjects[key]:
                del stable_subjects[key]
        for key, topic in revision.topics.items():
            seen_by_subject.setdefault(topic.subject, set()).add(key)
    if not cohort:
        result["reason"] = "No common cohort remains continuously present across both complete windows."
        return result

    by_subject: dict[str, set[str]] = {}
    for key, subject in stable_subjects.items():
        by_subject.setdefault(subject, set()).add(key)
    result.update({
        "available": True,
        "overall": _comparison(history, first, middle, last, cohort, len(seen) - len(cohort), months),
        "subjects": {
            subject: _comparison(
                history, first, middle, last, members, len(seen_by_subject[subject]) - len(members),
                months,
            )
            for subject, members in sorted(by_subject.items())
        },
        "flow": history.flow(middle, last),
    })
    return result


def _snapshot(
    history: _History, index: int, at: datetime, kind: str,
    previous: int | None, windows: dict,
) -> dict:
    revision = history.revisions[index]
    return {
        "date": at.date().isoformat(),
        "as_of": iso(at),
        "kind": kind,
        "event_index": index,
        "source": revision.source,
        "commit": revision.commit,
        "commit_date": iso(revision.committed_at),
        "overall": summarise_topics(revision.topics.values()),
        "subjects": subject_summaries(revision.topics),
        "flow": history.flow(previous, index) if previous is not None else None,
        "windows": windows,
    }


def make_snapshots(revisions: list[Revision], now: datetime) -> tuple[list[dict], dict]:
    """Build monthly and latest observations without sorting or reindexing events."""
    now = _utc(now, "Latest observation")
    history = _History(revisions)
    latest_index = bisect_right(history.times, now) - 1
    if latest_index < 0:
        raise DataError("No catalog observation exists at or before the requested latest cutoff")

    timeline = []
    previous = None
    for boundary in month_starts(history.times[0], now):
        index = history.before(boundary)
        windows = {str(months): _window(history, boundary, months) for months in _MONTHS}
        timeline.append(_snapshot(history, index, boundary, "monthly", previous, windows))
        previous = index

    if timeline:
        windows = deepcopy(timeline[-1]["windows"])
    else:
        boundary = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        windows = {str(months): _window(history, boundary, months) for months in _MONTHS}
    latest = _snapshot(history, latest_index, now, "latest", previous, windows)
    return timeline, latest
