"""Streamlit shell. Composition only: no file reads and no geospatial math."""

from __future__ import annotations

import html
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import streamlit as st

from src.ui.charts import render_series_tab
from src.ui.context_view import render_hazard_tab
from src.ui.educational import render_physics_tab
from src.ui.formatters import DEMO_BANNER, SCALE_LABELS, choice_label, format_dates_span
from src.ui.map_view import render_map_tab
from src.ui.theme import MAP_RAMP_LABELS, apply_theme_marker, inject_css

TAB_MAP = "1. Map"
TAB_SERIES = "2. Series and KPIs"
TAB_HAZARD = "3. Hazard and infrastructure"
TAB_PHYSICS = "4. Provenance and limits"
TITLE = "Dancing with the SARs: NISAR Interferometry Cockpit"
TAB_OPTIONS = (TAB_MAP, TAB_SERIES, TAB_HAZARD, TAB_PHYSICS)

# Header telemetry may use only these keys. Missing keys are omitted.
_TELEMETRY_KEYS = ("sensor", "product", "unit", "dates", "coherence_threshold")
_TELEMETRY_LABELS = {
    "sensor": "Sensor",
    "product": "Product",
    "unit": "Unit",
    "coherence_threshold": "Coherence threshold",
}


def _loaders() -> Any:
    try:
        from src.data import loaders as real
    except ImportError:
        real = None
    required = (
        "load_study_cases",
        "load_meta",
        "load_land_use_options",
        "load_risk_levels",
        "get_map_layer_df",
        "get_view_state",
        "get_cell_detail",
        "load_timeseries",
    )
    if real is not None and all(hasattr(real, name) for name in required):
        return real
    from src.ui import _stubs

    return _stubs


def is_demonstration(meta: dict[str, Any] | None) -> bool:
    """True when the artefact declares itself mock. No extra contract field."""
    if not isinstance(meta, dict):
        return False
    if meta.get("product") == "mock":
        return True
    provenance = meta.get("provenance")
    if isinstance(provenance, dict) and "mock" in str(provenance.get("source", "")).lower():
        return True
    return False


def telemetry_line(meta: dict[str, Any] | None) -> str:
    """Join only telemetry keys that exist and are non-empty."""
    if not isinstance(meta, dict):
        return ""
    parts: list[str] = []
    for key in _TELEMETRY_KEYS:
        if key not in meta:
            continue
        value = meta[key]
        if value is None or value == "" or value == []:
            continue
        if key == "dates":
            span = format_dates_span(value if isinstance(value, list) else None)
            if span:
                parts.append(span.capitalize())
            continue
        parts.append(f"{_TELEMETRY_LABELS.get(key, key)} {value}")
    if "coherence_threshold" not in meta:
        thresholds = meta.get("thresholds")
        floor = thresholds.get("coherence_min") if isinstance(thresholds, dict) else None
        if isinstance(floor, (int, float)) and not isinstance(floor, bool):
            parts.append(f"Coherence floor {floor:g}")
    return " · ".join(parts)


def coherence_default(meta: dict[str, Any] | None) -> float | None:
    """Slider default from meta. Do not invent or clamp the received number.

    v1.1 stores the floor at thresholds.coherence_min. coherence_threshold is
    read only when that key is actually present.
    """
    if not isinstance(meta, dict):
        return None
    if "coherence_threshold" in meta and isinstance(meta["coherence_threshold"], (int, float)):
        return float(meta["coherence_threshold"])
    thresholds = meta.get("thresholds")
    if isinstance(thresholds, dict) and isinstance(thresholds.get("coherence_min"), (int, float)):
        return float(thresholds["coherence_min"])
    return None


def _blank(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    return value


def _filters_from_state(case_id: str, coherence_floor: float | None) -> dict[str, Any]:
    """Read current controls before drawing them, so the count is for this rerun."""
    coherence = st.session_state.get("filter_coherence_min", coherence_floor)
    if not isinstance(coherence_floor, (int, float)) or not 0.0 <= coherence_floor <= 1.0:
        coherence = None
    return {
        "case_id": case_id,
        "land_use": _blank(st.session_state.get("filter_land_use")),
        "coherence_min": float(coherence)
        if isinstance(coherence, (int, float)) and not isinstance(coherence, bool)
        else None,
        "risk_level": _blank(st.session_state.get("filter_risk_level")),
        "extrude_3d": bool(st.session_state.get("filter_extrude_3d", False)),
    }


def _clear_control(key: str, value: Any) -> None:
    """Button callback: clear one widget before Streamlit instantiates it again."""
    st.session_state[key] = value


def _reset_filter_controls(coherence_floor: float | None) -> None:
    st.session_state.filter_land_use = ""
    st.session_state.filter_risk_level = ""
    st.session_state.filter_extrude_3d = False
    if isinstance(coherence_floor, (int, float)) and 0.0 <= coherence_floor <= 1.0:
        st.session_state.filter_coherence_min = float(coherence_floor)


def _apply_reliable_preset(coherence_floor: float | None) -> None:
    floor = float(coherence_floor) if isinstance(coherence_floor, (int, float)) else 0.0
    st.session_state.filter_coherence_min = max(floor, 0.5)


def _apply_critical_preset() -> None:
    st.session_state.filter_risk_level = "critico"


# URL state: keys are short query params; values map to session_state keys.
# A shared URL must reopen the cockpit on the same case, filters and camera choice.
_THEME_MODES = ("system", "light", "dark")
_SCALE_MODES = ("independent", "shared")


def _seed_state_from_query(case_ids: list[str], coherence_floor: float | None) -> None:
    """Apply query params to session_state on the first run only.

    Unknown or out-of-range values are ignored; stale land/risk values are
    dropped later by the existing per-case option check. Seeding never
    overrides a key the current session already holds.
    """
    qp = st.query_params
    if not qp:
        return
    if "filter_case_id" not in st.session_state and qp.get("case") in case_ids:
        st.session_state.filter_case_id = qp["case"]
    if "filter_land_use" not in st.session_state and "land" in qp:
        st.session_state.filter_land_use = qp["land"]
    if "filter_risk_level" not in st.session_state and "risk" in qp:
        st.session_state.filter_risk_level = qp["risk"]
    if "filter_extrude_3d" not in st.session_state and qp.get("extrude") in ("0", "1"):
        st.session_state.filter_extrude_3d = qp["extrude"] == "1"
    if "ui_theme_mode" not in st.session_state and qp.get("theme") in _THEME_MODES:
        st.session_state.ui_theme_mode = qp["theme"]
    if "scale_mode" not in st.session_state and qp.get("scale") in _SCALE_MODES:
        st.session_state.scale_mode = qp["scale"]
    if "map_color_ramp" not in st.session_state and qp.get("ramp") in MAP_RAMP_LABELS:
        st.session_state.map_color_ramp = qp["ramp"]
    if "selected_cell_id" not in st.session_state and qp.get("cell"):
        st.session_state.selected_cell_id = qp.get("cell")
    if "filter_coherence_min" not in st.session_state:
        try:
            value = float(qp["coh"])
        except (KeyError, TypeError, ValueError):
            value = None
        if value is not None and 0.0 <= value <= 1.0:
            # Seed the applied floor too, or render_filters would reset the slider
            # to the declared default on this first run.
            if isinstance(coherence_floor, (int, float)):
                st.session_state.filter_coherence_floor = coherence_floor
            st.session_state.filter_coherence_min = value


def _active_tab(default: str = TAB_MAP) -> str:
    state = st.session_state.get("cockpit-tabs")
    active = state.get("open") if isinstance(state, dict) else state
    if active in TAB_OPTIONS:
        return str(active)
    requested = st.query_params.get("tab")
    return str(requested) if requested in TAB_OPTIONS else default


def _on_tab_change() -> None:
    """Write the newly selected tab before the normal rerun renders URL state."""
    state = st.session_state.get("cockpit-tabs")
    active = state.get("open") if isinstance(state, dict) else state
    if active in TAB_OPTIONS:
        st.query_params["tab"] = str(active)


def _sync_query_params(filters: dict[str, Any], tab: str = TAB_MAP) -> None:
    """Mirror the live state into the URL so a copied link restores it."""
    qp = st.query_params
    qp["case"] = str(filters["case_id"])
    for key, value in (
        ("land", filters["land_use"]),
        ("risk", filters["risk_level"]),
        ("cell", st.session_state.get("selected_cell_id")),
    ):
        if value:
            qp[key] = str(value)
        elif key in qp:
            del qp[key]
    coherence = filters.get("coherence_min")
    if isinstance(coherence, (int, float)) and not isinstance(coherence, bool):
        qp["coh"] = f"{float(coherence):g}"
    elif "coh" in qp:
        del qp["coh"]
    qp["extrude"] = "1" if filters["extrude_3d"] else "0"
    qp["theme"] = str(st.session_state.get("ui_theme_mode", "system"))
    qp["scale"] = str(st.session_state.get("scale_mode", "independent"))
    qp["ramp"] = str(st.session_state.get("map_color_ramp", "classic"))
    qp["tab"] = tab if tab in TAB_OPTIONS else TAB_MAP


def _view_url(
    filters: dict[str, Any] | None = None,
    tab: str | None = None,
) -> str:
    """Current absolute URL, with a relative query-string fallback for test contexts."""
    params = dict(st.query_params.items())
    if isinstance(filters, dict):
        params["case"] = str(filters["case_id"])
        for key, value in (
            ("land", filters.get("land_use")),
            ("risk", filters.get("risk_level")),
            ("cell", st.session_state.get("selected_cell_id")),
        ):
            if value:
                params[key] = str(value)
            else:
                params.pop(key, None)
        coherence = filters.get("coherence_min")
        if isinstance(coherence, (int, float)) and not isinstance(coherence, bool):
            params["coh"] = f"{float(coherence):g}"
        else:
            params.pop("coh", None)
        params["extrude"] = "1" if filters.get("extrude_3d") else "0"
    params["theme"] = str(st.session_state.get("ui_theme_mode", "system"))
    params["scale"] = str(st.session_state.get("scale_mode", "independent"))
    params["ramp"] = str(st.session_state.get("map_color_ramp", "classic"))
    params["tab"] = tab if tab in TAB_OPTIONS else TAB_MAP
    try:
        current = st.context.url
    except Exception:
        current = None
    if isinstance(current, str) and current:
        parsed = urlsplit(current)
        return urlunsplit(parsed._replace(query=urlencode(params)))
    query = urlencode(params)
    return f"?{query}" if query else ""


def _case_options(loaders: Any, name: str, case_id: str) -> tuple[str, ...]:
    """Prefer case-scoped options; fall back for stubs whose hook takes no argument."""
    function = getattr(loaders, name)
    try:
        return tuple(function(case_id))
    except TypeError:
        return tuple(function())


def _mission_chips(
    filters: dict[str, Any] | None,
    counts: dict[str, Any] | None,
    coherence_floor: float | None,
) -> str:
    """Compact summary of what the map is showing: count plus active filters."""
    chips: list[tuple[str, bool]] = []
    shown = counts.get("shown") if isinstance(counts, dict) else None
    total = counts.get("total") if isinstance(counts, dict) else None
    if isinstance(shown, int) and isinstance(total, int):
        chips.append((f"{shown} of {total} cells", False))
    active = filters or {}
    land = active.get("land_use")
    if land:
        chips.append((f"Land · {choice_label(str(land))}", True))
    risk = active.get("risk_level")
    if risk:
        chips.append((f"Risk · {choice_label(str(risk))}", True))
    threshold = active.get("coherence_min")
    if (
        isinstance(threshold, (int, float))
        and not isinstance(threshold, bool)
        and isinstance(coherence_floor, (int, float))
        and abs(float(threshold) - float(coherence_floor)) > 1e-9
    ):
        chips.append((f"Coherence ≥ {float(threshold):g}", True))
    if active.get("extrude_3d"):
        chips.append(("3D · on", True))
    return "".join(
        f'<span class="mission-chip{" is-active" if is_active else ""}">{html.escape(chip)}</span>'
        for chip, is_active in chips
    )


def render_header(
    meta: dict[str, Any] | None,
    case_label: str | None = None,
    filters: dict[str, Any] | None = None,
    counts: dict[str, Any] | None = None,
    coherence_floor: float | None = None,
) -> None:
    line = telemetry_line(meta)
    telemetry = f'<p class="telemetry">{html.escape(line)}</p>' if line else ""
    # On a phone the full telemetry line is hidden by theme.py. A compact chip keeps the
    # same artefact-sourced values one tap away instead of dropping them from the view.
    telemetry_details = ""
    if line:
        telemetry_details = (
            '<details class="telemetry-disclosure">'
            '<summary class="mission-chip telemetry-chip">Telemetry</summary>'
            f'<p class="telemetry telemetry-detail">{html.escape(line)}</p>'
            "</details>"
        )
    case = (
        f'<span class="case-pill" aria-label="Active case">{html.escape(case_label)}</span>'
        if case_label
        else ""
    )
    chips = _mission_chips(filters, counts, coherence_floor)
    facts = f'<div class="mission-facts">{chips}</div>' if chips else ""
    st.markdown(
        '<header class="mission-bar">'
        '<div class="mission-line">'
        f'<h1 class="mission-title">{html.escape(TITLE)}{case}</h1>'
        f"{facts}"
        "</div>"
        f"{telemetry}"
        f"{telemetry_details}"
        "</header>",
        unsafe_allow_html=True,
    )
    if is_demonstration(meta):
        st.markdown(
            f'<div class="demo-banner" role="status">{DEMO_BANNER}</div>',
            unsafe_allow_html=True,
        )


def render_filters(
    case_ids: list[str],
    labels: dict[str, str],
    land_uses: tuple[str, ...] | list[str],
    risk_levels: tuple[str, ...] | list[str],
    coherence_floor: float | None,
    counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Draw the filter strip. Values stay in session_state; nothing is filtered."""
    theme_labels = {"system": "System", "light": "Light", "dark": "Dark"}
    if st.session_state.get("ui_theme_mode") not in theme_labels:
        st.session_state.ui_theme_mode = "system"
    # Streamlit has no viewport query on the server. The filter strip starts closed
    # on every viewport so the map keeps the first screen; the header chips carry
    # the live summary. `?filters=open` reopens it for a deep link or a demo.
    compact = st.query_params.get("compact") == "1"
    expanded = st.query_params.get("filters") == "open" and not compact
    shown = counts.get("shown") if isinstance(counts, dict) else None
    total = counts.get("total") if isinstance(counts, dict) else None
    filter_title = (
        f"Filters · {shown} of {total} cells"
        if isinstance(shown, int) and isinstance(total, int)
        else "Filters"
    )
    with st.expander(filter_title, expanded=expanded, key="filters"):
        case_col, land_col, coherence_col, risk_col, extrude_col, theme_col = st.columns(6)
        with case_col:
            st.selectbox(
                "Case",
                options=case_ids,
                format_func=lambda case_id: labels.get(case_id, case_id),
                key="filter_case_id",
                help="Choose which demonstration case to inspect.",
            )
        with land_col:
            st.selectbox(
                "Land use",
                options=["", *land_uses],
                format_func=choice_label,
                key="filter_land_use",
                help="Keep only cells in the selected land-use class.",
            )
        with coherence_col:
            if coherence_floor is None:
                st.caption("Coherence threshold not declared.")
            elif not 0.0 <= coherence_floor <= 1.0:
                st.caption("Coherence threshold is outside [0, 1]. It is not modified.")
            else:
                # Init when the key is missing. Reset only when this case declares
                # a different floor, so a user value survives an unchanged threshold.
                applied = st.session_state.get("filter_coherence_floor")
                if "filter_coherence_min" not in st.session_state or applied != coherence_floor:
                    st.session_state.filter_coherence_min = coherence_floor
                st.session_state.filter_coherence_floor = coherence_floor
                st.slider(
                    "Minimum coherence",
                    min_value=0.0,
                    max_value=1.0,
                    key="filter_coherence_min",
                    help="Dimensionless quality value from 0 to 1. Higher values keep more coherent cells.",
                )
        with risk_col:
            st.selectbox(
                "Risk level",
                options=["", *risk_levels],
                format_func=choice_label,
                key="filter_risk_level",
                help="Keep cells in the selected velocity-derived risk band.",
            )
        with extrude_col:
            if "filter_extrude_3d" not in st.session_state:
                st.session_state.filter_extrude_3d = False
            st.toggle(
                "3D extrusion",
                key="filter_extrude_3d",
                help="Change map presentation only; cell values are unchanged.",
            )
        with theme_col:
            st.selectbox(
                "Theme",
                options=list(theme_labels),
                format_func=lambda mode: theme_labels.get(mode, mode),
                key="ui_theme_mode",
                help="Use the system preference or select a theme explicitly.",
            )

        result = {
            "case_id": st.session_state.get("filter_case_id"),
            "land_use": _blank(st.session_state.get("filter_land_use")),
            "coherence_min": (
                st.session_state.get("filter_coherence_min", coherence_floor)
                if isinstance(coherence_floor, (int, float)) and 0.0 <= coherence_floor <= 1.0
                else None
            ),
            "risk_level": _blank(st.session_state.get("filter_risk_level")),
            "extrude_3d": bool(st.session_state.get("filter_extrude_3d", False)),
        }

        # Presets are available without adding another always-open toolbar row.
        active: list[tuple[str, str, Any]] = []
        if result["land_use"]:
            land_label = choice_label(str(result["land_use"]))
            if len(land_label) > 16:
                land_label = f"{land_label[:13]}…"
            active.append((f"Land · {land_label}", "filter_land_use", ""))
        threshold = result.get("coherence_min")
        if isinstance(threshold, (int, float)) and threshold != coherence_floor:
            active.append((f"Coherence ≥ {threshold:g}", "filter_coherence_min", coherence_floor))
        if result["risk_level"]:
            active.append(
                (f"Risk · {choice_label(str(result['risk_level']))}", "filter_risk_level", "")
            )
        if result["extrude_3d"]:
            active.append(("3D · on", "filter_extrude_3d", False))

        widths = [1.25, *([1.0] * len(active)), 1.05]
        with st.container(key="filter-actions"):
            action_columns = st.columns(widths, vertical_alignment="center")
            with action_columns[0]:
                with st.popover("Quick presets", help="Apply a preset to the current case."):
                    st.caption("Preset values change filters only; they do not change the data.")
                    st.button(
                        "Reliable signal · ≥ 0.5",
                        key="preset-reliable",
                        on_click=_apply_reliable_preset,
                        args=(coherence_floor,),
                        help="Set minimum coherence to at least 0.5.",
                    )
                    if "critico" in risk_levels:
                        st.button(
                            "High risk only",
                            key="preset-critical",
                            on_click=_apply_critical_preset,
                            help="Show only the contract's Critical risk band.",
                        )
            for column, (label, key, default) in zip(action_columns[1:-1], active):
                with column:
                    st.button(
                        f"× {label}",
                        key=f"remove-filter-{key}",
                        on_click=_clear_control,
                        args=(key, default),
                        help=f"Remove the active {label} filter.",
                    )
            with action_columns[-1]:
                st.button(
                    "Reset filters",
                    key="reset-filters",
                    disabled=not bool(active),
                    on_click=_reset_filter_controls,
                    args=(coherence_floor,),
                )

    return result


@st.fragment
def _render_map(
    filters: dict[str, Any],
    loaders: Any,
    meta: dict[str, Any] | None,
    case_labels: dict[str, str],
) -> None:
    render_map_tab(
        filters,
        loaders,
        meta,
        case_labels,
        share_url=lambda: _view_url(filters, _active_tab()),
    )
    _sync_query_params(filters, _active_tab())


def render_attribution() -> None:
    """Credit the context polygons where they are shown, as ODbL 1.0 requires.

    The map tab draws `context_layers.geojson` and the hazard tab lists it, so the credit is app-level rather than
    per-tab. `docs/context-sources.md` §5 carries the canonical wording; `meta.provenance.license` carries it into
    the artefact, but a licence that only exists inside a JSON file the reader never opens does not discharge the
    obligation. The second sentence keeps the credit from being read as a claim about the SAR values, which are
    synthetic.
    """
    st.caption(
        "Context layers © OpenStreetMap contributors, ODbL 1.0. "
        "The displacement values are synthetic (product: mock); no third-party data is used for them."
    )


@st.fragment
def render_app() -> None:
    loaders = _loaders()
    cases = list(loaders.load_study_cases())
    case_ids = [str(case["id"]) for case in cases if case.get("id")]
    labels = {str(case["id"]): str(case.get("label") or case["id"]) for case in cases}

    if not case_ids:
        st.error("No cases. config/study_cases.yaml is missing.")
        return

    if "filter_case_id" not in st.session_state:
        url_case = st.query_params.get("case")
        st.session_state.filter_case_id = url_case if url_case in case_ids else case_ids[0]
    if st.session_state.filter_case_id not in case_ids:
        st.session_state.filter_case_id = case_ids[0]

    meta = loaders.load_meta(st.session_state.filter_case_id)
    _seed_state_from_query(
        case_ids,
        coherence_default(meta if isinstance(meta, dict) else None),
    )
    if st.session_state.get("ui_theme_mode") not in _THEME_MODES:
        st.session_state.ui_theme_mode = "system"
    apply_theme_marker()
    land_uses = _case_options(loaders, "load_land_use_options", st.session_state.filter_case_id)
    risk_levels = _case_options(loaders, "load_risk_levels", st.session_state.filter_case_id)
    # Drop stale filter values when options shrink (stub no longer lists absent classes).
    if st.session_state.get("filter_land_use") not in ("", *land_uses):
        st.session_state.filter_land_use = ""
    if st.session_state.get("filter_risk_level") not in ("", *risk_levels):
        st.session_state.filter_risk_level = ""
    coherence_floor = coherence_default(meta if isinstance(meta, dict) else None)
    applied_floor = st.session_state.get("filter_coherence_floor")
    if (
        isinstance(coherence_floor, (int, float))
        and 0.0 <= coherence_floor <= 1.0
        and (
            "filter_coherence_min" not in st.session_state
            or applied_floor != coherence_floor
        )
    ):
        st.session_state.filter_coherence_min = float(coherence_floor)
        st.session_state.filter_coherence_floor = float(coherence_floor)
    current_filters = _filters_from_state(
        st.session_state.filter_case_id,
        coherence_floor,
    )
    count_loader = getattr(loaders, "get_layer_counts", None)
    try:
        counts = count_loader(current_filters["case_id"], current_filters) if count_loader else None
    except TypeError:
        counts = None
    render_header(
        meta if isinstance(meta, dict) else None,
        labels.get(st.session_state.filter_case_id),
        current_filters,
        counts if isinstance(counts, dict) else None,
        coherence_floor,
    )
    filters = render_filters(
        case_ids,
        labels,
        land_uses,
        risk_levels,
        coherence_floor,
        counts if isinstance(counts, dict) else None,
    )

    requested_tab = st.query_params.get("tab")
    default_tab = requested_tab if requested_tab in TAB_OPTIONS else TAB_MAP
    map_tab, series_tab, hazard_tab, physics_tab = st.tabs(
        TAB_OPTIONS,
        default=default_tab,
        key="cockpit-tabs",
        on_change=_on_tab_change,
    )
    with map_tab:
        _render_map(filters, loaders, meta if isinstance(meta, dict) else None, labels)
    with series_tab:
        render_series_tab(filters, loaders, meta if isinstance(meta, dict) else None)
    with hazard_tab:
        render_hazard_tab(filters, loaders)
    with physics_tab:
        render_physics_tab(loaders, meta if isinstance(meta, dict) else None)
    render_attribution()
    # Written last so a cell picked by the map in this run lands in the URL too.
    _sync_query_params(filters, _active_tab(default_tab))


st.set_page_config(
    page_title=TITLE,
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()
render_app()
