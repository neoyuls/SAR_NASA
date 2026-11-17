"""Cross-document guard for the SAR constant-geometry numbers.

The same physical constants are restated in several documents.  Prose audited by hand is not a
control, so this module parses the documents and recomputes every number from the code:

* ``pipeline/science/transforms.vertical_from_los`` -- the LOS -> vertical geometry;
* ``pipeline/process_case.DEFAULT_WAVELENGTH_M`` -- the documented L-band wavelength (0.2384 m);
* ``pipeline/science/transforms.DAYS_PER_YEAR`` -- 365.25 d;
* ``config/study_cases.yaml`` -- the mock peak rate and the declared revisit;
* ``src.domain.contracts.contract_fingerprint()`` -- the frozen contract digest.
* ``data/processed/*/meta.json`` -- the 2-year demo window that ``docs/science-guide.md`` narrates:
  its span and coverage, the two design conditions, the injected amplitudes, the detection band.

Nothing here hardcodes a second copy of a formula.  The one value that is not exported by the
science module is the 39 degree incidence angle (it is a study-case geometry, stated in
``docs/nisar-gunw-layout.md`` §4); :data:`INCIDENCE_DEG` is checked against every document that
restates it.

The historical mistake this file exists to prevent
--------------------------------------------------
The 12-day anchor was once written as ``−420 mm/yr -> −13.8 mm -> 0.09 fringe`` while a guard
argued for ``0.12``.  Both arithmetic chains were self-consistent: 13.8 / 153.4 = 0.090 (the
*vertical* fringe), 13.8 / 119.2 = 0.116 (the *LOS* fringe).  A velocity in mm/yr and the
displacement it produces are vertical quantities, so the fraction belongs over the **vertical**
fringe (153.4 mm).  :func:`test_fringe_fractions_use_the_vertical_denominator` asserts that on
every document claim, and explicitly fails the LOS reading.

The two coverage percentages are derived, not written down: :func:`_coverage_sets` asks
``scripts/demo_numbers.py`` -- the same code that prints the demo cards -- what the current AOI and
bbox coverage are.  What matters here is that a bbox-envelope figure is never presented as
coverage of the AOI.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import math
import pathlib
import re
import sys

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `python -m pytest` puts the cwd on the path; be explicit anyway
    sys.path.insert(0, str(ROOT))

from pipeline.process_case import DEFAULT_WAVELENGTH_M  # noqa: E402
from pipeline.science import transforms as T  # noqa: E402
from src.domain import contracts as C  # noqa: E402

#: Documents allowed to restate the science constants. Missing files are skipped. The detailed
#: guides inherited these claims from CONTEXT.md, so modularising the prose must not drop the guard.
DOCUMENTS: tuple[pathlib.Path, ...] = (
    pathlib.Path("docs/nisar-gunw-layout.md"),
    pathlib.Path("README.md"),
    pathlib.Path("pipeline/README.md"),
    pathlib.Path("CONTEXT.md"),
    pathlib.Path("docs/data-contract-v1.md"),
    pathlib.Path("docs/science-guide.md"),
    pathlib.Path("docs/pipeline-internals.md"),
    # The two documents that actually carry the coverage percentages (D-20/N-09): the decision memo
    # labels the AOI and bbox denominators, and the video script quotes both cards. Without them the
    # "no document states a coverage percentage" assertion fires even though the figures are written
    # down and the guard has nothing to police.
    pathlib.Path("docs/data-source-decision.md"),
    pathlib.Path("docs/video-script.md"),
)

CONFIG_PATH = ROOT / "config" / "study_cases.yaml"
MEXICO_GRID = ROOT / "data" / "processed" / "mexico-city" / "nisar_grid.parquet"

#: Incidence angle of every worked example (docs/nisar-gunw-layout.md §4, θ = 39°).  transforms.py
#: takes it as an argument rather than exporting it, so it is stated once here and checked against
#: each document that restates it.
INCIDENCE_DEG = 39.0

def _coverage_sets() -> tuple[frozenset[float], frozenset[float]]:
    """(AOI, bbox) coverage percentages to 2 dp, over every published case.

    The AOI is the threshold denominator; the bbox is the AOI's envelope and is never coverage of
    the city.  Deriving them instead of writing them down is deliberate: a hardcoded pair outlived
    one regeneration and then failed the document that was right rather than the one that was
    stale.  ``scripts/demo_numbers.py`` owns the arithmetic, so there is no second formula here.
    """
    spec = importlib.util.spec_from_file_location(
        "_demo_numbers", ROOT / "scripts" / "demo_numbers.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The module must be registered before execution: `@dataclass` resolves annotations through
    # `sys.modules[cls.__module__]`, and a dataclass here would fail with a bare AttributeError.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    aoi: set[float] = set()
    bbox: set[float] = set()
    for case_dir in sorted(pathlib.Path(ROOT / "data" / "processed").iterdir()):
        if not (case_dir / "meta.json").is_file():
            continue
        numbers = module.load_case(case_dir)
        aoi.add(round(float(numbers.aoi_coverage_fraction) * 100.0, 2))
        bbox.add(round(float(numbers.bbox_coverage_fraction) * 100.0, 2))
    return frozenset(aoi), frozenset(bbox)


AOI_COVERAGE, BBOX_COVERAGE = _coverage_sets()
COVERAGE_THRESHOLD = 50.0

#: One radian and one fringe, in millimetres, on both bases.
LOS_PER_RADIAN_MM = DEFAULT_WAVELENGTH_M / (4.0 * math.pi) * 1000.0
VERTICAL_PER_RADIAN_MM = float(T.vertical_from_los(LOS_PER_RADIAN_MM, INCIDENCE_DEG, 192.0))
LOS_PER_FRINGE_MM = DEFAULT_WAVELENGTH_M / 2.0 * 1000.0
VERTICAL_PER_FRINGE_MM = float(T.vertical_from_los(LOS_PER_FRINGE_MM, INCIDENCE_DEG, 192.0))

FRACTION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:of\s+a\s+)?fringe", re.IGNORECASE)
RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm/yr", re.IGNORECASE)
VERTICAL_DISPLACEMENT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*mm\s+vertical(?:ly)?", re.IGNORECASE
)
DAYS_RE = re.compile(r"(\d+)[\-\u2011\u2013]?\s*day\s+pair", re.IGNORECASE)
DECIMAL_PERCENT_RE = re.compile(r"(\d+\.\d+)\s*%")
FULL_HASH_RE = re.compile(r"\b[0-9a-f]{64}\b")
ABBREV_HASH_RE = re.compile(r"\b([0-9a-f]{6,64})\s*(?:\u2026|\.{3})\s*([0-9a-f]{2,64})?")

#: A line carrying this marker is a DELIBERATE historical quote (see ``docs/decisions.md``), not a
#: claim about this tree. Mirrors ``tests/test_fingerprint_consistency.py`` so the two guards agree
#: on what history is; it must never excuse a stale live quote.
HISTORICAL_MARKER = "fingerprint-historical"


# ---------------------------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------------------------


def _documents() -> dict[pathlib.Path, str]:
    """Existing documents, keyed by repo-relative path.  A missing file is simply absent."""
    found: dict[pathlib.Path, str] = {}
    for relative in DOCUMENTS:
        path = ROOT / relative
        if path.is_file():
            found[relative] = path.read_text(encoding="utf-8")
    if not found:
        pytest.skip("none of the constants documents are present in this checkout")
    return found


def _tolerance(printed: str) -> float:
    """Half a unit in the last decimal the document printed (0.005 for ``0.09``)."""
    if "." not in printed:
        return 0.5
    return 0.5 * 10.0 ** (-len(printed.split(".", 1)[1]))


def _agrees(printed: str, expected: float) -> bool:
    return abs(float(printed) - expected) <= _tolerance(printed) + 1e-12


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _line_text(text: str, line_number: int) -> str:
    lines = text.splitlines()
    return lines[line_number - 1] if 1 <= line_number <= len(lines) else ""


def _snippet(text: str, index: int, width: int = 160) -> str:
    start = max(0, index - width // 2)
    return " ".join(text[start : start + width].split())


def _claim_units(text: str):
    """Yield ``(line_number, unit_text)`` for table rows and prose sentences.

    A Markdown table row is one claim; consecutive prose lines are joined into a paragraph and
    split into sentences.  Joining prose matters because several anchors wrap the displacement and
    the fringe fraction onto two physical lines.
    """
    lines = text.splitlines()
    offsets: list[int] = []
    running = 0
    for line in lines:
        offsets.append(running)
        running += len(line) + 1

    # "i.e." and "e.g." end with a period but do not end a sentence.  The layout document wraps
    # the 12-day anchor across such an abbreviation, so splitting there would separate the
    # fraction from its displacement.
    abbreviation = re.compile(r"(?:^|\s)(?:i\.e|e\.g|cf|vs|etc)\.$", re.IGNORECASE)

    def sentences(block: str, first_line: int, base: int):
        start = 0
        for match in re.finditer(r"(?<=[.!?])\s+", block):
            if abbreviation.search(block[: match.start()]):
                continue
            piece = block[start : match.start()]
            if piece.strip():
                line_number = first_line + block[:start].count("\n")
                yield line_number, piece
            start = match.end()
        piece = block[start:]
        if piece.strip():
            line_number = first_line + block[:start].count("\n")
            yield line_number, piece

    buffer: list[str] = []
    buffer_line = 1
    buffer_offset = 0

    def flush():
        nonlocal buffer
        if buffer:
            yield from sentences("\n".join(buffer), buffer_line, buffer_offset)
            buffer = []

    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("|"):
            yield from flush()
            yield number, line
        elif line.strip():
            if not buffer:
                buffer_line = number
                buffer_offset = offsets[number - 1]
            buffer.append(line)
        else:
            yield from flush()
    yield from flush()


def _scale_rows(text: str):
    """Yield ``(line_number, kind, printed_values, line)`` for the phase -> mm scale table."""
    for number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        label = re.sub(r"[*`]", "", cells[0]).strip().lower()
        if not re.match(r"^(?:(?:1|one)\s+)?(?:radian|fringe)\b", label):
            continue
        kind = "radian" if "radian" in label else "fringe"
        values: list[str] = []
        for cell in cells[1:]:
            values.extend(match.group(1) for match in re.finditer(r"(\d+(?:\.\d+)?)\s*mm", cell))
        yield number, kind, values, line


def _paragraphs(text: str):
    """Yield ``(paragraph_text, start_offset)`` separated by blank lines."""
    start = 0
    for match in re.finditer(r"\n\s*\n", text):
        yield text[start : match.start()], start
        start = match.end()
    yield text[start:], start


def _config_anchor() -> tuple[str, float, int]:
    """Primary case, its configured peak rate (mm/yr, unsigned) and declared revisit (days)."""
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    case = str(config["primary"])
    case_config = config["cases"][case]
    peak = abs(float(case_config["mock"]["peak_velocity_mm_yr"]))
    return case, peak, int(case_config["revisit_days"])


def _report_failures(report: list[str]) -> None:
    if report:
        pytest.fail("\n\n".join(report))


# ---------------------------------------------------------------------------------------------
# 1. Per-radian and per-fringe: 18.97 / 24.41 and 119.2 / 153.4
# ---------------------------------------------------------------------------------------------


def test_phase_scale_restatements_agree_with_transforms() -> None:
    expected = {
        "radian": (LOS_PER_RADIAN_MM, VERTICAL_PER_RADIAN_MM),
        "fringe": (LOS_PER_FRINGE_MM, VERTICAL_PER_FRINGE_MM),
    }
    report: list[str] = []
    rows_seen = 0

    for relative, text in _documents().items():
        for number, kind, values, line in _scale_rows(text):
            rows_seen += 1
            if len(values) != 2:
                report.append(
                    f"{relative}:{number}: expected LOS and vertical mm values in the "
                    f"{kind} row, found {values!r}\n  {line.strip()}"
                )
                continue
            for column, printed, truth in zip(("LOS", "vertical"), values, expected[kind]):
                if not _agrees(printed, truth):
                    report.append(
                        f"{relative}:{number}: {kind} {column} is {printed} mm, computed "
                        f"{truth:.4f} mm\n  tolerance: half a unit in the last printed digit "
                        f"({_tolerance(printed):g} mm)\n  {line.strip()}"
                    )

        # Inline restatements, e.g. "119.2 mm LOS / 153.4 mm vertical".
        for match in re.finditer(
            r"(\d+(?:\.\d+)?)\s*mm\s*LOS\s*/\s*(\d+(?:\.\d+)?)\s*mm\s+vertical",
            text,
            re.IGNORECASE,
        ):
            number = _line_number(text, match.start())
            line = _line_text(text, number)
            if re.search(r"\b1\s*radian|\bone\s+radian", line, re.IGNORECASE):
                truth = expected["radian"]
            elif "fringe" in line.lower() or "2π" in line:
                truth = expected["fringe"]
            else:
                continue
            for column, printed, value in zip(("LOS", "vertical"), match.groups(), truth):
                if not _agrees(printed, value):
                    report.append(
                        f"{relative}:{number}: inline {column} is {printed} mm, computed "
                        f"{value:.4f} mm\n  {line.strip()}"
                    )

        # "one full 2π fringe is ~119 mm of line-of-sight motion" (rounded on purpose).
        for match in re.finditer(
            r"(\d+(?:\.\d+)?)\s*mm\s+of\s+line[\s-]of[\s-]sight", text, re.IGNORECASE
        ):
            number = _line_number(text, match.start())
            line = _line_text(text, number)
            if "fringe" not in line.lower():
                continue
            printed = match.group(1)
            if not _agrees(printed, LOS_PER_FRINGE_MM):
                report.append(
                    f"{relative}:{number}: rounded fringe LOS is {printed} mm, computed "
                        f"{LOS_PER_FRINGE_MM:.2f} mm\n  {line.strip()}"
                )

        # A reproduce command prints the per-radian vertical scale after an arrow.
        for match in re.finditer(r"vertical_from_los\(", text):
            window = text[match.start() : match.start() + 500]
            arrow = re.search(r"(?:\u2192|->)\s*`?(\d+(?:\.\d+)?)`?", window)
            if arrow is None or (
                "4*math.pi" not in window and "4 * math.pi" not in window
            ):
                continue
            printed = arrow.group(1)
            if not _agrees(printed, VERTICAL_PER_RADIAN_MM):
                report.append(
                    f"{relative}:{_line_number(text, match.start())}: reproduce command prints "
                    f"{printed} mm for one radian, computed {VERTICAL_PER_RADIAN_MM:.2f} mm"
                )

        # Prose restatement of the fringe scale: "one cycle slip is 2π = 153.4 mm vertical".
        for number, unit in _claim_units(text):
            if "slip" not in unit.lower():
                continue
            for match in re.finditer(
                r"(\d+(?:\.\d+)?)\s*mm\s+(?:of\s+)?vertical", unit, re.IGNORECASE
            ):
                printed = match.group(1)
                if not _agrees(printed, VERTICAL_PER_FRINGE_MM):
                    report.append(
                        f"{relative}:{number}: a cycle slip is {printed} mm vertical, one fringe "
                        f"is {VERTICAL_PER_FRINGE_MM:.1f} mm\n  {unit.strip()}"
                    )

    assert rows_seen, "no phase -> mm scale row was found in any document"
    _report_failures(report)


def test_wavelength_and_incidence_restatements_agree_with_the_code() -> None:
    report: list[str] = []
    lambda_seen = 0
    theta_seen = 0
    for relative, text in _documents().items():
        for match in re.finditer(r"λ(?:_?L)?\s*[=≈]\s*(\d+(?:\.\d+)?)\s*m\b", text):
            lambda_seen += 1
            printed = match.group(1)
            if not _agrees(printed, DEFAULT_WAVELENGTH_M):
                report.append(
                    f"{relative}:{_line_number(text, match.start())}: wavelength is {printed} m, "
                    f"pipeline/process_case.DEFAULT_WAVELENGTH_M is {DEFAULT_WAVELENGTH_M} m"
                )
        for match in re.finditer(r"θ\s*=\s*(\d+(?:\.\d+)?)\s*°", text):
            theta_seen += 1
            printed = match.group(1)
            if not _agrees(printed, INCIDENCE_DEG):
                report.append(
                    f"{relative}:{_line_number(text, match.start())}: incidence is {printed}°, "
                    f"the worked geometry is {INCIDENCE_DEG:g}°"
                )

    assert lambda_seen, "no document restates the NISAR wavelength λ_L"
    assert theta_seen, "no document restates the incidence angle θ"
    _report_failures(report)


# ---------------------------------------------------------------------------------------------
# 2. The 12-day anchor and its fringe fraction
# ---------------------------------------------------------------------------------------------


def _anchors(text: str):
    """Yield parsed anchors: ``(line_number, rate, displacement, days, fraction, unit)``."""
    for line_number, unit in _claim_units(text):
        rate = RATE_RE.search(unit)
        displacement = VERTICAL_DISPLACEMENT_RE.search(unit)
        days = DAYS_RE.search(unit)
        fraction = FRACTION_RE.search(unit)
        if rate and displacement and days and fraction:
            yield (
                line_number,
                float(rate.group(1)),
                float(displacement.group(1)),
                int(days.group(1)),
                fraction.group(1),
                unit,
            )


def test_twelve_day_anchor_is_computed_from_config_and_days_per_year() -> None:
    case, peak, revisit = _config_anchor()
    expected_displacement = peak * revisit / T.DAYS_PER_YEAR
    assert expected_displacement == pytest.approx(13.7988, abs=1e-4)
    expected_fraction = expected_displacement / VERTICAL_PER_FRINGE_MM
    assert expected_fraction == pytest.approx(0.09, abs=0.005)
    los_fraction = expected_displacement / LOS_PER_FRINGE_MM
    assert los_fraction / expected_fraction > 1.2, "the two bases must stay distinguishable"

    report: list[str] = []
    peak_anchors = 0
    measured_rates: list[float] = []

    for relative, text in _documents().items():
        for line_number, rate, displacement, days, fraction, unit in _anchors(text):
            snippet = f"\n  {_snippet(unit, 0)!r}"
            if days != revisit:
                report.append(
                    f"{relative}:{line_number}: anchor uses a {days}-day pair, "
                    f"{case} declares revisit_days={revisit}{snippet}"
                )
            computed = rate * days / T.DAYS_PER_YEAR
            if abs(displacement - computed) > _tolerance(f"{displacement:.1f}") + 1e-9:
                report.append(
                    f"{relative}:{line_number}: {rate:g} mm/yr over {days} d is "
                    f"{computed:.2f} mm, document prints {displacement:.1f} mm{snippet}"
                )

            is_peak = abs(rate - peak) <= _tolerance(f"{peak:g}")
            if is_peak:
                peak_anchors += 1
            else:
                measured_rates.append(rate)

            vertical = displacement / VERTICAL_PER_FRINGE_MM
            los = displacement / LOS_PER_FRINGE_MM
            if not _agrees(fraction, vertical):
                report.append(
                    f"{relative}:{line_number}: {displacement:.1f} mm over the VERTICAL fringe "
                    f"({VERTICAL_PER_FRINGE_MM:.1f} mm) is {vertical:.3f}, document prints "
                    f"{fraction} fringe{snippet}"
                )
            if abs(vertical - los) > 4 * _tolerance(fraction) and abs(
                float(fraction) - los
            ) <= _tolerance(fraction):
                report.append(
                    f"{relative}:{line_number}: {fraction} fringe is the LOS-basis fraction "
                    f"({displacement:.1f}/{LOS_PER_FRINGE_MM:.1f}); use the vertical basis "
                    f"({displacement:.1f}/{VERTICAL_PER_FRINGE_MM:.1f} = {vertical:.3f}){snippet}"
                )

    assert peak_anchors, (
        f"no document states the configured peak anchor for {case} "
        f"({peak:g} mm/yr, {revisit}-day pair)"
    )

    if measured_rates:
        if MEXICO_GRID.is_file():
            strongest = abs(float(pd.read_parquet(MEXICO_GRID, columns=["velocity_mm_yr"])[
                "velocity_mm_yr"
            ].min()))
            for rate in measured_rates:
                if abs(rate - strongest) > 0.005:
                    report.append(
                        f"a measured anchor quotes {rate:.2f} mm/yr but the strongest grid cell "
                        f"in {MEXICO_GRID.relative_to(ROOT)} is {strongest:.2f} mm/yr"
                    )
        else:  # pragma: no cover - a checkout without generated artefacts
            print(
                f"note: {MEXICO_GRID.relative_to(ROOT)} absent; measured anchor rate not compared "
                "with the grid"
            )

    _report_failures(report)


def _table_displacement_before(text: str, line_number: int) -> tuple[float, int] | None:
    """Nearest ``vertical motion`` row above a fraction row in the same Markdown table."""
    lines = text.splitlines()
    for previous in range(line_number - 1, 0, -1):
        line = lines[previous - 1]
        if not line.lstrip().startswith("|"):
            if line.strip():
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        label = re.sub(r"[*`]", "", cells[0]).lower()
        if "vertical motion" in label or "vertical displacement" in label:
            match = re.search(r"(\d+(?:\.\d+)?)\s*mm", cells[1])
            if match:
                return float(match.group(1)), previous
    return None


def test_fringe_fractions_use_the_vertical_denominator() -> None:
    report: list[str] = []
    claims = 0

    for relative, text in _documents().items():
        for line_number, unit in _claim_units(text):
            for fraction in FRACTION_RE.finditer(unit):
                claims += 1
                documented = fraction.group(1)
                displacement_match = VERTICAL_DISPLACEMENT_RE.search(unit)
                source_line = line_number
                if displacement_match:
                    displacement = float(displacement_match.group(1))
                else:
                    # The worked-example table prints displacement and fraction on separate rows.
                    looked_up = _table_displacement_before(text, line_number)
                    if looked_up is None:
                        # A bare fraction ("0.09 of a fringe") or a parenthetical fringe length
                        # ("0.09 of a fringe ≈ 11 mm") is not a vertical-displacement claim.
                        # When a length is printed, it must still equal one of the two bases.
                        length = re.search(r"(\d+(?:\.\d+)?)\s*mm", unit)
                        if length is not None:
                            printed_mm = float(length.group(1))
                            los_mm = float(documented) * LOS_PER_FRINGE_MM
                            vertical_mm = float(documented) * VERTICAL_PER_FRINGE_MM
                            if not (
                                _agrees(length.group(1), los_mm)
                                or _agrees(length.group(1), vertical_mm)
                            ):
                                report.append(
                                    f"{relative}:{line_number}: {documented} of a fringe is "
                                    f"{printed_mm:.1f} mm, but one fringe is "
                                    f"{LOS_PER_FRINGE_MM:.1f} mm LOS / "
                                    f"{VERTICAL_PER_FRINGE_MM:.1f} mm vertical\n"
                                    f"  {unit.strip()}"
                                )
                        continue
                    displacement, source_line = looked_up

                vertical = displacement / VERTICAL_PER_FRINGE_MM
                los = displacement / LOS_PER_FRINGE_MM
                tolerance = _tolerance(documented)
                if not _agrees(documented, vertical):
                    report.append(
                        f"{relative}:{line_number}: {documented} fringe next to "
                        f"{displacement:.1f} mm; the vertical fringe is "
                        f"{VERTICAL_PER_FRINGE_MM:.1f} mm so the fraction is {vertical:.3f} "
                        f"(displacement/153.4, not displacement/119.2 = {los:.3f})"
                        f"\n  displacement row: line {source_line}"
                    )
                if abs(vertical - los) > 4 * tolerance and abs(float(documented) - los) <= tolerance:
                    report.append(
                        f"{relative}:{line_number}: {documented} fringe is displacement over the "
                        f"LOS fringe ({displacement:.1f}/{LOS_PER_FRINGE_MM:.1f}); a vertical "
                        f"displacement belongs over the vertical fringe "
                        f"({displacement:.1f}/{VERTICAL_PER_FRINGE_MM:.1f} = {vertical:.3f})"
                    )

    assert claims, "no document states a numeric fringe fraction"
    _report_failures(report)


# ---------------------------------------------------------------------------------------------
# 3. Coverage denominators: AOI is not the bbox envelope
# ---------------------------------------------------------------------------------------------


def test_coverage_denominators_are_never_conflated() -> None:
    if not all((ROOT / path).is_file() for path in DOCUMENTS):
        pytest.skip("the documents that state coverage percentages are internal, not shipped")
    report: list[str] = []
    coverage_claims = 0

    for relative, text in _documents().items():
        for paragraph, start in _paragraphs(text):
            figures = [
                (match, float(match.group(1))) for match in DECIMAL_PERCENT_RE.finditer(paragraph)
            ]
            for match, figure in figures:
                line_number = _line_number(text, start + match.start())
                line = _line_text(text, line_number)
                paragraph_has_bbox = bool(re.search(r"\bbbox\b|envelope", paragraph, re.I))
                paragraph_has_coverage = bool(
                    re.search(r"\bAOI\b|\bcoverage\b|footprint", paragraph, re.I)
                )
                line_has_bbox = bool(re.search(r"\bbbox\b|envelope", line, re.I))
                line_has_aoi = bool(re.search(r"\bAOI\b", line, re.I))

                if figure in BBOX_COVERAGE:
                    coverage_claims += 1
                    if not line_has_bbox:
                        report.append(
                            f"{relative}:{line_number}: bbox-envelope coverage {figure:.2f} % "
                            f"is not labelled 'bbox'/'envelope' on its line; it must never read "
                            f"as coverage of the AOI\n  {line.strip()}"
                        )
                elif figure in AOI_COVERAGE:
                    coverage_claims += 1
                    if line_has_bbox and not line_has_aoi:
                        report.append(
                            f"{relative}:{line_number}: AOI coverage {figure:.2f} % sits on a "
                            f"line labelled bbox/envelope\n  {line.strip()}"
                        )
                    if paragraph_has_bbox and not re.search(
                        r"\bAOI\b|\bcoverage\b|footprint", paragraph, re.I
                    ):
                        report.append(
                            f"{relative}:{line_number}: AOI coverage {figure:.2f} % appears "
                            "beside a bbox claim with no AOI denominator named"
                        )
                elif figure != COVERAGE_THRESHOLD and paragraph_has_coverage:
                    report.append(
                        f"{relative}:{line_number}: {figure:.2f} % is quoted in a coverage "
                        f"paragraph but is neither an AOI figure {sorted(AOI_COVERAGE)} nor a "
                        f"bbox figure {sorted(BBOX_COVERAGE)}\n  {line.strip()}"
                    )

    assert coverage_claims, "no document states a coverage percentage"
    _report_failures(report)


# ---------------------------------------------------------------------------------------------
# 4. Contract fingerprint
# ---------------------------------------------------------------------------------------------


def test_contract_fingerprint_matches_the_contracts_module() -> None:
    if not all((ROOT / path).is_file() for path in DOCUMENTS):
        pytest.skip("the documents that quote the full fingerprint are internal, not shipped")
    fingerprint = C.contract_fingerprint()
    assert (
        fingerprint == "ed92be802ff8846fe369058d9a80c9545c2a694a17896de6a5f1844146e302ae"
    ), "the frozen contract digest moved; every document must be updated in the same change"

    report: list[str] = []
    full_seen = 0
    for relative, text in _documents().items():
        for match in FULL_HASH_RE.finditer(text):
            if HISTORICAL_MARKER in _line_text(text, _line_number(text, match.start())):
                continue
            full_seen += 1
            if match.group(0) != fingerprint:
                report.append(
                    f"{relative}:{_line_number(text, match.start())}: fingerprint "
                    f"{match.group(0)} != contract_fingerprint() {fingerprint}"
                )
        for match in ABBREV_HASH_RE.finditer(text):
            if HISTORICAL_MARKER in _line_text(text, _line_number(text, match.start())):
                continue
            prefix, suffix = match.group(1), match.group(2)
            if not fingerprint.startswith(prefix) or (suffix and not fingerprint.endswith(suffix)):
                report.append(
                    f"{relative}:{_line_number(text, match.start())}: abbreviated fingerprint "
                    f"{match.group(0)} does not agree with {fingerprint}"
                )

    assert full_seen, "no document states the full contract fingerprint"
    _report_failures(report)


# ---------------------------------------------------------------------------------------------
# 5. The 2-year demo window: the identifiability numbers the science guide quotes
# ---------------------------------------------------------------------------------------------

PROCESSED = ROOT / "data" / "processed"
SCIENCE_GUIDE = pathlib.Path("docs/science-guide.md")

#: The order the guide lists the three cases in when it quotes their amplitudes and secular motion.
CASE_ORDER: tuple[str, ...] = ("mexico-city", "jakarta", "malaga")


def _mock_metas() -> dict[str, dict]:
    """Committed ``meta.json`` per case id; empty when this checkout has no artefacts."""
    metas: dict[str, dict] = {}
    for path in sorted(PROCESSED.glob("*/meta.json")):
        metas[path.parent.name] = json.loads(path.read_text(encoding="utf-8"))
    return metas


def test_science_guide_quotes_the_current_demo_window() -> None:
    """The guide's *current* mock paragraph must quote the 2-year window, not the old 132-day one.

    Widening ``processing.dates_count`` from 132 d to 2 years is what makes ``seasonal_amp_mm``
    publishable (contract 1.1).  The guide restates that argument with numbers — coverage 2.004,
    design conditions 4.02 (one harmonic) and 4.12 (the two the mock fits), the injected amplitudes,
    the detection band — so each is recomputed here from the published dates and the config.  The
    old-window numbers (``annual_coverage 0.36``, ``design_condition ~67``) stay in the prose, but
    as history: the guard fails if the live snippet claims ``seasonal_identifiable # False`` again.
    """
    metas = _mock_metas()
    if not metas:
        pytest.skip("no committed mock artefacts under data/processed")
    guide = (ROOT / SCIENCE_GUIDE).read_text(encoding="utf-8")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    report: list[str] = []
    windows: dict[str, tuple[int, int, np.ndarray, dict]] = {}
    for case, meta in sorted(metas.items()):
        dates = meta["dates"]
        first = datetime.date.fromisoformat(dates[0])
        span_days = (datetime.date.fromisoformat(dates[-1]) - first).days
        t_years = np.array(
            [(datetime.date.fromisoformat(day) - first).days for day in dates], dtype=float
        ) / T.DAYS_PER_YEAR
        windows[case] = (len(dates), span_days, t_years, meta["stats"])

        # The published coverage must be the span the dates actually give, and the published
        # design condition must be the 2-harmonic design of those same dates.
        coverage = float(meta["stats"]["annual_coverage"])
        if abs(coverage - float(t_years[-1])) > 1e-6:
            report.append(
                f"{case}: stats.annual_coverage {coverage} is not the {t_years[-1]:.6f} yr span of "
                f"meta.dates ({dates[0]} -> {dates[-1]})"
            )
        two_harmonic = T._design_condition(T._harmonic_design(t_years, 1.0, 2))
        frozen = float(meta["stats"]["design_condition"])
        if abs(frozen - two_harmonic) > 1e-6:
            report.append(
                f"{case}: stats.design_condition {frozen} is not the 2-harmonic design condition "
                f"{two_harmonic:.6f} of its own dates"
            )

        # The guide says the mock is noise-free in time, so the published amplitude is the injected
        # config constant and not a fit residual.
        injected = float(config["cases"][case]["mock"]["seasonal_amplitude_mm"])
        published = float(meta["stats"]["median_seasonal_amp_mm"])
        if abs(published - injected) > 1e-6:
            report.append(
                f"{case}: median_seasonal_amp_mm {published} != the injected "
                f"seasonal_amplitude_mm {injected}; the guide's 'matches exactly' claim is false"
            )

    # The guide narrates one demo window; all three cases must still share it.
    spans = {(count, days) for count, days, _t, _s in windows.values()}
    if len(spans) != 1:
        report.append(f"the committed cases no longer share one window: {sorted(spans)}")
        _report_failures(report)
    n_dates, span_days, t_years, _stats = next(iter(windows.values()))
    coverage = float(t_years[-1])
    one_harmonic = T._design_condition(T._harmonic_design(t_years, 1.0, 1))
    two_harmonic = T._design_condition(T._harmonic_design(t_years, 1.0, 2))

    # Every number the current-mock paragraphs print, formatted exactly as the guide prints it.
    quoted = {
        "date count": f"{n_dates} dates",
        "span (days)": f"{span_days}-day window",
    }
    if all(case in windows for case in CASE_ORDER):
        amplitudes = [
            float(metas[case]["stats"]["median_seasonal_amp_mm"]) for case in CASE_ORDER
        ]
        quoted["injected amplitudes"] = " / ".join(f"{value:.1f}" for value in amplitudes) + " mm"
    for label, token in quoted.items():
        if token not in guide:
            report.append(
                f"{SCIENCE_GUIDE}: the current-mock paragraph no longer prints the {label} "
                f"{token!r} that this window gives"
            )

    # The live ``harmonic_fit`` snippet is checked on its own, not just against the whole file: a
    # stale snippet is exactly the failure this section exists to catch.
    snippet = next(
        (
            block
            for block in re.findall(r"```python\n(.*?)```", guide, re.S)
            if "fit.seasonal_identifiable" in block
        ),
        "",
    )
    if not snippet:
        report.append(
            f"{SCIENCE_GUIDE}: the harmonic_fit snippet with seasonal_identifiable is gone"
        )
    else:
        for label, token in (
            ("coverage", f"{coverage:.3f}"),
            ("one-harmonic condition", f"{one_harmonic:.2f}"),
            ("two-harmonic condition", f"{two_harmonic:.2f}"),
        ):
            if token not in snippet:
                report.append(
                    f"{SCIENCE_GUIDE}: the harmonic_fit snippet does not print the {label} "
                    f"{token!r} of the published dates"
                )

    # The detection band: a rate on a displacement axis is mm/yr x years (the same arithmetic
    # ``scripts/make_figures.py`` uses to shade it).
    if "malaga" in metas:
        sigma = float(config["cases"]["malaga"]["mock"]["noise_mm_yr"])
        limit = metas["malaga"]["stats"].get("detection_limit_mm_yr")
        if f"σ = {sigma:g} mm" not in guide:
            report.append(
                f"{SCIENCE_GUIDE}: the assumed per-epoch scatter is no longer stated as the "
                f"config noise_mm_yr ({sigma:g} mm)"
            )
        if limit is not None:
            band = float(limit) * span_days / T.DAYS_PER_YEAR
            if f"±{band:.1f} mm over the {span_days}-day window" not in guide:
                report.append(
                    f"{SCIENCE_GUIDE}: the shaded detection floor should read "
                    f"'±{band:.1f} mm over the {span_days}-day window' "
                    f"({float(limit):g} mm/yr x {span_days}/{T.DAYS_PER_YEAR:g})"
                )
        for n_epochs in (n_dates, None):
            computed = float(T.detection_limit_mm_yr(
                velocity_noise_mm=sigma, span_years=coverage, n_epochs=n_epochs
            ))
            label = "two-epoch default" if n_epochs is None else f"{n_epochs} epochs"
            if f"{computed:.2f}" not in guide:
                report.append(
                    f"{SCIENCE_GUIDE}: the detection arithmetic for {label} gives "
                    f"{computed:.2f} mm/yr over the {coverage:.4f} yr span; the guide does not "
                    "state it"
                )

    # The old window may stay as history, but never as the live result of the snippet.
    if "fit.seasonal_identifiable       # True" not in guide:
        report.append(
            f"{SCIENCE_GUIDE}: the harmonic_fit snippet no longer shows "
            "'fit.seasonal_identifiable       # True' for the published window"
        )
    if "# False over a 132-day window" in guide:
        report.append(
            f"{SCIENCE_GUIDE}: 'seasonal_identifiable # False over a 132-day window' is presented "
            "as the current result; the published 2-year window reports True"
        )

    _report_failures(report)
