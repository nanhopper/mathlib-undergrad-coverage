"""The syllabus is a reference checklist, not a certificate of mathematical absence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from coverage_model import DataError, Topic, is_http_url
from curriculum_legacy import load_curriculum

SUBJECT_ALIASES = {
    "Measures and integral Calculus": "Measures and integral calculus",
    "Affine and Euclidian Geometry": "Affine and Euclidean Geometry",
}


def classify(value: object) -> str:
    if value is None:
        return "unlinked"
    if not isinstance(value, str):
        raise DataError(f"Expected a declaration, module path, URL, or empty leaf; got {value!r}")
    text = value.strip()
    if not text:
        return "unlinked"
    if is_http_url(text):
        url = urlsplit(text)
        internal = url.hostname == "leanprover-community.github.io" and url.path.startswith(
            ("/mathlib_docs/", "/mathlib4_docs/")
        )
        return "module" if internal else "external"
    if "/" in text:
        path = urlsplit(text).path
        if (
            path.endswith(".html")
            and not path.startswith("/")
            and ".." not in PurePosixPath(path).parts
            and not re.search(r"\s|\\", path)
        ):
            return "module"
        raise DataError(f"Unrecognized module reference {text!r}")
    if not re.fullmatch(r"[^\s/:#]+", text):
        raise DataError(f"Unrecognized declaration reference {text!r}")
    return "declaration"


def _leaves(node: object, path: tuple[str, ...] = ()):
    if isinstance(node, dict) and node:
        for name, child in node.items():
            if not isinstance(name, str) or not name.strip():
                raise DataError(f"Invalid topic label at {path}: {name!r}")
            yield from _leaves(child, path + (name,))
    else:
        # An explicitly empty mapping is retained as an unlinked topic, not
        # dropped from the historical denominator.
        yield path, None if node == {} else node


def parse_curriculum(content: str) -> dict[str, Topic]:
    topics = {}
    paths = {}
    data, notes = load_curriculum(content)
    for path, value in _leaves(data):
        if len(path) < 3:
            raise DataError(f"Expected subject/section/topic nesting: {path}")
        canonical = (SUBJECT_ALIASES.get(path[0], path[0]), *path[1:])
        subject = re.sub(r"[^a-z0-9]+", "-", canonical[0].lower()).strip("-")
        key = hashlib.sha256(json.dumps(canonical, ensure_ascii=True).encode("utf-8")).hexdigest()[:20]
        if key in topics:
            raise DataError(f"Topic alias/identity collision between {paths[key]} and {path}")
        paths[key] = path
        text = value.strip() if isinstance(value, str) else ""
        topics[key] = Topic(
            id=key,
            label=path[-1],
            subject=subject,
            path=path,
            status=classify(value),
            references=(text,) if text else (),
            note=notes.get(path, ""),
        )
    return topics


def curriculum_subjects(topics: dict[str, Topic]) -> dict[str, str]:
    subjects = {}
    for topic in topics.values():
        label = SUBJECT_ALIASES.get(topic.path[0], topic.path[0])
        if topic.subject in subjects and subjects[topic.subject] != label:
            raise DataError(f"Subject identity collision for {label}")
        subjects[topic.subject] = label
    return subjects
