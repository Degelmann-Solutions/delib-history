"""Run every model point of a product folder and print one hash over the results.

    uv run python tools/run_release.py risikolebensversicherung

The folder holds the model (``RLV_DE_S``) and its input CSVs side by side. The runner
reads the model with modelx, evaluates ``result_cf`` and the five built-in checks for
every point of ``model_point_table.csv``, and prints the point count, the SHA-256 and the
wall time. The wall time is measured from the start of this script, before modelx is
imported, so it covers the import, the run, the checks and the hashing; it does not cover
interpreter start-up or ``uv run``. It only reads: no modelx writer is called and the folder is left untouched.

Exit status: 0 if every point ran and every check is true; 1 if a point raised or a check
is false (each failure is printed with its point and check); 2 on a usage error.

Hash recipe
-----------
One SHA-256 over all ``result_cf`` frames, points in ascending ``point_id`` order. For
each point these bytes enter, in this order:

1. the line ``point_id=<id>``;
2. the line ``columns=<column names joined by commas>``;
3. the line ``shape=<rows>,<columns>``;
4. the index as little-endian 64-bit integers;
5. the values as little-endian 64-bit floats, row by row, at full precision.

Nothing is rounded, so any change in any value, row, column or point changes the hash.

This is a minimal runner of one product folder. It carries no contract and no run record.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

_PROCESS_START = time.perf_counter()  # taken before the modelx import, which takes seconds

import modelx as mx  # noqa: E402

MODEL_NAME = "RLV_DE_S"
CHECKS = (
    "check_net_cf",
    "check_pols_roll_fwd",
    "check_prem_split",
    "check_res_roll_fwd",
    "check_no_cash_value",
)


def frame_bytes(point_id: int, frame) -> bytes:
    """The bytes one ``result_cf`` frame contributes to the hash (see module docstring)."""
    header = (
        f"point_id={point_id}\n"
        f"columns={','.join(str(c) for c in frame.columns)}\n"
        f"shape={frame.shape[0]},{frame.shape[1]}\n"
    ).encode("utf-8")
    index = frame.index.to_numpy(dtype="<i8").tobytes()
    values = frame.to_numpy(dtype="<f8").tobytes(order="C")
    return header + index + values


def run_release(release_dir: Path) -> tuple[int, str, list[str]]:
    """Run all points. Return the point count, the SHA-256 and the failures."""
    model = mx.read_model(release_dir / MODEL_NAME)
    try:
        point_ids = sorted(int(i) for i in model.Data.model_point_table().index)
        digest = hashlib.sha256()
        failures: list[str] = []
        for point_id in point_ids:
            projection = model.Projection[point_id]
            try:
                digest.update(frame_bytes(point_id, projection.result_cf()))
            except Exception as exc:  # a modelx FormulaError wraps the cause
                reason = str(exc).strip().splitlines()
                failures.append(
                    f"point {point_id}: result_cf raised {type(exc).__name__}"
                    + (f": {reason[-1]}" if reason else ""))
                continue
            for check in CHECKS:
                try:
                    passed = bool(getattr(projection, check)())
                except Exception as exc:
                    failures.append(f"point {point_id}: {check} raised {type(exc).__name__}")
                    continue
                if not passed:
                    failures.append(f"point {point_id}: {check} is false")
        return len(point_ids), digest.hexdigest(), failures
    finally:
        model.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: run_release.py <product-folder>", file=sys.stderr)
        return 2
    release_dir = Path(args[0]).resolve()
    if not (release_dir / MODEL_NAME).is_dir():
        print(f"error: no {MODEL_NAME} model in {release_dir}", file=sys.stderr)
        return 2
    count, sha256, failures = run_release(release_dir)
    elapsed = time.perf_counter() - _PROCESS_START
    print(f"model points: {count}")
    print(f"sha256: {sha256}")
    print(f"wall time: {elapsed:.1f} s")
    if failures:
        for failure in failures:
            print(f"FAILED {failure}", file=sys.stderr)
        print(f"checks: {len(failures)} failure(s)")
        return 1
    print("checks: all true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
