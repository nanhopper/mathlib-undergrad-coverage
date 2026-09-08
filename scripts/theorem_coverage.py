"""Adapt recorded theorem evidence without certifying proofs or replacing the mirror."""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date, datetime

from coverage_model import DataError, Topic, is_http_url, load_yaml

_WIKIDATA = re.compile(r"Q[0-9]+")
_THEOREM_ID = re.compile(r"Q[0-9]+[A-Za-z0-9]*")
_SUFFIX = re.compile(r"[A-Za-z0-9]+")
_MSC_CODE = re.compile(r"[0-9]{2}")
_DECLARATION = re.compile(r"[^\W\d][\w']*(?:\.[^\W\d][\w']*)*")
_DATE = re.compile(
    r"(?P<year>[0-9]{4})(?:(?P<separator>[-/])(?P<month>[0-9]{2})"
    r"(?:(?P=separator)(?P<day>[0-9]{2}))?)?"
)
_THEOREM_FIELDS = frozenset(
    ("title", "decl", "decls", "statement", "authors", "date", "url", "comment")
)
_PROVERS = frozenset(("isabelle", "hol_light", "rocq", "coq", "lean", "metamath", "mizar"))
_TAXONOMY_FIELDS = frozenset(
    ("wikidata", "id_suffix", "msc_classification", "wikipedia_links")
) | _PROVERS
_REPORT_FIELDS = frozenset(
    ("status", "library", "url", "authors", "identifiers", "date", "comment")
)
# Reviewed file blobs before the author -> authors correction in mathlib PR #20875.
# Earlier blobs also use note and external identifiers; these are not global aliases.
_LEGACY_BLOBS = frozenset((
    "8126486a00af974ee7216bb82bbced2ef6bee685",  # 93a38c113b9d, 2024-12-09
    "de096445b0516a84632cf087b1c9b3f6bb53dd01",  # 7669cc54f7c5
    "1eec82b710f9a94445c0d01208bf64b1b3427e86",  # 7987fe32ae08
    "eac9c1974558aa6293f5250a7742350a0b9d6dc2",  # ea4f170a3aa5
    "08b01979d53fe8107414053ddc2afc6411b7a253",  # fcdc29cb3e23
    "27d543c4435d4c22caac26231ab384c4485e9382",  # e518dee122a6
    "64168a6a6f4ae1f7a00eecd13ef08e801ef2e04a",  # 2e72e436be9e
    "50d0e3fb4af8f93ee9416750e87c4185ad339a95",  # a57f31753dde
    "b7f982e4112d6eb5bd4f33701fb32506d51e071d",  # 9ab795afa4a2
    "8261bce58958b2111715028c56a5826da63939c9",  # ab7742ecee7a
    "6fbfe1d7a786a647ee9b7c2a639960c46a99cd47",  # 425a48954db3
    "a1aecd443a62cff95e0d4c50e7ea41902f9f2468",  # 3c8e6314aab6
    "d2a6645ea7a964bac98ecb95baa57747b62dc578",  # 3f57df84d5d9, 2025-01-20
))
# Q776578 repeated decl from 2025-08-14 until the upstream correction in
# aa1dd647d3ccbb52a3e562dfb54d460cb96ea64e (PR #36001). Preserve both references
# using that exact correction, only in these reviewed immutable file blobs.
_DUPLICATE_DECL_BLOBS = frozenset((
    "a52d13c97c483ad1afb5e72d1b12e0e33571ea3c",
    "2f6aabec8c7b1999bcb1a7d599cbc8e29d07f7ca",
    "9d5347e3951021f91725c5f7c98c349fb77d4aa5",
    "a7f1dd10544e45ed8e67664f1d80422ac5490373",
    "77aff145cd507f431728adaaad6db06c1a75f415",
    "baac11d1263d777fb7d75580ddb1f2326ae3d0c0",
    "013f80ab45569407eed12d590bf2dc599884f61d",
    "f93d12c10fd753dcda9dab32e42c4c7efde74b9b",
    "49154160a657b793b5be36709afc191b8de4260c",
    "79083201f67560873780748319320c061d310791",
    "091f29feb624adfa89e62c2e9b8ac4a8b9a4d218",
    "d4d2837798e96f53834a2a73e4b77cf93e309e8d",
    "a856115f562a624921b20c65f22ecd63512fb347",
    "aa7b9b61a1edacbf2f1ef1375d8f63fb473bc43e",
    "53e010419ac21d260f74c22e255c338f8ddb29a8",
    "cca5cca40625c7e5e20dd48eade1c0e411f546ee",
    "02fc9bb9d63fc163523858b8cc62414d391c69cc",
    "c23bf6c506e6ac2a2895628f023240f8334ed213",
    "6f032d32e76df4e94c9381e143a6a67a9fe77c73",
    "d983387008c6a1e67d4c9969ec62335caa6441c9",
    "9b34087813bb77277431bb911619258467a08afd",
    "b9b44a358fad881f9a7db9de19b4e405d18c6c53",
    "92f10e1494cbdbcdda1ca5d8e170acf4df840caa",
    "7f8764925f71344b2e27bc9d74192678bd3b22cf",
    "1bffe6a9e5682dfbda3b6d21ac479b6d04197400",
    "645d41ba117198116756667ddc9a3586fee82258",
    "fc0ed80cf4314dccd5c7abc6874a01b81ce81eab",
    "cb885c00aae493b924f1a0b8b8c882df9935ff57",
    "ecf405d62ca60176cd34704e614d68410c800449",
    "430d09e47551d938ceacb80a9fde20b265034d0d",
    "5db947413b9567156bdf5ed16074c1711c60627a",
    "605385f399f7ce4034ebcead5f87eedb21d4799e",
    "fad5559254b79cdad8f6501bee13d95fa183fb32",
    "56b5459b2df9bccb9b5ceecf2e203cd8a0db8d0c",
    "484778ce17024a62c3666cb20e65301b169a94dc",
    "0fa798596a8ad2b7cede7c1849b6cf3df9ab0b7a",
    "beab513235bc3255e1c8e62a345ceb26143d0350",
    "d0bea9dfdf9afd24388bddd35de5e6214ef0e693",
    "2336f8c97b96f84f2fe00864786c7e5936b0265d",
    "779277ac26a218f6f198e70454ac1596427e2df7",
    "e6738ca6f8f2a274fb82e2f0eadda76b46e23784",
    "22a798e444f813536ef96d28b926787d66ce7676",
    "5021dba80eca1d451cca3e734c325526d733e187",
    "52386abf9a52eda20b2c0dc7f65b04eb7db6ed0b",
    "1773201db20029f52ca792f894ab32c4a1cb761c",
    "248d4ae1c34d890732b87799d27e073dd5111bbf",
    "cdadea06e1766702bc919899743a96aa5e4721a2",
))
_DUPLICATE_DECL_BLOCK = (
    "Q776578:\n"
    "  title: Wedderburn–Artin theorem\n"
    "  decl: IsSimpleRing.exists_algEquiv_matrix_divisionRing\n"
    "  decl: IsSemisimpleRing.exists_algEquiv_pi_matrix_divisionRing\n"
)
_CORRECTED_DECL_BLOCK = (
    "Q776578:\n"
    "  title: Wedderburn–Artin theorem\n"
    "  decls:\n"
    "    - IsSimpleRing.exists_algEquiv_matrix_divisionRing\n"
    "    - IsSemisimpleRing.exists_algEquiv_pi_matrix_divisionRing\n"
)
_DUPLICATE_DECL_NOTE = (
    "Historical duplicate decl keys repaired using leanprover-community/mathlib4#36001; "
    "both recorded declarations are preserved and the theorem is counted once."
)


def _mapping(content: str, context: str) -> dict:
    if not isinstance(content, str):
        raise DataError(f"{context}: expected UTF-8 text")
    try:
        return load_yaml(content)
    except (ValueError, TypeError, OverflowError) as exc:
        # PyYAML's timestamp constructor can raise ValueError, not YAMLError.
        raise DataError(f"{context}: {exc}") from exc


def _known_fields(value: dict, allowed: frozenset[str], context: str) -> None:
    unknown = value.keys() - allowed
    if unknown:
        raise DataError(f"{context}: unsupported fields {sorted(map(repr, unknown))}")


def _text(value: object, context: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise DataError(f"{context}: expected a string or null")
    return value


def _text_list(value: object, context: str) -> None:
    if value is not None and (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise DataError(f"{context}: expected a list of nonempty strings or null")


def _url(value: object, context: str) -> str | None:
    text = _text(value, context)
    if text is None or not text.strip():
        return None
    text = text.strip()
    if re.search(r"\s|\\", text) or not is_http_url(text):
        raise DataError(f"{context}: expected an HTTP(S) URL, got {text!r}")
    return text


def _reported_date(value: object, context: str) -> str | None:
    if value is None:
        return None
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, (bool, datetime)) or not isinstance(value, (str, int)):
        raise DataError(f"{context}: expected a reported year or calendar date")
    text = str(value).strip()
    if not text:
        return None
    # The mirror also records multiple reported years, e.g. "2019, 2021".
    for part in text.split(","):
        match = _DATE.fullmatch(part.strip())
        if match is None:
            raise DataError(f"{context}: invalid reported date {text!r}")
        year = int(match["year"])
        month = int(match["month"]) if match["month"] else None
        day = int(match["day"]) if match["day"] else None
        if not year or (month is not None and not 1 <= month <= 12):
            raise DataError(f"{context}: invalid reported date {text!r}")
        if day is not None and not 1 <= day <= calendar.monthrange(year, month)[1]:
            raise DataError(f"{context}: invalid reported date {text!r}")
    return text


def _subjects(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise DataError("MSC subjects must be a mapping of two-digit strings to labels")
    for code, label in value.items():
        if not isinstance(code, str) or not _MSC_CODE.fullmatch(code):
            raise DataError(f"MSC code must be a two-digit string, got {code!r}")
        if not isinstance(label, str) or not label.strip():
            raise DataError(f"MSC {code}: expected a nonempty subject label")
    return dict(sorted(value.items()))


def _front_matter(content: str, path: str) -> dict:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise DataError(f"{path}: missing opening --- front-matter fence")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise DataError(f"{path}: missing closing --- front-matter fence") from exc
    return _mapping("\n".join(lines[1:end]), path)


def _validate_canonical_metadata(data: dict, path: str) -> None:
    _known_fields(data, _TAXONOMY_FIELDS, path)
    _text_list(data.get("wikipedia_links"), f"{path} wikipedia_links")
    for prover in sorted(_PROVERS & data.keys()):
        reports = data[prover]
        if reports is None:
            continue
        if not isinstance(reports, list):
            raise DataError(f"{path} {prover}: expected a list of report mappings")
        for index, report in enumerate(reports):
            context = f"{path} {prover}[{index}]"
            if not isinstance(report, dict):
                raise DataError(f"{context}: expected a report mapping")
            _known_fields(report, _REPORT_FIELDS, context)
            if report.get("status") not in ("formalized", "statement"):
                raise DataError(f"{context}: unsupported canonical report status")
            if report.get("library") not in ("S", "L", "X"):
                raise DataError(f"{context}: unsupported canonical report library")
            if _url(report.get("url"), f"{context} url") is None:
                raise DataError(f"{context}: missing canonical report URL")
            _text_list(report.get("authors"), f"{context} authors")
            _text_list(report.get("identifiers"), f"{context} identifiers")
            _reported_date(report.get("date"), f"{context} date")
            _text(report.get("comment"), f"{context} comment")


def parse_taxonomy(files: dict[str, str]) -> dict:
    """Read pinned canonical Git contents; never use canonical reports as coverage."""
    if not isinstance(files, dict) or "_data/msc.yml" not in files:
        raise DataError("Canonical taxonomy is missing _data/msc.yml")
    for path, content in files.items():
        if (
            not isinstance(path, str)
            or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/"))
        ):
            raise DataError(f"Expected a repo-relative POSIX Git path, got {path!r}")
        if not isinstance(content, str):
            raise DataError(f"{path}: expected UTF-8 text")
    subjects = _subjects(_mapping(files["_data/msc.yml"], "_data/msc.yml"))
    paths = sorted(path for path in files if path.startswith("_thm/") and path.endswith(".md"))
    if not paths:
        raise DataError("Canonical taxonomy has no _thm/*.md records")
    assignments = {}
    for path in paths:
        data = _front_matter(files[path], path)
        wikidata = data.get("wikidata")
        if not isinstance(wikidata, str) or not _WIKIDATA.fullmatch(wikidata):
            raise DataError(f"{path}: invalid wikidata identifier {wikidata!r}")
        suffix = _text(data.get("id_suffix"), f"{path} id_suffix") or ""
        if suffix and not _SUFFIX.fullmatch(suffix):
            raise DataError(f"{path}: invalid alphanumeric id_suffix {suffix!r}")
        theorem_id = wikidata + suffix
        if theorem_id in assignments:
            raise DataError(f"Canonical theorem identity collision: {theorem_id}")
        if path != f"_thm/{theorem_id}.md":
            raise DataError(f"{path}: theorem ID {theorem_id!r} does not match its file path")
        subject = data.get("msc_classification")
        if not isinstance(subject, str) or subject not in subjects:
            raise DataError(f"{path}: unrecognized MSC subject {subject!r}")
        _validate_canonical_metadata(data, path)
        assignments[theorem_id] = subject
    return {
        "subjects": subjects,
        "assignments": dict(sorted(assignments.items())),
        "ids": sorted(assignments),
    }


def _taxonomy_parts(taxonomy: dict) -> tuple[dict, dict, set[str]]:
    if not isinstance(taxonomy, dict):
        raise DataError("Expected a canonical taxonomy mapping")
    subjects = _subjects(taxonomy.get("subjects"))
    assignments, ids = taxonomy.get("assignments"), taxonomy.get("ids")
    if not isinstance(assignments, dict) or not isinstance(ids, list):
        raise DataError("Taxonomy requires an assignments mapping and an IDs list")
    if any(not isinstance(key, str) or not _THEOREM_ID.fullmatch(key) for key in ids):
        raise DataError("Taxonomy contains an invalid theorem ID")
    if len(set(ids)) != len(ids):
        raise DataError("Taxonomy contains duplicate theorem IDs")
    if set(ids) != assignments.keys():
        raise DataError("Taxonomy IDs and subject assignments disagree")
    if any(not isinstance(code, str) or code not in subjects for code in assignments.values()):
        raise DataError("Taxonomy assignments contain an unrecognized MSC subject")
    return subjects, assignments, set(ids)


def _declaration(value: object, context: str) -> str | None:
    text = _text(value, context)
    if text is None or not text.strip():
        return None
    text = text.strip()
    if not _DECLARATION.fullmatch(text):
        raise DataError(f"{context}: invalid declaration name {text!r}")
    return text


def _declarations(value: object, context: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise DataError(f"{context}: expected a list of declaration names")
    references = []
    for item in value:
        reference = _declaration(item, context)
        if reference is None:
            raise DataError(f"{context}: declaration names must be nonempty")
        references.append(reference)
    return tuple(references)


def _blob_hash(content: str) -> str:
    raw = content.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def _legacy_record(record: dict, theorem_id: str) -> dict:
    record = dict(record)
    for old, new in (("author", "authors"), ("note", "comment")):
        if old in record:
            if new in record:
                raise DataError(f"{theorem_id}: legacy {old}/{new} identity collision")
            record[new] = record.pop(old)
    if "identifiers" in record:
        value = record.pop("identifiers")
        identifiers = _declarations(
            [value] if isinstance(value, str) else value, f"{theorem_id} identifiers",
        )
        if identifiers:
            note = _text(record.get("comment"), f"{theorem_id} comment") or ""
            explanation = (
                "Legacy source identifiers (not treated as mathlib declarations): "
                + ", ".join(identifiers) + "."
            )
            record["comment"] = f"{note}\n{explanation}" if note else explanation
    return record


def parse_theorems(content: str, taxonomy: dict) -> dict[str, Topic]:
    """Keep the mathlib mirror's IDs and classify only its recorded evidence."""
    subjects, assignments, _ = _taxonomy_parts(taxonomy)
    if not isinstance(content, str):
        raise DataError("docs/1000.yaml: expected UTF-8 text")
    source_blob = _blob_hash(content)
    repaired = source_blob in _DUPLICATE_DECL_BLOBS
    if repaired:
        if content.count(_DUPLICATE_DECL_BLOCK) != 1:
            raise DataError("Reviewed duplicate-declaration repair does not match Q776578")
        content = content.replace(_DUPLICATE_DECL_BLOCK, _CORRECTED_DECL_BLOCK, 1)
    data = _mapping(content, "docs/1000.yaml")
    legacy = source_blob in _LEGACY_BLOBS
    topics = {}
    for theorem_id, record in data.items():
        if not isinstance(theorem_id, str) or not _THEOREM_ID.fullmatch(theorem_id):
            raise DataError(f"Invalid mirror theorem ID {theorem_id!r}")
        if not isinstance(record, dict):
            raise DataError(f"{theorem_id}: expected a theorem mapping")
        if legacy:
            record = _legacy_record(record, theorem_id)
        _known_fields(record, _THEOREM_FIELDS, theorem_id)
        title = _text(record.get("title"), f"{theorem_id} title")
        if title is None or not title.strip():
            raise DataError(f"{theorem_id}: title must be a nonempty string")
        decl = _declaration(record.get("decl"), f"{theorem_id} decl")
        decls = _declarations(record.get("decls"), f"{theorem_id} decls")
        statement = _declaration(record.get("statement"), f"{theorem_id} statement")
        if decl and decls:
            raise DataError(f"{theorem_id}: decl and decls are mutually exclusive")
        references = (decl,) if decl else decls
        if references and statement:
            raise DataError(f"{theorem_id}: contradictory declaration and statement evidence")
        authors = _text(record.get("authors"), f"{theorem_id} authors")
        if authors is not None and not authors.strip():
            authors = None
        url = _url(record.get("url"), f"{theorem_id} url")
        note = _text(record.get("comment"), f"{theorem_id} comment") or ""
        if repaired and theorem_id == "Q776578":
            note = f"{note}\n{_DUPLICATE_DECL_NOTE}" if note else _DUPLICATE_DECL_NOTE
        reported_date = _reported_date(record.get("date"), f"{theorem_id} date")
        if references:
            status = "declaration"
        elif statement:
            status, references = "statement", (statement,)
        elif authors:
            status, references = "reported", (url,) if url else ()
        elif url:
            status, references = "qualified", (url,)
        else:
            status = "unlinked"
        if url and url not in references:
            references += (url,)
        subject = assignments.get(theorem_id, "unclassified")
        topics[theorem_id] = Topic(
            id=theorem_id,
            label=title,
            subject=subject,
            path=(subjects.get(subject, "Unclassified"), title),
            status=status,
            references=references,
            note=note,
            reported_date=reported_date,
            authors=authors,
        )
    return topics


def taxonomy_diagnostics(topics: dict[str, Topic], taxonomy: dict) -> dict:
    """Reconcile universes without aliases, additions, removals, or denominator changes."""
    _, _, canonical_ids = _taxonomy_parts(taxonomy)
    if not isinstance(topics, dict) or any(
        not isinstance(topic, Topic) or key != topic.id for key, topic in topics.items()
    ):
        raise DataError("Expected consistently identified theorem topics")
    warnings = taxonomy.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise DataError("Taxonomy warnings must be a list of strings")
    warnings = list(warnings)
    mirror_unmatched = sorted(topics.keys() - canonical_ids)
    canonical_only = sorted(canonical_ids - topics.keys())
    if mirror_unmatched:
        warnings.append(
            f"{len(mirror_unmatched)} mirror IDs have no canonical match; retained in "
            "the mirror denominator as Unclassified without inferred aliases."
        )
    if canonical_only:
        warnings.append(
            f"{len(canonical_only)} canonical IDs are absent from the mirror; "
            "not added to the mirror denominator."
        )
    return {
        "mirror_unmatched_ids": mirror_unmatched,
        "canonical_only_ids": canonical_only,
        "warnings": warnings,
    }
