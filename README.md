# Mathlib coverage

A coverage-first dashboard for comparing the **level and pace of recorded
mathematical coverage**, and the differences between subjects.

It uses two independent benchmarks, not one "percentage of all mathematics":

| Benchmark | What it measures | Main limitation |
| --- | --- | --- |
| [1000+ named theorems][named] | Named-theorem entries with declaration references in the mathlib repository, grouped by MSC subject | A changing Wikipedia-derived checklist, not a representative sample of all mathematics |
| [French undergraduate curriculum][undergrad] | Syllabus topics with declaration or internal mathlib module references | Unequal topic granularity, overlap, incomplete recording, and a limited curriculum |

The dashboard opens on the latest observation and does not autoplay or animate
its counters. Both overview cards show coverage and the latest complete
six-month recording pace, followed directly by subject comparisons. The shared
controls support other observations and windows, staying visible on larger
screens when they fit comfortably. History, detailed pace comparisons, and
evidence start collapsed; selecting a subject opens its evidence. Definitions,
reference breakdowns, and provenance remain available on demand. Library
activity is not substituted for mathematical coverage.

## Read the numbers as records, not proof-production statistics

The source files are manually maintained. An entry can be added long after the
underlying mathematics was formalized. Missing references do not prove absence,
and a reference does not certify every interpretation of a topic.

For example, 22 of March 2026's 24 newly declaration-linked undergraduate entries
came from two documentation-only changes:
[leanprover-community/mathlib4#36019][algebra-update] and
[leanprover-community/mathlib4#37424][probability-update].
These improved the coverage record; they were not 22 new proofs entering the
repository in those commits.

Consequently, the dashboard does **not** estimate a global coverage inflection,
an acceleration of mathematical effort, or a completion date. No composite
score averages these overlapping benchmarks.

## Evidence classes

| State | Meaning | In the primary covered count? |
| --- | --- | --- |
| Declaration | A nonempty declaration reference (or `decls` list for a named theorem) | Yes, once per checklist entry |
| Module | An internal mathlib documentation/module reference in the curriculum | Yes, with its lower specificity visible |
| External | An outside reference in the curriculum | No |
| Unlinked | No covered reference or other formalization record | No; not a proof of absence |
| Reported | Named-theorem authorship reported without a repository declaration; it may be external or unlocated | No |
| Statement | Only a theorem statement is referenced | No |
| Qualified | A URL-only named-theorem record, possibly partial or merely a discussion | No |

Named-theorem scope is **the mathlib repository**, which can include Archive and
Counterexamples, not exclusively the `Mathlib` directory and not every Lean
project. Comments and qualifications are retained even on declaration-linked
entries. A URL or author name alone does not establish mathlib coverage.

One entry with several declarations is counted once. Separate syllabus entries
sharing a declaration remain separate topics: these are checklist items, not
independent units of work.

### Why internal module links count

Mathlib's `scripts/yaml_check.py` filters references needing declaration-name
checking. Its slash test is not the full coverage policy. The [community website
renderer][renderer] also recognizes internal documentation paths.

At mathlib revision `156b4fb3500549c5983e06348faca9d6ee499841`, the curriculum
contains 396 declaration references, 3 internal module references, 37
external-only references, and 130 unlinked entries. That is **399/566 = 70.49%
recorded coverage**. Treating every slash-containing value as external incorrectly
reports 69.96%. Changing an internal module link to a declaration is not a
coverage gain.

At the same revision, the named-theorem mirror contains 1,199 entries and 214
declaration-linked records. These reference figures are not hard-coded totals.

## Comparisons and time

**Four clocks remain distinct:** source revision time, catalog-file edit time,
observation cutoff, and data generation time. A quiet checklist can be a valid,
freshly retrieved source without being a recently updated record of coverage.

The latest observation includes the current partial month. Monthly observations
are states immediately **before midnight UTC on the first of a month**. A commit
exactly at that boundary belongs to the next period.

The default pace compares six complete calendar months with the previous six.
Three- and twelve-month windows are also available. The latest partial month is
excluded from those comparisons, and their actual start/end dates are shown.
Insufficient history or an empty comparable cohort is unavailable, not zero.

Both windows use the **same continuously tracked topic cohort**. Catalog
additions/removals, equivalent renames, and reference-format changes do not
inflate its pace. Full-catalog counts remain visible alongside this comparison:

```text
covered-count change = status gains - status losses
                     + covered catalog additions - covered catalog removals
catalog-size change  = additions - removals
```

Gains/losses are recorded transitions, not necessarily distinct newly proved
theorems. An entry may gain and lose a reference within a period. Documentation-only,
source-accompanied, and unknown commit contexts explain recorded gains; even an
accompanying source change does not establish a causal proof-completion date.
Ratios are computed from unrounded counts.

## Historical scope and identities

The undergraduate history joins [mathlib (Lean 3)][mathlib3] and
[mathlib4 (Lean 4)][mathlib4] at the July 2023 file port. Old-source observations
stop when the new source starts. Mainline Git states are used rather than
sorting feature-branch timestamps into an apparent history. Rare nonmonotone
commit timestamps are clamped to preserve mainline ancestry and disclosed.

Known equivalent subject renames have explicit aliases. In particular,
`Measures and integral Calculus` and `Measures and integral calculus` are one
subject, not two bars with invented zero coverage.

### Malformed legacy YAML

Strict parsing exposed an additional historical counting defect: several
different Hilbert-space examples used the duplicate key `its completeness`.
Ordinary YAML loading silently overwrote earlier entries. The extractor now
preserves the separate sequence-space, function-space, and (where present)
trigonometric-basis completeness entries, using their references and the later
upstream names to disambiguate them.

The repaired Lean 3/4 boundary has **562 entries, 351 covered on both sides**.
The old 561/350 figures still lost one of those distinct topics. Identical,
repeated empty complex-analysis labels in the earliest source are counted once.

These narrowly reviewed repairs are restricted to the immutable Git blob
allowlist in `scripts/curriculum_legacy.py`. Repaired records carry explanatory
notes and the dashboard discloses the policy. Any unexpected duplicate, invalid
leaf type, or unsupported shape still stops publication rather than being
silently skipped.

### Named-theorem history and MSC

Mathlib's named-theorem file starts in December 2024, initially with 1,198 entries
but only one declaration reference. That is a catalog-initialization artifact,
not evidence that almost no mathematics was formalized. The first monthly
observation is January 2025; earlier observations are unavailable. Backfills
are recording activity, not reconstructed historical proof dates.

Historical `author`/`note` fields and external-project identifiers are normalized
only for reviewed immutable blobs. A known duplicated `decl` field is repaired
using upstream's correction: both references survive, but the theorem counts
once. External identifiers never become mathlib declarations by inference.

MSC labels come from a pinned revision of the [canonical 1000+ project][canonical].
That same taxonomy version groups all historical observations; it is not
presented as historical classification.

The benchmark denominator remains mathlib's versioned mirror. Unmatched IDs are
reported, and unmatched mirror entries stay in an Unclassified subject bucket.
The canonical catalog and mirror are never silently unioned or intersected to
improve a score. Optional reported theorem dates keep their original precision.

## Data and publication

The extractor uses checked upstream refreshes and freezes full source revisions
and one UTC cutoff for each run. The two mathlib caches are blobless partial
clones with only catalog blobs fetched on demand/in batches. The much smaller
canonical taxonomy repository is cached without a working-tree checkout.

Failures to fetch, read, parse, or reconcile required data abort publication.
The output is written atomically only after successful extraction. The live
mathlib source also has an age limit; the archived source and rarely edited
taxonomy are exempt from that activity-based check.

`web/data.json` uses schema version 2: shared provenance, separate benchmarks,
interned evidence records, compact revision events, monthly summaries, latest
observations, and comparable windows. Replaying events yields the actual
evidence at a historical observation instead of substituting today's labels.
The frontend rejects incompatible data.

The weekly Pages workflow tests the producer and frontend model, refreshes data,
commits the artifact, and deploys matching code/data. Pull requests run
read-only validation and cannot publish. A rejected refresh push fails rather
than replaying an old artifact onto changed dashboard code. Failures open or
update a tracking issue.

## Local use

Requires Python 3.11+, Git, and Node 22+ for frontend-model tests. No frontend
dependency installation or build step is needed. D3 loads separately from the
data: if its CDN is unavailable, counts, comparisons, history tables, and
evidence remain usable.

```powershell
pip install pyyaml pytest
python scripts\extract_undergrad_history.py --clone --output web\data.json
python -m pytest tests -q
node --test tests\dashboard-model.test.mjs
python -m http.server --bind 127.0.0.1 --directory web 8000
```

Open `http://127.0.0.1:8000`. On Unix, use `/` in local filesystem paths.

| Option | Purpose |
| --- | --- |
| `--cache PATH` | Location of upstream caches (default `.mathlib-cache`) |
| `--clone` | Create/refresh all caches and prefetch catalog history |
| `--max-source-age-days N` | Live source age limit; `0` disables for deliberate historical replay |
| `--as-of TIMESTAMP` | Explicit timezone-qualified UTC observation cutoff |
| `--mathlib3-rev SHA`, `--mathlib4-rev SHA`, `--catalog-rev SHA` | Pin source inputs for reproducibility |

For historical replay, pin revisions no later than `--as-of`. Reusing the same
source revisions and cutoff produces the same observations and metrics (the
generation timestamp records the actual run); source fingerprints are
available in the dashboard's methodology/provenance section.

[named]: https://github.com/leanprover-community/mathlib4/blob/master/docs/1000.yaml
[undergrad]: https://github.com/leanprover-community/mathlib4/blob/master/docs/undergrad.yaml
[mathlib3]: https://github.com/leanprover-community/mathlib
[mathlib4]: https://github.com/leanprover-community/mathlib4
[canonical]: https://github.com/1000-plus/1000-plus.github.io
[renderer]: https://github.com/leanprover-community/leanprover-community.github.io/blob/lean4/make_site.py
[algebra-update]: https://github.com/leanprover-community/mathlib4/pull/36019
[probability-update]: https://github.com/leanprover-community/mathlib4/pull/37424
