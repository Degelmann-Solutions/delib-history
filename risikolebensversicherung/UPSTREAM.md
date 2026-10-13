# Upstream provenance: `RLV_DE_S` (lifelib `delib`)

Release N of the liability cash-flow stage is the Risikolebensversicherung model of lifelib's `delib` library, copied as text at a pinned commit. Release N is the first commit of this repository, `b64334e09613c45a7a12468dfddc0d9ec47819bb`.

This file describes release N. Byte identity with upstream holds for the commit of release N. Later commits of this repository change files that are listed here; the hashes below stay those of upstream and of release N.

- Upstream repository: https://github.com/lifelib-dev/lifelib
- Commit: `fb1d195ab5423031cfd6d2548fe25a86b76cd0a1`
- Commit date: 2026-09-26
- Source path: `lifelib/libraries/delib/products/risikolebensversicherung/`
- Licence: MIT, "Copyright (c) 2022 lifelib Developers". The notice is `LICENSE-lifelib.txt`, copied from `LICENSE.txt` in the upstream repository root.

modelx, the engine that reads and runs the model, is not copied. It is an unmodified dependency installed from PyPI (see `pyproject.toml`).

## Files copied verbatim

At the commit of release N each file is byte-identical to upstream at the pinned commit. `tests/test_release_n.py` reads the files of release N from the history and checks these SHA-256 values. For a file that a later commit has changed, the same test file pins the SHA-256 of the present bytes in `CHANGED_SINCE_RELEASE_N`; a file that is not listed there is still byte-identical to upstream.

| File | SHA-256 |
|---|---|
| `LICENSE-lifelib.txt` | `f30a3558fa4b497b5dc70f2cf28b1f5309db42e4d405196f8cd621b8ca3d1d51` |
| `RLV_DE_S/__init__.py` | `01d307c7587d9ba0718f4a0c55e94e0e319e4adb5fd83fcbbf35b71c4fab6071` |
| `RLV_DE_S/_system.json` | `bd2b0595635b2377009e5667654277b31f454e6be52b84cb59725e97d6409334` |
| `RLV_DE_S/Data/__init__.py` | `c51a19b29c94dc99f0ee41d7594f5c117cc08eb719a75d2676e486e5e445aac8` |
| `RLV_DE_S/Projection/__init__.py` | `543b58a57764014b52f28f6da203a96c4bbf0f03958950e5db50693a2f43bf6a` |
| `benefit_schedule.csv` | `903b8faea3a6881bb5d03aa1d99773d5b2afe55c974d2511980ce8afe253060a` |
| `freq_loading_table.csv` | `4335fcc62821819668931a41cc9270c74ef63bbec35c9666e29c7d006e67fcf8` |
| `lapse_table.csv` | `d9e0d24e56b66900243183ea2cd7a9d937fb503c66a74b953eba4a1c126d4247` |
| `mort_table.csv` | `f0f35b93f071c580fa424114645990321e604e06295f2d85d7159c23c8867df2` |
| `nvg_schedule.csv` | `bddb7779f4727058494e1e055fa07dd69ee4e98ad673423e3474b88d2ec27397` |

## The one deviating file

At release N `model_point_table.csv` is the only file that differs from upstream. Upstream ships a header and 14 model points. Here the file keeps that header and those 14 rows unchanged as its first 15 lines and appends generated points, new business and in force, from `point_id` 15 onwards. `tools/build_portfolio.py` writes the file and is deterministic. A later commit may change the generated points; the first 15 lines stay upstream's.

SHA-256 of upstream's `model_point_table.csv` (header plus 14 rows), which equals the SHA-256 of the first 15 lines of the file here:

Upstream model points SHA-256: `dfc9fae39993a6d60b388650340d0a851c46a3d452bbf0c3a90936b70bf0414a`

## Not copied

Upstream's `run.py`, `model.md`, `product-spec.md`, `technical-notes.md` and `sources.md` are not copied. The product envelope that the portfolio build enforces (issue age 18 to 65, end age at most 75, term 5 to 40 years) comes from `product-spec.md`, section "Product identity and issue rules", at the pinned commit.
