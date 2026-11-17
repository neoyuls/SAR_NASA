"""Pin the numbers in `docs/handoff-mock.md` to the artefacts they describe.

That page is what pozo (Rol 1) and fradiaz (Rol 2) read to know what "normal" looks like, and its
table has gone stale twice in one day (cell counts, then coherence ranges). Schema validation
(`src.domain.contracts`) cannot catch that: a stale table is *valid*, just wrong. So every number
below is re-derived from `data/processed/{case}/` and compared against the doc, in both directions:
the doc's rows are parsed (never restated here), and a doc row with no case on disk fails too.

Nothing here writes files, imports Streamlit, or touches the network.

Tolerances — documented once, used everywhere, and *not* tuned to be green:

  cells, land-use class count   exact         integers, printed unrounded in the doc
  velocities                    ±0.1 mm/yr    doc prints one decimal; ±0.05 is the max rounding
                                              error, 0.1 keeps one digit so a .x5 boundary cannot flap
  coherence                     ±0.005        doc prints two decimals; 0.005 is that rounding error
  size                          ±0.02 MB      doc prints two decimals of *decimal* MB (1e6 bytes),
                                              so ±0.005 is rounding and the rest is slack for a copy
                                              whose parquet was rewritten at another compression
                                              level — a display tolerance, not a science one
  spread contrast (Mexico/Málaga) ±1          doc rounds the ratio to an integer (±0.5 max error)
  shared symmetric scale        none          a stated requirement ("must cover the extremes"),
                                              not a measurement — it either covers max|v| or it does not
  date window, date count       exact         ISO dates and an integer count, compared verbatim
  time constant T              ±5e-6 yr      the doc prints T (and its 732/365.25 restatement) to five
                                              decimals; 5e-6 is half of that last digit
  mean×T / median×T            ±0.1 mm       same one-decimal display as the velocities that produce
                                              them; the multiplication itself is exact
  legend p05/p95                ±0.1 mm/yr    same one-decimal rounding as the velocities
  legend spread                 ±0.2 mm/yr    difference of two one-decimal numbers; rounding can add
                                              up to 0.1, so 0.2 covers the arithmetic

Skipped with a clear reason while `data/processed/` has no generated cases.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass

import pandas as pd
import pytest

DOC = pathlib.Path("docs/handoff-mock.md")
if not DOC.is_file():
    pytest.skip(
        "docs/handoff-mock.md is not shipped in the submitted repository",
        allow_module_level=True,
    )
ROOT = pathlib.Path("data/processed")
REQUIRED_FILES = ("nisar_grid.parquet", "timeseries.csv", "context_layers.geojson", "meta.json")

TABLE_HEADING = "What the current mock actually contains"
TABLE_HEADER = ("case", "cells", "median mm/yr", "p05", "coherence", "land-use classes", "size")
LEGEND_HEADING = "Shared vs independent legend"
LEGEND_HEADER = ("case", "p05", "p95", "spread")
CHART_HEADING = "KPI (median) and chart (mean×T)"
CHART_HEADER = ("case", "mean mm/yr (chart)", "median mm/yr (kpi)", "mean×t", "median×t")

MINUS_SIGNS = "\u2212\u2010\u2011\u2012\u2013\u2014\u2015\u2043\ufe63\uff0d"

TOL_VELOCITY = 0.1
TOL_COHERENCE = 0.005
TOL_SIZE_MB = 0.02
TOL_RATIO = 1.0
TOL_LEGEND_SPREAD = 0.2
TOL_TIME_CONSTANT_YR = 5e-6


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
        "`./scripts/python.sh pipeline/generate_mock.py` before pinning the handoff numbers"
    ),
)


# --------------------------------------------------------------------------------------------
# doc parsing
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One parsed doc table row, with enough provenance to quote it in a failure message."""

    case: str
    values: dict[str, object]
    line_no: int
    text: str


def _doc_lines() -> list[str]:
    assert DOC.is_file(), (
        f"{DOC} is missing. This test exists to keep it honest; restore it (or retire this test "
        f"deliberately) before reading the numbers it documents."
    )
    return DOC.read_text(encoding="utf-8").splitlines()


def _split_row(text: str) -> list[str]:
    return [cell.strip() for cell in text.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells)


def _table(lines: list[str], heading: str) -> tuple[list[str], list[tuple[int, str]]]:
    """Return (header cells, [(line number, raw line)]) of the first markdown table after `heading`."""
    start = next((i for i, line in enumerate(lines) if heading in line), None)
    if start is None:
        pytest.fail(
            f"docs/handoff-mock.md: no line contains {heading!r}. The table this test pins has been "
            f"renamed or removed; update TABLE_HEADING (or this test) in the same change that moved it."
        )
    block: list[tuple[int, str]] = []
    for offset, line in enumerate(lines[start + 1 :], start=start + 2):  # 1-based line numbers
        if line.lstrip().startswith("|"):
            block.append((offset, line))
        elif block:
            break
    if len(block) < 2:
        pytest.fail(
            f"docs/handoff-mock.md:{start + 1}: found no markdown table under {heading!r}. "
            f"The numbers cannot be pinned if the table is gone."
        )
    header = _split_row(block[0][1])
    rows = [(line_no, text) for line_no, text in block[1:] if not _is_separator(_split_row(text))]
    if not rows:
        pytest.fail(
            f"docs/handoff-mock.md:{start + 1}: the table under {heading!r} has a header but no "
            f"data rows, so there is nothing to pin."
        )
    return header, rows


def _clean(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _number(cell: str, *, what: str, line_no: int, text: str) -> float:
    raw = _clean(cell).replace(",", "").replace("\u00a0", "").replace("\u2009", "")
    raw = raw.translate({ord(c): "-" for c in MINUS_SIGNS})
    try:
        return float(raw)
    except ValueError:
        pytest.fail(
            f"docs/handoff-mock.md:{line_no}: cannot read {what} from {cell!r} in the row\n"
            f"  {text.strip()}\n"
            f"Expected a number such as 4,811 or -141.9. Keep the table machine-readable."
        )


def _coherence_range(cell: str, *, line_no: int, text: str) -> tuple[float, float]:
    parts = [p for p in re.split(f"[{MINUS_SIGNS}~]|(?<=\\d)\\s*-\\s*(?=\\d)", _clean(cell)) if p.strip()]
    if len(parts) != 2:
        pytest.fail(
            f"docs/handoff-mock.md:{line_no}: cannot read the coherence range from {cell!r} in the row\n"
            f"  {text.strip()}\n"
            f"Expected `min–max`, e.g. `0.35–0.95`."
        )
    lo = _number(parts[0], what="coherence min", line_no=line_no, text=text)
    hi = _number(parts[1], what="coherence max", line_no=line_no, text=text)
    return lo, hi


def _size_mb(cell: str, *, line_no: int, text: str) -> float:
    raw = _clean(cell)
    match = re.fullmatch(r"([0-9][0-9,.]*)\s*MB", raw, flags=re.IGNORECASE)
    if not match:
        pytest.fail(
            f"docs/handoff-mock.md:{line_no}: cannot read the size from {cell!r} in the row\n"
            f"  {text.strip()}\n"
            f"Expected decimal megabytes, e.g. `1.01 MB`. If the doc switches unit, change "
            f"_size_mb and the comparison together — do not let the numbers be compared blindly."
        )
    return _number(match.group(1), what="size in MB", line_no=line_no, text=text)


def parse_table() -> dict[str, Row]:
    """Parse the 'What the current mock actually contains' table, keyed by case."""
    lines = _doc_lines()
    header, raw_rows = _table(lines, TABLE_HEADING)
    if tuple(_clean(c).lower() for c in header) != TABLE_HEADER:
        pytest.fail(
            f"docs/handoff-mock.md: the handoff table header changed.\n"
            f"  documented: {' | '.join(header)}\n"
            f"  expected:   {' | '.join(TABLE_HEADER)}\n"
            f"  tolerance:  exact — this test parses the columns by position\n"
            f"Reorder the columns here and in tests/test_handoff_numbers.py together."
        )

    table: dict[str, Row] = {}
    for line_no, text in raw_rows:
        cells = _split_row(text)
        if len(cells) != len(TABLE_HEADER):
            pytest.fail(
                f"docs/handoff-mock.md:{line_no}: {len(cells)} columns where {len(TABLE_HEADER)} "
                f"are declared\n  {text.strip()}\n"
                f"Every row must carry case, cells, median, p05, coherence, classes and size."
            )
        case = _clean(cells[0])
        coherence_min, coherence_max = _coherence_range(cells[4], line_no=line_no, text=text)
        table[case] = Row(
            case=case,
            values={
                "cells": int(_number(cells[1], what="cells", line_no=line_no, text=text)),
                "median": _number(cells[2], what="median mm/yr", line_no=line_no, text=text),
                "p05": _number(cells[3], what="p05", line_no=line_no, text=text),
                "coherence_min": coherence_min,
                "coherence_max": coherence_max,
                "classes": int(_number(cells[5], what="land-use classes", line_no=line_no, text=text)),
                "size_mb": _size_mb(cells[6], line_no=line_no, text=text),
            },
            line_no=line_no,
            text=text,
        )
    return table


def _millimetres(cell: str, *, what: str, line_no: int, text: str) -> float:
    raw = _clean(cell)
    match = re.fullmatch(r"(.+?)\s*mm", raw, flags=re.IGNORECASE)
    if not match:
        pytest.fail(
            f"docs/handoff-mock.md:{line_no}: cannot read {what} from {cell!r} in the row\n"
            f"  {text.strip()}\n"
            f"Expected millimetres, e.g. `-124.4 mm`."
        )
    return _number(match.group(1), what=what, line_no=line_no, text=text)


def parse_legend_table() -> dict[str, Row]:
    """Parse the §3b percentile table (the independent-legend values)."""
    lines = _doc_lines()
    header, raw_rows = _table(lines, LEGEND_HEADING)
    if tuple(_clean(c).lower() for c in header) != LEGEND_HEADER:
        pytest.fail(
            f"docs/handoff-mock.md: the independent-legend table header changed.\n"
            f"  documented: {' | '.join(header)}\n"
            f"  expected:   {' | '.join(LEGEND_HEADER)}\n"
            f"  tolerance:  exact — this test parses the columns by position"
        )
    table: dict[str, Row] = {}
    for line_no, text in raw_rows:
        cells = _split_row(text)
        if len(cells) != len(LEGEND_HEADER):
            pytest.fail(
                f"docs/handoff-mock.md:{line_no}: {len(cells)} columns where "
                f"{len(LEGEND_HEADER)} are declared\n  {text.strip()}"
            )
        case = _clean(cells[0])
        table[case] = Row(
            case=case,
            values={
                "p05": _number(cells[1], what="legend p05", line_no=line_no, text=text),
                "p95": _number(cells[2], what="legend p95", line_no=line_no, text=text),
                "spread": _number(cells[3], what="legend spread", line_no=line_no, text=text),
            },
            line_no=line_no,
            text=text,
        )
    return table


def parse_chart_table() -> dict[str, Row]:
    """Parse the §3c mean-vs-median table (both the mm/yr rates and their ×T totals)."""
    lines = _doc_lines()
    header, raw_rows = _table(lines, CHART_HEADING)
    if tuple(_clean(c).lower() for c in header) != CHART_HEADER:
        pytest.fail(
            f"docs/handoff-mock.md: the KPI/chart table header changed.\n"
            f"  documented: {' | '.join(header)}\n"
            f"  expected:   {' | '.join(CHART_HEADER)}\n"
            f"  tolerance:  exact — this test parses the columns by position"
        )
    table: dict[str, Row] = {}
    for line_no, text in raw_rows:
        cells = _split_row(text)
        if len(cells) != len(CHART_HEADER):
            pytest.fail(
                f"docs/handoff-mock.md:{line_no}: {len(cells)} columns where "
                f"{len(CHART_HEADER)} are declared\n  {text.strip()}"
            )
        table[_clean(cells[0])] = Row(
            case=_clean(cells[0]),
            values={
                "mean": _number(cells[1], what="chart mean mm/yr", line_no=line_no, text=text),
                "median": _number(cells[2], what="KPI median mm/yr", line_no=line_no, text=text),
                "mean_t": _millimetres(cells[3], what="mean×T", line_no=line_no, text=text),
                "median_t": _millimetres(cells[4], what="median×T", line_no=line_no, text=text),
            },
            line_no=line_no,
            text=text,
        )
    return table


def prose_line(pattern: str, *, what: str) -> tuple[int, str]:
    """First doc line matching `pattern`, as (1-based line number, text)."""
    for line_no, line in enumerate(_doc_lines(), start=1):
        if re.search(pattern, line):
            return line_no, line
    pytest.fail(
        f"docs/handoff-mock.md: no line matches {pattern!r} ({what}). The claim this test pins "
        f"was reworded or removed; update the regex in the same change that moved the claim."
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
        "p95": float(stats["p95_velocity_mm_yr"]),
        "coherence_min": float(grid["coherence"].min()),
        "coherence_max": float(grid["coherence"].max()),
        "classes": int(grid["land_use"].nunique()),
        # decimal MB, as the doc prints it; every file in the case directory is part of the copy
        "size_mb": sum(f.stat().st_size for f in directory.iterdir() if f.is_file()) / 1_000_000,
        "max_abs_velocity": float(grid["velocity_mm_yr"].abs().max()),
        "dates": list(meta["dates"]),
        "grid": grid,
    }


@pytest.fixture(scope="module")
def measured() -> dict[str, dict[str, object]]:
    return {case: _measure_case(case) for case in CASES}


@pytest.fixture(scope="module")
def doc_table() -> dict[str, Row]:
    return parse_table()


# --------------------------------------------------------------------------------------------
# failure reporting
# --------------------------------------------------------------------------------------------


def _mismatch(
    *,
    metric: str,
    row: Row,
    documented: object,
    measured_value: object,
    tolerance: str,
    reason: str,
) -> str:
    return (
        f"docs/handoff-mock.md:{row.line_no} — {metric} for {row.case!r} disagrees with the artefacts\n"
        f"  documented: {documented}\n"
        f"  measured:   {measured_value}\n"
        f"  tolerance:  {tolerance} ({reason})\n"
        f"  doc line:   {row.text.strip()}\n"
        f"  fix one of the two: if the artefacts are current, update that doc row; if the doc is "
        f"current, the mock was regenerated and the whole row moved."
    )


def _check(
    report: list[str],
    *,
    metric: str,
    row: Row,
    documented: object,
    measured_value: object,
    tolerance: float,
    unit: str = "",
    reason: str,
    fmt: str = "{:.4f}",
) -> None:
    documented_value = float(documented)
    measured_number = float(measured_value)
    if abs(measured_number - documented_value) <= tolerance:
        return
    label = "exact, no tolerance" if tolerance == 0 else f"±{tolerance:g} {unit}".strip()
    report.append(
        _mismatch(
            metric=metric,
            row=row,
            documented=fmt.format(documented_value),
            measured_value=fmt.format(measured_number),
            tolerance=label,
            reason=reason,
        )
    )


# --------------------------------------------------------------------------------------------
# the handoff table, one test per case so a stale row names itself
# --------------------------------------------------------------------------------------------


def test_doc_and_disk_cover_the_same_cases(doc_table: dict[str, Row]) -> None:
    documented = set(doc_table)
    present = set(CASES)
    if documented == present:
        return
    pytest.fail(
        "docs/handoff-mock.md and data/processed/ disagree about which cases exist\n"
        f"  documented: {', '.join(sorted(documented)) or '(none)'}"
        f"  [line {', '.join(str(doc_table[c].line_no) for c in sorted(documented))}]\n"
        f"  measured:   {', '.join(sorted(present)) or '(none)'} under data/processed/\n"
        f"  tolerance:  exact — the table is a list of published cases, not a sample\n"
        f"  missing from doc: {', '.join(sorted(present - documented)) or 'none'}\n"
        f"  missing on disk:  {', '.join(sorted(documented - present)) or 'none'}\n"
        f"  A case with no row is invisible to the app developers; a row with no case is a copy "
        f"they cannot open. Add or retire both in the same change."
    )


@pytest.mark.parametrize("case", CASES)
def test_table_row_matches_artefacts(
    case: str, doc_table: dict[str, Row], measured: dict[str, dict[str, object]]
) -> None:
    row = doc_table.get(case)
    if row is None:
        pytest.fail(
            f"data/processed/{case}/ exists but docs/handoff-mock.md has no row for it.\n"
            f"  documented: (no row)\n"
            f"  measured:   {len(measured[case]['grid'])} cells\n"
            f"  tolerance:  exact — one row per published case\n"
            f"  undocumented cases are exactly how a stale table hides: add the row."
        )

    got = measured[case]
    report: list[str] = []

    _check(
        report, metric="cells", row=row,
        documented=row.values["cells"], measured_value=got["cells"],
        tolerance=0.0, fmt="{:.0f}",
        reason="counts are integers and the doc does not round them",
    )
    _check(
        report, metric="median mm/yr", row=row,
        documented=row.values["median"], measured_value=got["median"],
        tolerance=TOL_VELOCITY, unit="mm/yr",
        reason="doc prints one decimal; ±0.05 is the rounding error, 0.1 leaves one digit",
    )
    _check(
        report, metric="p05", row=row,
        documented=row.values["p05"], measured_value=got["p05"],
        tolerance=TOL_VELOCITY, unit="mm/yr",
        reason="doc prints one decimal; ±0.05 is the rounding error, 0.1 leaves one digit",
    )
    _check(
        report, metric="coherence min", row=row,
        documented=row.values["coherence_min"], measured_value=got["coherence_min"],
        tolerance=TOL_COHERENCE, unit="coherence units",
        reason="doc prints two decimals, so 0.005 is the rounding error",
    )
    _check(
        report, metric="coherence max", row=row,
        documented=row.values["coherence_max"], measured_value=got["coherence_max"],
        tolerance=TOL_COHERENCE, unit="coherence units",
        reason="doc prints two decimals, so 0.005 is the rounding error",
    )
    _check(
        report, metric="land-use classes", row=row,
        documented=row.values["classes"], measured_value=got["classes"],
        tolerance=0.0, fmt="{:.0f}",
        reason="a class count is an integer; '6 instead of 7' is a claim about water being gone",
    )
    _check(
        report, metric="size (decimal MB)", row=row,
        documented=row.values["size_mb"], measured_value=got["size_mb"],
        tolerance=TOL_SIZE_MB, unit="MB",
        reason="doc prints two decimals of decimal MB (±0.005 rounding); the rest absorbs a copy "
               "whose parquet was rewritten at another compression level",
    )

    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# quantitative prose claims
# --------------------------------------------------------------------------------------------


def test_shared_scale_contrast_matches_doc(measured: dict[str, dict[str, object]]) -> None:
    line_no, line = prose_line(
        r"\*\*\s*\d+(?:\.\d+)?\s*[×x]\s*\*\*\s+Málaga", what="the spread contrast"
    )
    match = re.search(r"\*\*\s*(\d+(?:\.\d+)?)\s*[×x]\s*\*\*\s+Málaga", line)
    if match is None:  # pragma: no cover - prose_line already matched the same text
        pytest.fail(f"docs/handoff-mock.md:{line_no}: cannot read the documented ratio from {line!r}")
    documented = float(match.group(1))

    for case in ("mexico-city", "malaga"):
        if case not in measured:
            pytest.fail(
                f"docs/handoff-mock.md:{line_no} contrasts Mexico City's spread with Málaga's, but "
                f"data/processed/{case}/ is missing, so the claim cannot be checked."
            )
    span_mexico = float(measured["mexico-city"]["p95"]) - float(measured["mexico-city"]["p05"])
    span_malaga = float(measured["malaga"]["p95"]) - float(measured["malaga"]["p05"])
    ratio = span_mexico / span_malaga

    if abs(ratio - documented) <= TOL_RATIO:
        return
    pytest.fail(
        f"docs/handoff-mock.md:{line_no} — the documented contrast disagrees with meta.stats\n"
        f"  documented: {documented:.0f}× (Mexico City spread / Málaga spread)\n"
        f"  measured:   {ratio:.2f}× = ({float(measured['mexico-city']['p95']):.3f} − "
        f"{float(measured['mexico-city']['p05']):.3f} = {span_mexico:.3f}) / "
        f"({float(measured['malaga']['p95']):.3f} − {float(measured['malaga']['p05']):.3f} = "
        f"{span_malaga:.3f})\n"
        f"  tolerance:  ±{TOL_RATIO} (doc rounds the ratio to an integer; ±0.5 max rounding error)\n"
        f"  doc line:   {line.strip()}\n"
        f"  the contrast is the demo's scientific point: if it moved, the pitch figure and the "
        f"legend text move with it."
    )


def test_shared_scale_covers_every_published_velocity(
    doc_table: dict[str, Row], measured: dict[str, dict[str, object]]
) -> None:
    line_no, line = prose_line(r"symmetric scale about 0 at", what="the symmetric shared scale")
    match = re.search(r"±\s*(\d+(?:\.\d+)?)\s*mm/yr", line)
    if match is None:
        pytest.fail(
            f"docs/handoff-mock.md:{line_no} says the scale is 'symmetric about 0' but no "
            f"`±N mm/yr` on that line states the range:\n  {line.strip()}\n"
            f"The claim this test pins (the scale must cover every published cell) needs a number."
        )
    documented = float(match.group(1))

    published = [case for case in doc_table if case in measured]
    if not published:
        pytest.fail(
            f"docs/handoff-mock.md:{line_no} states a shared scale, but none of the documented "
            f"cases ({', '.join(sorted(doc_table))}) exist under data/processed/, so the scale "
            f"cannot be checked against the cells it has to cover."
        )
    worst_case, worst = max(
        ((case, float(measured[case]["max_abs_velocity"])) for case in published),
        key=lambda item: item[1],
    )
    if documented >= worst:
        return
    pytest.fail(
        f"docs/handoff-mock.md:{line_no} — the shared scale does not cover the published cells\n"
        f"  documented: ±{documented:.3f} mm/yr (the scale the legend and the pitch figure use)\n"
        f"  measured:   max|velocity_mm_yr| = {worst:.3f} mm/yr in {worst_case!r}, "
        f"i.e. {worst - documented:.3f} mm/yr beyond the top of the scale\n"
        f"  tolerance:  none — the doc states this as a requirement ('must cover'), not a "
        f"measurement, so either the scale grows or the claim is false\n"
        f"  doc line:   {line.strip()}\n"
        f"  a cell outside the scale renders saturated: the strongest signal in the demo goes "
        f"flat-topped, which is exactly what this paragraph says must not happen."
    )


def test_date_window_and_count_match_meta(
    doc_table: dict[str, Row], measured: dict[str, dict[str, object]]
) -> None:
    line_no, line = prose_line(
        r"\d+\s+dates?,\s*`\d{4}-\d{2}-\d{2}\s*(?:→|->|—|-)\s*\d{4}-\d{2}-\d{2}`",
        what="the date window",
    )
    match = re.search(
        r"(\d+)\s+dates?,\s*`(\d{4}-\d{2}-\d{2})\s*(?:→|->|—|-)\s*(\d{4}-\d{2}-\d{2})`", line
    )
    if match is None:  # pragma: no cover - prose_line already matched the same text
        pytest.fail(f"docs/handoff-mock.md:{line_no}: cannot read the date window from {line!r}")
    documented_count, documented_start, documented_end = int(match.group(1)), match.group(2), match.group(3)

    report: list[str] = []
    for case, row in sorted(doc_table.items()):
        if case not in measured:
            continue
        dates = measured[case]["dates"]
        assert isinstance(dates, list)
        start, end, count = dates[0], dates[-1], len(dates)
        if (count, start, end) == (documented_count, documented_start, documented_end):
            continue
        report.append(
            f"docs/handoff-mock.md:{line_no} — date window for {case!r} disagrees with meta.dates\n"
            f"  documented: {documented_count} dates, {documented_start} → {documented_end}\n"
            f"  measured:   {count} dates, {start} → {end} "
            f"(meta.json, data/processed/{case}/)\n"
            f"  tolerance:  exact — ISO dates and an integer count are compared verbatim\n"
            f"  doc line:   {line.strip()}\n"
            f"  fix one of the two: the two-year window is what identifies the annual harmonic "
            f"(annual_coverage 2.004 against the 0.75 yr-per-harmonic gate), so a 12-date copy is "
            f"a pre-1.1 artefact."
        )
    if report:
        pytest.fail("\n\n".join(report))


def test_time_constant_matches_the_meta_window(measured: dict[str, dict[str, object]]) -> None:
    """The §2 map bindings publish T = days/365.25; a stale T silently rescales every height."""
    line_no, line = prose_line(
        r"T = \d+ days = [0-9.]+ yr, from \d+/365\.25 = [0-9.]+", what="the map-binding time constant"
    )
    match = re.search(
        r"T = (\d+) days = ([0-9.]+) yr, from \d+/365\.25 = ([0-9.]+)", line
    )
    if match is None:  # pragma: no cover - prose_line already matched the same text
        pytest.fail(f"docs/handoff-mock.md:{line_no}: cannot read T from {line!r}")
    documented_days = int(match.group(1))
    documented_yr = float(match.group(2))
    documented_exact = float(match.group(3))

    table_line = next(
        (text for text in _doc_lines() if re.search(r"\|\s*time constant\s*\|", text)), None
    )
    if table_line is None:
        pytest.fail(
            "docs/handoff-mock.md: the §2 map-bindings table no longer has a `time constant` row. "
            "A reader binds `height` to `delta_change` through it; restore the row instead of "
            "leaving T implicit."
        )
    table_match = re.search(r"T\s*=\s*([0-9.]+)", table_line)
    if table_match is None:
        pytest.fail(f"docs/handoff-mock.md: cannot read T from the table row {table_line.strip()!r}")
    table_yr = float(table_match.group(1))

    report: list[str] = []
    for case in CASES:
        dates = measured[case]["dates"]
        assert isinstance(dates, list)
        days = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days
        measured_yr = days / 365.25
        if days != documented_days:
            report.append(
                _mismatch(
                    metric="window days (T)",
                    row=Row(case=case, values={}, line_no=line_no, text=line),
                    documented=documented_days,
                    measured_value=days,
                    tolerance="exact",
                    reason="T is (last date − first date) in whole days, from meta.dates",
                )
            )
            continue
        for label, documented in (
            ("T (yr)", documented_yr),
            ("days/365.25", documented_exact),
            ("T (yr) in the table row", table_yr),
        ):
            if abs(documented - measured_yr) <= TOL_TIME_CONSTANT_YR:
                continue
            report.append(
                _mismatch(
                    metric=label,
                    row=Row(case=case, values={}, line_no=line_no, text=line),
                    documented=documented,
                    measured_value=measured_yr,
                    tolerance=f"±{TOL_TIME_CONSTANT_YR:g} yr (the doc prints five decimals)",
                    reason="T must be the measured span in years, not a remembered constant",
                )
            )
    if report:
        pytest.fail("\n\n".join(report))


def test_kpi_chart_table_matches_artefacts(
    doc_table: dict[str, Row], measured: dict[str, dict[str, object]]
) -> None:
    """§3c mixes an aggregation (mean) with a KPI (median); both and their ×T totals are pinned."""
    chart = parse_chart_table()
    report: list[str] = []
    for case in CASES:
        row = chart.get(case)
        if row is None:
            pytest.fail(
                f"docs/handoff-mock.md has no §3c chart row for {case!r}, which exists on disk.\n"
                f"  documented: {', '.join(sorted(chart)) or '(none)'}\n"
                f"  measured:   data/processed/{case}/"
            )
        got = measured[case]
        grid = got["grid"]
        assert isinstance(grid, pd.DataFrame)
        dates = got["dates"]
        assert isinstance(dates, list)
        span_years = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25
        mean = float(grid["velocity_mm_yr"].mean())
        median = float(got["median"])
        _check(
            report, metric="chart mean mm/yr", row=row,
            documented=row.values["mean"], measured_value=mean,
            tolerance=TOL_VELOCITY, unit="mm/yr",
            reason="the chart is the grid mean; the doc prints one decimal",
        )
        _check(
            report, metric="KPI median mm/yr", row=row,
            documented=row.values["median"], measured_value=median,
            tolerance=TOL_VELOCITY, unit="mm/yr",
            reason="the KPI is meta.stats.median_velocity_mm_yr; the doc prints one decimal",
        )
        _check(
            report, metric="mean×T", row=row,
            documented=row.values["mean_t"], measured_value=mean * span_years,
            tolerance=TOL_VELOCITY, unit="mm",
            reason="mean × the measured T (732/365.25 yr); one decimal in the doc",
        )
        _check(
            report, metric="median×T", row=row,
            documented=row.values["median_t"], measured_value=median * span_years,
            tolerance=TOL_VELOCITY, unit="mm",
            reason="median × the measured T (732/365.25 yr); one decimal in the doc",
        )
    undocumented = sorted(set(chart) - set(doc_table))
    if undocumented:
        pytest.fail(
            f"docs/handoff-mock.md §3c rows for {undocumented} have no case in the §1 table — "
            f"the two tables describe the same published set."
        )
    if report:
        pytest.fail("\n\n".join(report))


def test_water_cells_absent_from_grid_but_present_as_context(
    doc_table: dict[str, Row], measured: dict[str, dict[str, object]]
) -> None:
    line_no, line = prose_line(
        r"Water cells are absent from the grid", what="the absent-water-cells claim"
    )
    report: list[str] = []
    for case in sorted(doc_table):
        if case not in measured:
            continue
        grid = measured[case]["grid"]
        assert isinstance(grid, pd.DataFrame)
        water_cells = int((grid["land_use"] == "water").sum())

        context = json.loads((CASE_DIRS[case] / "context_layers.geojson").read_text(encoding="utf-8"))
        water_features = [
            feature
            for feature in context.get("features", [])
            if str(feature.get("properties", {}).get("layer", "")).lower() == "water"
        ]

        if water_cells:
            report.append(
                f"docs/handoff-mock.md:{line_no} — grid for {case!r} still carries water cells\n"
                f"  documented: 0 cells with land_use == \"water\"\n"
                f"  measured:   {water_cells} of {len(grid)} cells\n"
                f"  tolerance:  0 (exact) — 'absent, never 0' is the contract's nodata rule\n"
                f"  doc line:   {line.strip()}\n"
                f"  a specular surface has no usable phase: publishing it gives the map a "
                f"subsiding ocean."
            )
        if not water_features:
            report.append(
                f"docs/handoff-mock.md:{line_no} — the coastline disappeared with the cells in {case!r}\n"
                f"  documented: ≥1 context feature with layer == \"water\" in context_layers.geojson\n"
                f"  measured:   {len(water_features)} water features; layers present = "
                f"{sorted({str(f.get('properties', {}).get('layer')) for f in context.get('features', [])})}\n"
                f"  tolerance:  0 (exact) — the claim is that the cells are dropped, not the geometry\n"
                f"  doc line:   {line.strip()}\n"
                f"  dropping the cells must not drop the coast: the map has to be able to draw it."
            )
    if report:
        pytest.fail("\n\n".join(report))


# --------------------------------------------------------------------------------------------
# §3b: the independent-legend table is also a published number set
# --------------------------------------------------------------------------------------------


def test_legend_table_matches_meta_stats(measured: dict[str, dict[str, object]]) -> None:
    legend = parse_legend_table()
    report: list[str] = []
    for case, row in sorted(legend.items()):
        if case not in measured:
            report.append(
                f"docs/handoff-mock.md:{row.line_no} — legend row for {case!r} has no case on disk\n"
                f"  documented: p05 {row.values['p05']}, p95 {row.values['p95']}\n"
                f"  measured:   data/processed/{case}/ does not exist\n"
                f"  tolerance:  exact — one row per published case\n"
                f"  doc line:   {row.text.strip()}"
            )
            continue
        got = measured[case]
        p05, p95 = float(got["p05"]), float(got["p95"])
        _check(
            report, metric="legend p05", row=row,
            documented=row.values["p05"], measured_value=p05,
            tolerance=TOL_VELOCITY, unit="mm/yr",
            reason="doc prints one decimal; ±0.05 is the rounding error, 0.1 leaves one digit",
        )
        _check(
            report, metric="legend p95", row=row,
            documented=row.values["p95"], measured_value=p95,
            tolerance=TOL_VELOCITY, unit="mm/yr",
            reason="doc prints one decimal; ±0.05 is the rounding error, 0.1 leaves one digit",
        )
        _check(
            report, metric="legend spread (p95 − p05)", row=row,
            documented=row.values["spread"], measured_value=p95 - p05,
            tolerance=TOL_LEGEND_SPREAD, unit="mm/yr",
            reason="difference of two one-decimal numbers: rounding can add up to 0.1, so 0.2 covers "
                   "the arithmetic (a 2 mm/yr gap is not rounding, it is a different dataset)",
        )
    if report:
        pytest.fail("\n\n".join(report))
