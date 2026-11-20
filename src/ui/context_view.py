"""Context layers. Empty unless Rol 3 has delivered the GeoJSON.

Presentation only: reads the loader payload, never the artefact files. The proximity
cross-reference (`get_context_exposure`) says which H3 cell is nearest to each feature
and what that cell's velocity band is; it is **not** a hazard assessment.
"""

from __future__ import annotations

import html
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from src.ui.formatters import (
    CONTEXT_LAYER_GLOSSARY,
    NOT_DECLARED,
    choice_label,
    humanize,
    risk_label,
    translate_feature_name,
)

_TABLE_FIELDS = (
    "layer",
    "class",
    "name",
    "source",
    "nearest_cell_id",
    "risk_level",
    "distance_m",
    "provenance_id",
)
_NO_VALUE = ("", "None", "nan")


def _features(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    geo = payload.get("geojson")
    features = geo.get("features") if isinstance(geo, dict) else None
    if not isinstance(features, list):
        return []
    rows: list[dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            continue
        rows.append({field: props.get(field) for field in _TABLE_FIELDS})
    return rows


def _visible_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if "name" not in frame.columns:
        return frame
    filled = frame["name"].astype(str).str.strip()
    if filled.eq("").all() or filled.eq("None").all():
        return frame.drop(columns=["name"])
    return frame


PAGE_SIZE = 25


def _render_table(frame: pd.DataFrame, provenance: str | None = None, page: int = 1) -> str:
    shown = _visible_frame(frame)
    note = (
        f'<p class="kpi-note">Provenance ID {html.escape(provenance)}</p>'
        if provenance
        else ""
    )
    headers = "".join(f"<th>{html.escape(humanize(col))}</th>" for col in shown.columns)
    body_rows: list[str] = []
    for index, row in enumerate(shown.itertuples(index=False)):
        risk = str(getattr(row, "risk_level", "") or "")
        row_class = ' class="row-alert"' if risk == "critico" else (
            ' class="row-warn"' if risk == "moderado" else ""
        )
        cells = []
        for col, val in zip(shown.columns, row):
            text = str(val).replace(chr(10), " ")
            if text in _NO_VALUE:
                cells.append("<td>—</td>")
            elif col == "risk_level":
                cells.append(f"<td>{html.escape(risk_label(text))}</td>")
            else:
                cells.append(f"<td>{html.escape(text)}</td>")
        row_page = index // PAGE_SIZE + 1
        hidden_attr = ' hidden aria-hidden="true"' if row_page != page else ""
        body_rows.append(
            f'<tr{row_class} data-page="{row_page}"{hidden_attr}>{"".join(cells)}</tr>'
        )
    # All rows stay in the DOM (the artefact-parity tests read them), but off-page
    # rows carry both `hidden`/`aria-hidden="true"` and `display: none !important`,
    # removing them from layout, tab order and the accessibility tree.
    return (
        f"{note}"
        f'<style>.cockpit-table[data-page="{page}"] tbody tr[data-page]:not([data-page="{page}"]) '
        "{ display: none !important; }</style>"
        '<div class="cockpit-table-wrap" role="region" aria-label="Context layers" tabindex="0">'
        f'<table class="cockpit-table" data-page="{page}" aria-label="Context layer properties">'
        f"<thead><tr>{headers}</tr></thead>"
        f'<tbody>{"".join(body_rows)}</tbody>'
        "</table></div>"
    )


def _set_page(key: str, value: int) -> None:
    st.session_state[key] = max(1, int(value))


def _stat_card(column: Any, label: str, value: str, note: str | None = None) -> None:
    note_html = f'<p class="kpi-note">{html.escape(note)}</p>' if note else ""
    column.markdown(
        '<div class="cockpit-card">'
        f'<p class="kicker">{html.escape(label)}</p>'
        f'<p class="kpi-value">{html.escape(value)}</p>'
        f"{note_html}</div>",
        unsafe_allow_html=True,
    )


def _render_distance_summary(loaders: Any, case_id: Any, filters: dict[str, Any]) -> None:
    """Delivered nearest-cell distances as descriptive values; no near/far class exists.

    The domain computes the summary from `distance_m`. Neither the artefact, the contract
    nor the config declares a "far" threshold, so this view never labels a distance. The
    existing envelope caveat above already explains why a representative point can be far.
    """
    function = getattr(loaders, "get_distance_summary", None)
    if function is None:
        return
    try:
        summary = function(case_id, filters)
    except TypeError:
        return
    if not isinstance(summary, dict) or not summary.get("n_features"):
        return
    unit = str(summary.get("unit") or "m")

    def value(key: str) -> str:
        number = summary.get(key)
        if isinstance(number, (int, float)) and not isinstance(number, bool):
            return f"{number:g} {unit}"
        return NOT_DECLARED

    cards = st.columns(3)
    _stat_card(cards[0], "Minimum distance", value("min_m"), "nearest filtered cell")
    _stat_card(cards[1], "Median distance", value("median_m"), "nearest filtered cell")
    _stat_card(cards[2], "Maximum distance", value("max_m"), "nearest filtered cell")
    st.caption(
        "Delivered nearest-cell distances, descriptive only. No distance band is declared in "
        "the artefact or the contract, so these values are not classified. Source: the case "
        "artefact credited with the context table below."
    )


def _row_counts(loaders: Any, rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Ask the domain (through the loader) to count delivered rows; never count in the UI."""
    function = getattr(loaders, "summarize_context_rows", None)
    if function is not None:
        try:
            result = function(rows)
        except TypeError:
            result = None
        if isinstance(result, dict):
            return result
    return {"layers": {}, "by_risk": {}}


def _layer_counts(
    summary: dict[str, Any],
    counted: dict[str, dict[str, int]],
) -> dict[str, int]:
    """Prefer the artefact summary; otherwise use the domain's count of the rows."""
    layers = summary.get("layers") if isinstance(summary, dict) else None
    if isinstance(layers, dict) and layers:
        return {str(key): int(value) for key, value in layers.items()}
    return {str(key): int(value) for key, value in counted.get("layers", {}).items()}


def _load(loaders: Any, case_id: Any, filters: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """Prefer the exposure hook (nearest cell + risk); fall back to the plain GeoJSON."""
    exposure_fn = getattr(loaders, "get_context_exposure", None)
    if exposure_fn is not None:
        try:
            exposure = exposure_fn(case_id, filters)
        except TypeError:
            exposure = None
        if isinstance(exposure, Mapping) and exposure.get("features"):
            summary = exposure.get("summary") if isinstance(exposure.get("summary"), Mapping) else {}
            return list(exposure["features"]), dict(summary), "exposure"
    loader = getattr(loaders, "load_context_layers", None)
    if loader is None:
        return [], {}, None
    try:
        payload = loader(case_id)
    except TypeError:
        payload = loader()
    if not payload:
        return [], {}, None
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return _features(payload), summary, "plain"


def context_caption(shown: pd.DataFrame) -> str:
    """What a reader is most likely to misread on this tab, derived from the rows in front of them.

    Both halves were once hard-coded, and both were wrong.

    `unknown` has **two** causes — no mapped polygon contains the cell's centroid, *or* the containing polygon's tags
    map to no class of the frozen vocabulary. Naming only the first is false: every `unknown` cell in Málaga sits
    *inside* a mapped polygon, which is why `tests/test_limitation_disclosures.py` rejects single-cause wording.

    The source claim depends on the payload. The `land_use` shapes are the dissolved H3 cells of this grid and are
    published with the same case source string as the OpenStreetMap geometry, so calling every polygon OSM data is
    false for those; and a synthetic-fallback artefact must not be credited to OpenStreetMap at all.
    """
    sources = shown["source"].astype(str) if "source" in shown.columns else pd.Series(dtype=str)
    osm = bool(sources.str.contains("OpenStreetMap", na=False).any())
    fallback = (not osm) and bool(sources.str.contains("mock|synthetic", case=False, na=False).any())
    # `shown` has already been humanised for display (`land_use` -> "Land use"), so accept either spelling: the
    # raw form arrives from a direct call, the humanised one from the rendered table.
    layer_values = (
        shown["layer"].astype(str).str.strip().str.lower()
        if "layer" in shown.columns
        else pd.Series(dtype=str)
    )
    is_land_use = layer_values.isin({"land_use", "land use"})
    has_land_use = bool(is_land_use.any())
    # The land_use shapes are dissolved grid cells published with the case source string, so a frame made only of
    # them must not open with an OpenStreetMap claim: every row shown would be the exception, not the rule.
    if has_land_use and "source" in shown.columns:
        osm_others = bool(
            shown[~is_land_use]["source"].astype(str).str.contains("OpenStreetMap", na=False).any()
        )
    else:
        osm_others = osm
    if fallback:
        origin = (
            "These polygons are the declared synthetic fallback, not OpenStreetMap data — the Source "
            "column says so on every row."
        )
    elif has_land_use and not osm_others:
        origin = (
            "These are the dissolved H3 cells of this grid, not OpenStreetMap geometry; they carry the "
            "case source string."
        )
    else:
        origin = "Context polygons carry OpenStreetMap provenance (ODbL 1.0)"
        if has_land_use:
            origin += (
                "; the `land_use` shapes are the dissolved H3 cells of this grid and carry the same "
                "case source string rather than OpenStreetMap geometry"
            )
        origin += "."
    return (
        "Land use “unknown” is a published category, not missing data: either no mapped polygon "
        "contains the cell's centroid, or the containing polygon's tags map to no class of the frozen "
        "vocabulary — and it is never extrapolated from a neighbouring cell. The per-case share is "
        "disclosed under “Limits of this artefact” in tab 4. "
        + origin
        + " The provenance ID below names this case's published product, not the origin of the polygons."
    )


def render_hazard_tab(filters: dict[str, Any], loaders: Any) -> None:
    case_id = filters.get("case_id")
    rows, summary, source = _load(loaders, case_id, filters)
    if not rows:
        st.markdown(
            '<div class="cockpit-card is-empty">'
            '<p class="kicker">Context</p>'
            '<p class="empty-prompt">No context layers are available for this case.</p>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    counts = _layer_counts(summary, _row_counts(loaders, rows))
    total = summary.get("n_features")
    if not isinstance(total, int) or isinstance(total, bool):
        total = len(rows)
    breakdown = ", ".join(
        f"{humanize(layer)} {count}" for layer, count in sorted(counts.items())
    )
    columns = st.columns(3)
    _stat_card(columns[0], "Delivered features", f"{total}", "GeoJSON features")
    _stat_card(columns[1], "Delivered layers", f"{len(counts)}", "distinct layer values")
    _stat_card(columns[2], "Layer counts", breakdown or "none", None)

    frame = pd.DataFrame(rows, columns=list(_TABLE_FIELDS)).fillna("")
    for column in ("layer", "class"):
        frame[column] = frame[column].map(lambda value: humanize(value) if str(value) else value)
    if "name" in frame.columns:
        frame["name"] = frame["name"].map(translate_feature_name)

    # Display-only filters over the delivered rows. Keys are tab-scoped: never reuse
    # the global `filter_*` keys or the map would change underneath the user.
    control_cols = st.columns(3)
    with control_cols[0]:
        layers_present = sorted(str(value) for value in frame["layer"].unique() if str(value))
        picked_layers = st.multiselect(
            "Layer",
            options=layers_present,
            key=f"ctx-layer-{case_id}",
        )
    with control_cols[1]:
        classes_present = sorted(str(value) for value in frame["class"].unique() if str(value))
        picked_class = st.selectbox(
            "Class",
            options=["", *classes_present],
            format_func=choice_label,
            key=f"ctx-class-{case_id}",
        )
    with control_cols[2]:
        picked_risk = st.selectbox(
            "Nearest cell risk",
            options=["", "estable", "moderado", "critico"],
            format_func=choice_label,
            key=f"ctx-risk-{case_id}",
        )

    # One provenance line per view when every row shares the same case artefact;
    # repeating the identical id in 12 rows is noise, not traceability.
    provenance_ids = sorted(
        {str(value) for value in frame["provenance_id"] if str(value) not in ("", "None", "nan")}
    )
    single_source = provenance_ids[0] if len(provenance_ids) == 1 else None
    if single_source:
        frame = frame.drop(columns=["provenance_id"])

    shown = frame
    if picked_layers:
        shown = shown[shown["layer"].isin(picked_layers)]
    if picked_class:
        shown = shown[shown["class"] == humanize(picked_class)]
    if picked_risk:
        shown = shown[shown["risk_level"] == picked_risk]

    has_exposure = source == "exposure" and "risk_level" in shown.columns
    shown_counts = _row_counts(loaders, shown.to_dict(orient="records"))
    by_risk = shown_counts.get("by_risk", {})
    critical = int(by_risk.get("critico", 0)) if has_exposure else 0
    moderate = int(by_risk.get("moderado", 0)) if has_exposure else 0

    note = (
        "Delivered context only, not a hazard assessment. "
        "A context class is not the Land use filter."
    )
    exposure_note = (
        f'<p class="kpi-note">Nearest filtered H3 cell per feature — {critical} on Critical, '
        f"{moderate} on Moderate. Proximity is informative, not an exposure model. An administrative "
        f"envelope is summarised by its representative point, so its distance is the envelope's, not a "
        f"site's.</p>"
        if has_exposure
        else ""
    )
    st.markdown('<p class="kicker">Context layers</p>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="kpi-note">{html.escape(note)}</p>',
        unsafe_allow_html=True,
    )
    if exposure_note:
        st.markdown(exposure_note, unsafe_allow_html=True)
    if has_exposure:
        _render_distance_summary(loaders, case_id, filters)
    st.caption(context_caption(shown))
    st.markdown(
        f"<p>{len(shown)} features shown of {len(frame)}</p>",
        unsafe_allow_html=True,
    )
    pages = max(1, (len(shown) + PAGE_SIZE - 1) // PAGE_SIZE)
    page_key = f"ctx-page-{case_id}"
    page = st.session_state.get(page_key, 1)
    if not isinstance(page, int) or isinstance(page, bool):
        page = 1
    page = min(max(1, page), pages)
    st.session_state[page_key] = page
    pager = st.columns([1, 2, 1], vertical_alignment="center")
    with pager[0]:
        st.button(
            "Previous page",
            key=f"ctx-prev-{case_id}",
            disabled=page <= 1,
            on_click=_set_page,
            args=(page_key, page - 1),
        )
    with pager[1]:
        st.markdown(
            f'<p class="context-pager" role="status">Page {page} / {pages} · '
            f"{PAGE_SIZE} rows per page</p>",
            unsafe_allow_html=True,
        )
    with pager[2]:
        st.button(
            "Next page",
            key=f"ctx-next-{case_id}",
            disabled=page >= pages,
            on_click=_set_page,
            args=(page_key, page + 1),
        )
    st.markdown(_render_table(shown, single_source, page), unsafe_allow_html=True)
    # `CONTEXT_LAYER_GLOSSARY` was imported here and never rendered, so the video script promised a glossary no
    # reader could find. Four layers with one line each is cheap, collapsed so it never displaces the table.
    if CONTEXT_LAYER_GLOSSARY:
        with st.expander("What each layer means", expanded=False):
            for layer_name, meaning in CONTEXT_LAYER_GLOSSARY.items():
                st.markdown(f"**{layer_name}** — {meaning}")

    text_cols = st.columns(2)
    with text_cols[0]:
        st.download_button(
            "Export context (CSV)",
            data=shown.to_csv(index=False),
            file_name=f"{case_id}_context.csv",
            mime="text/csv",
            key=f"ctx-export-{case_id}",
        )
    with text_cols[1]:
        jumpable = shown[
            ~shown["nearest_cell_id"].astype(str).isin([""] + list(_NO_VALUE))
        ] if "nearest_cell_id" in shown.columns else shown.iloc[0:0]
        if not jumpable.empty:
            options = {
                f"{row['name'] or row['class']} · {risk_label(row['risk_level'])}": row[
                    "nearest_cell_id"
                ]
                for _, row in jumpable.iterrows()
            }
            picked = st.selectbox(
                "Jump to nearest cell",
                options=["", *options],
                format_func=lambda key: "Select a feature" if key == "" else key,
                key=f"ctx-jump-{case_id}",
            )
            clicked = st.button("Jump to cell on Map", key=f"ctx-jump-btn-{case_id}")
            if picked and clicked:
                st.session_state.selected_cell_id = options[picked]
                st.session_state[f"inspector_cell_{case_id}"] = ""
                st.rerun()
