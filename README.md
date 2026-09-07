# mathlib undergraduate coverage dashboard

A dashboard tracking how much of the undergraduate mathematics curriculum, as
recorded in [`docs/undergrad.yaml`][undergrad], has been formalised over time.

The data is read **directly from upstream** on every run. This repository holds
only the extractor and the dashboard; it is not a fork of mathlib and holds no
copy of the topic list.

## Two sources, one timeline

`undergrad.yaml` lived in [leanprover-community/mathlib][mathlib3] (Lean 3)
from 2020-09, and was ported to [leanprover-community/mathlib4][mathlib4] on
2023-07-21 by [#6026][port]. A port between two unrelated repositories is not a
rename, so `git log --follow` cannot cross it — the two histories have to be
read separately and stitched.

They stitch cleanly. The last mathlib3 revision of the file (`07992a1d1`,
2023-05-04) and the first mathlib4 one (`bd0c9574a6`, 2023-07-21) are
identical: 561 topics, 345 formalised, 56 external, the same 13 categories and
the same 561 leaf paths. The join introduces no discontinuity, and the
dashboard marks it explicitly rather than hiding it.

Each source is truncated where the next one begins, so commits that continued
to land on the archived mathlib3 after the port cannot reappear and overwrite
newer mathlib4 readings.

## How a topic is counted

`undergrad.yaml` maps each topic to a value, and that value is classified
exactly the way mathlib's own [`scripts/yaml_check.py`][yamlcheck] classifies
it — `if entry and "/" not in entry` selects real declarations:

| Class | Value | Counted as formalised |
|---|---|---|
| `implemented` | a Lean declaration, e.g. `LinearMap.range` | yes |
| `external` | a URL or path, e.g. `https://en.wikipedia.org/wiki/...` | **no** |
| `todo` | empty or missing | no |

An `external` entry marks a topic that is *not* in mathlib and merely links to
an outside reference. Counting those as formalised does two kinds of damage:

1. it overstates coverage (at the time of writing, 77.0% instead of 70.0%); and
2. it **hides real progress** — when a topic is finally formalised its value
   changes from a URL to a declaration, so a dashboard that already counted it
   as done records no movement at all.

The second is the more serious one for a dashboard whose whole output is
velocity and acceleration. The recovered mathlib3 era shows how badly it
distorts the shape of the curve. Between 2021-11 and 2022-01 a documentation
campaign attached reference URLs to topics that were still unformalised:

| Month | `implemented` | `external` | `todo` | Miscounted as formalised |
|---|---|---|---|---|
| 2021-11 | 278 | 6 | 271 | 284 |
| 2021-12 | 283 | 26 | 246 | 309 |
| 2022-01 | 286 | 75 | 193 | 361 |

Real work over those two months was **+8 topics**. The buggy rule reports
**+77** — the largest month in six years of history, and entirely fictional.
The URLs came out of `todo`, not out of new formalisation.

## Why it does not use a fork

The extractor needs the Git history of one file. Reading it from a fork means
the numbers are only as fresh as the last manual sync, and a stale fork fails
silently: the page keeps stamping a new `generated_at` on frozen data.

Instead the job makes a blobless partial clone of each upstream repository
(`--filter=blob:none --no-checkout --single-branch`), which fetches the full
commit history but downloads file contents on demand — about 61 MB for mathlib4
and 23 MB for mathlib3, rather than the ~390 MB a full mathlib4 checkout costs.
A cold run takes roughly a minute.

The extractor also refuses to run if a *live* source's newest commit is older
than `--max-source-age-days`, so a broken clone fails loudly instead of
publishing stale figures. mathlib3 is archived and is exempt from that check by
design; mathlib4 is not.

## Layout

```
scripts/extract_undergrad_history.py   history extractor -> web/data.json
web/                                   static D3 dashboard
tests/                                 tests for the extractor
.github/workflows/dashboard.yml        weekly build and Pages deploy
```

## Running it locally

```bash
pip install pyyaml pytest

# clone both sources into .mathlib-cache and extract (first run downloads ~84 MB)
python3 scripts/extract_undergrad_history.py --clone --output web/data.json

python3 -m pytest tests/ -q
python3 -m http.server --directory web    # then open http://localhost:8000
```

Useful flags:

| Flag | Purpose |
|---|---|
| `--cache PATH` | directory holding the per-source clones (default `.mathlib-cache`) |
| `--clone` | create or refresh those clones |
| `--max-source-age-days N` | fail if a live source looks stale (`0` disables) |

## The weekly job

`.github/workflows/dashboard.yml` runs every Monday at 04:00 UTC. It tests the
extractor, rebuilds `web/data.json` from upstream, commits it back, and deploys
`web/` to GitHub Pages.

Two details are deliberate:

* **The data is committed back each week.** It gives a diffable record of every
  reading, and it counts as repository activity — GitHub disables scheduled
  workflows after 60 days without any, which would otherwise silently kill a
  repository whose only activity is its own cron.
* **Failures open an issue.** Nothing else here would notice a broken run.

[undergrad]: https://github.com/leanprover-community/mathlib4/blob/master/docs/undergrad.yaml
[mathlib3]: https://github.com/leanprover-community/mathlib
[mathlib4]: https://github.com/leanprover-community/mathlib4
[yamlcheck]: https://github.com/leanprover-community/mathlib4/blob/master/scripts/yaml_check.py
[port]: https://github.com/leanprover-community/mathlib4/pull/6026
