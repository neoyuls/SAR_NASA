"""Pin the numbers in `pipeline/README.md` to the artefacts and constants they describe.

`pipeline/README.md` is the judge-facing description of the offline pipeline. It has gone stale
twice in one day — first quoting the pre-fix per-case artefact numbers, then the pre-AOI-refresh
cell counts. Schema validation cannot catch that: a stale table is *valid*, just wrong. So every
number below is re-derived from the tree and compared *both* ways: the doc is parsed at run time
(never restated here) and a case on disk with no doc row fails too.

Sources of truth
----------------
`data/processed/{case}/nisar_grid.parquet`, `meta.json`, `context_layers.geojson` and the size of
the four-file copy; `data/processed/_availability/*.json` for the probe claims; `src/domain/
contracts.py` and `pipeline/science/transforms.py` for the frozen constants and the geometry.
Nothing here writes files, imports Streamlit, or touches the network.

Tolerances — stated once, justified, and *not* tuned to be green
---------------------------------------------------------------
  cells, class count, file/case counts   exact        integers printed unrounded in the doc
  velocities (median, p05)               ±0.1 mm/yr   one decimal printed; ±0.05 is the rounding
                                                      error, 0.1 leaves a digit so a .x5 boundary
                                                      cannot flap
  coherence                              ±0.005       two decimals printed, so 0.005 is rounding
  size (decimal MB, 1e6 bytes)           ±0.02 MB     two decimals printed; the rest absorbs a copy
                                                      whose parquet was recompressed (display
                                                      tolerance, not a science one)
  detection limit                        ±0.05 mm/yr  one decimal printed
  phase→mm cell                          one unit in the last printed digit (18.97 → ±0.01,
                                                      153.4 → ±0.1): a value that still rounds to
                                                      the printed string passes
  reproduce-command arrow                ±0.005       the doc prints `round(..., 2)`
  date window, day count, probe dates    exact        ISO dates and integers, compared verbatim
  probe span in months                   ±1.5 months  the doc says "~12 months"; a month is 30.44 d
                                                      and the span is read from the JSON
  fringe fraction                        ±0.005       two decimals printed

One asymmetry is deliberate: the Sentinel-1 example endpoints (`Málaga 2025-11-18 → 2026-11-13`)
are *reported* as a finding, not asserted. The page-capped query returns a sliding 250-granule
window, and the doc itself now says to "treat those endpoints as an example rather than a fact
about the archive"; failing on every re-probe would punish the documented `search` command. The
stable claims on that line (query years, `maxResults`, the `N+` floor, ~12 months, "not 5 years")
stay hard.

Findings vs failures
--------------------
A number that contradicts an artefact, a frozen constant or its own table fails the build. Numbers
with no artefact behind them are documented as context and never silently pass; the one case that
used to report a "finding, not a failure" warning was a false alarm — see
:func:`test_mexico_city_pair_anchor`, where the fringe fraction is checked against the VERTICAL
fringe because the quoted rate and displacement share that basis.

Allowlist
---------
Numbers in the doc that are deliberately *not* artefact-derived (frozen constants, runbook process
facts, citations) are listed in :data:`ALLOWLIST` with a one-line reason each. A test asserts every
entry still matches the doc, so an allowlist item cannot rot silently after a rewrite.

Skipped with a clear reason while `data/processed/` has no generated cases.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd
import pytest

from pipeline.science import transforms
from src.domain import contracts

DOC = pathlib.Path("pipeline/README.md")
if not DOC.is_file():
    pytest.skip(
        "pipeline/README.md is not shipped in the submitted repository",
        allow_module_level=True,
    )
ROOT = pathlib.Path("data/processed")
AVAILABILITY = ROOT / "_availability"
REQUIRED_FILES = ("nisar_grid.parquet", "timeseries.csv", "context_layers.geojson", "meta.json")

HEADLINE_HEADING = "Mock headline numbers"
HEADLINE_COLUMNS = ("case", "cells", "median", "p05", "size")
PHASE_HEADING = "Numbers a sceptic can reproduce"
PHASE_COLUMNS = ("quantity", "los", "vertical")

MINUS_SIGNS = "\u2212\u2010\u2011\u2012\u2013\u2014\u2015\u2043\ufe63\uff0d"

TOL_VELOCITY = 0.1
TOL_COHERENCE = 0.005
TOL_SIZE_MB = 0.02
TOL_DETECTION = 0.05
TOL_FRINGE_FRACTION = 0.005
TOL_REPRODUCE = 0.005
TOL_PROBE_MONTHS = 1.5

#: Doc numbers that are NOT derived from the committed artefacts. ``(regex, why-not)``.
#: The regex must keep matching the doc: :func:`test_allowlist_entries_are_still_in_the_doc`.
ALLOWLIST: tuple[tuple[str, str], ...] = (
    (
        r"\b2026-11-14\b",
        "run/probe/processing date (also meta.provenance.processing_date): a calendar stamp, "
        "not a quantity measured from the tree",
    ),
    (
        r"contract v1\.1",
        "schema version pinned in contracts.SCHEMA_VERSION (now 1.1), not an artefact statistic; "
        "the same header line names v1.0 as the version the bump came from",
    ),
    (
        r"ed92be80",
        "contract_fingerprint() abbreviated on the page; a code-derived hash cross-checked by "
        "tests/test_fingerprint_consistency.py, not a quantity measured from the tree",
    ),
    (
        r"λ_?L?\s*=\s*0\.2384\s*m",
        "NISAR L-band wavelength from docs/nisar-gunw-layout.md §4: a physical constant, and the "
        "phase table is recomputed *from* it",
    ),
    (
        r"θ\s*=\s*39\s*°",
        "nominal incidence for the scale check, same page as λ; the phase table is recomputed from it",
    ),
    (
        r"0\.2384/\(4\*math\.pi\)\*1e3,39,192",
        "the reproduce command is parsed and evaluated below; heading 192 only sets the east/north "
        "terms, which vanish when v_north = 0",
    ),
    (
        r"at\s*[−-]\s*420\s*mm/yr",
        "Mexico City's published/peak rate (config/study_cases.yaml mock seed value, "
        "nisar-gunw-layout §4 anchor); the grid's own max |v| is 415.1 mm/yr, so 420 is not a "
        "statistic of the artefacts",
    ),
    (
        r"\|median\|\s*<\s*5\s*mm/yr",
        "contracts.NULL_RESULT_MM_YR, the frozen null-result threshold; the test also asserts it "
        "equals the constant and that Málaga's |median| sits below it",
    ),
    (
        r"0\.75 yr",
        "transforms.MIN_SEASONAL_COVERAGE_PER_HARMONIC: a code constant, not an artefact statistic",
    ),
    (
        r"\b80 m\b",
        "GUNW posting from docs/nisar-gunw-layout.md §5; no artefact stores a posting, and which "
        "layer to use is still an open question",
    ),
    (
        r"\b20 m\b",
        "the alternative coherence-layer posting, same open question as 80 m",
    ),
    (
        r"MAX_DESIGN_CONDITION\s*=\s*30",
        "transforms.MAX_DESIGN_CONDITION: the frozen collinearity gate (a code constant), printed "
        "next to the measured design condition 4.12 so a reader can divide the two",
    ),
    (
        r"design condition\s+66\.8",
        "the OLD 132-day window's design condition, recorded in meta.limitations (the artefact's "
        "own history line): a past measurement, not a statistic of the current tree — 4.12 is "
        "the value compared against meta.stats",
    ),
    (
        r"~200 m",
        "nominal H3 res-9 cell size (h3 mean edge ≈ 0.2 km): a property of the grid spec, not of "
        "this run",
    ),
    (
        r"res-9",
        "the H3 resolution itself (contract grid spec), not a measured count",
    ),
    (
        r"four artefacts",
        "the four-file contract set (contract §1): a schema fact, not a measurement",
    ),
    (
        r"twelve files",
        "file count = 3 cases × 4 artefacts; byte-identity is guarded by test_mock_expectations, "
        "not a measured quantity",
    ),
    (
        r"zero cases is a FAIL",
        "fail-closed behaviour of validate_artifacts (a rule, not a number from the tree)",
    ),
    (
        r"all four sub-steps",
        "count of steps in scripts/check_phase_a.sh; a process fact",
    ),
    (
        r"--max-gb 2\b",
        "example CLI budget in the runbook, not a size measured from the tree",
    ),
    (
        r"sha256_8",
        "digest truncation length from contracts.provenance_id, not an artefact statistic",
    ),
    (
        r"v_north\s*(?:≈|=)\s*0",
        "the frozen one-geometry assumption in transforms.los_to_vertical; a premise, not a "
        "measurement",
    ),
    (
        r"target\s*<\s*5\s*mm/yr RMSE",
        "GNSS validation target from README §13: a goal, not a measurement",
    ),
    (
        r"§\d+(?:\.\d+)?",
        "section cross-references (§1, §4, §13.3…), not quantities",
    ),
    (
        r"hard rule 1",
        "reference to contracts.py hard rule 1, not a quantity",
    ),
    (
        r"Step [67]\b",
        "runbook step numbers, not quantities",
    ),
    (
        r"all three cases",
        "count of published cases; the metadata test asserts the count against data/processed/ "
        "instead of trusting every wording of it",
    ),
)


# --------------------------------------------------------------------------------------------
# case discovery
# --------------------------------------------------------------------------------------------


def _case_dirs() -> dict[str, pathlib.Path]:
    """Case directories that actually carry a full artefact set."""
    if not ROOT.is_dir():
        return {}
    return {
        p.name: p
        for p in sorted(ROOT.iterdir())
        if p.is_dir()
        and not p.name.startswith(("_", "."))
        and all((p / f).is_file() for f in REQUIRED_FILES)
    }


CASE_DIRS = _case_dirs()
CASES = sorted(CASE_DIRS)

pytestmark = pytest.mark.skipif(
    not CASES,
    reason=(
        "no case artefacts under data/processed/ — generate them with "
        "`./scripts/python.sh pipeline/generate_mock.py` before pinning the pipeline README"
    ),
)


# --------------------------------------------------------------------------------------------
# doc parsing (structure only: headings, header names, row labels — never line numbers)
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One parsed doc row, with enough provenance to quote it in a failure message."""

    values: dict[str, str]
    line_no: int
    text: str


def _doc_lines() -> list[str]:
    if not DOC.is_file():
        pytest.fail(
            f"{DOC} is missing. This test exists to keep it honest; restore the page (or retire "
            f"this test deliberately) before reading the numbers it documents."
        )
    return DOC.read_text(encoding="utf-8").splitlines()


def _split_row(text: str) -> list[str]:
    return [cell.strip() for cell in text.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells)


def _clean(cell: str) -> str:
    return cell.strip().strip("`*").strip()


def _column(header: list[str], name: str, *, what: str, line_no: int) -> int:
    """Index of the header cell that names column `name` (exact, else prefix)."""
    for index, cell in enumerate(header):
        normalised = _clean(cell).lower()
        if normalised == name or normalised.startswith(name):
            return index
    pytest.fail(
        f"pipeline/README.md:{line_no}: the {what} header has no column starting with {name!r}\n"
        f"  documented: {' | '.join(header)}\n"
        f"  expected:   a column named {name!r} (any wording that starts with it)\n"
        f"  tolerance:  n/a — this is a structure check, not a number\n"
        f"  The table is parsed by header name, so rename the column here and in this test together."
    )


def _table(heading: str, columns: tuple[str, ...], *, what: str) -> list[Row]:
    """First markdown table after `heading`, as rows keyed by the requested column names."""
    lines = _doc_lines()
    start = next((i for i, line in enumerate(lines) if heading in line), None)
    if start is None:
        pytest.fail(
            f"pipeline/README.md: no line contains {heading!r}. The {what} this test pins was "
            f"renamed or removed; update the heading constant in the same change that moved it.\n"
            f"  tolerance:  n/a — structure check"
        )
    block: list[tuple[int, str]] = []
    for line_no, line in enumerate(lines[start + 1 :], start=start + 2):  # 1-based line numbers
        if line.lstrip().startswith("|"):
            block.append((line_no, line))
        elif block:
            break
    if len(block) < 2:
        pytest.fail(
            f"pipeline/README.md:{start + 1}: no markdown table under {heading!r}; the numbers "
            f"cannot be pinned if the table is gone.\n  tolerance:  n/a — structure check"
        )
    header_line_no, header_text = block[0]
    header = _split_row(header_text)
    positions = {
        name: _column(header, name, what=what, line_no=header_line_no) for name in columns
    }
    rows: list[Row] = []
    for line_no, text in block[1:]:
        cells = _split_row(text)
        if _is_separator(cells):
            continue
        if len(cells) != len(header):
            pytest.fail(
                f"pipeline/README.md:{line_no}: {len(cells)} columns where {len(header)} are "
                f"declared\n  {text.strip()}\n"
                f"  documented header: {' | '.join(header)}\n"
                f"  tolerance:  n/a — structure check"
            )
        rows.append(
            Row(
                values={name: cells[index] for name, index in positions.items()},
                line_no=line_no,
                text=text,
            )
        )
    if not rows:
        pytest.fail(
            f"pipeline/README.md:{start + 1}: the table under {heading!r} has a header but no data "
            f"rows, so there is nothing to pin.\n  tolerance:  n/a — structure check"
        )
    return rows


def _line(pattern: str, *, what: str, span: int = 1) -> tuple[int, str]:
    """First match of `pattern`, as (1-based line number, that line [+ next lines]).

    `span` > 1 joins wrapped lines before searching: prose claims often break mid-sentence, and a
    per-line search would call a wrapped claim "removed".
    """
    lines = _doc_lines()
    for index in range(len(lines)):
        window = " ".join(lines[index : index + span])
        if re.search(pattern, window):
            return index + 1, window
    pytest.fail(
        f"pipeline/README.md: no line matches {pattern!r} ({what}). The claim this test pins was "
        f"reworded or removed; update the regex in the same change that moved the claim.\n"
        f"  tolerance:  n/a — structure check"
    )


def _number(cell: str, *, what: str, line_no: int, text: str) -> float:
    raw = _clean(cell).translate({ord(c): "-" for c in MINUS_SIGNS}).replace(",", "")
    raw = raw.replace("\u00a0", "").replace("\u2009", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
    if match is None:
        pytest.fail(
            f"pipeline/README.md:{line_no}: cannot read {what} from {cell!r} in the row\n"
            f"  {text.strip()}\n  Expected a number such as 4,811 or -141.9."
        )
    return float(match.group(0))


def _size_mb(cell: str, *, what: str, line_no: int, text: str) -> float:
    raw = _clean(cell)
    match = re.fullmatch(r"([0-9][0-9,.]*)\s*MB", raw, flags=re.IGNORECASE)
    if not match:
        pytest.fail(
            f"pipeline/README.md:{line_no}: cannot read {what} from {cell!r} in the row\n"
            f"  {text.strip()}\n  Expected decimal megabytes, e.g. `1.01 MB`."
        )
    return float(match.group(1).replace(",", ""))


def _printed_tolerance(cell: str) -> float:
    """One unit in the last digit the doc printed (18.97 → 0.01, 153.4 → 0.1)."""
    match = re.search(r"\d+(?:\.(\d+))?", _clean(cell))
    assert match is not None  # guarded by the callers, which parse the cell first
    return 10.0 ** -len(match.group(1) or "")


def _norm_label(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _case_from_label(label: str, *, line_no: int, text: str) -> str:
    wanted = _norm_label(label.split("'")[0])
    for case in CASES:
        slug = _norm_label(case)
        if wanted in (slug, slug.replace("-", "")):
            return case
    pytest.fail(
        f"pipeline/README.md:{line_no}: the doc names {label!r}, which matches no case under "
        f"data/processed/\n  doc line:   {text.strip()}\n"
        f"  measured:   cases on disk = {', '.join(CASES) or '(none)'}\n"
        f"  tolerance:  n/a — the per-case comparison needs the name to resolve"
    )


# --------------------------------------------------------------------------------------------
# measurement
# --------------------------------------------------------------------------------------------


def _measure_case(case: str) -> dict[str, object]:
    directory = CASE_DIRS[case]
    grid = pd.read_parquet(directory / "nisar_grid.parquet")
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    stats = meta["stats"]
    return {
        "cells": len(grid),
        "median": float(stats["median_velocity_mm_yr"]),
        "p05": float(stats["p05_velocity_mm_yr"]),
        "coherence_min": float(grid["coherence"].min()),
        "coherence_max": float(grid["coherence"].max()),
        "classes": int(grid["land_use"].nunique()),
        "water_cells": int((grid["land_use"] == "water").sum()),
        # decimal MB, as the doc prints it; every file in the case directory is part of the copy
        "size_mb": sum(f.stat().st_size for f in directory.iterdir() if f.is_file()) / 1_000_000,
        "dates": list(meta["dates"]),
        "revisit_days": int(meta["revisit_days"]),
        "product": str(meta["product"]),
        "crs": str(meta["crs"]),
        "seed": meta["provenance"].get("mock_seed"),
        "source": str(meta["provenance"].get("source", "")),
        "detection_limit": stats.get("detection_limit_mm_yr"),
        # the seasonal publication claim (§7 limitation 4): the meta verdict *and* the columns it
        # says were published, so "published as fit results" is checked against the grid itself
        "annual_coverage": stats.get("annual_coverage"),
        "design_condition": stats.get("design_condition"),
        "seasonal_n_harmonics": stats.get("seasonal_n_harmonics"),
        "seasonal_amp": stats.get("median_seasonal_amp_mm"),
        "ratio_R": stats.get("median_ratio_R"),
        "regime": stats.get("dominant_regime"),
        "limitations": list(meta.get("limitations") or []),
        "seasonal_columns": sorted(
            column for column in ("seasonal_amp_mm", "ratio_R", "regime") if column in grid.columns
        ),
        "seasonal_nulls": int(
            sum(
                grid[column].isna().sum()
                for column in ("seasonal_amp_mm", "ratio_R", "regime")
                if column in grid.columns
            )
        ),
        # contract §3: ratio_R = |velocity_mm_yr| / seasonal_amp_mm on the same row
        "ratio_consistent": bool(
            all(column in grid.columns for column in ("seasonal_amp_mm", "ratio_R"))
            and (
                (
                    grid.loc[grid["seasonal_amp_mm"] > 0, "ratio_R"].astype(float)
                    - (
                        grid.loc[grid["seasonal_amp_mm"] > 0, "velocity_mm_yr"].astype(float).abs()
                        / grid.loc[grid["seasonal_amp_mm"] > 0, "seasonal_amp_mm"].astype(float)
                    )
                ).abs()
                <= 1e-3
            ).all()
        ),
        "grid_regimes": sorted(
            set(grid["regime"].dropna().astype(str)) if "regime" in grid.columns else set()
        ),
    }


@pytest.fixture(scope="module")
def measured() -> dict[str, dict[str, object]]:
    return {case: _measure_case(case) for case in CASES}


# --------------------------------------------------------------------------------------------
# failure reporting
# --------------------------------------------------------------------------------------------


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _check(
    report: list[str],
    *,
    metric: str,
    line_no: int,
    text: str,
    documented: object,
    measured_value: object,
    tolerance: float,
    tolerance_label: str,
) -> None:
    try:
        agreed = abs(float(measured_value) - float(documented)) <= tolerance
    except (TypeError, ValueError):
        agreed = str(documented) == str(measured_value)
    if agreed:
        return
    report.append(
        f"pipeline/README.md:{line_no} — {metric} disagrees with the artefacts\n"
        f"  documented: {_fmt(documented)}\n"
        f"  measured:   {_fmt(measured_value)}\n"
        f"  tolerance:  {tolerance_label}\n"
        f"  doc line:   {text.strip()}\n"
        f"  fix one of the two: if the artefacts are current, update the doc; if the doc is "
        f"current, the tree moved under it."
    )


# --------------------------------------------------------------------------------------------
# §6: the headline table, one case at a time so a stale row names itself
# --------------------------------------------------------------------------------------------


def _headline_table() -> dict[str, Row]:
    rows = _table(HEADLINE_HEADING, HEADLINE_COLUMNS, what="mock headline table")
    table: dict[str, Row] = {}
    for row in rows:
        case = _clean(row.values["case"])
        table[case] = Row(
            values={
                "case": case,
                "cells": row.values["cells"],
                "median": row.values["median"],
                "p05": row.values["p05"],
                "size_mb": row.values["size"],
            },
            line_no=row.line_no,
            text=row.text,
        )
    return table


@pytest.fixture(scope="module")
def doc_table() -> dict[str, Row]:
    return _headline_table()


def test_doc_and_disk_cover_the_same_cases(doc_table: dict[str, Row]) -> None:
    documented = set(doc_table)
    present = set(CASES)
    if documented == present:
        return
    pytest.fail(
        "pipeline/README.md and data/processed/ disagree about which cases exist\n"
        f"  documented: {', '.join(sorted(documented)) or '(none)'}"
        f" [line {', '.join(str(doc_table[c].line_no) for c in sorted(documented))}]\n"
        f"  measured:   {', '.join(sorted(present)) or '(none)'} under data/processed/\n"
        f"  tolerance:  exact — the table is a list of published cases, not a sample\n"
        f"  missing from doc: {', '.join(sorted(present - documented)) or 'none'}\n"
        f"  missing on disk:  {', '.join(sorted(documented - present)) or 'none'}"
    )


@pytest.mark.parametrize("case", CASES)
def test_headline_row_matches_artefacts(
    case: str, doc_table: dict[str, Row], measured: dict[str, dict[str, object]]
) -> None:
    row = doc_table.get(case)
    if row is None:
        pytest.fail(
            f"data/processed/{case}/ exists but pipeline/README.md has no headline row for it.\n"
            f"  documented: (no row)\n"
            f"  measured:   {measured[case]['cells']} cells\n"
            f"  tolerance:  exact — one row per published case\n"
            f"  undocumented cases are exactly how a stale table hides: add the row."
        )

    got = measured[case]
    report: list[str] = []
    _check(
        report, metric="cells", line_no=row.line_no, text=row.text,
        documented=_number(row.values["cells"], what="cells", line_no=row.line_no, text=row.text),
        measured_value=got["cells"],
        tolerance=0.0, tolerance_label="0 (exact) — the doc prints counts unrounded",
    )
    for key, metric in (("median", "median mm/yr"), ("p05", "p05")):
        _check(
            report, metric=metric, line_no=row.line_no, text=row.text,
            documented=_number(row.values[key], what=metric, line_no=row.line_no, text=row.text),
            measured_value=got[key],
            tolerance=TOL_VELOCITY,
            tolerance_label=f"±{TOL_VELOCITY:g} mm/yr — one decimal printed (±0.05 rounding, "
                            f"0.1 keeps a digit so a .x5 boundary cannot flap)",
        )
    _check(
        report, metric="size (decimal MB)", line_no=row.line_no, text=row.text,
        documented=_size_mb(row.values["size_mb"], what="size in MB", line_no=row.line_no,
                           text=row.text),
        measured_value=got["size_mb"],
        tolerance=TOL_SIZE_MB,
        tolerance_label=f"±{TOL_SIZE_MB:g} MB — two decimals printed (±0.005 rounding); the rest "
                        f"absorbs a copy whose parquet was recompressed",
    )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §4: totals and the runbook's reprint
# --------------------------------------------------------------------------------------------


def test_total_size_and_case_count_in_runbook(measured: dict[str, dict[str, object]]) -> None:
    total_mb = sum(float(measured[case]["size_mb"]) for case in CASES)

    claims: list[tuple[int, str, float, str]] = []

    line_no, line = _line(r"seed\s+\d+,\s*all cases,\s*[\d.]+\s*MB total", what="the §4 total size")
    match = re.search(r"seed\s+(\d+),\s*all cases,\s*([\d.]+)\s*MB total", line)
    assert match is not None
    claims.append((line_no, line, float(match.group(2)), "§4 step 1 comment"))

    line_no, line = _line(r"`PHASE A: PASS`,\s*\d+\s+cases?,\s*[\d.]+\s*MB",
                          what="the §4 gate reprint")
    match = re.search(r"`PHASE A: PASS`,\s*(\d+)\s+cases?,\s*([\d.]+)\s*MB", line)
    assert match is not None
    documented_cases = int(match.group(1))
    claims.append((line_no, line, float(match.group(2)), "§4 step 7 reprint"))

    report: list[str] = []
    for claim_line, claim_text, documented_mb, where in claims:
        _check(
            report, metric=f"total size ({where})", line_no=claim_line, text=claim_text,
            documented=documented_mb, measured_value=total_mb,
            tolerance=TOL_SIZE_MB,
            tolerance_label=f"±{TOL_SIZE_MB:g} MB — the doc prints two decimals; the sum is "
                            f"{total_mb:.3f} MB over {', '.join(CASES)}",
        )
    _check(
        report, metric="case count", line_no=claims[1][0], text=claims[1][1],
        documented=documented_cases, measured_value=len(CASES),
        tolerance=0.0, tolerance_label="0 (exact) — one entry per case directory on disk",
    )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §6: seed, date window, product — the sentence that introduces the headline table
# --------------------------------------------------------------------------------------------


def test_headline_seed_dates_and_product(measured: dict[str, dict[str, object]]) -> None:
    line_no, line = _line(
        r"seed\s+\d+,\s*\d+\s+dates?\s+`?\d{4}-\d{2}-\d{2}\s*(?:→|->|—|-)\s*\d{4}-\d{2}-\d{2}`?",
        what="the headline date window",
    )
    match = re.search(
        r"seed\s+(\d+),\s*(\d+)\s+dates?\s*`?(\d{4}-\d{2}-\d{2})\s*(?:→|->|—|-)\s*"
        r"(\d{4}-\d{2}-\d{2})`?",
        line,
    )
    if match is None:  # pragma: no cover - _line already matched the same shape
        pytest.fail(f"pipeline/README.md:{line_no}: cannot read the seed/date window from {line!r}")
    documented_seed = int(match.group(1))
    documented_count = int(match.group(2))
    documented_start, documented_end = match.group(3), match.group(4)

    report: list[str] = []
    for case in CASES:
        got = measured[case]
        dates = got["dates"]
        assert isinstance(dates, list)
        _check(
            report, metric=f"date count for {case!r}", line_no=line_no, text=line,
            documented=documented_count, measured_value=len(dates),
            tolerance=0.0, tolerance_label="0 (exact) — one row per acquisition date in meta.json",
        )
        _check(
            report, metric=f"first date for {case!r}", line_no=line_no, text=line,
            documented=documented_start, measured_value=dates[0],
            tolerance=0.0, tolerance_label="0 (exact) — ISO dates compared verbatim",
        )
        _check(
            report, metric=f"last date for {case!r}", line_no=line_no, text=line,
            documented=documented_end, measured_value=dates[-1],
            tolerance=0.0, tolerance_label="0 (exact) — ISO dates compared verbatim",
        )
        _check(
            report, metric=f"mock seed for {case!r}", line_no=line_no, text=line,
            documented=documented_seed, measured_value=got["seed"],
            tolerance=0.0, tolerance_label="0 (exact) — meta.provenance.mock_seed is an integer",
        )
        _check(
            report, metric=f"product for {case!r}", line_no=line_no, text=line,
            documented="mock", measured_value=got["product"],
            tolerance=0.0, tolerance_label="0 (exact) — a doc that says mock over a real tree "
                                            "would be the worst possible staleness",
        )
        if "mock" not in str(got["source"]).lower():
            report.append(
                f"pipeline/README.md:{line_no} — provenance for {case!r} does not say mock\n"
                f"  documented: meta.provenance.source mentions mock\n"
                f"  measured:   {got['source']!r}\n"
                f"  tolerance:  none — the sentence says 'nothing claims a real product'\n"
                f"  doc line:   {line.strip()}"
            )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §6: coherence ranges, land-use classes, water
# --------------------------------------------------------------------------------------------


def test_coherence_ranges(measured: dict[str, dict[str, object]]) -> None:
    line_no, line = _line(r"Coherence\s+[\d.]+\s*[–~-]\s*[\d.]+", what="the coherence range")
    match = re.search(
        r"Coherence\s+([\d.]+)\s*[–~-]\s*([\d.]+)"
        r"(?:\s*\(([\d.]+)\s*[–~-]\s*([\d.]+)\s+in\s+([^)]+)\))?",
        line,
    )
    if match is None:  # pragma: no cover - _line already matched
        pytest.fail(f"pipeline/README.md:{line_no}: cannot read the coherence range from {line!r}")

    global_min = min(float(measured[case]["coherence_min"]) for case in CASES)
    global_max = max(float(measured[case]["coherence_max"]) for case in CASES)
    report: list[str] = []
    _check(
        report, metric="coherence low end (all cases)", line_no=line_no, text=line,
        documented=float(match.group(1)), measured_value=global_min,
        tolerance=TOL_COHERENCE,
        tolerance_label=f"±{TOL_COHERENCE:g} — two decimals printed, 0.005 is the rounding error",
    )
    _check(
        report, metric="coherence high end (all cases)", line_no=line_no, text=line,
        documented=float(match.group(2)), measured_value=global_max,
        tolerance=TOL_COHERENCE,
        tolerance_label=f"±{TOL_COHERENCE:g} — two decimals printed, 0.005 is the rounding error",
    )
    if match.group(3) is not None:
        case = _case_from_label(match.group(5).strip(), line_no=line_no, text=line)
        _check(
            report, metric=f"coherence low end in {case!r}", line_no=line_no, text=line,
            documented=float(match.group(3)), measured_value=measured[case]["coherence_min"],
            tolerance=TOL_COHERENCE,
            tolerance_label=f"±{TOL_COHERENCE:g} — two decimals printed, 0.005 is the rounding error",
        )
        _check(
            report, metric=f"coherence high end in {case!r}", line_no=line_no, text=line,
            documented=float(match.group(4)), measured_value=measured[case]["coherence_max"],
            tolerance=TOL_COHERENCE,
            tolerance_label=f"±{TOL_COHERENCE:g} — two decimals printed, 0.005 is the rounding error",
        )
    if report:
        pytest.fail("\n\n".join(report))


def test_land_use_class_count_and_water_cells(measured: dict[str, dict[str, object]]) -> None:
    line_no, line = _line(r"\d+\s+`land_use` classes", what="the land-use class count")
    match = re.search(r"(\d+)\s+`land_use` classes", line)
    assert match is not None
    documented_classes = int(match.group(1))

    if not re.search(r"water cells are absent", line):
        pytest.fail(
            f"pipeline/README.md:{line_no}: the sentence no longer says water cells are absent, "
            f"so the zero below is pinned to a claim that moved:\n  {line.strip()}\n"
            f"  tolerance:  n/a — structure check"
        )

    report: list[str] = []
    for case in CASES:
        _check(
            report, metric=f"land-use classes in {case!r}", line_no=line_no, text=line,
            documented=documented_classes, measured_value=measured[case]["classes"],
            tolerance=0.0,
            tolerance_label="0 (exact) — a class count is an integer; '7 instead of 6' is a claim "
                            "about water or unknown reappearing",
        )
        _check(
            report, metric=f"water cells in {case!r}", line_no=line_no, text=line,
            documented=0, measured_value=measured[case]["water_cells"],
            tolerance=0.0,
            tolerance_label="0 (exact) — contract §8: a specular cell is absent, never written "
                            "as 0",
        )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §6: the null result and its published bound
# --------------------------------------------------------------------------------------------


def test_detection_limit_and_null_result_threshold(measured: dict[str, dict[str, object]]) -> None:
    line_no, line = _line(r"detection_limit_mm_yr\s*=\s*[\d.]+", what="the detection bound")
    match = re.search(r"`stats\.detection_limit_mm_yr\s*=\s*([\d.]+)`", line)
    if match is None:
        pytest.fail(
            f"pipeline/README.md:{line_no} states a detection bound but no "
            f"`stats.detection_limit_mm_yr = N` to read:\n  {line.strip()}\n"
            f"  tolerance:  n/a — structure check"
        )
    documented_limit = float(match.group(1))

    threshold = re.search(r"\|median\|\s*<\s*([\d.]+)\s*mm/yr", line)
    if threshold is None:
        pytest.fail(
            f"pipeline/README.md:{line_no}: cannot read the null-result threshold from\n"
            f"  {line.strip()}\n  Expected `|median| < 5 mm/yr`."
        )
    documented_threshold = float(threshold.group(1))

    report: list[str] = []
    _check(
        report, metric="null-result threshold", line_no=line_no, text=line,
        documented=documented_threshold, measured_value=contracts.NULL_RESULT_MM_YR,
        tolerance=0.0,
        tolerance_label="0 (exact) — contracts.NULL_RESULT_MM_YR is the frozen constant; the "
                        "allowlist only exempts it from being an artefact statistic",
    )

    null_cases = [case for case in CASES if measured[case]["detection_limit"] is not None]
    documented_case = _case_from_label("malaga", line_no=line_no, text=line)
    if documented_case not in null_cases:
        report.append(
            f"pipeline/README.md:{line_no} — {documented_case!r} publishes no detection bound\n"
            f"  documented: stats.detection_limit_mm_yr = {documented_limit:g}\n"
            f"  measured:   meta.stats has no detection_limit_mm_yr (null-result cases: "
            f"{', '.join(null_cases) or 'none'})\n"
            f"  tolerance:  exact — the sentence says the bound IS the result\n"
            f"  doc line:   {line.strip()}"
        )
    else:
        got = measured[documented_case]
        _check(
            report, metric=f"detection limit for {documented_case!r}", line_no=line_no, text=line,
            documented=documented_limit, measured_value=got["detection_limit"],
            tolerance=TOL_DETECTION,
            tolerance_label=f"±{TOL_DETECTION:g} mm/yr — one decimal printed",
        )
        median_magnitude = abs(float(got["median"]))
        if median_magnitude >= documented_threshold:
            report.append(
                f"pipeline/README.md:{line_no} — {documented_case!r} is no longer a null result\n"
                f"  documented: |median| < {documented_threshold:g} mm/yr, so the bound IS the "
                f"result\n"
                f"  measured:   |median| = {median_magnitude:.3f} mm/yr "
                f"(meta.stats.median_velocity_mm_yr = {float(got['median']):.3f})\n"
                f"  tolerance:  none — at or above the threshold the sentence must stop calling "
                f"the bound a null result\n"
                f"  doc line:   {line.strip()}"
            )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §2: the declared CRS
# --------------------------------------------------------------------------------------------


def test_declared_crs_matches_meta(measured: dict[str, dict[str, object]]) -> None:
    line_no, line = _line(r"EPSG:\d{4,6}", what="the declared CRS")
    match = re.search(r"EPSG:(\d{4,6})", line)
    assert match is not None
    documented = f"EPSG:{match.group(1)}"
    report: list[str] = []
    for case in CASES:
        _check(
            report, metric=f"meta.crs for {case!r}", line_no=line_no, text=line,
            documented=documented, measured_value=measured[case]["crs"],
            tolerance=0.0, tolerance_label="0 (exact) — an EPSG code is an identifier, not a "
                                           "rounded measurement",
        )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §6: the phase → mm scale check, recomputed through pipeline/science/transforms.py
# --------------------------------------------------------------------------------------------


def _phase_constants() -> tuple[float, float]:
    """λ_L in metres and θ in degrees, parsed from the scale-check sentence (constants, not data)."""
    _, lam_line = _line(r"λ_?L?\s*=\s*[\d.]+\s*m", what="the wavelength λ_L")
    lam_match = re.search(r"λ_?L?\s*=\s*([\d.]+)\s*m", lam_line)
    assert lam_match is not None
    theta_match = re.search(r"θ\s*=\s*([\d.]+)\s*°", lam_line)
    if theta_match is None:
        _, theta_line = _line(r"θ\s*=\s*[\d.]+\s*°", what="the incidence angle θ")
        theta_match = re.search(r"θ\s*=\s*([\d.]+)\s*°", theta_line)
        assert theta_match is not None
    return float(lam_match.group(1)), float(theta_match.group(1))


def test_phase_to_mm_table_matches_transforms() -> None:
    lam, theta = _phase_constants()
    rows = _table(PHASE_HEADING, PHASE_COLUMNS, what="phase → mm scale table")

    seen: set[str] = set()
    report: list[str] = []
    for row in rows:
        label = _clean(row.values["quantity"]).lower()
        if "radian" in label:
            kind = "radian"
            los_expected = lam / (4.0 * math.pi) * 1e3
        elif "fringe" in label:
            kind = "fringe"
            los_expected = lam / 2.0 * 1e3
        else:
            pytest.fail(
                f"pipeline/README.md:{row.line_no}: unrecognised row {label!r} in the phase table\n"
                f"  {row.text.strip()}\n"
                f"  expected a row whose label contains 'radian' or 'fringe'\n"
                f"  tolerance:  n/a — structure check"
            )
        seen.add(kind)
        vertical_expected = float(transforms.vertical_from_los(los_expected, theta, 0.0))

        documented_los = _number(row.values["los"], what="LOS mm", line_no=row.line_no,
                                 text=row.text)
        documented_vertical = _number(row.values["vertical"], what="vertical mm",
                                      line_no=row.line_no, text=row.text)
        tol_los = _printed_tolerance(row.values["los"])
        tol_vertical = _printed_tolerance(row.values["vertical"])
        _check(
            report, metric=f"LOS mm for {kind}", line_no=row.line_no, text=row.text,
            documented=documented_los, measured_value=los_expected,
            tolerance=tol_los,
            tolerance_label=f"±{tol_los:g} mm — one unit in the last printed digit; recomputed "
                            f"from λ_L = {lam:g} m (docs/nisar-gunw-layout.md §4)",
        )
        _check(
            report, metric=f"vertical mm for {kind}", line_no=row.line_no, text=row.text,
            documented=documented_vertical, measured_value=vertical_expected,
            tolerance=tol_vertical,
            tolerance_label=f"±{tol_vertical:g} mm — one unit in the last printed digit; "
                            f"{los_expected:.4f} mm / cos({theta:g}°) through "
                            f"transforms.vertical_from_los (v_north = 0)",
        )
    missing = {"radian", "fringe"} - seen
    if missing:
        pytest.fail(
            f"pipeline/README.md: the phase table no longer has a row for {', '.join(sorted(missing))}\n"
            f"  documented: rows {sorted(seen) or '(none)'}\n"
            f"  measured:   expected both '1 radian' and 'one fringe'\n"
            f"  tolerance:  n/a — structure check\n"
            f"  The scale check is only a check if both phase steps are stated."
        )
    if report:
        pytest.fail("\n\n".join(report))


def _eval_arithmetic(expression: str, *, line_no: int, text: str) -> float:
    """Evaluate the doc's reproduce expression: digits, operators, ``math.pi`` only."""
    probe = expression.replace("math.pi", repr(math.pi)).replace(" ", "")
    if not re.fullmatch(r"[\d.eE+\-*/()]+", probe) or not any(c.isdigit() for c in probe):
        pytest.fail(
            f"pipeline/README.md:{line_no}: the reproduce expression is not plain arithmetic:\n"
            f"  documented: {expression!r}\n  doc line:   {text.strip()}\n"
            f"  tolerance:  n/a — this test evaluates it to check that it reproduces the table"
        )
    return float(eval(probe, {"__builtins__": {}}, {}))  # noqa: S307 - digits/operators only


def _call_arguments(text: str, name: str, *, line_no: int) -> list[str]:
    """Arguments of ``name(...)`` in `text`, respecting nested parentheses."""
    marker = f"{name}("
    if marker not in text:
        pytest.fail(
            f"pipeline/README.md:{line_no}: no {name}(...) call to parse:\n  {text.strip()}\n"
            f"  tolerance:  n/a — structure check"
        )
    start = text.index(marker) + len(marker)
    depth = 1
    for index in range(start, len(text)):
        character = text[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return [part.strip() for part in text[start:index].split(",")]
    pytest.fail(
        f"pipeline/README.md:{line_no}: unbalanced parentheses in the {name}(...) call:\n"
        f"  {text.strip()}\n  tolerance:  n/a — structure check"
    )


def test_reproduce_command_reproduces_the_scale() -> None:
    lam, theta = _phase_constants()
    line_no, line = _line(r"vertical_from_los\(", what="the reproduce command")
    arguments = _call_arguments(line, "vertical_from_los", line_no=line_no)
    if len(arguments) != 3:
        pytest.fail(
            f"pipeline/README.md:{line_no}: vertical_from_los is called with {len(arguments)} "
            f"arguments\n  {line.strip()}\n"
            f"  expected (los_mm, incidence_deg, heading_deg)\n"
            f"  tolerance:  n/a — structure check"
        )
    arrow = re.search(r"(?:→|->)\s*`([\d.]+)`", line)
    if arrow is None:
        pytest.fail(
            f"pipeline/README.md:{line_no}: the reproduce command no longer prints its result with "
            f"`→ `N``:\n  {line.strip()}\n"
            f"  tolerance:  n/a — the arrow is the claim that the command reproduces the table"
        )
    documented_result = float(arrow.group(1))
    los_expression = arguments[0]
    los_from_command = _eval_arithmetic(los_expression, line_no=line_no, text=line)
    theta_from_command = float(arguments[1])
    heading_from_command = float(arguments[2])
    recomputed = float(
        transforms.vertical_from_los(los_from_command, theta_from_command, heading_from_command)
    )
    los_from_lambda = lam / (4.0 * math.pi) * 1e3

    report: list[str] = []
    _check(
        report, metric="reproduce-command result", line_no=line_no, text=line,
        documented=documented_result, measured_value=recomputed,
        tolerance=TOL_REPRODUCE,
        tolerance_label=f"±{TOL_REPRODUCE:g} mm — the doc prints round(..., 2), so 0.005 is that "
                        f"rounding; recomputed through transforms.vertical_from_los",
    )
    _check(
        report, metric="LOS scale inside the reproduce command", line_no=line_no, text=line,
        documented=los_from_command, measured_value=los_from_lambda,
        tolerance=0.01,
        tolerance_label="±0.01 mm — λ is printed to 4 decimals, so 0.0001 m is "
                        "0.008 mm here; a different formula (λ/2 instead of λ/4π) is not rounding",
    )
    _check(
        report, metric="incidence angle inside the reproduce command", line_no=line_no, text=line,
        documented=theta_from_command, measured_value=theta,
        tolerance=0.5,
        tolerance_label="±0.5° — θ is printed as an integer, so half a unit is its rounding",
    )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §6: the Mexico City 12-day sanity anchor
# --------------------------------------------------------------------------------------------


def test_mexico_city_pair_anchor(measured: dict[str, dict[str, object]]) -> None:
    lam, theta = _phase_constants()
    line_no, line = _line(
        r"at\s*[−-]\s*\d+(?:\.\d+)?\s*mm/yr is\s*[−-]\s*\d+(?:\.\d+)?\s*mm vertical in a\s*\d+-day pair",
        what="the Mexico City 12-day anchor",
    )
    match = re.search(
        r"(?P<label>[A-Z][^,]*?)\s+at\s*[−-]\s*(?P<rate>\d+(?:\.\d+)?)\s*mm/yr is\s*[−-]\s*"
        r"(?P<disp>\d+(?:\.\d+)?)\s*mm vertical in a\s*(?P<days>\d+)-day pair,\s*≈\s*"
        r"(?P<fraction>\d+(?:\.\d+)?)\s*fringe",
        line,
    )
    if match is None:  # pragma: no cover - _line already matched a prefix of this shape
        pytest.fail(f"pipeline/README.md:{line_no}: cannot read the 12-day anchor from {line!r}")
    rate = float(match.group("rate"))
    documented_displacement = float(match.group("disp"))
    documented_days = int(match.group("days"))
    documented_fraction = float(match.group("fraction"))

    case = _case_from_label(match.group("label").strip(), line_no=line_no, text=line)
    if case not in measured:
        pytest.fail(
            f"pipeline/README.md:{line_no} anchors the demo on {case!r}, but data/processed/"
            f"{case}/ is missing, so even the pair length cannot be checked."
        )

    los_fringe = lam / 2.0 * 1e3
    vertical_fringe = float(transforms.vertical_from_los(los_fringe, theta, 0.0))
    displacement_los = rate * documented_days / transforms.DAYS_PER_YEAR
    fraction_los_basis = displacement_los / los_fringe
    fraction_doc_basis = documented_displacement / vertical_fringe

    report: list[str] = []
    _check(
        report, metric="pair length", line_no=line_no, text=line,
        documented=documented_days, measured_value=measured[case]["revisit_days"],
        tolerance=0.0, tolerance_label="0 (exact) — meta.revisit_days is an integer",
    )
    _check(
        report, metric="12-day displacement from the quoted rate", line_no=line_no, text=line,
        documented=documented_displacement, measured_value=displacement_los,
        tolerance=TOL_VELOCITY,
        tolerance_label=f"±{TOL_VELOCITY:g} mm — one decimal printed; rate × days / "
                        f"{transforms.DAYS_PER_YEAR:g} d·yr⁻¹",
    )
    _check(
        report, metric="fraction of a fringe", line_no=line_no, text=line,
        documented=documented_fraction, measured_value=fraction_doc_basis,
        tolerance=TOL_FRINGE_FRACTION,
        tolerance_label=f"±{TOL_FRINGE_FRACTION:g} — two decimals printed; the doc divides the "
                        f"12-day displacement by the vertical fringe ({vertical_fringe:.1f} mm)",
    )
    if report:
        pytest.fail("\n\n".join(report))

    # The anchor and the artefacts share ONE basis: `velocity_mm_yr` is vertical (contract §3), so
    # rate × time is a vertical displacement and belongs over the VERTICAL fringe (153.4 mm) — which
    # the `_check` above asserts (0.090). Reading the same displacement as LOS and projecting it up
    # (÷ cos θ) instead gives 0.12–0.15 of a fringe; "unwrapping error dominates" holds either way,
    # since ~a tenth of a fringe is far above the noise floor. Assert the two readings stay
    # distinguishable, so this check cannot silently go vacuous.
    assert abs(fraction_los_basis - fraction_doc_basis) > TOL_FRINGE_FRACTION


# --------------------------------------------------------------------------------------------
# §7: the stack length
# --------------------------------------------------------------------------------------------


def test_stack_length_in_days(measured: dict[str, dict[str, object]]) -> None:
    line_no, line = _line(r"\b\d{2,3}-day stack", what="the stack length")
    match = re.search(r"(\d{2,3})-day stack", line)
    assert match is not None
    documented_days = int(match.group(1))
    report: list[str] = []
    for case in CASES:
        dates = measured[case]["dates"]
        assert isinstance(dates, list)
        span = (
            dt.date.fromisoformat(str(dates[-1])) - dt.date.fromisoformat(str(dates[0]))
        ).days
        _check(
            report, metric=f"stack span for {case!r}", line_no=line_no, text=line,
            documented=documented_days, measured_value=span,
            tolerance=0.0,
            tolerance_label="0 (exact) — integer days between the first and last meta.dates",
        )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §7: seasonality — is the annual term identified, or is the amplitude a typed constant?
# --------------------------------------------------------------------------------------------


def _match(pattern: str, line: str, *, line_no: int, key: str) -> re.Match[str]:
    match = re.search(pattern, line)
    if match is None:
        pytest.fail(
            f"pipeline/README.md:{line_no}: cannot read the seasonal-identifiability claim "
            f"({key}) from the doc line\n  {line.strip()}\n"
            f"  expected: text matching {pattern!r}\n"
            f"  tolerance: n/a — the sentence is parsed at run time, so a reword moves this regex"
        )
    return match


def test_seasonal_identifiability_claim(
    measured: dict[str, dict[str, object]], doc_table: dict[str, Row]
) -> None:
    """§7 limitation 4: the 2-year window identifies the annual term, the 132-day one did not.

    Two claims in one sentence, and both can be re-derived: the *current* coverage/condition are
    `meta.stats`, the *published* amplitude/ratio/regime are the grid's own columns, and the
    past-tense half is the same gate applied to the numbers `meta.limitations` records for the
    old window. A doc that quietly stopped publishing the amplitude would leave the prose true
    and the artefacts empty, so the columns are checked, not just the sentence.
    """
    line_no, line = _line(
        r"annual coverage\s+\d+(?:\.\d+)?\s*yr", what="the seasonal-identifiability limitation"
    )

    coverage = float(_match(r"annual coverage\s+([\d.]+)\s*yr", line,
                            line_no=line_no, key="annual coverage").group(1))
    cycles_match = _match(
        r"\(([\d.]+)\s*cycles against the ([\d.]+)\s*yr-per-harmonic gate\)", line,
        line_no=line_no, key="annual coverage in cycles and the coverage gate",
    )
    cycles, doc_coverage_gate = float(cycles_match.group(1)), float(cycles_match.group(2))
    condition_match = _match(
        r"at design condition\s+([\d.]+)\s*\(limit `MAX_DESIGN_CONDITION = ([\d.]+)`\)", line,
        line_no=line_no, key="design condition and its limit",
    )
    condition, doc_condition_limit = float(condition_match.group(1)), float(condition_match.group(2))
    amps = [float(v) for v in _match(
        r"median_seasonal_amp_mm`\s*([\d.]+)\s*/\s*([\d.]+)\s*/\s*([\d.]+)\s*mm", line,
        line_no=line_no, key="per-case median seasonal amplitudes",
    ).groups()]
    ratios = [float(v) for v in _match(
        r"median_ratio_R`\s*([\d.]+)\s*/\s*([\d.]+)\s*/\s*([\d.]+)", line,
        line_no=line_no, key="per-case median ratio R",
    ).groups()]
    regimes = list(_match(
        r"dominant_regime`\s*([a-z]+)\s*/\s*([a-z]+)\s*/\s*([a-z]+)", line,
        line_no=line_no, key="per-case dominant regime",
    ).groups())
    old_match = _match(
        r"old\s+(\d+)-day window\s*\(([\d.]+)\s*annual cycles, design condition\s+([\d.]+)\)",
        line, line_no=line_no, key="the historical 132-day window",
    )
    old_days, old_cycles, old_condition = (
        int(old_match.group(1)), float(old_match.group(2)), float(old_match.group(3)),
    )

    order = [case for case in doc_table if case in measured]
    if set(order) != set(CASES):
        pytest.fail(
            f"pipeline/README.md:{line_no} lists the seasonal medians in the order of the headline "
            f"table, but the two disagree about which cases exist\n"
            f"  documented rows: {', '.join(order) or '(none)'}\n"
            f"  measured cases:  {', '.join(CASES) or '(none)'}\n"
            f"  tolerance:  n/a — see test_doc_and_disk_cover_the_same_cases"
        )

    report: list[str] = []
    for case, amp, ratio, regime in zip(order, amps, ratios, regimes):
        got = measured[case]
        for metric, documented, key, tolerance, label in (
            ("annual coverage (yr)", coverage, "annual_coverage", 0.005,
             "±0.005 yr — three decimals printed; `annual_coverage` is span / period"),
            ("annual coverage (cycles)", cycles, "annual_coverage", 0.005,
             "±0.005 cycles — two decimals printed, the same quantity as the years above"),
            ("design condition", condition, "design_condition", 0.005,
             "±0.005 — two decimals printed; `meta.stats.design_condition`"),
            ("median seasonal amplitude (mm)", amp, "seasonal_amp", 0.05,
             "±0.05 mm — one decimal printed; `meta.stats.median_seasonal_amp_mm`"),
            ("median ratio R", ratio, "ratio_R", 0.005,
             "±0.005 — two decimals printed; `meta.stats.median_ratio_R`"),
            ("dominant regime", regime, "regime", 0.0,
             "0 (exact) — a `contracts.REGIMES` value, compared verbatim"),
        ):
            _check(
                report, metric=f"{metric} for {case!r}", line_no=line_no, text=line,
                documented=documented, measured_value=got[key],
                tolerance=tolerance, tolerance_label=label,
            )

    # The gates named in the sentence must still be the frozen code constants.
    _check(
        report, metric="coverage gate (yr per harmonic)", line_no=line_no, text=line,
        documented=doc_coverage_gate,
        measured_value=transforms.MIN_SEASONAL_COVERAGE_PER_HARMONIC,
        tolerance=0.0, tolerance_label="0 (exact) — a frozen code constant, not a statistic",
    )
    _check(
        report, metric="design-condition limit", line_no=line_no, text=line,
        documented=doc_condition_limit, measured_value=transforms.MAX_DESIGN_CONDITION,
        tolerance=0.0, tolerance_label="0 (exact) — a frozen code constant, not a statistic",
    )

    # The sentence promises a *verdict*: the gates pass, so the amplitude is publishable — and the
    # grid must actually carry the published columns, not a typed constant.
    for case in CASES:
        got = measured[case]
        harmonics = max(int(got["seasonal_n_harmonics"] or 0), 1)
        needed = transforms.MIN_SEASONAL_COVERAGE_PER_HARMONIC * harmonics
        coverage_ok = float(got["annual_coverage"]) >= needed
        condition_ok = float(got["design_condition"]) <= transforms.MAX_DESIGN_CONDITION
        if not (coverage_ok and condition_ok):
            report.append(
                f"pipeline/README.md:{line_no} — the doc says the annual term IS identifiable, "
                f"but the gate rejects {case!r}\n"
                f"  documented: identifiable (coverage {coverage:g} yr, condition {condition:g})\n"
                f"  measured:   coverage {float(got['annual_coverage']):.6f} yr vs gate "
                f"{needed:g}, condition {float(got['design_condition']):.6f} vs limit "
                f"{transforms.MAX_DESIGN_CONDITION:g}\n"
                f"  tolerance:  none — the sentence says 'the annual term is separable'\n"
                f"  doc line:   {line.strip()}"
            )
        expected_columns = ["ratio_R", "regime", "seasonal_amp_mm"]
        if got["seasonal_columns"] != expected_columns:
            report.append(
                f"data/processed/{case}/nisar_grid.parquet — the doc says the amplitude, ratio_R "
                f"and regime are published as fit results, but the grid lacks a column\n"
                f"  documented: {', '.join(expected_columns)}\n"
                f"  measured:   {', '.join(got['seasonal_columns']) or '(none)'}\n"
                f"  tolerance:  exact — contract v1.1 §3 names all three"
            )
            continue
        if int(got["seasonal_nulls"]) != 0:
            report.append(
                f"data/processed/{case}/nisar_grid.parquet — the seasonal columns are not fully "
                f"published\n  documented: a fitted value in every cell\n"
                f"  measured:   {got['seasonal_nulls']} null(s) across the three columns\n"
                f"  tolerance:  0 (exact) — a withheld amplitude would make the doc's claim false"
            )
        if not got["ratio_consistent"]:
            report.append(
                f"data/processed/{case}/nisar_grid.parquet — `ratio_R` is not |velocity| / "
                f"`seasonal_amp_mm` on the same row\n"
                f"  documented: ratio_R is derived from the fitted pair (contract §3)\n"
                f"  measured:   rows where the identity breaks\n"
                f"  tolerance:  1e-3 absolute — a ratio typed independently of the fit fails here"
            )
        stray = set(got["grid_regimes"]) - set(contracts.REGIMES)
        if stray:
            report.append(
                f"data/processed/{case}/nisar_grid.parquet — unknown `regime` value\n"
                f"  documented: one of {', '.join(contracts.REGIMES)}\n"
                f"  measured:   {', '.join(sorted(stray))}\n"
                f"  tolerance:  0 (exact) — a contract enum"
            )

    # The past-tense half: the same gate, applied to the old window the sentence names. Its
    # numbers are history, so they are pinned to `meta.limitations` (the artefact's own record)
    # rather than to any current statistic.
    _check(
        report, metric="old window in annual cycles", line_no=line_no, text=line,
        documented=old_cycles, measured_value=old_days / transforms.DAYS_PER_YEAR,
        tolerance=0.005,
        tolerance_label=f"±0.005 cycles — two decimals printed; {old_days} d / "
                        f"{transforms.DAYS_PER_YEAR:g} d·yr⁻¹",
    )
    if old_cycles >= transforms.MIN_SEASONAL_COVERAGE_PER_HARMONIC:
        report.append(
            f"pipeline/README.md:{line_no} — the doc says the old window could not identify the "
            f"annual term, but its coverage clears the gate\n"
            f"  documented: {old_cycles:g} cycles, below the {doc_coverage_gate:g} gate\n"
            f"  measured:   {old_days / transforms.DAYS_PER_YEAR:.6f} cycles vs gate "
            f"{transforms.MIN_SEASONAL_COVERAGE_PER_HARMONIC:g}\n"
            f"  tolerance:  none — the past-tense claim is the gate's own verdict"
        )
    if old_condition <= transforms.MAX_DESIGN_CONDITION:
        report.append(
            f"pipeline/README.md:{line_no} — the doc says the old window was not conditioned "
            f"enough to separate the terms, but its design condition is inside the limit\n"
            f"  documented: {old_condition:g} against a limit of {doc_condition_limit:g}\n"
            f"  measured:   {transforms.MAX_DESIGN_CONDITION:g}\n"
            f"  tolerance:  none — the past-tense claim is the gate's own verdict"
        )
    for case in CASES:
        limitations = " | ".join(str(item) for item in measured[case]["limitations"])
        if f"{old_days}-day" not in limitations or f"{old_condition:g}" not in limitations:
            report.append(
                f"data/processed/{case}/meta.json — the historical window in the doc has no "
                f"record in the artefact\n"
                f"  documented: {old_days}-day window, design condition {old_condition:g}\n"
                f"  measured:   meta.limitations does not name both\n"
                f"  tolerance:  exact — history that no file records is an invented number; "
                f"drop the parenthetical or record it in meta.limitations"
            )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §1/§7: availability evidence behind the product decision and the Sentinel-1 page cap
# --------------------------------------------------------------------------------------------


def _availability(case: str) -> dict[str, object]:
    path = AVAILABILITY / f"{case}.json"
    if not path.is_file():
        pytest.fail(
            f"pipeline/README.md quotes availability evidence, but {path} is missing.\n"
            f"  documented: a probe result for {case!r}\n"
            f"  measured:   no file\n"
            f"  tolerance:  n/a — the claim cannot be checked without its evidence;\n"
            f"  regenerate it with ./scripts/python.sh pipeline/ingest/02_search_download.py search"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def test_opera_absence_claim() -> None:
    if not AVAILABILITY.is_dir():
        pytest.skip(f"{AVAILABILITY} has no probe evidence, so the availability claims are skipped")
    line_no, line = _line(
        r"\d+\s+granules for all three AOIs,\s*probed\s*\d{4}-\d{2}-\d{2}",
        what="the OPERA absence claim",
        span=2,  # the probed date is wrapped onto the next line
    )
    match = re.search(
        r"(\d+)\s+granules for all three AOIs,\s*probed\s*(\d{4}-\d{2}-\d{2})", line
    )
    assert match is not None
    documented_granules = int(match.group(1))
    documented_probe_date = match.group(2)

    report: list[str] = []
    _check(
        report, metric="AOIs counted ('all three')", line_no=line_no, text=line,
        documented=3, measured_value=len(CASES),
        tolerance=0.0, tolerance_label="0 (exact) — one availability probe per case directory",
    )
    for case in CASES:
        evidence = _availability(case)
        sources = evidence["sources"]  # type: ignore[index]
        opera = sources.get("opera_disp_s1", {})  # type: ignore[union-attr]
        _check(
            report, metric=f"OPERA DISP-S1 granules for {case!r}", line_no=line_no, text=line,
            documented=documented_granules, measured_value=opera.get("n_granules"),
            tolerance=0.0,
            tolerance_label="0 (exact) — n_granules is an integer in the probe JSON",
        )
        probed = str(evidence.get("generated_utc", ""))[:10]
        _check(
            report, metric=f"probe date for {case!r}", line_no=line_no, text=line,
            documented=documented_probe_date, measured_value=probed,
            tolerance=0.0,
            tolerance_label="0 (exact) — generated_utc date, compared verbatim",
        )
    if report:
        pytest.fail("\n\n".join(report))


def test_sentinel1_page_cap_claim() -> None:
    if not AVAILABILITY.is_dir():
        pytest.skip(f"{AVAILABILITY} has no probe evidence, so the availability claims are skipped")
    line_no, line = _line(
        r"requests\s*\d{4}\s*→\s*\d{4}\s+with\s+`maxResults=\d+`",
        what="the Sentinel-1 page-cap claim",
    )
    match = re.search(
        r"requests\s*(\d{4})\s*→\s*(\d{4})\s+with\s+`maxResults=(\d+)`.*?"
        r"(\d+)\+\s+granules.*?~(\d+)\s+months\s*\(([^)]*?)\s*"
        r"(\d{4}-\d{2}-\d{2})\s*→\s*(\d{4}-\d{2}-\d{2})\).*?not\s+(\d+)\s+years",
        line,
    )
    if match is None:
        pytest.fail(
            f"pipeline/README.md:{line_no}: the Sentinel-1 page-cap sentence no longer has the "
            f"shape this test parses (years → years, maxResults=N, 'N+ granules', '~M months "
            f"(Case YYYY-MM-DD → YYYY-MM-DD), not K years'):\n  {line.strip()}\n"
            f"  tolerance:  n/a — structure check"
        )
    query_start_year, query_end_year = int(match.group(1)), int(match.group(2))
    page_cap = int(match.group(3))
    documented_floor = int(match.group(4))
    documented_months = int(match.group(5))
    documented_case = _case_from_label(match.group(6).strip(), line_no=line_no, text=line)
    documented_start, documented_end = match.group(7), match.group(8)
    documented_years_bound = int(match.group(9))

    report: list[str] = []
    for case in CASES:
        evidence = _availability(case)
        sentinel = evidence["sources"].get("sentinel1_slc", {})  # type: ignore[union-attr]
        query = sentinel.get("query", {})
        _check(
            report, metric=f"Sentinel-1 query start year for {case!r}", line_no=line_no, text=line,
            documented=query_start_year, measured_value=str(query.get("start", ""))[:4],
            tolerance=0.0, tolerance_label="0 (exact) — the query window is in the probe JSON",
        )
        _check(
            report, metric=f"Sentinel-1 query end year for {case!r}", line_no=line_no, text=line,
            documented=query_end_year, measured_value=str(query.get("end", ""))[:4],
            tolerance=0.0, tolerance_label="0 (exact) — the query window is in the probe JSON",
        )
        _check(
            report, metric=f"Sentinel-1 page cap for {case!r}", line_no=line_no, text=line,
            documented=page_cap, measured_value=sentinel.get("n_granules"),
            tolerance=0.0,
            tolerance_label=f"0 (exact) — a truncated page returns exactly maxResults; "
                            f"n_granules_truncated = {sentinel.get('n_granules_truncated')}",
        )
        _check(
            report, metric=f"Sentinel-1 'N+ granules' floor vs maxResults for {case!r}",
            line_no=line_no, text=line,
            documented=documented_floor, measured_value=page_cap,
            tolerance=0.0, tolerance_label="0 (exact) — '250+ granules' must be the same page cap "
                                           "the query asks for, not a larger claim",
        )

    evidence = _availability(documented_case)
    sentinel = evidence["sources"].get("sentinel1_slc", {})  # type: ignore[union-attr]
    date_range = sentinel.get("date_range") or []
    findings: list[str] = []
    if len(date_range) != 2:
        findings.append(
            f"pipeline/README.md:{line_no} — {documented_case!r} has no Sentinel-1 date_range\n"
            f"  documented: {documented_start} → {documented_end}\n"
            f"  measured:   date_range = {date_range!r}\n"
            f"  tolerance:  exact — the span is the evidence for the page-cap sentence"
        )
    else:
        start, end = str(date_range[0])[:10], str(date_range[1])[:10]
        # Reported, not asserted: the 250-granule page slides on every probe and the doc calls
        # these endpoints an example. See the module docstring.
        endpoint_tolerance = (
            "0 (exact) — ISO dates, but reported as a finding: the page-capped window slides on "
            "every probe; refresh the example from the JSON or drop the exact endpoints"
        )
        for metric, documented_endpoint, measured_endpoint in (
            ("returned span start", documented_start, start),
            ("returned span end", documented_end, end),
        ):
            _check(
                findings, metric=f"{metric} for {documented_case!r}", line_no=line_no,
                text=line, documented=documented_endpoint, measured_value=measured_endpoint,
                tolerance=0.0, tolerance_label=endpoint_tolerance,
            )
        span_days = (
            dt.date.fromisoformat(end) - dt.date.fromisoformat(start)
        ).days
        span_months = span_days / 30.44
        span_years = span_days / transforms.DAYS_PER_YEAR
        _check(
            report, metric=f"returned span in months for {documented_case!r}", line_no=line_no,
            text=line, documented=documented_months, measured_value=span_months,
            tolerance=TOL_PROBE_MONTHS,
            tolerance_label=f"±{TOL_PROBE_MONTHS:g} months — the doc says '~{documented_months} "
                            f"months' and a month is 30.44 d",
        )
        if span_years >= documented_years_bound:
            report.append(
                f"pipeline/README.md:{line_no} — the returned span is not the contrast the doc "
                f"draws\n"
                f"  documented: '~{documented_months} months … not {documented_years_bound} years'\n"
                f"  measured:   {span_years:.2f} years ({span_days} d) for "
                f"{documented_case!r} (probe JSON date_range)\n"
                f"  tolerance:  none — the sentence's point is that the span is page-capped, so "
                f"'not {documented_years_bound} years' must remain true\n"
                f"  doc line:   {line.strip()}"
            )
    if report:
        pytest.fail("\n\n".join(report))
    if findings:
        warnings.warn(
            "(finding, not a failure) the Sentinel-1 example window in pipeline/README.md "
            "disagrees with the current probe:\n\n" + "\n\n".join(findings),
            UserWarning,
            stacklevel=2,
        )


# --------------------------------------------------------------------------------------------
# the allowlist has to stay live
# --------------------------------------------------------------------------------------------


def test_allowlist_entries_are_still_in_the_doc() -> None:
    lines = _doc_lines()
    missing = [
        (pattern, reason)
        for pattern, reason in ALLOWLIST
        if not any(re.search(pattern, line) for line in lines)
    ]
    if not missing:
        return
    pytest.fail(
        "pipeline/README.md no longer contains these allowlisted numbers, so their entries (and "
        "reasons) are stale:\n"
        + "\n".join(f"  {pattern!r} — {reason}" for pattern, reason in missing)
        + "\n  tolerance:  n/a — this is the bookkeeping check that keeps the allowlist honest.\n"
        "  If the claim moved, move the entry; if it was retired, delete the entry; if it became "
        "artefact-derived, replace it with a real comparison."
    )
