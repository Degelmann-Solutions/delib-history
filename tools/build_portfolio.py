"""Build the portfolio: upstream's 14 model points plus generated ones.

    uv run python tools/build_portfolio.py [product-folder]

The product folder defaults to ``risikolebensversicherung``. The script

1. reads the header and the first 14 rows of ``model_point_table.csv`` in that folder,
2. checks their bytes against the upstream SHA-256 recorded in ``UPSTREAM.md``,
3. keeps them unchanged and appends generated points, new business and in force,
4. validates every row with :func:`validate_portfolio`,
5. writes the file with LF line endings.

No random number generator is used. The same script on the same 14 rows writes the same
bytes, and running it on its own output changes nothing. If validation fails, the script
exits non-zero and writes nothing.

How the generated points are derived
------------------------------------
Each of the 14 shipped points is a template with 24 variants. A variant keeps the
template's product features (benefit schedule, Nachversicherungsgarantie, premium form,
surplus form, number of lives, rating factor) and varies these dimensions:

* policy term, over the terms the template allows;
* issue age, at 24 evenly spaced positions between the lowest and the highest issue age
  that the envelope allows for the term, so one variant per template sits on each edge;
* sex and smoker status, the four combinations equally often;
* sum assured, the template's amount times 0.5, 1, 1.5 or 2.5;
* premium frequency, for regular-premium templates;
* state: 16 variants are new business, 8 are in force, two each after one completed year,
  after 40 percent of the term, after 70 percent of the term and in the final year (for
  term 5 the last two coincide at 4 years);
* for two lives, the age gap between the lives and the smoker status of the second life.

Every dimension is balanced within a template: each of its levels is used equally often.
Which variant gets which level is decided per dimension by sorting on a SHA-256 of the
template id, the dimension name and the slot number. The dimensions are therefore mixed
independently of each other and of the template, and the result is reproducible on any
machine. With 24 variants the mix is even only on average: a single template can lack a
particular combination of two levels.

Further rules:

* ``prem_term`` follows the term: 1 for ``einmal``; otherwise the template's ratio of
  premium term to policy term, applied to the new term (point 6 pays for 12 of 20 years,
  its variants for 60 percent of their term).
* The falling benefit schedules keep the term they were written for (point 4: 20 years,
  point 5: 30 years), because the assumption CSVs stay verbatim.
* Variants of point 9 (Nachversicherungsgarantie) use terms of 15 to 28 years: the shipped
  schedule ends at year 28, and its two increases fall in policy years 6 and 12, so every
  variant reaches both.
* An in-force variant's issue date lies ``duration_y`` years before the valuation date.
  The model prices every point on its one current basis, whatever the issue date.

The envelope is upstream's documented product envelope, not what the model tolerates:
issue age 18 to 65, end age at most 75, term 5 to 40 years. The model's built-in checks
pass for rows outside it, so the envelope is asserted here on the rows themselves.
"""
from __future__ import annotations

import csv
import hashlib
import io
import itertools
import math
import re
import sys
from datetime import date
from pathlib import Path

DEFAULT_RELEASE = Path(__file__).resolve().parent.parent / "risikolebensversicherung"
PORTFOLIO_FILE = "model_point_table.csv"
UPSTREAM_FILE = "UPSTREAM.md"

N_SHIPPED = 14
VARIANTS_PER_TEMPLATE = 24

# Upstream's documented product envelope (product-spec.md, "Product identity and issue rules").
MIN_ISSUE_AGE = 18
MAX_ISSUE_AGE = 65
MAX_END_AGE = 75
MIN_TERM = 5
MAX_TERM = 40

# A falling schedule is written for one term; the NVG schedule is shipped for 28 years.
SCHEDULE_TERM = {"linear_fallend": 20, "annuitaet_fallend_3pct": 30}
KNOWN_BENEFIT_SCHEDULES = {"konstant", *SCHEDULE_TERM}
NVG_MAX_TERM = {"keine": MAX_TERM, "nvg_zwei_erhoehungen": 28}

VALUATION_DATE = date(2026, 1, 1)

# Dimension levels. Each list's length divides VARIANTS_PER_TEMPLATE.
TERMS = (5, 10, 15, 20, 25, 30, 35, 40)
# Both increases of the NVG schedule (policy years 6 and 12) lie inside these terms.
NVG_TERMS = (15, 20, 25, 28)
SUM_ASSURED_FACTORS = (0.5, 1.0, 1.5, 2.5)
SEXES = ("M", "F")
SMOKERS = ("N", "R")
PREM_FREQS = ("jaehrlich", "halbjaehrlich", "vierteljaehrlich", "monatlich")
SURPLUS_FORMS = ("beitragsverrechnung", "keine")
# New business twice as often as each in-force stage: 16 new, 2 per stage.
STATES = ("new", "new", "first_year", "new", "new", "early", "new", "new", "late",
          "new", "new", "final_year")
AGE_GAPS = (-6, -2, 2, 6)  # issue_age minus issue_age2, two lives only


class PortfolioError(ValueError):
    """The portfolio breaks the envelope, a schedule rule or the upstream pin."""


def issue_date_for(duration_y: int) -> str:
    """The issue date of a policy that has been in force for ``duration_y`` years."""
    return VALUATION_DATE.replace(year=VALUATION_DATE.year - duration_y).isoformat()


def row_errors(row: dict[str, str]) -> list[str]:
    """Return the rule violations of one model point (empty if the row is valid)."""
    errors: list[str] = []
    try:
        issue_age = int(row["issue_age"])
        term = int(row["policy_term"])
        prem_term = int(row["prem_term"])
        lives = int(row["lives"])
        issue_age2 = int(row["issue_age2"])
        duration_y = int(row["duration_y"])
        sum_assured = float(row["sum_assured"])
    except (KeyError, TypeError, ValueError) as exc:
        return [f"unreadable column: {exc}"]

    if not MIN_TERM <= term <= MAX_TERM:
        errors.append(f"policy_term {term} outside {MIN_TERM} to {MAX_TERM}")

    ages = [("issue_age", issue_age)]
    if lives == 2:
        ages.append(("issue_age2", issue_age2))
    elif lives != 1:
        errors.append(f"lives {lives} is not 1 or 2")
    for name, age in ages:
        if not MIN_ISSUE_AGE <= age <= MAX_ISSUE_AGE:
            errors.append(f"{name} {age} outside {MIN_ISSUE_AGE} to {MAX_ISSUE_AGE}")
        if age + term > MAX_END_AGE:
            errors.append(f"{name} {age} plus policy_term {term} ends above age {MAX_END_AGE}")

    schedule = row["benefit_schedule_id"]
    if schedule not in KNOWN_BENEFIT_SCHEDULES:
        errors.append(f"unknown benefit_schedule_id {schedule!r}")
    elif schedule in SCHEDULE_TERM and term != SCHEDULE_TERM[schedule]:
        errors.append(
            f"benefit schedule {schedule} is written for term {SCHEDULE_TERM[schedule]}, not {term}")

    nvg = row["nvg_schedule_id"]
    if nvg not in NVG_MAX_TERM:
        errors.append(f"unknown nvg_schedule_id {nvg!r}")
    elif term > NVG_MAX_TERM[nvg]:
        errors.append(f"nvg schedule {nvg} ends at policy year {NVG_MAX_TERM[nvg]}, term is {term}")

    if not 1 <= prem_term <= term:
        errors.append(f"prem_term {prem_term} outside 1 to policy_term {term}")
    premium_form = row["premium_form"]
    if premium_form == "einmal":
        if prem_term != 1:
            errors.append(f"einmal needs prem_term 1, not {prem_term}")
    elif premium_form != "laufend":
        errors.append(f"unknown premium_form {premium_form!r}")

    if row["prem_freq"] not in PREM_FREQS:
        errors.append(f"unknown prem_freq {row['prem_freq']!r}")
    if row["surplus_form"] not in SURPLUS_FORMS:
        errors.append(f"unknown surplus_form {row['surplus_form']!r}")
    if row["smoker2"] not in (SMOKERS if lives == 2 else ("-",)):
        errors.append(f"smoker2 {row['smoker2']!r} does not fit lives {lives}")
    if row["sex"] not in SEXES:
        errors.append(f"unknown sex {row['sex']!r}")
    if row["smoker"] not in SMOKERS:
        errors.append(f"unknown smoker {row['smoker']!r}")
    if not (math.isfinite(sum_assured) and sum_assured > 0):
        errors.append(f"sum_assured {row['sum_assured']} is not positive")

    if not 0 <= duration_y < term:
        errors.append(f"duration_y {duration_y} outside 0 to policy_term {term} - 1")
    elif row["issue_date"] != issue_date_for(duration_y):
        errors.append(
            f"issue_date {row['issue_date']} is not {duration_y} years before {VALUATION_DATE}")
    return errors


def validate_portfolio(rows: list[dict[str, str]]) -> None:
    """Raise :class:`PortfolioError` unless every row is a valid model point.

    Checks, on the rows themselves: consecutive ``point_id`` from 1, no two points with
    the same content, the product envelope
    for every life, the schedule-to-term mapping, the ``prem_term`` rule, and a duration
    below the term with a matching issue date.
    """
    problems: list[str] = []
    seen: dict[tuple[str, ...], str] = {}
    for position, row in enumerate(rows, start=1):
        point_id = row.get("point_id", "?")
        if point_id != str(position):
            problems.append(f"row {position}: point_id {point_id} is not {position}")
        twin = seen.setdefault(_content(row), point_id)
        if twin != point_id:
            problems.append(f"point {point_id}: same content as point {twin}")
        for error in row_errors(row):
            problems.append(f"point {point_id}: {error}")
    if problems:
        raise PortfolioError("invalid portfolio:\n  " + "\n  ".join(problems))


def _content(row: dict[str, str]) -> tuple[str, ...]:
    """A row without its identifiers, to detect duplicates."""
    return tuple(str(v) for k, v in row.items() if k not in ("point_id", "policy_id"))


def _mixed(template_id: str, dimension: str, levels: tuple) -> list:
    """The levels of one dimension for a template's variants, balanced and mixed.

    Each level is used equally often. The order is fixed by a SHA-256 of the template id,
    the dimension and the slot, so it differs between dimensions and between templates.
    """
    repeats, rest = divmod(VARIANTS_PER_TEMPLATE, len(levels))
    if rest:
        raise PortfolioError(f"{dimension}: {len(levels)} levels do not divide the variants")
    order = sorted(range(VARIANTS_PER_TEMPLATE), key=lambda slot: hashlib.sha256(
        f"{template_id}:{dimension}:{slot}".encode("ascii")).digest())
    balanced = [level for level in levels for _ in range(repeats)]
    result = [None] * VARIANTS_PER_TEMPLATE
    for level, slot in zip(balanced, order):
        result[slot] = level
    return result


def _duration(state: str, term: int) -> int:
    """Elapsed policy years for an in-force stage; 0 for new business."""
    return {
        "new": 0,
        "first_year": 1,
        "early": max(1, round(0.4 * term)),
        "late": round(0.7 * term),
        "final_year": term - 1,
    }[state]


def _template_terms(template: dict[str, str]) -> tuple[int, ...]:
    if template["benefit_schedule_id"] in SCHEDULE_TERM:
        return (SCHEDULE_TERM[template["benefit_schedule_id"]],)
    if template["nvg_schedule_id"] != "keine":
        return NVG_TERMS
    return TERMS


def _issue_age(row: dict[str, str], gap: int, position: float) -> int:
    """The issue age at ``position`` (0 to 1) between the lowest and highest valid age."""
    def valid(age: int) -> bool:
        return not row_errors({**row, "issue_age": str(age), "issue_age2": str(age - gap)})

    ages = [age for age in range(MIN_ISSUE_AGE, MAX_ISSUE_AGE + 1) if valid(age)]
    if not ages:
        raise PortfolioError(f"no valid issue age for term {row['policy_term']}, gap {gap}")
    return ages[0] + round(position * (ages[-1] - ages[0]))


def _variants(template: dict[str, str]) -> list[dict[str, str]]:
    """The variants of one shipped point, without identifiers."""
    tid = template["point_id"]
    two_lives = int(template["lives"]) == 2
    regular = template["premium_form"] != "einmal"
    positions = tuple(i / (VARIANTS_PER_TEMPLATE - 1) for i in range(VARIANTS_PER_TEMPLATE))
    dimensions = zip(
        _mixed(tid, "term", _template_terms(template)),
        _mixed(tid, "age", positions),
        _mixed(tid, "sex_smoker", tuple(itertools.product(SEXES, SMOKERS))),
        _mixed(tid, "sum_assured", SUM_ASSURED_FACTORS),
        _mixed(tid, "prem_freq", PREM_FREQS),
        _mixed(tid, "state", STATES),
        _mixed(tid, "age_gap", AGE_GAPS),
        _mixed(tid, "smoker2", SMOKERS),
    )
    variants = []
    for term, position, (sex, smoker), factor, prem_freq, state, gap, smoker2 in dimensions:
        row = dict(template)
        row["policy_term"] = str(term)
        ratio = int(template["prem_term"]) / int(template["policy_term"])
        row["prem_term"] = str(max(1, round(term * ratio))) if regular else "1"
        row["sex"], row["smoker"] = sex, smoker
        row["sum_assured"] = repr(float(template["sum_assured"]) * factor)
        if regular:
            row["prem_freq"] = prem_freq
        duration_y = _duration(state, term)
        row["duration_y"] = str(duration_y)
        row["issue_date"] = issue_date_for(duration_y)
        if not two_lives:
            gap = 0
        age = _issue_age(row, gap, position)
        row["issue_age"] = str(age)
        if two_lives:
            row["issue_age2"] = str(age - gap)
            row["smoker2"] = smoker2
        variants.append(row)
    return variants


def generate_points(shipped: list[dict[str, str]]) -> list[dict[str, str]]:
    """Derive the generated points from the 14 shipped ones, in a fixed order."""
    generated: list[dict[str, str]] = []
    next_id = len(shipped) + 1
    for template in shipped:
        for row in _variants(template):
            row["point_id"] = str(next_id)
            row["policy_id"] = f"RLV-{next_id:06d}"
            generated.append(row)
            next_id += 1
    return generated


def upstream_points_hash(release_dir: Path) -> str:
    """The SHA-256 of upstream's model point table, as recorded in ``UPSTREAM.md``."""
    text = (release_dir / UPSTREAM_FILE).read_text(encoding="utf-8")
    match = re.search(r"^Upstream model points SHA-256: `([0-9a-f]{64})`$", text, re.MULTILINE)
    if match is None:
        raise PortfolioError(f"{UPSTREAM_FILE} records no upstream model points SHA-256")
    return match.group(1)


def shipped_bytes(portfolio: bytes) -> bytes:
    """The header and the first 14 rows of a model point table, as bytes."""
    lines = portfolio.split(b"\n")
    if len(lines) < N_SHIPPED + 2:
        raise PortfolioError(f"model point table has fewer than {N_SHIPPED} rows")
    return b"\n".join(lines[: N_SHIPPED + 1]) + b"\n"


def parse_rows(portfolio: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Parse a model point table into its column names and rows of strings."""
    reader = csv.DictReader(io.StringIO(portfolio.decode("ascii"), newline=""))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


def build(release_dir: Path) -> bytes:
    """Return the bytes of the full portfolio for ``release_dir``; write nothing."""
    head = shipped_bytes((release_dir / PORTFOLIO_FILE).read_bytes())
    expected = upstream_points_hash(release_dir)
    actual = hashlib.sha256(head).hexdigest()
    if actual != expected:
        raise PortfolioError(
            f"the first {N_SHIPPED} model points differ from upstream: "
            f"SHA-256 {actual}, {UPSTREAM_FILE} records {expected}")
    columns, shipped = parse_rows(head)
    rows = shipped + generate_points(shipped)
    validate_portfolio(rows)
    tail = "".join(",".join(row[c] for c in columns) + "\n" for row in rows[N_SHIPPED:])
    return head + tail.encode("ascii")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: build_portfolio.py [product-folder]", file=sys.stderr)
        return 2
    release_dir = Path(args[0]) if args else DEFAULT_RELEASE
    try:
        portfolio = build(release_dir)
    except (PortfolioError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    (release_dir / PORTFOLIO_FILE).write_bytes(portfolio)
    count = portfolio.count(b"\n") - 1
    print(f"{release_dir / PORTFOLIO_FILE}: {count} model points, "
          f"SHA-256 {hashlib.sha256(portfolio).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
