"""End-to-end integration tests against the shipped 3-city mock artefacts in `data/processed/`.

Verifies that Rol 1 (`src.data` + `src.domain`) loads, validates, filters, aggregates and builds
PyDeck map payloads over all 19,294 real H3 cells emitted by Rol 3 (`pipeline/generate_mock.py`),
preserving every numerical expectation documented in `docs/handoff-mock.md` — and, for the KPIs and
comparison, reading those expectations out of the page instead of restating them here.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from src.data import (
    aoi_series,
    kpis,
    list_available_cases,
    load_all_available_bundles,
    load_case,
    load_study_cases_config,
    map_payload,
)
from src.domain.filters import FilterCriteria, apply_filters, available_filter_options
from src.domain.map_adapter import (
    COLUMN_BASELINE_M,
    GLOBAL_VELOCITY_RANGE_MM_YR,
    RISK_COLORS_RGB,
    build_map_payload,
    build_pydeck_layer_specs,
)
from src.domain.metrics import (
    build_city_comparison,
    build_provenance_badge,
    compute_kpis,
    extract_series_view,
)


def test_shipped_three_cities_load_and_match_handoff_expectations():
    cases = list_available_cases()
    assert cases == ["mexico-city", "jakarta", "malaga"]

    cfg = load_study_cases_config()
    assert len(cfg.cases["mexico-city"].aoi_polygon) > 100  # loaded from config/aoi/*.geojson

    bundles = load_all_available_bundles()

    # Also verify drop-in reference_loader compatibility via src.data
    ref_case = load_case("mexico-city")
    assert len(map_payload(ref_case, coherence_min=0.7)) < len(ref_case.grid)
    dates, vals = aoi_series(ref_case)
    # Two-year mock window: 62 dates, 2024-11-10 -> 2026-11-12 (handoff §1)
    assert len(dates) == len(vals) == 62
    assert kpis(ref_case)["cells"] == len(ref_case.grid)

    for slug, bundle in bundles.items():
        # The row count is checked against the artefact's own record (meta.stats.n_cells), never
        # against a literal kept here: the mock is rebuilt as the OSM geography improves, and a
        # stale literal in this file is exactly how docs/handoff-mock.md §1 went wrong.
        assert len(bundle.grid) == int(bundle.meta["stats"]["n_cells"]), slug
        assert bundle.validation.is_valid, f"{slug} failed validation: {bundle.validation.all_problems}"
        assert bundle.is_mock is True
        opts = available_filter_options(bundle)
        assert opts.sensor_coherence_min == pytest.approx(0.35)
        assert len(opts.available_dates) == 62


# The handoff page is the thing Rol 1 and Rol 2 code against, so the numbers below are READ from
# `docs/handoff-mock.md` instead of restated here: a literal in this file and a literal in the doc
# can drift apart silently (the doc's §1 table went stale that way while this test stayed green).
DOC = pathlib.Path("docs/handoff-mock.md")
if not DOC.is_file():
    pytest.skip(
        "docs/handoff-mock.md is not shipped in the submitted repository",
        allow_module_level=True,
    )

MINUS_SIGNS = "\u2212\u2010\u2011\u2012\u2013\u2014\u2015\u2043\ufe63\uff0d"

#: One decimal in the doc, so 0.1 is the width of the printed value (no tuning).
TOL_ONE_DECIMAL = 0.1


def _cells(line: str) -> list[str]:
    return [cell.strip().strip("`").strip() for cell in line.strip().strip("|").split("|")]


def _number(cell: str, *, line: str) -> float:
    """First number in a table cell, tolerating the doc's unicode minus and a trailing unit."""
    raw = cell.replace(",", "").replace("\u00a0", " ").translate({ord(c): "-" for c in MINUS_SIGNS})
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
    assert match is not None, f"docs/handoff-mock.md: cannot read a number from {cell!r} in {line!r}"
    return float(match.group(0))


def _doc_rows(heading: str) -> dict[str, dict[str, float]]:
    """First markdown table after `heading`, keyed by case id, columns keyed by lowercased header."""
    lines = DOC.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if heading in line), None)
    assert start is not None, f"docs/handoff-mock.md: no line contains {heading!r}"
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.lstrip().startswith("|"):
            block.append(line)
        elif block:
            break
    assert len(block) >= 2, f"docs/handoff-mock.md: no table under {heading!r}"
    header = [cell.lower() for cell in _cells(block[0])]
    rows: dict[str, dict[str, float]] = {}
    for line in block[1:]:
        cells = _cells(line)
        if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        rows[cells[0]] = {name: _number(cell, line=line) for name, cell in zip(header[1:], cells[1:])}
    return rows


def _doc_number(pattern: str, *, what: str) -> float:
    """The one documented number matching `pattern` in the prose."""
    for line in DOC.read_text(encoding="utf-8").splitlines():
        match = re.search(pattern, line)
        if match is not None:
            return float(match.group(1).replace(",", "").translate({ord(c): "-" for c in MINUS_SIGNS}))
    raise AssertionError(f"docs/handoff-mock.md: no line states {what} ({pattern!r})")


def test_shipped_kpis_and_comparison_match_handoff_mock_doc():
    bundles = load_all_available_bundles()

    summary = _doc_rows("What the current mock actually contains")
    chart = _doc_rows("KPI (median) and chart (mean×T)")

    cdmx_kpis = compute_kpis(bundles["mexico-city"])
    # Documented twice (§1 and §3c); both rows have to agree with the artefact's median.
    for documented in (summary["mexico-city"]["median mm/yr"], chart["mexico-city"]["median mm/yr (kpi)"]):
        assert cdmx_kpis.median_velocity_mm_yr == pytest.approx(documented, abs=TOL_ONE_DECIMAL)
    assert cdmx_kpis.is_null_result is False
    assert cdmx_kpis.critical_cells_count > 5000

    malaga_kpis = compute_kpis(bundles["malaga"])
    assert malaga_kpis.median_velocity_mm_yr == pytest.approx(
        summary["malaga"]["median mm/yr"], abs=TOL_ONE_DECIMAL
    )
    assert malaga_kpis.is_null_result is True
    # §2b publishes the configured mock limit ("detection_limit_mm_yr = 1.5"); absent in the other two.
    assert malaga_kpis.detection_limit_mm_yr == pytest.approx(
        _doc_number(r"detection_limit_mm_yr = ([0-9.]+)", what="the detection limit")
    )
    assert malaga_kpis.critical_cells_count == 0

    badge = build_provenance_badge(bundles["malaga"])
    assert badge.is_mock is True
    assert badge.revisit_days == 12

    series = extract_series_view(bundles["mexico-city"])
    assert series.n_points == int(_doc_number(r"two years \((\d+) dates,", what="the date count"))
    assert series.fitted_trend_mm_yr is not None
    # §3c calls the chart "mean mm/yr (chart)": the aoi series carries the grid mean by construction,
    # and §3c also publishes mean×T, so the two are the same claim measured twice.
    assert series.fitted_trend_mm_yr == pytest.approx(
        chart["mexico-city"]["mean mm/yr (chart)"], abs=TOL_ONE_DECIMAL
    )

    scale = _doc_number(r"symmetric scale about 0 at ±\s*([0-9.]+)\s*mm/yr", what="the shared scale")
    comp = build_city_comparison(list(bundles.values()))
    assert comp.shared_velocity_range_mm_yr == (-scale, scale)
    assert comp.has_mixed_sensors is False
    assert comp.sensor_warning is None
    # The doc states this as a requirement, not a measurement: the scale must cover every cell.
    assert max(float(bundle.grid["velocity_mm_yr"].abs().max()) for bundle in bundles.values()) <= scale


def test_shipped_pydeck_payload_respects_symmetric_425_shared_scale():
    bundles = load_all_available_bundles()

    p_cdmx = build_map_payload(bundles["mexico-city"], scale_mode="shared", extrude_3d=True)
    p_malaga = build_map_payload(bundles["malaga"], scale_mode="shared", extrude_3d=True)

    assert p_cdmx.legend.domain_min == GLOBAL_VELOCITY_RANGE_MM_YR[0] == -425.0
    assert p_cdmx.legend.domain_max == GLOBAL_VELOCITY_RANGE_MM_YR[1] == 425.0

    # In Málaga >99.5% of cells sit inside [-5, +5] mm/yr (2,751 of 2,758) -> neutral grey on the
    # shared scale (re-derived from the grid each run; the count moves with the mock)
    neutral_rgb = list(RISK_COLORS_RGB["estable"])
    for rec in p_malaga.grid_records:
        if rec["risk_level"] == "estable":
            assert rec["fill_color"][:3] == neutral_rgb
    malaga_neutral_share = sum(
        1 for r in p_malaga.grid_records if r["fill_color"][:3] == neutral_rgb
    ) / len(p_malaga.grid_records)
    assert malaga_neutral_share > 0.995
    # O-07: column height is SIGNED around COLUMN_BASELINE_M (subsidence below it, uplift above),
    # so "small on the shared scale" means a small deviation from the baseline, not a small
    # absolute height. CDMX subsides hard, so it must reach far BELOW the baseline.
    assert max(abs(r["elevation_m"] - COLUMN_BASELINE_M) for r in p_malaga.grid_records) < 55.0
    assert min(r["elevation_m"] for r in p_cdmx.grid_records) < COLUMN_BASELINE_M - 1000.0

    # Independent toggle seeds from meta.stats p05/p95 without mutating data
    p_malaga_ind = build_map_payload(
        bundles["malaga"],
        FilterCriteria(coherence_min=0.5),
        scale_mode="independent",
        extrude_3d=False,
    )
    assert p_malaga_ind.legend.scale_mode == "independent"
    assert len(p_malaga_ind.grid_records) < len(bundles["malaga"].grid)

    spec = build_pydeck_layer_specs(p_cdmx)
    assert len(spec["layers"]) == 2
