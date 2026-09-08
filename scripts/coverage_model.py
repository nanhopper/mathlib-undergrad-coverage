"""Shared evidence model and schema-v2 dashboard contract.

The payload has ``schema_version``, ``meta`` (generated_at, observed_at, sources),
and a ``benchmarks`` array. Each benchmark has id/title/description/scope,
subjects [{id, label}], records [Topic records], events, timeline, latest, and
diagnostics. Records are interned; an event's changes are [topic_id, record_index]
pairs (null removes a topic). Replay events through snapshot.event_index to get
the exact evidence at that observation, including historical names/references.

Snapshots have date, as_of, event_index, source, commit, commit_date, overall,
subjects, flow, and windows. Summaries have total, covered, percentage (null for
an empty catalog), and statuses. Windows are keyed by "3", "6", "12"; see
coverage_metrics.py. A latest snapshot is separate from closed monthly cutoffs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlsplit

import yaml

SCHEMA_VERSION = 2
STATUSES = ("declaration", "module", "external", "unlinked", "reported", "statement", "qualified")
COVERED = frozenset(("declaration", "module"))


class DataError(ValueError):
    """Required source data is invalid; publishing a partial result is unsafe."""


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, (str, int)) or isinstance(key, bool):
            raise DataError(f"Unsupported YAML key at line {key_node.start_mark.line + 1}")
        if key in result:
            raise DataError(f"Duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_yaml(content: str) -> dict:
    try:
        result = yaml.load(content, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise DataError(f"Invalid YAML: {exc}") from exc
    if not isinstance(result, dict) or not result:
        raise DataError("Expected a nonempty YAML mapping")
    return result


def is_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise DataError(f"Malformed reference URL: {value!r}") from exc
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise DataError("Observation timestamps must have a timezone")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    subject: str
    path: tuple[str, ...]
    status: str
    references: tuple[str, ...] = ()
    note: str = ""
    reported_date: str | None = None
    authors: str | None = None

    def __post_init__(self) -> None:
        if not self.id or not self.label or not self.subject:
            raise DataError("Topic identity, label, and subject must be nonempty")
        if self.status not in STATUSES:
            raise DataError(f"Unsupported evidence status {self.status!r}")
        if any(not isinstance(ref, str) or not ref.strip() for ref in self.references):
            raise DataError(f"Invalid reference on {self.id}")
        if self.status in COVERED and not self.references:
            raise DataError(f"Covered topic {self.id} has no recorded reference")

    @property
    def covered(self) -> bool:
        return self.status in COVERED

    def record(self, source: str) -> dict:
        return {**asdict(self), "source": source}


@dataclass
class Revision:
    at: datetime
    commit: str
    committed_at: datetime
    source: str
    url: str
    summary: str
    context: str
    topics: dict[str, Topic]

    def __post_init__(self) -> None:
        if not self.topics or any(key != topic.id for key, topic in self.topics.items()):
            raise DataError("A revision must have nonempty, consistently identified topics")
        if self.context not in ("documentation_only", "source_accompanied", "unknown"):
            raise DataError(f"Unknown commit context {self.context}")
        iso(self.at)
        iso(self.committed_at)


def summarise_topics(topics: Iterable[Topic]) -> dict:
    statuses = dict.fromkeys(STATUSES, 0)
    for topic in topics:
        statuses[topic.status] += 1
    total = sum(statuses.values())
    covered = sum(statuses[status] for status in COVERED)
    return {
        "total": total,
        "covered": covered,
        "percentage": 100 * covered / total if total else None,
        "statuses": statuses,
    }


def subject_summaries(topics: dict[str, Topic]) -> dict[str, dict]:
    groups: dict[str, list[Topic]] = {}
    for topic in topics.values():
        groups.setdefault(topic.subject, []).append(topic)
    return {subject: summarise_topics(group) for subject, group in sorted(groups.items())}
