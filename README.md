# mathlib undergraduate coverage dashboard

A dashboard tracking how much of the undergraduate mathematics curriculum,
as recorded in [`docs/undergrad.yaml`][undergrad] in
[leanprover-community/mathlib4][mathlib], has been formalised over time.

The data is read **directly from upstream mathlib4** on every run. This
repository holds only the extractor and the dashboard; it is not a fork of
mathlib and holds no copy of the topic list.

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
velocity and acceleration. Over 2023-08 to 2026-09 it concealed 16 of 51
formalised topics, about a third of the work.

## Why it does not use a fork

The extractor needs the Git history of one file. Reading it from a fork means
the numbers are only as fresh as the last manual sync, and a stale fork fails
silently: the page keeps stamping a new `generated_at` on frozen data.

Instead the job makes a blobless partial clone of upstream
(`--filter=blob:none --no-checkout --single-branch`), which fetches the full
commit history but downloads file contents on demand — about 61 MB rather than
the ~390 MB a full mathlib checkout costs. The extractor also refuses to run if
the upstream ref's newest commit is more than `--max-source-age-days` old, so a
broken clone fails loudly instead of publishing stale figures.

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

# clone upstream into .mathlib-cache and extract (first run downloads ~61 MB)
python3 scripts/extract_undergrad_history.py --clone --output web/data.json

python3 -m pytest tests/ -q
python3 -m http.server --directory web    # then open http://localhost:8000
```

Useful flags:

| Flag | Purpose |
|---|---|
| `--repo PATH` | read an existing mathlib checkout instead of the cache |
| `--clone` | create or refresh the checkout at `--repo` |
| `--ref REF` | read history from a ref other than `master` |
| `--max-source-age-days N` | fail if upstream looks stale (`0` disables) |

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

## Caveats

The history begins **2023-08**. `undergrad.yaml` was added to mathlib4 on
2023-07-21 by [#6026][port], which ported it from mathlib3; earlier history
lives in the mathlib3 repository and is not reachable from mathlib4 (it is a
port, not a rename, so `git log --follow` cannot recover it).

[undergrad]: https://github.com/leanprover-community/mathlib4/blob/master/docs/undergrad.yaml
[mathlib]: https://github.com/leanprover-community/mathlib4
[yamlcheck]: https://github.com/leanprover-community/mathlib4/blob/master/scripts/yaml_check.py
[port]: https://github.com/leanprover-community/mathlib4/pull/6026
