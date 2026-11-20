"""UI/data coherence A–J: counts, quantiles and bounds originate in `src.domain`.

The cockpit must not re-derive statistics that the backend already publishes, and it must
not invent thresholds that neither the artefact nor the contract declares. Every test here
uses the frozen artefacts through the loaders; nothing writes into `data/processed/`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.data import loaders
from src.domain import contracts as C
from src.domain.metrics import (
    cell_velocity_context,
    coherence_bounds,
    context_row_counts,
    distance_summary,
    threshold_counts,
    velocity_distribution,
)
from src.ui import charts, map_view

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
APP = ROOT / "app.py"
CASE = "mexico-city"


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    loaders.clear_loader_cache()
    yield
    loaders.clear_loader_cache()


def _grid() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED / CASE / "nisar_grid.parquet")


def _meta() -> dict[str, Any]:
    return json.loads((PROCESSED / CASE / "meta.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- A: cell context
def test_cell_velocity_context_uses_published_percentiles_for_a_cell() -> None:
    grid, meta = _grid(), _meta()
    cell = str(grid["cell_id"].iloc[0])
    context = cell_velocity_context(grid, cell, meta["stats"])
    assert context is not None
    assert context["source"] == "meta.stats"
    assert context["n_cells"] == meta["stats"]["n_cells"] == len(grid)
    assert context["p05_mm_yr"] == meta["stats"]["p05_velocity_mm_yr"]
    assert context["p95_mm_yr"] == meta["stats"]["p95_velocity_mm_yr"]
    assert context["position"] in {"below p05", "p05 to median", "median to p95", "above p95"}


def test_cell_velocity_context_recomputes_for_a_filtered_view() -> None:
    grid, meta = _grid(), _meta()
    filtered = grid.loc[grid["coherence"] >= meta["thresholds"]["coherence_min"] + 0.2]
    cell = str(filtered["cell_id"].iloc[0])
    context = cell_velocity_context(filtered, cell, meta["stats"])
    assert context is not None and context["source"] == "filtered grid"
    assert context["n_cells"] == len(filtered)
    assert context["p05_mm_yr"] != meta["stats"]["p05_velocity_mm_yr"]


def test_cell_context_hook_reaches_the_published_cell() -> None:
    cell = str(loaders.get_map_layer_df(CASE)["cell_id"].iloc[0])
    context = loaders.get_cell_velocity_context(CASE, cell, {})
    assert context is not None
    assert context["cell_id"] == cell
    assert context["unit"] == C.VELOCITY_UNIT


# ---------------------------------------------------------------- B: tooltip risk
def test_map_tooltip_labels_risk_as_a_band_and_undefined_ratio_as_not_fitted() -> None:
    assert "Risk band {risk_band} (from |velocity|" in map_view._MAP_TOOLTIP_TEXT
    records = map_view._deck_records(
        pd.DataFrame(
            [
                {
                    "cell_id": "cell-a",
                    "delta_change": -1.0,
                    "unit": "mm",
                    "velocity_mm_yr": -5.0,
                    "velocity_unit": "mm/year",
                    "coherence": 0.5,
                    "regime": "elastic",
                    "ratio_R": None,
                    "seasonal_amp_mm": 0.0,
                    "risk_level": "estable",
                    "land_use": "urban-dense",
                    "color": [0, 0, 0, 255],
                    "height": 0.0,
                }
            ]
        ),
        extrude=False,
    )
    assert records[0]["ratio_text"] == "not fitted"
    assert records[0]["risk_band"] == "Stable"
    assert "ratio_text" in map_view._TOOLTIP_FIELDS


# ---------------------------------------------------------------- C: Tab 2 cards
def test_series_kpis_are_domain_values_not_ui_arithmetic() -> None:
    grid, meta = _grid(), _meta()
    kpis = loaders.get_series_kpis(CASE, {})
    above = threshold_counts(grid["velocity_mm_yr"], C.NULL_RESULT_MM_YR)
    coherent = threshold_counts(grid["coherence"], meta["thresholds"]["coherence_min"], absolute=False)
    by_label = {item["label"]: item for item in kpis}
    assert by_label["Cells above threshold"]["value"] == above.percentage
    assert by_label["Coherent coverage"]["value"] == coherent.percentage
    assert by_label["Critical cells"]["value"] == int((grid["risk_level"] == "critico").sum())


def test_velocity_distribution_hook_prefers_meta_stats_for_the_whole_case() -> None:
    meta = _meta()
    published = loaders.get_velocity_distribution(CASE, {})
    assert published["source"] == "meta.stats"
    assert published["p05_mm_yr"] == meta["stats"]["p05_velocity_mm_yr"]
    assert published["median_mm_yr"] == meta["stats"]["median_velocity_mm_yr"]
    assert published["p95_mm_yr"] == meta["stats"]["p95_velocity_mm_yr"]
    assert published["unit"] == C.VELOCITY_UNIT


def test_app_renders_one_distribution_line_in_tab_two() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["filter_case_id"] = CASE
    at.run()
    assert not at.exception
    stats = _meta()["stats"]
    lines = [str(item.value) for item in at.caption]
    matches = [
        line
        for line in lines
        if "Velocity distribution" in line and f"{stats['p05_velocity_mm_yr']:.2f}" in line
    ]
    assert len(matches) == 1, f"expected one distribution line, got {matches}"
    assert "meta.stats" in matches[0]


def test_app_inspector_shows_the_cell_position_once() -> None:
    cell = str(_grid()["cell_id"].iloc[0])
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["filter_case_id"] = CASE
    at.session_state["selected_cell_id"] = cell
    at.run()
    assert not at.exception
    markup = "\n".join(str(node.value) for node in at.markdown)
    assert markup.count("Provenance ID:") == 1
    assert markup.count("Position: ") == 1
    assert "p05 " in markup and "p95 " in markup


def test_coherence_bounds_are_domain_computed() -> None:
    grid = _grid()
    bounds = coherence_bounds(grid)
    assert bounds["min"] == float(grid["coherence"].min())
    assert bounds["max"] == float(grid["coherence"].max())
    assert loaders.get_coherence_summary(CASE, {})["min"] == bounds["min"]


def test_distance_summary_reports_no_classification() -> None:
    summary = distance_summary([{"distance_m": 10.0}, {"distance_m": 30.0}])
    assert summary == {
        "n_features": 2,
        "min_m": 10.0,
        "median_m": 20.0,
        "max_m": 30.0,
        "unit": "m",
    }
    assert not any("far" in str(value).lower() for value in summary.values())


def test_velocity_distribution_empty_view_is_not_fabricated() -> None:
    empty = velocity_distribution(pd.DataFrame(columns=["velocity_mm_yr"]), {})
    assert empty.p05_mm_yr is None and empty.median_mm_yr is None and empty.p95_mm_yr is None


# ---------------------------------------------------------------- D: velocity strip
def test_velocity_strip_draws_only_domain_values_and_the_selected_cell() -> None:
    distribution = loaders.get_velocity_distribution(CASE, {})
    figure = charts.velocity_strip_figure(
        distribution,
        {"velocity_mm_yr": distribution["median_mm_yr"], "provenance_id": "prov"},
    )
    assert figure.data, "expected the p05/p95 range to be drawn"
    names = {trace.name for trace in figure.data if trace.name}
    assert {"p05", "median", "p95", "Selected cell"}.issubset(names)
    xs = [float(trace.x[0]) for trace in figure.data if trace.x is not None and len(trace.x)]
    for key in ("p05_mm_yr", "median_mm_yr", "p95_mm_yr"):
        assert distribution[key] in xs
    assert figure.layout.height == charts.STRIP_HEIGHT


def test_velocity_strip_does_not_invent_a_range_when_stats_are_missing() -> None:
    figure = charts.velocity_strip_figure({"unit": "mm/year"}, None)
    assert not figure.data


def test_app_renders_a_velocity_strip_in_tab_two() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["filter_case_id"] = CASE
    at.run()
    assert not at.exception
    assert len(at.get("plotly_chart")) >= 2, "expected the series chart plus the velocity strip"


# ---------------------------------------------------------------- E: coherence + context counts
def test_context_row_counts_are_domain_computed() -> None:
    rows = [
        {"layer": "roads", "risk_level": "critico"},
        {"layer": "roads", "risk_level": "estable"},
        {"layer": "schools", "risk_level": "critico"},
        {},
    ]
    assert context_row_counts(rows) == {
        "layers": {"roads": 2, "schools": 1},
        "by_risk": {"critico": 2, "estable": 1},
    }
    assert loaders.summarize_context_rows(rows) == context_row_counts(rows)


def test_coherence_summary_has_no_unit_and_declares_the_floor() -> None:
    meta = _meta()
    summary = loaders.get_coherence_summary(CASE, {})
    assert summary["declared_min"] == meta["thresholds"]["coherence_min"]
    assert "unit" not in summary
    assert summary["provenance_id"]


# ---------------------------------------------------------------- F: segmented scale
def test_scale_control_is_segmented_and_preserves_the_default() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    scales = [control for control in at.segmented_control if control.label == "Scale"]
    assert len(scales) == 1, "scale must be one segmented control, not a radio group"
    assert scales[0].value == "independent"
    assert at.session_state["scale_mode"] == "independent"


def test_shared_scale_caption_appears_only_in_shared_mode() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["scale_mode"] = "shared"
    at.run()
    assert not at.exception
    captions = [str(item.value) for item in at.caption]
    assert any("Shared scale" in text for text in captions)


def test_segmented_control_css_targets_the_real_streamlit_dom() -> None:
    theme = (ROOT / "src" / "ui" / "theme.py").read_text(encoding="utf-8")
    assert '[data-variant="segmented_control"]' in theme
    assert '[data-testid="stSegmentedControl"]' not in theme
    assert "background: var(--bg) !important;" in theme


def test_client_toolbar_is_minimal_in_streamlit_config() -> None:
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "[client]" in config
    assert 'toolbarMode = "minimal"' in config


# ---------------------------------------------------------------- G: distances, no far class
def test_hazard_tab_reports_distances_without_a_far_classification() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["filter_case_id"] = CASE
    at.run()
    assert not at.exception
    text = "\n".join(str(node.value) for node in at.markdown)
    captions = "\n".join(str(node.value) for node in at.caption)
    for label in ("Minimum distance", "Median distance", "Maximum distance"):
        assert label in text
    assert "not classified" in captions
    summary = loaders.get_distance_summary(CASE, {})
    assert f"{summary['median_m']:g} m" in text
    # The distance caption must explicitly refuse a classification; no band label is emitted.
    distance_caption = [line for line in captions.splitlines() if "not classified" in line]
    assert distance_caption
    assert not re.search(r"\b(far|near)\b", " ".join(distance_caption), re.IGNORECASE)


def test_distance_summary_hook_has_no_threshold_key() -> None:
    summary = loaders.get_distance_summary(CASE, {})
    assert not any("threshold" in key.lower() or "far" in key.lower() for key in summary)


# ---------------------------------------------------------------- H: mobile telemetry
def test_header_has_a_compact_telemetry_chip_with_details() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    text = "\n".join(str(node.value) for node in at.markdown)
    assert 'class="telemetry-disclosure"' in text
    assert 'class="mission-chip telemetry-chip">Telemetry<' in text
    assert "telemetry-detail" in text
    theme = (ROOT / "src" / "ui" / "theme.py").read_text(encoding="utf-8")
    assert ".mission-bar .telemetry:not(.telemetry-detail)" in theme


# ---------------------------------------------------------------- I: 3D presentation
def test_extrusion_caption_uses_adapter_constants() -> None:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["filter_case_id"] = CASE
    at.session_state["filter_extrude_3d"] = True
    at.run()
    assert not at.exception
    captions = "\n".join(str(node.value) for node in at.caption)
    presentation = loaders.get_extrusion_presentation()
    assert "3D column height is presentation only" in captions
    assert f"baseline {presentation['baseline_m']:g} {presentation['unit']}" in captions


# ---------------------------------------------------------------- J: README §3
def test_readme_section_three_documents_the_new_controls() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## 3. Using the app", 1)[1].split("## 4.", 1)[0]
    lowered = section.lower()
    assert "segmented" in lowered
    assert "not fitted" in lowered
    assert "near/far" in lowered
    assert "compact chip" in lowered
