# delib-history

delib-history holds reference models from the `delib` library of [lifelib](https://github.com/lifelib-dev/lifelib) as a revision history. A release of a model is a commit of this repository, and the changes between two releases are the commits between them. [DeltaRecon](https://github.com/Degelmann-Solutions/deltarecon) runs a release that is named by this repository and a commit hash, and traces the difference between two releases back to the commits that cause it.

The first commit is release N of the Risikolebensversicherung model. Later commits change data, parameters, or code of the model, one change per commit, or only its documentation.

## Quick start

You need [uv](https://docs.astral.sh/uv/). `uv sync` fetches Python 3.12 if it is absent and installs the locked dependencies.

```sh
uv sync
uv run python tools/run_release.py risikolebensversicherung
uv run pytest -q
```

`tools/run_release.py` projects every model point of the product folder, evaluates the five built-in checks of the model for each, and prints the point count, one SHA-256 over all result frames, and the wall time. It writes no file and reads no network. The run of the 350 model points takes about 50 s on the author's machine.

For release N the hash is `215f0fac603116f1e8def81bd386730a252d0ea082143b427ea40c95f4901370`. `tests/test_release_n.py` pins the hash of the present state, which is that of release N until a commit moves a result. The hash is taken from raw 64-bit floats and has been confirmed on one machine only.

## Commits that demonstrate the interval search

The commits after `47f6a33` (Inflate the claim expense with expense inflation) were added
for DeltaRecon's interval search, which halves the history between two recorded releases
for a target and checks itself against the walk over every commit. They are placed so that
a search for the *Bruttobeitrag* in the first five projection years meets every case it must
report: most commits leave that target unchanged, a commit and its revert and a pair whose
second commit sets the first one's value back fall into one interval whose ends agree, and
two steps below a tolerance of one cent fall into the two halves of one interval. They
are no seeded changes of a benchmark: they carry no tiers and no sealed ground truth.

## Layout

| Path | Content |
|---|---|
| `risikolebensversicherung/` | The product folder, under upstream's name: the model `RLV_DE_S` and its six input CSVs. Further delib models become sibling folders. |
| `risikolebensversicherung/UPSTREAM.md` | Upstream commit, source path, and SHA-256 of every copied file. |
| `risikolebensversicherung/LICENSE-lifelib.txt` | The licence notice of lifelib, copied from upstream. |
| `tools/run_release.py` | The bare runner: runs every model point of a product folder and hashes the results. |
| `tools/build_portfolio.py` | Builds `model_point_table.csv` deterministically from upstream's 14 model points. |
| `tests/` | Provenance, portfolio, and runner tests, with the pinned portfolio hash and result hash of the present state. The provenance tests read the files of release N from the history, so they need Git and a complete clone. |

## The model and its limits

`RLV_DE_S` is the Risikolebensversicherung (German term life) model of lifelib's `delib` library. It projects monthly liability cash flows per model point. [modelx](https://github.com/fumitoh/modelx) reads and runs it.

Read every result from this model with these limits in mind:

- It is a demonstration of mechanics, not a valuation model. Upstream marks the library as a draft.
- The biometric tables are proxies. The mortality table is a Gompertz-form stand-in for DAV 2008 T, which is not public and is not shipped. Lapse rates are upstream's own assumptions.
- The cash flows are gross and undiscounted.
- The statutory references in the model's documentation are unverified upstream.
- No HGB reserve, no Zinszusatzreserve, and no profit participation can be claimed from this model.

The portfolio holds upstream's 14 model points unchanged, plus 336 generated points, 24 variants of each. A variant keeps its template's product features and varies term, issue age, sex, smoker status, sum assured, premium frequency and, for two lives, the age gap and the second life's smoker status. One third of the generated points are in force, after one completed year, at 40 and 70 percent of the term, and in the final year; the others are new business. Each dimension is balanced within a template and mixed independently of the others, so a change in one input can be told apart from the others. Generated points stay inside upstream's documented product envelope (issue age 18 to 65, end age at most 75, term 5 to 40 years) and reach its edges.

The portfolio is synthetic and contains no client data. It is built to exercise the model's mechanics, not to resemble a real book: in-force points carry issue dates back to 1987, and the model prices all of them on its one current basis.

## History

The main line is the chain of first parents of `main`: `git log --first-parent main` lists it. Each of its commits is one change, and a branch that was merged is one change, the merge; the commits inside the branch are not on the main line. The commit message says what the change is meant to do, and the files it touches say what kind of change it is: `model_point_table.csv` is data, the other CSV files of the product folder are parameters, and the folder `RLV_DE_S` is code.

The history of the main line is never rewritten: a commit hash names a release for good. A change that moves a result updates the pinned hashes in `tests/test_release_n.py` in the same commit, and so does a change of a file that was copied from upstream: byte identity with upstream holds for the commit of release N, and the tests pin the present bytes of every file a later commit has changed.

The commit after `244f18b`, *Set the model back to release N and keep the three fixes*, holds the data, parameters and code of release N with the three fixes of `038dd35`, `78d8baa` and `244f18b`, which keep every result bit for bit, and the commits after it repeat the earlier changes from `25a166a` to `fefc8cc` on the fixed model, in their order and with their messages.

## Upstream attribution and licence

At release N the model files and five of the six input CSVs under `risikolebensversicherung/` are copied byte for byte from lifelib at commit `fb1d195ab5423031cfd6d2548fe25a86b76cd0a1`; later commits change some of them. The sixth CSV, `model_point_table.csv`, extends upstream's file. `risikolebensversicherung/UPSTREAM.md` records the details.

The repository is licensed under the MIT licence, see `LICENSE`. The files copied from lifelib are "Copyright (c) 2022 lifelib Developers"; the other files are "Copyright (c) 2026 Degelmann Solutions".

modelx is licensed under LGPL-3.0. It is not part of this repository. It is installed unmodified from PyPI as a dependency declared in `pyproject.toml`.
