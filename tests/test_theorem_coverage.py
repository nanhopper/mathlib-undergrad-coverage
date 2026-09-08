"""Constructed fixtures for the named-theorem adapter; no live test dependencies."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from coverage_model import DataError, subject_summaries, summarise_topics
import theorem_coverage
from theorem_coverage import parse_taxonomy, parse_theorems, taxonomy_diagnostics


def front_matter(fields: str) -> str:
    return f"---\n{fields}\n---\n"


@pytest.fixture
def taxonomy_files():
    return {
        "_data/msc.yml": (
            '"00": General topics\n"03": Mathematical logic\n'
            '"08": General algebraic systems\n"11": Number theory\n'
        ),
        "_thm/Q1.md": front_matter("wikidata: Q1\nmsc_classification: '00'"),
        "_thm/Q2.md": front_matter("wikidata: Q2\nmsc_classification: '03'"),
        "_thm/Q2A1.md": front_matter("wikidata: Q2\nid_suffix: A1\nmsc_classification: '08'"),
        "_thm/Q3.md": front_matter("wikidata: Q3\nmsc_classification: '11'"),
    }


@pytest.fixture
def taxonomy(taxonomy_files):
    return parse_taxonomy(taxonomy_files)


def test_taxonomy_preserves_codes_labels_suffixes_and_sorted_ids(taxonomy_files):
    taxonomy = parse_taxonomy(dict(reversed(list(taxonomy_files.items()))))
    assert taxonomy == {
        "subjects": {
            "00": "General topics",
            "03": "Mathematical logic",
            "08": "General algebraic systems",
            "11": "Number theory",
        },
        "assignments": {"Q1": "00", "Q2": "03", "Q2A1": "08", "Q3": "11"},
        "ids": ["Q1", "Q2", "Q2A1", "Q3"],
    }


def test_statuses_count_each_mirror_entry_once(taxonomy):
    topics = parse_theorems("""
Q1:
  title: Single declaration
  decl: Nat.example
Q2:
  title: Several declarations
  decls: [Logic.first, Logic.second, Logic.third]
Q2A1:
  title: Authored report without a location
  authors: Ada Example
Q3:
  title: External Lean report
  authors: Bea Example
  url: https://example.org/lean/report
Q4:
  title: Discussion only
  url: https://leanprover.zulipchat.com/example
Q5:
  title: A mathlib URL is not declaration evidence
  url: https://leanprover-community.github.io/mathlib4_docs/Mathlib/Example.html
Q6:
  title: No recorded link
Q7:
  title: Comment alone is not formalization evidence
  comment: There may be a partial result elsewhere.
Q132469:
  title: Fermat's Last Theorem
  statement: FermatLastTheorem
  comment: A statement is recorded; the proof is ongoing.
""", taxonomy)
    summary = summarise_topics(topics.values())
    assert summary["total"] == 9
    assert summary["covered"] == 2
    assert summary["statuses"] == {
        "declaration": 2, "module": 0, "external": 0, "unlinked": 2,
        "reported": 2, "statement": 1, "qualified": 2,
    }
    assert topics["Q2"].references == ("Logic.first", "Logic.second", "Logic.third")
    assert topics["Q2A1"].references == ()
    assert topics["Q2A1"].authors == "Ada Example"
    assert topics["Q3"].references == ("https://example.org/lean/report",)
    assert topics["Q132469"].references == ("FermatLastTheorem",)
    assert not topics["Q132469"].covered
    assert topics["Q1"].subject == "00"
    assert topics["Q1"].path == ("General topics", "Single declaration")
    assert topics["Q7"].subject == "unclassified"
    assert topics["Q7"].path[0] == "Unclassified"


@pytest.mark.parametrize("evidence", [
    "decl: Polynomial.partial_result",
    "decls: [Polynomial.first, Polynomial.second]",
    "statement: Polynomial.conjecture",
])
def test_qualifications_and_authors_are_preserved_even_with_references(taxonomy, evidence):
    topic = parse_theorems(
        "Q1:\n  title: A qualified entry\n"
        f"  {evidence}\n"
        "  authors: Ada Example, Bea Example\n"
        "  date: 2021\n"
        "  comment: |\n"
        "    Only a special case is linked.\n"
        "    The general case remains in progress.\n",
        taxonomy,
    )["Q1"]
    assert topic.note == "Only a special case is linked.\nThe general case remains in progress.\n"
    assert topic.authors == "Ada Example, Bea Example"
    assert topic.reported_date == "2021"


def test_distinct_ids_suffixes_and_repeated_references_remain_distinct(taxonomy):
    topics = parse_theorems("""
Q2:
  title: Same title
  decl: Shared.result
Q2A1:
  title: Same title
  decl: Shared.result
""", taxonomy)
    assert set(topics) == {"Q2", "Q2A1"}
    assert summarise_topics(topics.values())["covered"] == 2
    assert topics["Q2"].subject == "03"
    assert topics["Q2A1"].subject == "08"


@pytest.mark.parametrize("fields", [
    "", "decl: null", "decl: ''", "decl: '  '", "decls: null", "decls: []",
    "statement: null", "statement: ''", "authors: ''", "authors: '  '",
    "url: null", "url: ''", "date: 2021", "comment: null",
    "decl: null\n  decls: []\n  statement: null\n  authors: null\n"
    "  date: null\n  url: null\n  comment: null",
])
def test_optional_empty_fields_do_not_create_coverage(taxonomy, fields):
    topic = parse_theorems(f"Q1:\n  title: No reference\n  {fields}\n", taxonomy)["Q1"]
    assert topic.status == "unlinked"
    assert topic.references == ()
    assert not topic.covered


def test_empty_alternate_reference_fields_do_not_conflict(taxonomy):
    topics = parse_theorems("""
Q1:
  title: A declaration
  decl: Nat.result
  decls: []
  statement: null
Q2:
  title: A declaration list
  decl: null
  decls: [Logic.result]
  statement: ''
Q3:
  title: A statement
  decl: ''
  decls: null
  statement: NumberTheory.conjecture
""", taxonomy)
    assert [topic.status for topic in topics.values()] == [
        "declaration", "declaration", "statement",
    ]


@pytest.mark.parametrize("fields", [
    "decl: Nat.first\n  decls: [Nat.second]",
    "decl: Nat.first\n  statement: Nat.conjecture",
    "decls: [Nat.first]\n  statement: Nat.conjecture",
])
def test_contradictory_evidence_fails(taxonomy, fields):
    with pytest.raises(DataError, match="exclusive|contradictory"):
        parse_theorems(f"Q1:\n  title: Invalid evidence\n  {fields}\n", taxonomy)


@pytest.mark.parametrize("fields", [
    "title: null", "title: ''", "title: '  '", "title: 2021", "title: [name]",
    "decl: true", "decl: 7", "decl: [Nat.result]", "decl: {}",
    "decls: Nat.result", "decls: ''", "decls: {}", "decls: [null]",
    "decls: [Nat.result, '']", "decls: [Nat.result, 7]",
    "statement: [Nat.result]", "statement: true",
    "authors: [Ada]", "authors: false", "comment: {detail: note}",
    "date: [2020, 2021]", "url: [https://example.org]",
    "proof: Nat.result", "unknown: null", "1: null", "author: Ada",
    "identifiers: [External.result]", "note: A legacy note",
])
def test_invalid_types_or_unknown_fields_fail(taxonomy, fields):
    prefix = "Q1:\n" if fields.startswith("title:") else "Q1:\n  title: Invalid shape\n"
    with pytest.raises(DataError):
        parse_theorems(f"{prefix}  {fields}\n", taxonomy)


@pytest.mark.parametrize("field", ["decl", "statement"])
@pytest.mark.parametrize("reference", [
    "https://example.org/proof", "Mathlib/Example.lean", r"Mathlib\Example.lean",
    "../Example.lean", "not a declaration", "Nat..result", ".Nat.result",
    "Nat.result.", "Nat:result", "Nat#result", "123", "Nat.result()",
])
def test_declaration_fields_reject_urls_paths_and_arbitrary_text(taxonomy, field, reference):
    with pytest.raises(DataError):
        parse_theorems(
            f"Q1:\n  title: Invalid reference\n  {field}: '{reference}'\n", taxonomy,
        )


def test_supported_unicode_and_prime_declaration_names(taxonomy):
    topic = parse_theorems("""
Q1:
  title: Declaration spelling
  decls: [Nat.result', α.example₁, _root_.Example.result]
""", taxonomy)["Q1"]
    assert topic.references == ("Nat.result'", "α.example₁", "_root_.Example.result")


@pytest.mark.parametrize("url", [
    "ftp://example.org/result", "mailto:person@example.org", "javascript:alert(1)",
    "//example.org/result", "Mathlib/Example.html", "https://", "https://exa mple.org",
])
def test_invalid_urls_fail_even_on_covered_records(taxonomy, url):
    with pytest.raises(DataError):
        parse_theorems(
            f"Q1:\n  title: A result\n  decl: Nat.result\n  url: '{url}'\n", taxonomy,
        )


@pytest.mark.parametrize("evidence,references", [
    ("decl: Nat.result", ("Nat.result",)),
    ("decls: [Nat.first, Nat.second]", ("Nat.first", "Nat.second")),
])
def test_declaration_supplementary_url_preserves_evidence_and_counts_once(
    taxonomy, evidence, references,
):
    url = "https://example.org/discussion"
    topics = parse_theorems(
        f"Q1:\n  title: A qualified result\n  {evidence}\n  url: {url}\n"
        "  authors: Ada Example\n  comment: Only a special case is recorded.\n",
        taxonomy,
    )
    topic = topics["Q1"]
    assert topic.references == (*references, url)
    assert topic.status == "declaration"
    assert topic.covered
    assert topic.note == "Only a special case is recorded."
    summary = summarise_topics(topics.values())
    assert (summary["covered"], summary["total"]) == (1, 1)


def test_statement_supplementary_url_preserves_evidence_without_coverage(taxonomy):
    url = "https://example.org/ongoing-project"
    topics = parse_theorems(
        "Q132469:\n  title: Fermat's Last Theorem\n  statement: FermatLastTheorem\n"
        f"  url: {url}\n  authors: Ada Example\n  comment: The proof is ongoing.\n",
        taxonomy,
    )
    topic = topics["Q132469"]
    assert topic.references == ("FermatLastTheorem", url)
    assert topic.status == "statement"
    assert not topic.covered
    assert topic.note == "The proof is ongoing."
    summary = summarise_topics(topics.values())
    assert (summary["covered"], summary["total"]) == (0, 1)


@pytest.mark.parametrize("value,expected", [
    ("2021", "2021"), ("'2021'", "2021"), ("'2021-03'", "2021-03"),
    ("'2021/03'", "2021/03"), ("'2020-02-29'", "2020-02-29"),
    ("2020-02-29", "2020-02-29"), ("'2020/02/29'", "2020/02/29"),
    ("'2000-02-29'", "2000-02-29"), ("'2019, 2021'", "2019, 2021"),
    ("'2021, 2025'", "2021, 2025"), ("null", None), ("''", None),
])
def test_reported_date_retains_precision_and_source_spelling(taxonomy, value, expected):
    topic = parse_theorems(
        f"Q1:\n  title: Reported result\n  authors: Ada\n  date: {value}\n", taxonomy,
    )["Q1"]
    assert topic.reported_date == expected
    assert topic.reported_date is None or type(topic.reported_date) is str
    assert topic.status == "reported"


@pytest.mark.parametrize("value", [
    "true", "false", "2021.5", "0", "-2021", "10000", "'0000'", "'2021-00'",
    "'2021-13'", "'2021/13'", "'2021-02-29'", "2021-02-29", "'1900-02-29'",
    "'2020-04-31'", "'2020-01-00'", "'2020/02/30'", "'2021-1'", "'2021-01-1'",
    "'2021/01-02'", "'2021-01/02'", "'2021/2022'", "'spring 2021'",
    "'2021,'", "'2021, later'", "'2021, 2020-02-30'",
    "2021-01-01T00:00:00Z", "'2021-01-01T00:00:00Z'",
])
def test_malformed_or_overprecise_reported_dates_fail(taxonomy, value):
    with pytest.raises(DataError):
        parse_theorems(
            f"Q1:\n  title: Invalid report\n  authors: Ada\n  date: {value}\n", taxonomy,
        )


@pytest.mark.parametrize("content", [
    None, 17, [], "", "[]", "{}", "Q1: null", "Q1: []", "Q1: {}", "Q1: a title",
    "123:\n  title: Numeric ID", "Q:\n  title: Missing digits",
    "q1:\n  title: Wrong prefix", "Q1_X:\n  title: Invalid suffix",
    "Q1-X:\n  title: Invalid suffix", "' Q1':\n  title: Padded ID",
    "Q1:\n  title: First\nQ1:\n  title: Duplicate",
    "Q1:\n  title: First\n  title: Duplicate",
    "Q1:\n  title: Duplicate reference\n  decl: Nat.one\n  decl: Nat.two",
    "Q1:\n  title: Malformed YAML\n  decl: [Nat.one",
])
def test_malformed_mirror_and_duplicate_ids_or_keys_fail(taxonomy, content):
    with pytest.raises(DataError):
        parse_theorems(content, taxonomy)


@pytest.mark.parametrize("contents", [
    "", "wikidata: Q1\nmsc_classification: '00'", "---\nwikidata: Q1",
    "\n---\nwikidata: Q1\n---", "---\n[]\n---", "---\n---",
    front_matter("wikidata: [Q1]\nmsc_classification: '00'"),
    front_matter("wikidata: Q1X\nmsc_classification: '00'"),
    front_matter("msc_classification: '00'"),
    front_matter("wikidata: Q1"),
    front_matter("wikidata: Q1\nmsc_classification: 0"),
    front_matter("wikidata: Q1\nmsc_classification: ['00']"),
    front_matter("wikidata: Q1\nmsc_classification: '99'"),
    front_matter("wikidata: Q1\nmsc_classification: '00'\nid_suffix: '?'"),
    front_matter("wikidata: Q1\nmsc_classification: '00'\nid_suffix: 1"),
    front_matter("wikidata: Q1\nmsc_classification: '00'\nid_suffix: ' '"),
    front_matter("wikidata: Q1\nmsc_classification: '00'\nunknown: null"),
    front_matter("wikidata: Q1\nmsc_classification: '00'\nwikipedia_links: a page"),
    front_matter("wikidata: Q1\nmsc_classification: '00'\nlean: formalized"),
    front_matter("wikidata: Q1\nmsc_classification: '00'\nlean: [not a mapping]"),
    front_matter("wikidata: Q1\nwikidata: Q1\nmsc_classification: '00'"),
])
def test_invalid_canonical_front_matter_fails(taxonomy_files, contents):
    taxonomy_files["_thm/Q1.md"] = contents
    with pytest.raises(DataError):
        parse_taxonomy(taxonomy_files)


@pytest.mark.parametrize("msc", [
    "", "[]", "'00': General\n'00': Duplicate", "00: General", "3: Logic",
    "'003': Logic", "'xx': Logic", "'00': null", "'00': []", "'00': '  '",
])
def test_invalid_msc_mapping_or_lost_leading_zero_fails(taxonomy_files, msc):
    taxonomy_files["_data/msc.yml"] = msc
    with pytest.raises(DataError):
        parse_taxonomy(taxonomy_files)


def test_canonical_requires_identity_to_match_filename(taxonomy_files):
    taxonomy_files["_thm/Q1.md"] = front_matter("wikidata: Q999\nmsc_classification: '00'")
    with pytest.raises(DataError, match="file path"):
        parse_taxonomy(taxonomy_files)


def test_canonical_identity_collision_fails(taxonomy_files):
    taxonomy_files["_thm/Q3.md"] = front_matter("wikidata: Q1\nmsc_classification: '11'")
    with pytest.raises(DataError, match="collision"):
        parse_taxonomy(taxonomy_files)


def test_alphanumeric_numeric_suffix_is_not_silently_merged(taxonomy_files):
    taxonomy_files["_thm/Q12.md"] = front_matter(
        "wikidata: Q1\nid_suffix: '2'\nmsc_classification: '00'"
    )
    taxonomy = parse_taxonomy(taxonomy_files)
    assert "Q12" in taxonomy["ids"]
    taxonomy_files["_thm/Q3.md"] = front_matter("wikidata: Q12\nmsc_classification: '11'")
    with pytest.raises(DataError, match="collision"):
        parse_taxonomy(taxonomy_files)


def test_crlf_front_matter_body_and_null_optional_metadata(taxonomy_files):
    taxonomy_files["_thm/Q1.md"] = (
        front_matter(
            "wikidata: Q1\nmsc_classification: '00'\nid_suffix: null\n"
            "wikipedia_links: null\nlean: null"
        ) + "Markdown body outside the YAML mapping.\n"
    ).replace("\n", "\r\n")
    assert parse_taxonomy(taxonomy_files)["assignments"]["Q1"] == "00"


def test_canonical_formalization_metadata_never_supplies_mirror_coverage(taxonomy_files):
    taxonomy_files["_thm/Q1.md"] = front_matter("""
wikidata: Q1
msc_classification: '00'
wikipedia_links: ['[[An example]]']
lean:
- status: formalized
  library: L
  url: https://example.org/lean/proof
  identifiers: [Example.theorem]
  authors: [Ada Example]
  date: 2020-02-29
  comment: Canonical evidence is not mirror evidence.
""")
    taxonomy = parse_taxonomy(taxonomy_files)
    topic = parse_theorems("Q1:\n  title: No mirror reference\n", taxonomy)["Q1"]
    assert topic.status == "unlinked"
    assert topic.references == ()
    assert topic.authors is None


@pytest.mark.parametrize("fields", [
    "status: formalized\n  status: formalized\n  library: L\n  url: https://example.org",
    "status: formalized\n  library: L\n  url: https://example.org\n  unknown: null",
    "status: formalized\n  library: L\n  url: https://example.org\n  authors: Ada",
    "status: formalized\n  library: L\n  url: https://example.org\n  identifiers: [null]",
    "status: proved\n  library: L\n  url: https://example.org",
    "status: formalized\n  library: elsewhere\n  url: https://example.org",
    "status: formalized\n  library: L\n  url: file:///proof",
])
def test_unsupported_canonical_metadata_and_nested_duplicate_keys_fail(taxonomy_files, fields):
    taxonomy_files["_thm/Q1.md"] = front_matter(
        f"wikidata: Q1\nmsc_classification: '00'\nlean:\n- {fields}"
    )
    with pytest.raises(DataError):
        parse_taxonomy(taxonomy_files)


@pytest.mark.parametrize("files", [
    {}, {"_data/msc.yml": "'00': General"}, {"_thm/Q1.md": "---\n---"},
    {"_data/msc.yml": b"'00': General"},
    {"_data/msc.yml": "'00': General", r"_thm\Q1.md": "---\n---"},
    {"_data/msc.yml": "'00': General", "/_thm/Q1.md": "---\n---"},
    {"_data/msc.yml": "'00': General", "_thm/../Q1.md": "---\n---"},
])
def test_incomplete_or_non_git_taxonomy_inputs_fail(files):
    with pytest.raises(DataError):
        parse_taxonomy(files)


def test_diagnostics_preserve_mirror_denominator_and_do_not_guess_aliases(taxonomy):
    topics = parse_theorems("""
Q1:
  title: Shared canonical entry
  decl: Example.first
Q2X:
  title: Not the canonical Q2 or Q2A1
  decl: Example.second
Q99:
  title: Another unmatched entry
""", taxonomy)
    taxonomy["warnings"] = ["Labels use the pinned taxonomy version."]
    before_topics, before_taxonomy = copy.deepcopy(topics), copy.deepcopy(taxonomy)
    diagnostics = taxonomy_diagnostics(topics, taxonomy)
    assert diagnostics["mirror_unmatched_ids"] == ["Q2X", "Q99"]
    assert diagnostics["canonical_only_ids"] == ["Q2", "Q2A1", "Q3"]
    assert diagnostics["warnings"][0] == "Labels use the pinned taxonomy version."
    assert len(diagnostics["warnings"]) == 3
    assert topics == before_topics
    assert taxonomy == before_taxonomy
    assert (summarise_topics(topics.values())["total"],
            summarise_topics(topics.values())["covered"]) == (3, 2)
    subjects = subject_summaries(topics)
    assert sum(row["total"] for row in subjects.values()) == 3
    assert subjects["unclassified"]["total"] == 2
    assert subjects["unclassified"]["covered"] == 1


def test_matching_universes_have_no_reconciliation_warnings(taxonomy):
    topics = parse_theorems(
        "\n".join(f"{key}:\n  title: Example {key}" for key in taxonomy["ids"]), taxonomy,
    )
    assert taxonomy_diagnostics(topics, taxonomy) == {
        "mirror_unmatched_ids": [], "canonical_only_ids": [], "warnings": [],
    }


@pytest.mark.parametrize("change", [
    {"subjects": None}, {"subjects": {"00": "General"}, "assignments": {"Q1": "99"}},
    {"ids": ["Q1", "Q1"]}, {"ids": ["Q1"]}, {"ids": ["bad"]}, {"assignments": []},
])
def test_inconsistent_taxonomy_fails_instead_of_losing_classification(taxonomy, change):
    taxonomy.update(change)
    with pytest.raises(DataError):
        parse_theorems("Q1:\n  title: Example\n", taxonomy)


@pytest.mark.parametrize("identifiers", ["[External.theorem]", "External.theorem"])
def test_reviewed_legacy_schema_preserves_reports_without_inventing_declarations(
    taxonomy, monkeypatch, identifiers,
):
    content = f"""
Q1:
  title: An initial declaration
  decl: Example.theorem
  author: Ada Example
  note: A qualified library reference.
Q2:
  title: An initial external report
  author: Bea Example
  identifiers: {identifiers}
  url: https://example.org/external
  date: 2020-02-29
  comment: Original qualification.
"""
    monkeypatch.setattr(theorem_coverage, "_LEGACY_BLOBS", {theorem_coverage._blob_hash(content)})
    topics = parse_theorems(content, taxonomy)
    assert topics["Q1"].status == "declaration"
    assert topics["Q1"].authors == "Ada Example"
    assert topics["Q1"].note == "A qualified library reference."
    assert topics["Q2"].status == "reported"
    assert topics["Q2"].references == ("https://example.org/external",)
    assert topics["Q2"].authors == "Bea Example"
    assert topics["Q2"].reported_date == "2020-02-29"
    assert topics["Q2"].note == (
        "Original qualification.\n"
        "Legacy source identifiers (not treated as mathlib declarations): External.theorem."
    )
    assert summarise_topics(topics.values())["covered"] == 1
    with pytest.raises(DataError, match="unsupported fields"):
        parse_theorems(content + "\n", taxonomy)


@pytest.mark.parametrize("fields", [
    "author: Ada\n  authors: Bea", "note: First note\n  comment: Second note",
])
def test_reviewed_legacy_alias_collision_fails(taxonomy, monkeypatch, fields):
    content = f"Q1:\n  title: Conflicting legacy fields\n  {fields}\n"
    monkeypatch.setattr(theorem_coverage, "_LEGACY_BLOBS", {theorem_coverage._blob_hash(content)})
    with pytest.raises(DataError, match="collision"):
        parse_theorems(content, taxonomy)


@pytest.fixture
def duplicate_declarations():
    return (
        "Q776578:\n"
        "  title: Wedderburn–Artin theorem\n"
        "  decl: IsSimpleRing.exists_algEquiv_matrix_divisionRing\n"
        "  decl: IsSemisimpleRing.exists_algEquiv_pi_matrix_divisionRing\n"
    )


def test_reviewed_duplicate_declarations_preserve_both_but_count_once(
    taxonomy, monkeypatch, duplicate_declarations,
):
    content = duplicate_declarations + "  comment: Preserve this qualification.\n"
    monkeypatch.setattr(
        theorem_coverage, "_DUPLICATE_DECL_BLOBS", {theorem_coverage._blob_hash(content)},
    )
    topics = parse_theorems(content, taxonomy)
    topic = topics["Q776578"]
    assert topic.references == (
        "IsSimpleRing.exists_algEquiv_matrix_divisionRing",
        "IsSemisimpleRing.exists_algEquiv_pi_matrix_divisionRing",
    )
    assert topic.status == "declaration"
    assert topic.note.startswith("Preserve this qualification.\n")
    assert "leanprover-community/mathlib4#36001" in topic.note
    assert "counted once" in topic.note
    summary = summarise_topics(topics.values())
    assert (summary["covered"], summary["total"]) == (1, 1)
    corrected = (
        "Q776578:\n"
        "  title: Wedderburn–Artin theorem\n"
        "  decls:\n"
        "    - IsSimpleRing.exists_algEquiv_matrix_divisionRing\n"
        "    - IsSemisimpleRing.exists_algEquiv_pi_matrix_divisionRing\n"
    )
    corrected_topics = parse_theorems(corrected, taxonomy)
    assert corrected_topics["Q776578"].references == topic.references
    assert summarise_topics(corrected_topics.values()) == summary


def test_duplicate_repair_is_restricted_to_reviewed_immutable_blobs(
    taxonomy, monkeypatch, duplicate_declarations,
):
    with pytest.raises(DataError, match="Duplicate"):
        parse_theorems(duplicate_declarations, taxonomy)
    monkeypatch.setattr(
        theorem_coverage, "_DUPLICATE_DECL_BLOBS",
        {theorem_coverage._blob_hash(duplicate_declarations)},
    )
    with pytest.raises(DataError, match="Duplicate"):
        parse_theorems(duplicate_declarations + "\n", taxonomy)


def test_reviewed_duplicate_repair_does_not_ignore_other_duplicate_keys(
    taxonomy, monkeypatch, duplicate_declarations,
):
    content = duplicate_declarations + "\nQ1:\n  title: First\n  title: Second\n"
    monkeypatch.setattr(
        theorem_coverage, "_DUPLICATE_DECL_BLOBS", {theorem_coverage._blob_hash(content)},
    )
    with pytest.raises(DataError, match="Duplicate"):
        parse_theorems(content, taxonomy)


def test_reviewed_duplicate_repair_requires_the_exact_reviewed_record(
    taxonomy, monkeypatch, duplicate_declarations,
):
    content = duplicate_declarations.replace("IsSimpleRing.", "DifferentRing.")
    monkeypatch.setattr(
        theorem_coverage, "_DUPLICATE_DECL_BLOBS", {theorem_coverage._blob_hash(content)},
    )
    with pytest.raises(DataError, match="Reviewed duplicate-declaration repair"):
        parse_theorems(content, taxonomy)
