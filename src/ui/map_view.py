"""Thin map presentation. No file reads and no geospatial calculations.

Colors, height, view and cell detail come from the loaders. This module only
draws them.
"""

from __future__ import annotations

import csv
import html
import json
import re
from io import StringIO
from typing import Any, Callable

import pydeck as pdk
import streamlit as st

from src.ui.color_scale import FALLBACK_DOMAIN, color_for
from src.ui.components import empty_state
from src.ui.formatters import (
    NOT_DECLARED,
    NOT_FITTED,
    SCALE_LABELS,
    UNIT_NOT_DECLARED,
    format_number,
    humanize,
    is_shared_scale,
    risk_label,
)
from src.ui.theme import MAP_RAMPS, MAP_RAMP_LABELS, active_palette, map_ramp, reported_scheme, style_figure

LAYER_ID = "h3-cells"
MAP_HEIGHT = 560
ROW_WARN = 50_000
SELECT_PROMPT = "Select a cell"
EMPTY_HINT = "Pick a cell on the map or in the list."
SATURATION_NOTE = "Values outside the range are saturated."
LIMIT_MISSING = "detection limit not available"
# Reading panel: the series is the hero of the right column (plan Fase 1).
# 225 px keeps the whole figure above the fold at 1440x900 with the filters open.
HERO_HEIGHT = 225
HERO_MIN_HEIGHT = 420

_RISK_CLASS = {
    "critico": "chip chip-coral",
    "moderado": "chip chip-alert",
    "estable": "chip",
}
# Presentation strokes only. Not a risk scale. Unknown layers fall back to muted.
_CONTEXT_ROLE = {
    "land_use": "accent",
    "water": "coherence",
    "infrastructure": "alert",
    "admin_boundary": "muted",
}


def detection_caption(above_limit: bool | None, limit: Any, unit: str | None) -> str | None:
    """Format the control message. Does not decide the science."""
    if above_limit is not False:
        return None
    if isinstance(limit, bool) or not isinstance(limit, (int, float)):
        return LIMIT_MISSING
    return "No detectable signal above the detection limit (the neutral band above)"


def _lower_coherence_filter() -> None:
    """One-click exploration aid; never alters the declared backend threshold."""
    floor = st.session_state.get("filter_coherence_floor")
    current = st.session_state.get("filter_coherence_min", floor)
    floor_value = float(floor) if isinstance(floor, (int, float)) and 0 <= floor <= 1 else 0.0
    current_value = float(current) if isinstance(current, (int, float)) else floor_value
    st.session_state.filter_coherence_min = floor_value if current_value > floor_value else 0.0


def _reset_map_filters() -> None:
    st.session_state.filter_land_use = ""
    st.session_state.filter_risk_level = ""
    st.session_state.filter_extrude_3d = False
    floor = st.session_state.get("filter_coherence_floor")
    if isinstance(floor, (int, float)) and 0.0 <= floor <= 1.0:
        st.session_state.filter_coherence_min = float(floor)


def _limit_from_meta(meta: dict[str, Any] | None) -> tuple[Any, str | None]:
    if not isinstance(meta, dict):
        return None, None
    stats = meta.get("stats")
    if not isinstance(stats, dict):
        return None, None
    for key, value in stats.items():
        if key.startswith("detection_limit") and isinstance(value, (int, float)) and not isinstance(value, bool):
            unit = "mm/year" if key.endswith("_mm_yr") else meta.get("unit")
            return value, str(unit) if unit else None
    return None, None


def _call(loaders: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    function = getattr(loaders, name, None)
    if function is None:
        return None
    try:
        return function(*args, **kwargs)
    except TypeError:
        if kwargs:
            return function(*args)
        return None


def _selected_cell(state: Any) -> str | None:
    selection = getattr(state, "selection", None)
    if selection is None:
        return None
    objects = selection["objects"] if "objects" in selection else {}
    rows = objects.get(LAYER_ID) if isinstance(objects, dict) else None
    if not rows:
        return None
    cell_id = rows[0].get("cell_id")
    return str(cell_id) if cell_id else None


def _scale(loaders: Any, case_id: str, filters: dict[str, Any]) -> dict[str, Any]:
    scale = _call(loaders, "get_color_scale", case_id, filters)
    if isinstance(scale, dict) and "min" in scale and "max" in scale:
        return scale
    # TODO(contract): single fallback until the backend publishes the domain.
    return {
        "min": FALLBACK_DOMAIN[0],
        "max": FALLBACK_DOMAIN[1],
        "unit": None,
        "saturated": False,
        "fallback": True,
    }


def _legend_inline(scale: dict[str, Any], mode: str, ramp: str = "classic") -> str:
    """One-row ramp for the reading panel: label+unit, gradient, range.

    The scale mode is already visible in the radio above the map, and the adapter
    caption / saturation note live in the "Case comparison and context" expander.
    """
    vmin = scale.get("min")
    vmax = scale.get("max")
    unit = scale.get("unit") or UNIT_NOT_DECLARED
    metric = scale.get("metric") or "delta_change"
    chosen_stops = map_ramp(ramp, reported_scheme())
    gradient = ", ".join(
        f"rgb({red}, {green}, {blue})" for _, (red, green, blue, _alpha) in chosen_stops
    )
    if isinstance(vmin, (int, float)) and isinstance(vmax, (int, float)):
        span = f"{format_number(vmin, 1)} … {format_number(vmax, 1)}"
    else:
        span = ""
    flag = '<span class="legend-flag">saturated</span>' if scale.get("saturated") else ""
    return (
        '<div class="cockpit-card legend-inline">'
        f'<span class="legend-inline-label">{html.escape(humanize(metric))} · {html.escape(str(unit))}</span>'
        f'<div class="legend-bar" style="background: linear-gradient(90deg, {gradient})"></div>'
        f'<span class="legend-inline-range">{html.escape(span)}</span>'
        f"{flag}"
        "</div>"
    )


def _legend_details(scale: dict[str, Any], counts_text: str) -> str:
    """Scale note for the expander: origin + neutral band, saturation and counts."""
    caption = _scale_caption(scale)
    parts = [f'<p class="legend-meta">{html.escape(caption)}</p>'] if caption else []
    if scale.get("saturated"):
        parts.append(f'<p class="legend-meta">{html.escape(SATURATION_NOTE)}</p>')
    if counts_text:
        parts.append(f'<p class="legend-meta">{html.escape(counts_text)}</p>')
    return '<div class="legend-details">' + "".join(parts) + "</div>"


def _provenance(meta: dict[str, Any] | None) -> tuple[str, str]:
    """(source, provenance_id) of the case. Sensor/product/unit/dates live in the header."""
    if not isinstance(meta, dict):
        return NOT_DECLARED, NOT_DECLARED
    provenance = meta.get("provenance") if isinstance(meta.get("provenance"), dict) else {}
    source = provenance.get("source") or meta.get("source") or NOT_DECLARED
    provenance_id = meta.get("provenance_id") or provenance.get("provenance_id") or NOT_DECLARED
    return str(source), str(provenance_id)


def _scale_caption(scale: dict[str, Any]) -> str:
    """Trim the adapter caption to what the ramp does not already say.

    The gradient and its ticks are the single representation of the domain, so the
    prose keeps only the origin (p05/p95) and the neutral band.
    """
    caption = str(scale.get("caption") or "").replace("meta.stats ", "").strip()
    if not caption:
        if scale.get("fallback"):
            unit = scale.get("unit") or UNIT_NOT_DECLARED
            return (
                f"Provisional domain [{format_number(scale.get('min'), 1)}, "
                f"{format_number(scale.get('max'), 1)}] {unit}."
            )
        return ""
    band = re.search(r"neutral band ±([\d.]+)\s*([a-zA-Z/]+)", caption)
    parts: list[str] = []
    if "p05" in caption:
        parts.append("Domain seeded from p05/p95.")
    if band:
        parts.append(f"Neutral band ±{band.group(1)} {band.group(2)}.")
    return " ".join(parts) if parts else caption


def _figure_line(
    label: str,
    value: Any,
    unit: str | None,
    *,
    dimensionless: bool = False,
) -> str:
    """One inspector row. The source is printed once per group, not per line."""
    if value in (None, ""):
        return f"{label}: {NOT_DECLARED}"
    number = format_number(value)
    if dimensionless:
        unit_text = ""
    else:
        unit_text = f" {unit}" if unit else f" ({UNIT_NOT_DECLARED})"
    return f"{label}: {number}{unit_text}"


def _series_csv(rows: list[dict[str, Any]]) -> str:
    """Serialize emitted per-cell series as-is; this is not a fit or aggregation."""
    if not rows:
        return ""
    fields = list(dict.fromkeys(key for row in rows for key in row))
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _risk_hint(value: str) -> str:
    return f"Risk band: {risk_label(value)} (from |velocity|, not a separate measurement)."


def _candidate_cells(frame: Any, current: str | None, limit: int = 25) -> list[str]:
    """Return top cells from the active map frame for the manual backup selector."""
    if frame is None or not hasattr(frame, "columns") or "cell_id" not in frame.columns or len(frame) == 0:
        return [current] if current else []
    metric_col = "velocity_mm_yr" if "velocity_mm_yr" in frame.columns else (
        "delta_change" if "delta_change" in frame.columns else None
    )
    if metric_col is not None:
        ordered = frame.assign(_mag=frame[metric_col].abs()).sort_values("_mag", ascending=False)
    else:
        ordered = frame
    cells = [str(cid) for cid in ordered["cell_id"].head(limit).tolist() if cid]
    if current and current not in cells:
        cells.insert(0, str(current))
    return cells


def _hex_rgba(value: str, alpha: int = 180) -> list[int]:
    color = value.lstrip("#")
    return [int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), alpha]


def _context_groups(geojson: dict[str, Any] | None) -> list[tuple[str, str, dict[str, Any]]]:
    """Split delivered features by `layer`. Does not invent a missing layer."""
    if not isinstance(geojson, dict):
        return []
    features = geojson.get("features")
    if not isinstance(features, list):
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        layer = str(props.get("layer") or "")
        if not layer:
            continue
        grouped.setdefault(layer, []).append(feature)
    palette = active_palette()
    groups: list[tuple[str, str, dict[str, Any]]] = []
    for layer, rows in grouped.items():
        role = _CONTEXT_ROLE.get(layer, "muted")
        color = str(palette.get(role, palette["muted"]))
        groups.append((layer, color, {"type": "FeatureCollection", "features": rows}))
    return groups


def _artefact_omits_cell_series(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    stats = meta.get("stats")
    block = stats.get("per_cell_series") if isinstance(stats, dict) else None
    return isinstance(block, dict) and block.get("enabled") is False


def _coord_line(label: str, value: Any) -> str:
    if value in (None, ""):
        return f"{label}: {NOT_DECLARED}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{label}: {value:.5f} deg"
    return f"{label}: {value}"


def _stats_strip(items: list[tuple[Any, Any, Any]]) -> None:
    """Three key figures under the hero series: value, unit, label."""
    cells = []
    for label, value, unit in items:
        shown = NOT_DECLARED if value in (None, "") else format_number(value)
        unit_text = f'<span class="stat-unit"> {html.escape(str(unit))}</span>' if unit else ""
        cells.append(
            '<div class="reading-stat">'
            f'<span class="stat-value">{html.escape(shown)}{unit_text}</span>'
            f'<span class="stat-label">{html.escape(str(label))}</span>'
            "</div>"
        )
    st.markdown(
        f'<div class="cockpit-card reading-stats">{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )


def _inspector_groups(
    detail: dict[str, Any],
    case_id: str | None,
    context: dict[str, Any] | None = None,
) -> None:
    """Grouped cell read-out: Deformation, Quality, Provenance (compact, 3–4 lines each)."""
    risk = str(detail.get("risk_level") or "")
    unit = detail.get("unit") if isinstance(detail.get("unit"), str) else None
    seasonal = detail.get("seasonal_amp_mm")
    lat, lon = detail.get("lat"), detail.get("lon")
    coords = (
        f"{lat:.5f}, {lon:.5f} deg"
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float))
        else NOT_DECLARED
    )
    groups: list[tuple[str, list[str]]] = [
        (
            "Deformation",
            [
                _figure_line("Displacement change", detail.get("delta_change"), unit),
                # Rol 3: positive is toward the sensor, which reads as uplift here.
                "Positive = toward the sensor (uplift); not GNSS-validated.",
            ],
        ),
        (
            "Quality",
            [
                f"Regime: {humanize(detail.get('regime')) if detail.get('regime') else NOT_DECLARED}",
                _figure_line("Seasonal amplitude", seasonal, unit),
                _risk_hint(risk),
            ],
        ),
    ]
    if isinstance(context, dict) and context:
        p05, median, p95 = (
            context.get("p05_mm_yr"),
            context.get("median_mm_yr"),
            context.get("p95_mm_yr"),
        )
        position = context.get("position")
        percentiles = " · ".join(
            f"{name} {format_number(value)}"
            for name, value in (("p05", p05), ("median", median), ("p95", p95))
            if value is not None
        )
        groups.append(
            (
                "Distribution",
                [
                    f"Position: {humanize(position) if position else NOT_DECLARED}",
                    f"{percentiles} {unit or UNIT_NOT_DECLARED}" if percentiles else NOT_DECLARED,
                    f"Population: {context.get('n_cells')} cells · {context.get('source') or NOT_DECLARED}",
                ],
            )
        )
    groups.extend([
        (
            "Provenance",
            [
                f"{coords} · {humanize(detail.get('land_use')) if detail.get('land_use') else NOT_DECLARED}",
                f"{detail.get('product') or NOT_DECLARED} · {detail.get('sensor') or NOT_DECLARED} · "
                f"{detail.get('case_id') or case_id or NOT_DECLARED}",
                f"Provenance ID: {detail.get('provenance_id') or NOT_DECLARED}",
            ],
        ),
    ])
    body = "".join(
        f'<p class="detail-head">{html.escape(heading)}</p>'
        + "".join(f'<p class="detail-line">{html.escape(line)}</p>' for line in lines)
        for heading, lines in groups
    )
    st.markdown(f'<div class="cockpit-card inspector">{body}</div>', unsafe_allow_html=True)


def _reading_panel(
    detail: dict[str, Any] | None,
    case_id: str | None,
    meta: dict[str, Any] | None,
    loaders: Any,
    filters: dict[str, Any],
) -> None:
    """Right column: selector state → title → series (hero) → 3 figures → grouped read-out."""
    risk = str((detail or {}).get("risk_level") or "")
    chip = (
        f'<span class="{_RISK_CLASS.get(risk, "chip chip-muted")}">{html.escape(risk_label(risk))}</span>'
        if detail
        else ""
    )
    title = str(detail.get("cell_id")) if detail else "Whole area"
    kicker = f"{detail.get('case_id') or case_id}" if detail else "No cell selected"
    hint = "" if detail else f'<p class="kpi-note">{html.escape(EMPTY_HINT)}</p>'
    st.markdown(
        '<div class="cockpit-card reading-head">'
        f'<p class="kicker">{html.escape(str(kicker))}</p>'
        f'<p class="reading-title">{html.escape(title)} {chip}</p>'
        f"{hint}</div>",
        unsafe_allow_html=True,
    )

    series = detail.get("series") if isinstance(detail, dict) else None
    scope = str(detail.get("series_scope") or "cell") if detail else "aoi"
    if not isinstance(series, list) or not series:
        series = _call(loaders, "get_case_series", case_id, filters) or []
        scope = "aoi"
    if series:
        _render_series(series, scope, meta, height=HERO_HEIGHT, selected=bool(detail))
    else:
        st.caption("Series not declared by the backend.")

    if detail:
        seasonal = detail.get("seasonal_amp_mm")
        ratio = detail.get("ratio_R")
        ratio_value: Any = ratio
        if ratio is None and isinstance(seasonal, (int, float)) and not isinstance(seasonal, bool) and seasonal == 0:
            ratio_value = NOT_FITTED
        _stats_strip(
            [
                ("Velocity", detail.get("velocity_mm_yr"), detail.get("velocity_unit") or "mm/year"),
                ("Coherence", detail.get("coherence"), None),
                ("Ratio R", ratio_value, None),
            ]
        )
        context = _call(
            loaders,
            "get_cell_velocity_context",
            case_id,
            str(detail.get("cell_id")),
            filters,
        )
        _inspector_groups(detail, case_id, context if isinstance(context, dict) else None)
        export = _call(loaders, "get_cell_export", str(case_id), str(detail.get("cell_id")))
        if isinstance(export, dict) and export:
            st.download_button(
                "Export selected cell (JSON)",
                data=json.dumps(export, ensure_ascii=False, indent=2, default=str),
                file_name=f"{case_id}_{detail.get('cell_id')}.json",
                mime="application/json",
                key=f"export-cell-{case_id}",
            )
        if scope == "cell" and isinstance(series, list) and series:
            st.download_button(
                "Export selected cell series (CSV)",
                data=_series_csv(series),
                file_name=f"{case_id}_{detail.get('cell_id')}_timeseries.csv",
                mime="text/csv",
                key=f"export-cell-series-{case_id}",
                help="Exports the per-cell series emitted by this artefact.",
            )
    else:
        kpis = _call(loaders, "get_map_kpis", case_id, filters) or []
        stats = [
            (item.get("label"), item.get("value"), item.get("unit"))
            for item in kpis[:3]
            if isinstance(item, dict)
        ]
        if stats:
            # Different scope from the series above: say it before the numbers.
            st.caption("Grid statistics for the current filter (not the aggregate series above).")
            _stats_strip(stats)


def _series_figure(series: list[dict[str, Any]], height: int) -> Any:
    """Build the displacement series figure. One Y axis, 2 px line, 8 px markers."""
    import plotly.graph_objects as go

    dates = [row.get("date") for row in series if row.get("date")]
    values = [row.get("value") for row in series if row.get("date")]
    unit = next((row.get("unit") for row in series if row.get("unit")), None)
    figure = go.Figure(
        go.Scatter(
            x=dates,
            y=values,
            mode="lines+markers",
            line={"color": active_palette()["accent"], "width": 2},
            marker={"size": 8},
        )
    )
    style_figure(
        figure,
        height=height,
        x_title="Date",
        y_title=f"Cumulative displacement ({unit})" if unit else f"Cumulative displacement ({UNIT_NOT_DECLARED})",
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
    )
    return figure


def _render_series(
    series: list[dict[str, Any]],
    scope: str = "cell",
    meta: dict[str, Any] | None = None,
    *,
    height: int = HERO_HEIGHT,
    selected: bool = True,
) -> None:
    st.plotly_chart(_series_figure(series, height), width="stretch", theme=None, config={"displayModeBar": False})
    if not selected:
        st.caption("Whole-area aggregate series")
        return
    if scope == "aoi":
        note = "This H3 cell has no series of its own; showing the area aggregate"
        if _artefact_omits_cell_series(meta):
            note += " (the artefact does not emit per-cell series)"
        st.caption(note)
        return
    st.caption("Cell series")


def _render_comparison(
    report: dict[str, Any] | None,
    mode: str,
    case_labels: dict[str, str] | None = None,
) -> None:
    if not isinstance(report, dict) or not report.get("cases"):
        return
    shared = is_shared_scale(mode)
    if shared and report.get("mixed_units"):
        st.markdown(
            '<div class="null-note">Notice: the shared scale combines distinct declared units. '
            "mm is not converted to a rate. The smaller-magnitude case sits at the end of the scale: "
            "that is the scale result, not a failure.</div>",
            unsafe_allow_html=True,
        )
    # The declaration comes from `get_scale_comparison`; this only makes it visible.
    for flag, field, what in (
        ("mixed_sensors", "sensors", "sensors"),
        ("mixed_products", "products", "SAR products"),
    ):
        values = report.get(field) or []
        if report.get(flag) and values:
            joined = ", ".join(html.escape(str(value)) for value in values)
            st.markdown(
                f'<div class="null-note">Notice: these cases mix declared {what} '
                f"({joined}). Nothing is converted or pooled: each peak keeps the unit and "
                "provenance of its own artefact.</div>",
                unsafe_allow_html=True,
            )
    rows = []
    for item in report["cases"]:
        unit = item.get("unit") or UNIT_NOT_DECLARED
        peak = item.get("peak")
        peak_text = format_number(peak) if isinstance(peak, (int, float)) else NOT_DECLARED
        case_id = str(item.get("id") or "")
        case_name = (case_labels or {}).get(case_id, case_id)
        # In per-case mode `share` is 1.0 for every case, so a bar would read as
        # "same magnitude". Only the shared scale makes the length meaningful.
        if shared:
            share = float(item.get("share") or 0)
            width = 4 if share < 0.05 else max(4, int(share * 100))
            track = (
                '<div class="compare-track">'
                f'<div class="compare-fill" style="width:{width}%"></div></div>'
            )
        else:
            track = ""
        rows.append(
            '<div class="compare-row">'
            f'<span class="compare-case">{html.escape(case_name)}</span>'
            f"{track}"
            f'<span class="compare-meta">{html.escape(peak_text)} {html.escape(str(unit))}</span>'
            "</div>"
        )
    note = (
        '<p class="kpi-note">Peak |velocity| per case. '
        + (
            "Bars share one scale, so their length is comparable."
            if shared
            else "Each case is on its own scale: bars are omitted, compare the numbers."
        )
        + " Case provenance lives in the Provenance and limits tab.</p>"
    )
    st.markdown(
        '<div class="cockpit-card compare-card">'
        '<p class="kicker">Relative magnitude across cases</p>'
        f"{note}{''.join(rows)}"
        "</div>",
        unsafe_allow_html=True,
    )


def _context_legend(groups: list[tuple[str, str, dict[str, Any]]]) -> str:
    if not groups:
        return ""
    rows = "".join(
        '<p class="detail-line">'
        f'<span class="swatch" style="background:{html.escape(color)}"></span>'
        f"{html.escape(humanize(layer))}</p>"
        for layer, color, _payload in groups
    )
    return (
        '<div class="cockpit-card">'
        '<p class="kicker">Context strokes</p>'
        '<p class="kpi-note">Stroke color is presentation only. It is not a risk class.</p>'
        f"{rows}</div>"
    )


# Every `{field}` the hover card prints. The deck used to ship the whole frame — ~21 columns per cell —
# for 11 600 H3 cells, so most of several megabytes of payload was columns no consumer reads.
_MAP_TOOLTIP_TEXT = (
    "Cell {cell_id}\n"
    "Displacement {delta_change} {unit}\n"
    "Velocity {velocity_mm_yr} {velocity_unit}\n"
    "Coherence {coherence}\n"
    "Regime {regime_label}\n"
    "Ratio R {ratio_text}\n"
    "Risk band {risk_band} (from |velocity|, not a measurement)\n"
    "Land use {land_use_label}"
)
_TOOLTIP_FIELDS = frozenset(re.findall(r"\{(\w+)\}", _MAP_TOOLTIP_TEXT))
_LAYER_FIELDS = frozenset({"cell_id", "color", "height"})
_DECK_FIELDS = _TOOLTIP_FIELDS | _LAYER_FIELDS


def _deck_records(frame: Any, extrude: bool) -> list[dict[str, Any]]:
    """Rows for the H3 layer: exactly the fields the layer draws and the tooltip reads.

    `_DECK_FIELDS` is derived from `_MAP_TOOLTIP_TEXT`, so adding a placeholder to the hover card
    cannot silently start reading a field the record no longer carries.
    """
    if frame is None or not hasattr(frame, "to_dict"):
        return []
    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        record = {field: row.get(field) for field in sorted(_DECK_FIELDS)}
        # Display-only labels for the hover card; the stored enum is untouched.
        record["risk_band"] = risk_label(row.get("risk_level"))
        record["land_use_label"] = humanize(row.get("land_use")) if row.get("land_use") else NOT_DECLARED
        record["regime_label"] = humanize(row.get("regime")) if row.get("regime") else NOT_DECLARED
        ratio = row.get("ratio_R")
        amplitude = row.get("seasonal_amp_mm")
        # A null ratio with a zero amplitude is the contract's "not fitted" state.
        record["ratio_text"] = (
            NOT_FITTED
            if ratio is None
            or (isinstance(ratio, float) and ratio != ratio)
            or (isinstance(amplitude, (int, float)) and amplitude == 0)
            else format_number(ratio)
        )
        # Flat mode must not keep loader heights: non-zero elevation still
        # produces z-fighting that reads as overlapping hexes.
        record["height"] = record.get("height") if extrude else 0
        records.append(record)
    return records


def _render_deck(
    frame: Any,
    active: dict[str, Any],
    view: dict[str, Any],
    context_groups: list[tuple[str, str, dict[str, Any]]],
    case_id: Any,
    scale: dict[str, Any] | None = None,
    ramp: str = "classic",
    alt_text: str | None = None,
    ignore_pick: bool = False,
    source_id: str | None = None,
) -> None:
    """Draw the H3 deck and sync the picked cell into session state."""
    extrude = bool(active.get("extrude_3d"))
    records = _deck_records(frame, extrude)
    if ramp in MAP_RAMPS and ramp != "classic" and scale:
        metric = str(scale.get("metric") or "velocity_mm_yr")
        vmin, vmax = scale.get("min"), scale.get("max")
        raw_rows = frame.to_dict(orient="records") if frame is not None and hasattr(frame, "to_dict") else []
        if (
            isinstance(vmin, (int, float))
            and isinstance(vmax, (int, float))
            and len(raw_rows) == len(records)
        ):
            for record, row in zip(records, raw_rows):
                record["color"] = color_for(
                    row.get(metric),
                    float(vmin),
                    float(vmax),
                    map_ramp(ramp, reported_scheme()),
                )
    layer = pdk.Layer(
        "H3HexagonLayer",
        data=records,
        id=LAYER_ID,
        get_hexagon="cell_id",
        get_fill_color="color",
        get_elevation="height",
        pickable=True,
        auto_highlight=True,
        extruded=extrude,
        elevation_scale=1 if extrude else 0,
        coverage=1.0,
        # A 1 px boundary in the theme's text ink keeps each cell's shape at >= 3:1
        # against both basemaps, including the pale mid-ramp as seen on light tiles.
        stroked=True,
        get_line_color=_hex_rgba(active_palette()["border-strong"], 200),
        line_width_min_pixels=1,
    )
    layers = [layer]
    for layer_name, color, collection in context_groups:
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                data=collection,
                id=f"context-{layer_name}",
                pickable=False,
                stroked=True,
                filled=False,
                get_line_color=_hex_rgba(color),
                get_line_width=20,
                line_width_min_pixels=1,
                point_radius_min_pixels=4,
            )
        )
    # Selected cell: a stroked outline on top, never a second color ramp.
    selected = st.session_state.get("selected_cell_id")
    highlighted = [
        row for row in records if selected and str(row.get("cell_id")) == str(selected)
    ]
    if highlighted:
        layers.append(
            pdk.Layer(
                "H3HexagonLayer",
                data=highlighted,
                id="h3-selected",
                get_hexagon="cell_id",
                filled=False,
                stroked=True,
                extruded=False,
                elevation_scale=0,
                get_line_color=_hex_rgba(active_palette()["accent"], 255),
                line_width_min_pixels=3,
                pickable=False,
            )
        )
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=view["latitude"],
            longitude=view["longitude"],
            # Camera only: one step closer than the loader default so the
            # published cells fill the viewport. Not a geospatial value.
            zoom=float(view["zoom"]) + 1.0 if isinstance(view["zoom"], (int, float)) else view["zoom"],
            pitch=40 if extrude else 0,
            bearing=0,
        ),
        map_provider="carto",
        map_style="light" if reported_scheme() == "light" else "dark",
        tooltip={"text": _MAP_TOOLTIP_TEXT},
    )
    with st.container(key="map-slot", border=False):
        event = st.pydeck_chart(
            deck,
            height=MAP_HEIGHT,
            width="stretch",
            on_select="rerun",
            selection_mode="single-object",
            alt=alt_text or "H3 velocity map; demonstration data. Select a cell to inspect its attributes.",
            # Remount when the case changes so initial_view_state applies
            # and the previous AOI layer cannot linger on top.
            key=f"h3-map-{case_id}",
        )
    picked = _selected_cell(event)
    selector_key = f"inspector_cell_{case_id}"
    st.session_state._map_case = case_id
    if picked and not ignore_pick:
        current = st.session_state.get("selected_cell_id")
        if str(picked) != str(current or ""):
            st.session_state.selected_cell_id = picked
            st.session_state[selector_key] = picked
            st.session_state._last_h3_selector = picked
            # The first pass receives the click event. Rerun this fragment once
            # so the selected outline is present in the deck sent back to deck.gl.
            st.rerun(scope="fragment")
        st.session_state.selected_cell_id = picked
        st.session_state[selector_key] = picked
        st.session_state._last_h3_selector = picked


def render_map_tab(
    filters: dict[str, Any],
    loaders: Any,
    meta: dict[str, Any] | None,
    case_labels: dict[str, str] | None = None,
    *,
    share_url: str | Callable[[], str] | None = None,
) -> None:
    case_id = filters.get("case_id")
    selector_key = f"inspector_cell_{case_id}"
    ignore_map_pick = False
    if st.session_state.pop("_clear_cell_request", False):
        st.session_state.selected_cell_id = None
        st.session_state[selector_key] = ""
        st.session_state._last_h3_selector = ""
        ignore_map_pick = True
    previous_case = st.session_state.get("_map_case")
    if previous_case is not None and previous_case != case_id:
        st.session_state.selected_cell_id = None
        st.session_state[selector_key] = ""
        st.session_state._last_h3_selector = ""
        ignore_map_pick = True
    if selector_key not in st.session_state and st.session_state.get("selected_cell_id"):
        st.session_state[selector_key] = st.session_state.selected_cell_id
    if selector_key in st.session_state:
        selector_value = st.session_state.get(selector_key) or None
        last_selector_value = st.session_state.get("_last_h3_selector", selector_value) or None
        if selector_value != last_selector_value:
            st.session_state.selected_cell_id = selector_value
            ignore_map_pick = True
        st.session_state._last_h3_selector = selector_value or ""
    current_cell = st.session_state.get("selected_cell_id")
    if current_cell:
        initial_detail = _call(loaders, "get_cell_detail", case_id, str(current_cell))
        if not isinstance(initial_detail, dict) or not initial_detail:
            current_cell = None
            st.session_state.selected_cell_id = None
            st.session_state[selector_key] = ""
            st.session_state._last_h3_selector = ""
            ignore_map_pick = True
    # The scale control lives above the columns (presentation-only); validate the
    # seeded value so a bad URL cannot pick an unknown mode.
    if st.session_state.get("scale_mode") not in SCALE_LABELS:
        st.session_state.scale_mode = "independent"
    # Streamlit 1.67: a segmented control keeps the same key and default as the old
    # radio, but reads as one control rather than two independent radio groups.
    mode = st.segmented_control(
        "Scale",
        list(SCALE_LABELS),
        format_func=lambda key: SCALE_LABELS[key],
        key="scale_mode",
        label_visibility="collapsed",
        width="stretch",
    )
    if mode not in SCALE_LABELS:
        mode = "independent"
    if st.session_state.get("map_color_ramp") not in MAP_RAMP_LABELS:
        st.session_state.map_color_ramp = "classic"
    ramp = st.session_state.map_color_ramp
    active = {**filters, "scale_mode": mode}
    frame = _call(loaders, "get_map_layer_df", case_id, active)
    counts = _call(loaders, "get_layer_counts", case_id, active) or {}
    shown = counts.get("shown")
    total = counts.get("total")
    if shown is None and frame is not None:
        shown = len(frame)
    if isinstance(shown, int) and isinstance(total, int) and (shown > ROW_WARN or total > ROW_WARN):
        st.warning("More than 50000 rows. Ask the backend to aggregate; the UI does not aggregate.")

    view = _call(loaders, "get_view_state", case_id) or {}
    ctx_payload = _call(loaders, "load_context_layers", case_id)
    ctx_geojson = ctx_payload.get("geojson") if isinstance(ctx_payload, dict) else None
    context_groups = _context_groups(ctx_geojson if isinstance(ctx_geojson, dict) else None)
    scale = _scale(loaders, str(case_id), active)

    # Plan Fase 1: 2/3 map + 1/3 reading panel. The CSS rule that makes this row
    # 2:1 lives in theme.py (`.st-key-map-grid`), since a global column flex rule
    # would otherwise flatten every st.columns() to equal widths.
    with st.container(key="map-grid"):
        map_col, panel_col = st.columns([2, 1], gap="medium", vertical_alignment="top")

    with map_col:
        no_cells = (isinstance(shown, int) and shown == 0) or (
            frame is not None and hasattr(frame, "__len__") and len(frame) == 0
        )
        if no_cells:
            empty_state(
                "No cells match these filters",
                "The selected land-use, risk, or coherence filters leave no published cells.",
                icon="0",
            )
            action_columns = st.columns(2)
            action_columns[0].button(
                "Lower minimum coherence",
                key=f"lower-coherence-{case_id}",
                on_click=_lower_coherence_filter,
                help="Lower the current map filter; this does not change the case's declared threshold.",
            )
            action_columns[1].button(
                "Reset filters",
                key=f"reset-empty-filters-{case_id}",
                on_click=_reset_map_filters,
            )
        elif "latitude" not in view or "longitude" not in view or "zoom" not in view:
            st.markdown(
                '<div class="cockpit-card is-empty">'
                '<p class="kicker">Map</p>'
                '<p class="empty-prompt">View not available.</p>'
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            case_label = (case_labels or {}).get(str(case_id), str(case_id))
            count_text = (
                f"{shown} of {total} cells"
                if isinstance(shown, int) and isinstance(total, int)
                else "the delivered cells"
            )
            unit_text = str(scale.get("unit") or UNIT_NOT_DECLARED)
            alt_text = (
                f"{case_label} demonstration map: {count_text} colored by velocity "
                f"({unit_text}). Select a hexagon to inspect the cell."
            )
            _, source_id = _provenance(meta)
            _render_deck(
                frame,
                active,
                view,
                context_groups,
                case_id,
                scale,
                ramp,
                alt_text,
                ignore_map_pick,
                source_id,
            )
        # The ramp belongs to the canvas: directly under it, before the export.
        st.markdown(_legend_inline(scale, mode, ramp), unsafe_allow_html=True)
        if is_shared_scale(mode):
            st.caption(
                "Shared scale: one colour domain is used for every published case. "
                "Bars in the comparison card are comparable only in this mode."
            )
        if active.get("extrude_3d"):
            # Column height comes from the map adapter's presentation constants; it is a camera
            # choice, never a geophysical measurement. The values are unchanged.
            presentation = _call(loaders, "get_extrusion_presentation")
            if isinstance(presentation, dict):
                baseline = presentation.get("baseline_m")
                amplitude = presentation.get("amplitude_m")
                unit = str(presentation.get("unit") or "m")
                if isinstance(baseline, (int, float)) and isinstance(amplitude, (int, float)):
                    st.caption(
                        f"3D column height is presentation only: baseline {baseline:g} {unit} "
                        f"plus amplitude {amplitude:g} {unit}. Cell values and units are unchanged."
                    )
        export_csv = _call(loaders, "get_filtered_export_csv", case_id, active)
        if isinstance(export_csv, str) and export_csv:
            st.download_button(
                "Export filtered cells (CSV)",
                data=export_csv,
                file_name=f"{case_id}_filtered_grid.csv",
                mime="text/csv",
                key=f"export-grid-{case_id}",
            )

    with panel_col:
        with st.container(key="reading-slot"):
            current_cell = st.session_state.get("selected_cell_id")
            candidates = _candidate_cells(frame, str(current_cell) if current_cell else None)
            if current_cell and not st.session_state.get(selector_key):
                st.session_state[selector_key] = str(current_cell)
            if candidates:
                selector_col, share_col = st.columns([4, 1], gap="small", vertical_alignment="bottom")
                with selector_col:
                    chosen = st.selectbox(
                        "H3 cell",
                        options=["", *candidates],
                        format_func=lambda cid: SELECT_PROMPT if cid == "" else cid,
                        key=selector_key,
                    )
                st.session_state.selected_cell_id = chosen or None
                st.session_state._last_h3_selector = chosen or ""
                with share_col:
                    with st.popover(
                        "Share",
                        help="Copy a link that restores the current case, filters, tab and selected cell.",
                    ):
                        st.caption("Copy link to this view")
                        url = share_url() if callable(share_url) else share_url
                        st.code(url or "", language=None)
            if st.session_state.get("selected_cell_id"):
                if st.button("Clear selection", key=f"clear-cell-{case_id}"):
                    st.session_state._clear_cell_request = True
                    st.rerun()
            cell_id = st.session_state.get("selected_cell_id")
            detail = _call(loaders, "get_cell_detail", case_id, cell_id) if cell_id else None
            _reading_panel(
                detail if isinstance(detail, dict) else None,
                str(case_id) if case_id else None,
                meta if isinstance(meta, dict) else None,
                loaders,
                active,
            )

    status = _call(loaders, "get_signal_status", case_id) or {}
    limit, limit_unit = _limit_from_meta(meta)
    if limit is None:
        limit = status.get("detection_limit")
        limit_unit = status.get("detection_limit_unit")
    caption = detection_caption(status.get("above_limit"), limit, limit_unit if isinstance(limit_unit, str) else None)
    if caption:
        if (
            status.get("above_limit") is False
            and isinstance(limit, (int, float))
            and not isinstance(limit, bool)
        ):
            unit_text = f" {limit_unit}" if limit_unit else ""
            caption = f"{caption.rstrip('.')} of {format_number(limit)}{unit_text}."
        st.markdown(
            f'<div class="null-note" role="status">{html.escape(caption)}</div>',
            unsafe_allow_html=True,
        )
        if status.get("above_limit") is False:
            st.caption(
                "This is the case-level detection result, not an empty filter result. "
                "Changing coherence does not change the declared detection limit."
            )
            st.button(
                "Lower minimum coherence",
                key=f"lower-coherence-null-{case_id}",
                on_click=_lower_coherence_filter,
                help="Explore more map cells; the case-level detection status remains unchanged.",
            )
            st.button(
                "Reset filters",
                key=f"reset-null-filters-{case_id}",
                on_click=_reset_map_filters,
            )

    with st.expander("Case comparison and context", expanded=False):
        with st.popover(
            "Map color ramp",
            help="Choose the original ramp or a blue–neutral–orange alternative designed to avoid red–green coding.",
        ):
            st.radio(
                "Ramp",
                options=list(MAP_RAMP_LABELS),
                format_func=lambda key: MAP_RAMP_LABELS[key],
                key="map_color_ramp",
                horizontal=False,
            )
        st.markdown('<p class="kicker">Scale and provenance</p>', unsafe_allow_html=True)
        # The live filtered count is in the one-line mission header; repeating it here
        # would duplicate the same datum inside one view.
        st.markdown(_legend_details(scale, ""), unsafe_allow_html=True)
        coherence_summary = _call(loaders, "get_coherence_summary", case_id, active)
        if isinstance(coherence_summary, dict) and coherence_summary.get("min") is not None:
            low = format_number(coherence_summary["min"], 3)
            high = format_number(coherence_summary.get("max"), 3)
            floor = coherence_summary.get("declared_min")
            floor_text = (
                f" · published floor {format_number(floor, 3)}"
                if isinstance(floor, (int, float)) and not isinstance(floor, bool)
                else ""
            )
            st.markdown(
                '<p class="legend-meta">'
                f"Observed coherence: {html.escape(low)} … {html.escape(high)} (dimensionless)"
                f"{html.escape(floor_text)}.</p>",
                unsafe_allow_html=True,
            )
        # One provenance line per selected case in this tab; the full per-case IDs
        # (all three cities) live in "Provenance and limits".
        if not st.session_state.get("selected_cell_id"):
            source, provenance_id = _provenance(meta)
            st.caption(f"Source {source} · Provenance ID {provenance_id}")
        _render_comparison(_call(loaders, "get_scale_comparison", mode), mode, case_labels)
        context_legend = _context_legend(context_groups)
        if context_legend:
            st.markdown(context_legend, unsafe_allow_html=True)
