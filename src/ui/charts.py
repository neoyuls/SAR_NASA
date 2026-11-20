"""Series and land-use charts. No aggregations and no file reads.

Figure builders are pure (they return `go.Figure` and never touch Streamlit state) so
`tests/test_ui_smoke.py` can assert axis titles carry units without a live browser.
Chart procedure follows the `dataviz` skill: one Y axis, 2 px lines, >= 8 px markers,
`hovermode="x unified"` with value + unit + provenance_id, direct end labels and a
detection-limit reference line when the artefact declares one.
"""

from __future__ import annotations

import html
from typing import Any, Mapping

import plotly.graph_objects as go
import streamlit as st

from src.ui.formatters import (
    NOT_DECLARED,
    SOURCE_NOT_DECLARED,
    UNIT_NOT_DECLARED,
    format_number,
    humanize,
)
from src.ui.kpi_cards import render_kpi_cards
from src.ui.theme import active_palette, case_color, style_figure

CHART_HEIGHT = 280
THREE_CITIES_HEIGHT = 320
MARKER_SIZE = 8
LINE_WIDTH = 2


def _call(loaders: Any, name: str, *args: Any) -> Any:
    function = getattr(loaders, name, None)
    if function is None:
        return None
    return function(*args)


def _unit_of(rows: list[dict[str, Any]]) -> str | None:
    return next((row.get("unit") for row in rows if row.get("unit")), None)


def _prov_of(rows: list[dict[str, Any]]) -> str | None:
    return next((row.get("provenance_id") for row in rows if row.get("provenance_id")), None)


def _has_seasonal(rows: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(row.get("seasonal_mm"), (int, float)) and not isinstance(row.get("seasonal_mm"), bool)
        for row in rows
    )


def line_figure(series: list[dict[str, Any]], *, height: int = CHART_HEIGHT) -> go.Figure:
    """Cumulative displacement of the AOI series, with the fitted seasonal term."""
    palette = active_palette()
    unit = _unit_of(series) or UNIT_NOT_DECLARED
    provenance = _prov_of(series) or SOURCE_NOT_DECLARED
    dates = [row.get("date") for row in series]
    figure = go.Figure(
        go.Scatter(
            x=dates,
            y=[row.get("value") for row in series],
            name="Cumulative displacement",
            mode="lines+markers",
            line={"color": palette["accent"], "width": LINE_WIDTH},
            marker={"size": MARKER_SIZE},
            customdata=[provenance] * len(series),
            hovertemplate=f"%{{y:.2f}} {unit}<br>Provenance ID %{{customdata}}<extra></extra>",
        )
    )
    if _has_seasonal(series):
        figure.add_trace(
            go.Scatter(
                x=dates,
                y=[row.get("seasonal_mm") for row in series],
                name="Seasonal fit",
                mode="lines",
                line={"color": palette["coherence"], "width": LINE_WIDTH, "dash": "dash"},
                hoverinfo="skip",
            )
        )
    style_figure(
        figure,
        height=height,
        x_title="Date",
        y_title=f"Cumulative displacement ({unit})",
        margin={"l": 52, "r": 18, "t": 34, "b": 42},
    )
    figure.update_layout(
        hovermode="x unified",
        showlegend=_has_seasonal(series),
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    figure.update_xaxes(rangeslider={"visible": True, "thickness": 0.08})
    return figure


def three_cities_figure(
    series_by_case: Mapping[str, list[dict[str, Any]]],
    labels: Mapping[str, str] | None = None,
) -> go.Figure:
    """One line per case on one shared axis, fixed identity colors and end labels."""
    palette = active_palette()
    figure = go.Figure()
    unit = "mm"
    for case_id, rows in series_by_case.items():
        if not rows:
            continue
        unit = _unit_of(rows) or unit
        provenance = _prov_of(rows) or SOURCE_NOT_DECLARED
        label = str((labels or {}).get(case_id, case_id))
        figure.add_trace(
            go.Scatter(
                x=[row.get("date") for row in rows],
                y=[row.get("value") for row in rows],
                name=label,
                mode="lines",
                line={"color": case_color(case_id), "width": LINE_WIDTH},
                customdata=[provenance] * len(rows),
                hovertemplate=f"%{{y:.2f}} {unit}<br>Provenance ID %{{customdata}}<extra></extra>",
            )
        )
        # Direct label at the end of every line: identity never color-alone, and the
        # light-mode aqua (Malaga) is below 3:1, so its label is mandatory.
        figure.add_annotation(
            x=rows[-1].get("date"),
            y=rows[-1].get("value"),
            text=label,
            showarrow=False,
            xanchor="left",
            xshift=6,
            font={"color": palette["text"], "size": 11},
        )
    style_figure(
        figure,
        height=THREE_CITIES_HEIGHT,
        x_title="Date",
        y_title=f"Cumulative displacement ({unit})",
        margin={"l": 52, "r": 150, "t": 34, "b": 42},
    )
    figure.update_layout(
        hovermode="x unified",
        showlegend=len(series_by_case) > 1,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    return figure


def bars_figure(
    rows: list[dict[str, Any]],
    meta: Mapping[str, Any] | None = None,
) -> go.Figure:
    """Median velocity by land use. Reference line when a detection limit is declared."""
    palette = active_palette()
    unit = _unit_of(rows) or UNIT_NOT_DECLARED
    provenance = _prov_of(rows) or SOURCE_NOT_DECLARED
    figure = go.Figure(
        go.Bar(
            x=[humanize(row.get("land_use")) if row.get("land_use") else NOT_DECLARED for row in rows],
            y=[row.get("value") for row in rows],
            width=0.45,
            marker={"color": palette["accent"], "cornerradius": 4},
            customdata=[row.get("provenance_id") or provenance for row in rows],
            hovertemplate=f"%{{y:.2f}} {unit}<br>Provenance ID %{{customdata}}<extra></extra>",
        )
    )
    style_figure(
        figure,
        height=CHART_HEIGHT,
        x_title="Land use",
        y_title=f"Velocity ({unit})" if unit == "mm/year" else f"value ({unit})",
    )
    figure.update_layout(bargap=0.55)
    stats = meta.get("stats") if isinstance(meta, Mapping) else None
    limit = stats.get("detection_limit_mm_yr") if isinstance(stats, Mapping) else None
    if isinstance(limit, (int, float)) and not isinstance(limit, bool) and unit == "mm/year":
        for sign in (-1.0, 1.0):
            figure.add_shape(
                type="line",
                xref="paper",
                x0=0,
                x1=1,
                y0=sign * float(limit),
                y1=sign * float(limit),
                line={"color": palette["muted"], "width": 1, "dash": "dash"},
            )
        figure.add_annotation(
            xref="paper",
            x=1,
            xanchor="right",
            y=float(limit),
            yanchor="bottom",
            text=f"Detection limit {format_number(limit)} {unit}",
            showarrow=False,
            font={"color": palette["muted"], "size": 11},
        )
    return figure


STRIP_HEIGHT = 104


def velocity_strip_figure(
    distribution: Mapping[str, Any],
    cell: Mapping[str, Any] | None = None,
) -> go.Figure:
    """p05 — median — p95 on one labelled axis; the selected cell is a separate marker.

    Every x value comes from the domain hook; this function only draws them. The strip has
    no density or histogram: the artefacts do not publish a cell-density estimate.
    """
    palette = active_palette()
    unit = str(distribution.get("unit") or UNIT_NOT_DECLARED)
    provenance = str(distribution.get("provenance_id") or SOURCE_NOT_DECLARED)
    figure = go.Figure()
    p05 = distribution.get("p05_mm_yr")
    p95 = distribution.get("p95_mm_yr")
    if not isinstance(p05, (int, float)) or not isinstance(p95, (int, float)):
        return figure
    figure.add_trace(
        go.Scatter(
            x=[p05, p95],
            y=[0, 0],
            mode="lines",
            line={"color": palette["accent"], "width": 2},
            hoverinfo="skip",
        )
    )
    for key, label, color in (
        ("p05_mm_yr", "p05", palette["muted"]),
        ("median_mm_yr", "median", palette["coherence"]),
        ("p95_mm_yr", "p95", palette["muted"]),
    ):
        value = distribution.get(key)
        if isinstance(value, (int, float)):
            figure.add_trace(
                go.Scatter(
                    x=[value],
                    y=[0],
                    mode="markers",
                    name=label,
                    marker={"size": 9, "color": color},
                    hovertemplate=f"{label} %{{x:.2f}} {unit}<br>Provenance ID {provenance}<extra></extra>",
                )
            )
    if isinstance(cell, Mapping) and isinstance(cell.get("velocity_mm_yr"), (int, float)):
        figure.add_trace(
            go.Scatter(
                x=[cell["velocity_mm_yr"]],
                y=[0],
                mode="markers",
                name="Selected cell",
                marker={"size": 11, "color": palette["alert"], "symbol": "diamond"},
                hovertemplate=(
                    f"Selected cell %{{x:.2f}} {unit}<br>Provenance ID "
                    f"{html.escape(str(cell.get('provenance_id') or provenance))}<extra></extra>"
                ),
            )
        )
    style_figure(
        figure,
        height=STRIP_HEIGHT,
        x_title=f"Velocity ({unit})",
        y_title="",
        margin={"l": 52, "r": 18, "t": 20, "b": 34},
    )
    figure.update_layout(showlegend=True, legend={"orientation": "h", "y": 1.2, "x": 0})
    figure.update_yaxes(visible=False, fixedrange=True)
    figure.update_xaxes(fixedrange=True)
    return figure


def _line(series: list[dict[str, Any]] | None) -> None:
    if not series:
        st.caption("Series not declared by the backend.")
        return
    unit = _unit_of(series) or UNIT_NOT_DECLARED
    st.plotly_chart(line_figure(series), width="stretch", theme=None, config={"displayModeBar": False})
    trend = next(
        (
            row.get("trend_mm_yr")
            for row in series
            if isinstance(row.get("trend_mm_yr"), (int, float)) and not isinstance(row.get("trend_mm_yr"), bool)
        ),
        None,
    )
    trend_text = f" · Linear trend {format_number(trend)} mm/year" if trend is not None else ""
    scaled = any(row.get("scaled") for row in series)
    factor = next((row.get("scale_factor") for row in series if row.get("scaled")), None)
    scale_text = ""
    if scaled:
        factor_text = f" ×{factor:g}" if isinstance(factor, (int, float)) else ""
        scale_text = f" · scaled{factor_text} to the filtered subset"
    st.caption(f"Cumulative displacement · {unit}{trend_text}{scale_text}")


def _three_cities(loaders: Any) -> None:
    """Three cities on one shared axis, one fixed identity color per case."""
    cases = _call(loaders, "load_study_cases") or []
    labels = {str(item.get("id")): str(item.get("label") or item.get("id")) for item in cases}
    series_by_case: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id:
            continue
        frame = _call(loaders, "load_timeseries", case_id)
        rows = frame.to_dict(orient="records") if hasattr(frame, "to_dict") else []
        rows = [row for row in rows if row.get("date")]
        if rows:
            series_by_case[case_id] = rows
    if not series_by_case:
        st.caption("No case series declared by the backend.")
        return
    st.plotly_chart(
        three_cities_figure(series_by_case, labels),
        width="stretch",
        theme=None,
        config={"displayModeBar": False},
    )
    st.caption(
        "Three cities, shared axis · Cumulative displacement (mm) · "
        "case provenance is listed in Provenance and limits."
    )


def _bars(rows: list[dict[str, Any]] | None, meta: Mapping[str, Any] | None = None) -> None:
    if not rows:
        st.caption("Land-use bars not declared by the backend.")
        return
    unit = _unit_of(rows) or UNIT_NOT_DECLARED
    st.plotly_chart(
        bars_figure(rows, meta),
        width="stretch",
        theme=None,
        config={"displayModeBar": False},
    )
    st.caption(f"Velocity by land use · {unit}")


def render_series_tab(filters: dict[str, Any], loaders: Any, meta: dict[str, Any] | None) -> None:
    # The persistent demo banner lives in app.py; do not duplicate it per tab.
    case_id = filters.get("case_id")
    render_kpi_cards(_call(loaders, "get_series_kpis", case_id, filters))
    # The five cards above are computed in src.domain.metrics. This line is the whole-case
    # distribution the artefact publishes in meta.stats (or the filtered view's own quantiles).
    distribution = _call(loaders, "get_velocity_distribution", case_id, filters)
    if isinstance(distribution, dict):
        unit = distribution.get("unit") or UNIT_NOT_DECLARED
        quantiles = " … ".join(
            f"{name} {format_number(distribution.get(key))}"
            for name, key in (
                ("p05", "p05_mm_yr"),
                ("median", "median_mm_yr"),
                ("p95", "p95_mm_yr"),
            )
            if distribution.get(key) is not None
        )
        if quantiles:
            st.caption(
                f"Velocity distribution · {quantiles} {unit} · "
                f"{distribution.get('n_cells')} cells · {distribution.get('source')}"
            )
    area_series = _call(loaders, "get_case_series", case_id, filters)
    selected_cell = st.session_state.get("selected_cell_id")
    detail = (
        _call(loaders, "get_cell_detail", str(case_id), str(selected_cell))
        if selected_cell and case_id
        else None
    )
    if isinstance(distribution, dict) and distribution.get("p05_mm_yr") is not None:
        figure = velocity_strip_figure(distribution, detail if isinstance(detail, dict) else None)
        if figure.data:
            st.plotly_chart(
                figure,
                width="stretch",
                theme=None,
                config={"displayModeBar": False},
            )
    cell_series = detail.get("series") if isinstance(detail, dict) else None
    cell_scope = detail.get("series_scope") if isinstance(detail, dict) else None
    if isinstance(cell_series, list) and cell_series and cell_scope == "cell":
        st.toggle(
            "Compare selected cell with whole-area aggregate",
            key=f"compare-cell-series-{case_id}",
            help="Show both series in separate panels, each with its own labelled axis.",
        )
        if st.session_state.get(f"compare-cell-series-{case_id}") and area_series:
            cell_col, area_col = st.columns(2)
            with cell_col:
                st.caption(f"Selected H3 cell {selected_cell}")
                _line(cell_series)
            with area_col:
                st.caption("Whole-area aggregate")
                _line(area_series)
        else:
            st.caption(f"Selected H3 cell {selected_cell}")
            _line(cell_series)
    else:
        _line(area_series)
        if selected_cell and isinstance(detail, dict) and cell_scope == "aoi":
            st.caption(
                f"Selected H3 cell {selected_cell} has no per-cell series; "
                "showing the whole-area aggregate."
            )
    _three_cities(loaders)
    _bars(_call(loaders, "get_land_use_bars", case_id, filters), meta)
