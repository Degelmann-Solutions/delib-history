"""The Risikolebensversicherung model: provenance, portfolio and runner.

Two states of the repository are told apart. Release N is the first commit of this repository, and its
files are checked against upstream as that commit holds them. The present state is the
working tree: a file that a later commit has changed is listed in
``CHANGED_SINCE_RELEASE_N`` with the hash of its present bytes, and the portfolio hash and
the result hash below are those of the present state. A commit that changes one of them
updates its pin in the same commit.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "risikolebensversicherung"
PORTFOLIO = RELEASE / "model_point_table.csv"
RUNNER = ROOT / "tools" / "run_release.py"

sys.path.insert(0, str(ROOT / "tools"))
import build_portfolio as bp  # noqa: E402

FIRST_GENERATED = bp.N_SHIPPED + 1

RELEASE_N = "b64334e09613c45a7a12468dfddc0d9ec47819bb"  # the first commit of this repository
RELEASE_N_PORTFOLIO_HASH = "d3d90e3725304643cfa12b79a874b34dacd2bf2edba7baabe582d0f97a11c693"
RELEASE_N_RESULT_HASH = "c2870360917250d95f823271e8a5c181adbb7fba9ed78ffbf2088065a9249d38"

# The present state. Files copied from upstream that a commit after release N has
# changed, by their name in UPSTREAM.md, with the SHA-256 of their present bytes.
CHANGED_SINCE_RELEASE_N: dict[str, str] = {
    "RLV_DE_S/Data/__init__.py": "152bff88b270bcc9f88577fd1d8789ca29859dcf624f124df0bf6e650b9d4e13",
    "RLV_DE_S/Projection/__init__.py": "7815ee561a613e69217d010008ef5831d057a88cc92cc5fca4fd3981c130550d",
    "freq_loading_table.csv": "180052492935204542309e515ebc904e4238eff5eee28a56128fd79f3c1bb511",
    "lapse_table.csv": "981fb0a53c9a28ced2d1db44925de2f05722e7bdd567387a056fe8f43bcb8efa",
}
PORTFOLIO_HASH = "d5f9512b7e799a0a46069c3f6955d0a81a6e9acb3e6bc9ef48c700f32124d551"
RESULT_HASH = "c2870360917250d95f823271e8a5c181adbb7fba9ed78ffbf2088065a9249d38"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def folder_hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): sha256(p)
            for p in sorted(folder.rglob("*")) if p.is_file()}


def recorded_hashes() -> dict[str, str]:
    text = (RELEASE / "UPSTREAM.md").read_text(encoding="utf-8")
    return dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.MULTILINE))


def release_n_bytes(name: str) -> bytes:
    """A file of the product folder as the commit of release N holds it, from the object store."""
    done = subprocess.run(["git", "-C", str(ROOT), "cat-file", "blob", f"{RELEASE_N}:{RELEASE.name}/{name}"],
                          capture_output=True)
    assert done.returncode == 0, (
        f"the commit of release N, {RELEASE_N}, cannot be read; the tests need Git and the "
        f"complete history of this repository: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def committed_rows() -> list[dict[str, str]]:
    return bp.parse_rows(PORTFOLIO.read_bytes())[1]


def scratch_copy(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copytree(RELEASE, target)
    return target


def edit_point(release_dir: Path, point_id: int, **changes: str) -> None:
    """Change columns of one model point in a scratch copy, as text."""
    path = release_dir / "model_point_table.csv"
    lines = path.read_bytes().decode("ascii").split("\n")
    columns = lines[0].split(",")
    values = lines[point_id].split(",")
    assert values[0] == str(point_id)
    for column, value in changes.items():
        assert values[columns.index(column)] != value
        values[columns.index(column)] = value
    lines[point_id] = ",".join(values)
    path.write_bytes("\n".join(lines).encode("ascii"))


# --- provenance ---------------------------------------------------------------------


def test_upstream_md_records_every_copied_file():
    recorded = set(recorded_hashes())
    present = set(folder_hashes(RELEASE))
    assert len(recorded) == 10
    assert present == recorded | {"UPSTREAM.md", "model_point_table.csv"}


@pytest.mark.parametrize("name", sorted(recorded_hashes()))
def test_copied_file_matches_upstream_hash_at_release_n(name):
    digest = hashlib.sha256(release_n_bytes(name)).hexdigest()
    assert digest == recorded_hashes()[name], f"{name} of release N differs from upstream"


@pytest.mark.parametrize("name", sorted(recorded_hashes()))
def test_copied_file_has_its_pinned_hash(name):
    # Unchanged since release N, or changed by a commit that pinned the new bytes.
    upstream = recorded_hashes()[name]
    assert sha256(RELEASE / name) == CHANGED_SINCE_RELEASE_N.get(name, upstream), (
        f"{name} differs from its pinned hash")
    assert CHANGED_SINCE_RELEASE_N.get(name) != upstream, f"{name} is listed as changed and is not"


def test_only_copied_files_are_listed_as_changed():
    assert set(CHANGED_SINCE_RELEASE_N) <= set(recorded_hashes())


def test_shipped_model_points_match_upstream_hash():
    head = bp.shipped_bytes(PORTFOLIO.read_bytes())
    assert head.count(b"\n") == 15
    assert hashlib.sha256(head).hexdigest() == bp.upstream_points_hash(RELEASE)
    assert bp.upstream_points_hash(RELEASE) == (
        "dfc9fae39993a6d60b388650340d0a851c46a3d452bbf0c3a90936b70bf0414a")


def test_release_files_are_lf():
    for name in folder_hashes(RELEASE):
        assert b"\r" not in (RELEASE / name).read_bytes(), name


def test_no_modelx_writer_is_called():
    sources = list((ROOT / "tools").glob("*.py"))
    assert len(sources) == 2
    for path in sources:
        source = path.read_text(encoding="utf-8")
        for writer in ("write_model", "export_model", "zip_model"):
            assert writer not in source, f"{path.name} mentions {writer}"


# --- portfolio ----------------------------------------------------------------------


def generated_row(**changes: object) -> dict[str, str]:
    """Shipped point 1 (new business, age 35, term 25) as a base row, with columns overridden."""
    row = dict(committed_rows()[0])
    row.update({k: str(v) for k, v in changes.items()})
    return row


def test_validator_accepts_committed_portfolio():
    rows = committed_rows()
    assert len(rows) > 250
    bp.validate_portfolio(rows)


def test_generated_points_stay_inside_the_envelope():
    for row in committed_rows()[bp.N_SHIPPED:]:
        age, term = int(row["issue_age"]), int(row["policy_term"])
        assert 18 <= age <= 65 and 5 <= term <= 40 and age + term <= 75, row["point_id"]
        if row["lives"] == "2":
            age2 = int(row["issue_age2"])
            assert 18 <= age2 <= 65 and age2 + term <= 75, row["point_id"]
        duration_y = int(row["duration_y"])
        assert 0 <= duration_y < term, row["point_id"]
        assert row["issue_date"] == f"{2026 - duration_y}-01-01", row["point_id"]
        assert 1 <= int(row["prem_term"]) <= term, row["point_id"]
        if row["benefit_schedule_id"] == "linear_fallend":
            assert term == 20, row["point_id"]
        if row["benefit_schedule_id"] == "annuitaet_fallend_3pct":
            assert term == 30, row["point_id"]
        if row["nvg_schedule_id"] == "nvg_zwei_erhoehungen":
            assert 12 <= term <= 28, row["point_id"]  # both increases, years 6 and 12


def templates() -> list[list[dict[str, str]]]:
    """The generated points, grouped by the shipped point they vary."""
    generated = committed_rows()[bp.N_SHIPPED:]
    assert len(generated) == bp.N_SHIPPED * bp.VARIANTS_PER_TEMPLATE
    return [generated[i:i + bp.VARIANTS_PER_TEMPLATE]
            for i in range(0, len(generated), bp.VARIANTS_PER_TEMPLATE)]


def counts(rows, *columns) -> dict[tuple[str, ...], int]:
    result: dict[tuple[str, ...], int] = {}
    for row in rows:
        key = tuple(row[c] for c in columns)
        result[key] = result.get(key, 0) + 1
    return result


def in_force(row: dict[str, str]) -> bool:
    return int(row["duration_y"]) > 0


def test_portfolio_is_the_recorded_one():
    # The portfolio of the present state. Change it on purpose: rebuild, then update
    # PORTFOLIO_HASH, RESULT_HASH, and the figures in README.md in the same commit.
    assert sha256(PORTFOLIO) == PORTFOLIO_HASH


def test_portfolio_of_release_n_is_the_recorded_one():
    released = release_n_bytes(PORTFOLIO.name)
    assert hashlib.sha256(released).hexdigest() == RELEASE_N_PORTFOLIO_HASH
    assert hashlib.sha256(bp.shipped_bytes(released)).hexdigest() == bp.upstream_points_hash(RELEASE)


def test_every_dimension_is_balanced_within_each_template():
    v = bp.VARIANTS_PER_TEMPLATE
    for shipped, variants in zip(committed_rows(), templates()):
        point = shipped["point_id"]
        terms = counts(variants, "policy_term")
        assert len(set(terms.values())) == 1, point
        if shipped["benefit_schedule_id"] in bp.SCHEDULE_TERM:
            assert len(terms) == 1, point
        elif shipped["nvg_schedule_id"] != "keine":
            assert set(terms) == {(str(t),) for t in bp.NVG_TERMS}, point
        else:
            assert set(terms) == {(str(t),) for t in bp.TERMS}, point
        assert set(counts(variants, "sex", "smoker").values()) == {v // 4}, point
        assert len(counts(variants, "sex", "smoker")) == 4, point
        assert len({row["sum_assured"] for row in variants}) == 4, point
        assert set(counts(variants, "sum_assured").values()) == {v // 4}, point
        assert sum(in_force(row) for row in variants) == v // 3, point
        if shipped["premium_form"] == "laufend":
            assert counts(variants, "prem_freq") == {(f,): v // 4 for f in bp.PREM_FREQS}, point
        if shipped["lives"] == "2":
            assert counts(variants, "smoker2") == {("N",): v // 2, ("R",): v // 2}, point
            gaps = [int(row["issue_age"]) - int(row["issue_age2"]) for row in variants]
            assert sorted(set(gaps)) == sorted(bp.AGE_GAPS), point


def test_dimensions_are_not_tied_to_each_other():
    generated = [row for variants in templates() for row in variants]
    unrestricted = [row for shipped, variants in zip(committed_rows(), templates())
                    if shipped["benefit_schedule_id"] == "konstant"
                    and shipped["nvg_schedule_id"] == "keine" for row in variants]

    # Every term occurs with both sexes, both smoker classes, new business and in force.
    for term in bp.TERMS:
        rows = [row for row in unrestricted if row["policy_term"] == str(term)]
        assert len(counts(rows, "sex", "smoker")) == 4, term
        assert {in_force(row) for row in rows} == {True, False}, term
        assert len(counts(rows, "prem_freq")) == 4, term
    # In-force points are not all one sex or smoker class, in any template.
    for variants in templates():
        rows = [row for row in variants if in_force(row)]
        assert len(counts(rows, "sex")) == 2 and len(counts(rows, "smoker")) == 2
    # Every premium frequency meets every benefit schedule and both numbers of lives.
    assert len(counts(generated, "prem_freq", "benefit_schedule_id")) == 4 * 3
    assert len(counts(generated, "prem_freq", "lives")) == 4 * 2
    # No (age, term, duration) combination dominates.
    assert max(counts(generated, "issue_age", "policy_term", "duration_y").values()) <= 6
    assert len(counts(generated, "issue_age", "policy_term")) >= 150


def test_generated_points_cover_the_envelope_and_the_mechanics():
    generated = [row for variants in templates() for row in variants]
    ages = {int(row["issue_age"]) for row in generated}
    assert {18, 65} <= ages
    # One variant per template on each edge of its age range.
    for variants in templates():
        assert any(int(r["issue_age"]) + int(r["policy_term"]) == 75 or r["issue_age"] == "65"
                   or (r["lives"] == "2" and int(r["issue_age2"]) + int(r["policy_term"]) == 75)
                   for r in variants)
    assert sum(int(r["issue_age"]) + int(r["policy_term"]) == 75 for r in generated) >= 5

    # In-force stages: first year, mid term, and the final policy year.
    assert any(row["duration_y"] == "1" for row in generated)
    final_year = [r for r in generated if int(r["duration_y"]) == int(r["policy_term"]) - 1]
    assert len(final_year) >= bp.N_SHIPPED

    # Every variant of point 6 keeps its limited premium term, 60 percent of the term,
    # and some of them are in force past it.
    limited = templates()[5]
    for row in limited:
        assert int(row["prem_term"]) == round(int(row["policy_term"]) * 12 / 20), row["point_id"]
        assert int(row["prem_term"]) < int(row["policy_term"]), row["point_id"]
    assert any(int(row["duration_y"]) >= int(row["prem_term"]) for row in limited)

    # In-force variants of the Nachversicherungsgarantie before, between and after the
    # two increases in policy years 6 and 12 need not all exist; at least two stages do.
    nvg = [int(row["duration_y"]) for row in templates()[8] if in_force(row)]
    assert len({(d >= 5) + (d >= 11) for d in nvg}) >= 2


@pytest.mark.parametrize("changes", [
    {"issue_age": 18, "policy_term": 40, "prem_term": 40},
    {"issue_age": 65, "policy_term": 5, "prem_term": 5},
    {"issue_age": 35, "policy_term": 40, "prem_term": 40},   # end age 75
    {"issue_age": 60, "policy_term": 15, "prem_term": 15},   # end age 75
    {"issue_age": 40, "policy_term": 5, "prem_term": 5},
    {"issue_age": 40, "policy_term": 20, "prem_term": 20, "benefit_schedule_id": "linear_fallend"},
    {"issue_age": 40, "policy_term": 30, "prem_term": 30,
     "benefit_schedule_id": "annuitaet_fallend_3pct"},
    {"issue_age": 40, "policy_term": 28, "prem_term": 28,
     "nvg_schedule_id": "nvg_zwei_erhoehungen"},
    {"issue_age": 40, "policy_term": 20, "prem_term": 1, "premium_form": "einmal"},
    {"issue_age": 40, "policy_term": 20, "prem_term": 20, "duration_y": 19,
     "issue_date": "2007-01-01"},
    {"lives": 2, "smoker2": "N", "issue_age": 65, "issue_age2": 18, "policy_term": 10, "prem_term": 10},
])
def test_validator_accepts_boundary_rows(changes):
    assert bp.row_errors(generated_row(**changes)) == []


@pytest.mark.parametrize("changes", [
    {"issue_age": 66, "policy_term": 5, "prem_term": 5},
    {"issue_age": 61, "policy_term": 15, "prem_term": 15},
    {"issue_age": 17, "policy_term": 20, "prem_term": 20},
    {"issue_age": 40, "policy_term": 4, "prem_term": 4},
    {"issue_age": 20, "policy_term": 41, "prem_term": 41},
    {"issue_age": 40, "policy_term": 10, "prem_term": 10, "benefit_schedule_id": "linear_fallend"},
    {"issue_age": 40, "policy_term": 20, "prem_term": 20,
     "benefit_schedule_id": "annuitaet_fallend_3pct"},
    {"issue_age": 40, "policy_term": 30, "prem_term": 30,
     "nvg_schedule_id": "nvg_zwei_erhoehungen"},
    {"issue_age": 40, "policy_term": 20, "prem_term": 21},
    {"issue_age": 40, "policy_term": 20, "prem_term": 0},
    {"issue_age": 40, "policy_term": 20, "prem_term": 20, "premium_form": "einmal"},
    {"issue_age": 40, "policy_term": 20, "prem_term": 20, "duration_y": 20,
     "issue_date": "2006-01-01"},
    {"issue_age": 40, "policy_term": 20, "prem_term": 20, "duration_y": 3},  # issue date 2026
    {"lives": 2, "smoker2": "N", "issue_age": 40, "issue_age2": 17, "policy_term": 20, "prem_term": 20},
    {"lives": 2, "smoker2": "N", "issue_age": 40, "issue_age2": 61, "policy_term": 15, "prem_term": 15},
    {"issue_age": 40, "policy_term": 20, "prem_term": 20, "prem_freq": "woechentlich"},
    {"issue_age": 40, "policy_term": 20, "prem_term": 20, "smoker2": "N"},  # one life
])
def test_validator_rejects_invalid_rows(changes):
    row = generated_row(**changes)
    assert bp.row_errors(row)
    rows = committed_rows()
    row["point_id"] = rows[-1]["point_id"]
    with pytest.raises(bp.PortfolioError):
        bp.validate_portfolio(rows[:-1] + [row])


def test_rebuild_from_shipped_rows_is_byte_identical(tmp_path):
    scratch = scratch_copy(tmp_path, "rebuild")
    target = scratch / "model_point_table.csv"
    target.write_bytes(bp.shipped_bytes(PORTFOLIO.read_bytes()))
    assert bp.main([str(scratch)]) == 0
    assert target.read_bytes() == PORTFOLIO.read_bytes()
    assert bp.main([str(scratch)]) == 0  # running on its own output changes nothing
    assert target.read_bytes() == PORTFOLIO.read_bytes()


def test_build_with_invalid_row_exits_non_zero_and_writes_nothing(tmp_path, monkeypatch):
    scratch = scratch_copy(tmp_path, "invalid")
    target = scratch / "model_point_table.csv"
    target.write_bytes(bp.shipped_bytes(PORTFOLIO.read_bytes()))
    before = folder_hashes(scratch)
    bad = generated_row(point_id=FIRST_GENERATED, issue_age=66, policy_term=5, prem_term=5)
    monkeypatch.setattr(bp, "generate_points", lambda shipped: [bad])
    assert bp.main([str(scratch)]) == 1
    assert folder_hashes(scratch) == before


def test_build_rejects_changed_shipped_rows(tmp_path):
    scratch = scratch_copy(tmp_path, "drift")
    edit_point(scratch, 3, sum_assured="300001.0")
    before = folder_hashes(scratch)
    assert bp.main([str(scratch)]) == 1
    assert folder_hashes(scratch) == before


# --- runner -------------------------------------------------------------------------


def parse_output(stdout: str) -> dict[str, str]:
    return dict(line.split(": ", 1) for line in stdout.splitlines() if ": " in line)


@pytest.fixture(scope="session")
def runs(tmp_path_factory):
    """Run the runner four times, in parallel processes, and collect the outcomes.

    ``first`` and ``second`` are two processes on the product folder. ``changed`` is a scratch copy
    with one value changed in a generated point. ``false_check`` is a scratch copy with
    one generated point whose ``duration_y`` equals its ``policy_term``.
    """
    tmp_path = tmp_path_factory.mktemp("runs")
    last = len(committed_rows())
    changed = scratch_copy(tmp_path, "changed")
    edit_point(changed, last, sum_assured="123456.0")
    false_check = scratch_copy(tmp_path, "false_check")
    term = committed_rows()[FIRST_GENERATED - 1]["policy_term"]
    edit_point(false_check, FIRST_GENERATED, duration_y=term)

    before = folder_hashes(RELEASE)
    folders = {"first": RELEASE, "second": RELEASE, "changed": changed,
               "false_check": false_check}
    processes = {
        name: subprocess.Popen([sys.executable, str(RUNNER), str(folder)], cwd=ROOT,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for name, folder in folders.items()}
    results = {}
    for name, process in processes.items():
        stdout, stderr = process.communicate(timeout=900)
        results[name] = (process.returncode, parse_output(stdout), stderr)
    results["before"] = before
    results["after"] = folder_hashes(RELEASE)
    return results


def test_release_n_runs_with_all_checks_true(runs):
    # The runner evaluates the five built-in checks for every point and exits non-zero
    # if any is false, so exit 0 and "all true" cover every point and every check.
    code, output, stderr = runs["first"]
    assert code == 0, stderr
    assert output["checks"] == "all true"
    assert re.fullmatch(r"\d+\.\d s", output["wall time"])
    assert "FAILED" not in stderr


def test_runner_checks_the_five_built_in_checks():
    sys.path.insert(0, str(RUNNER.parent))
    import run_release
    assert set(run_release.CHECKS) == {
        "check_net_cf", "check_pols_roll_fwd", "check_prem_split",
        "check_res_roll_fwd", "check_no_cash_value"}


def test_point_count_equals_portfolio_rows(runs):
    assert int(runs["first"][1]["model points"]) == len(committed_rows())


def test_two_processes_give_one_hash(runs):
    first, second = runs["first"][1]["sha256"], runs["second"][1]["sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first == second


def test_result_hash_is_the_recorded_one(runs):
    # The hash of the present state. A revision that moves a result changes it on
    # purpose: update RESULT_HASH in the same commit. Until a revision moves a result it
    # is the hash of release N. It is taken from raw 64-bit floats and has been confirmed
    # on one machine only.
    assert runs["first"][1]["sha256"] == RESULT_HASH
    unchanged = not CHANGED_SINCE_RELEASE_N and PORTFOLIO_HASH == RELEASE_N_PORTFOLIO_HASH
    assert not unchanged or RESULT_HASH == RELEASE_N_RESULT_HASH


def test_changed_generated_point_changes_the_hash(runs):
    code, output, stderr = runs["changed"]
    assert code == 0, stderr
    assert output["sha256"] != runs["first"][1]["sha256"]


def test_false_check_gives_non_zero_exit_and_names_point_and_check(runs):
    code, output, stderr = runs["false_check"]
    assert code == 1
    assert f"point {FIRST_GENERATED}: check_pols_roll_fwd is false" in stderr
    assert int(output["model points"]) == len(committed_rows())


def test_run_leaves_the_product_folder_untouched(runs):
    assert runs["after"] == runs["before"]
