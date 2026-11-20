"""Smoke test: the shell starts on the in-memory mock and renders four tabs."""

from __future__ import annotations

from pathlib import Path

import json
import re

from streamlit.testing.v1 import AppTest

from src.domain.contracts import CASE_IDS

APP = Path(__file__).resolve().parents[1] / "app.py"
ROOT = Path(__file__).resolve().parents[1]


def published_feature_names(case: str) -> list[str]:
    """Names the artefact actually publishes, so this test cannot pin a placeholder."""
    payload = json.loads((ROOT / "data" / "processed" / case / "context_layers.geojson").read_text())
    names = {feature.get("properties", {}).get("name") for feature in payload.get("features", [])}
    return sorted(name for name in names if isinstance(name, str) and name.strip())
TAB_LABELS = (
    "1. Map",
    "2. Series and KPIs",
    "3. Hazard and infrastructure",
    "4. Provenance and limits",
)
FORBIDDEN = ("Guadalquivir", "Doñana", "MALG-01", "B_PERP", "deriva cero", "Sector 4")


def test_context_table_is_paginated_without_dropping_rows() -> None:
    """Tab 3 paints 25 rows per page in a focusable region; off-page rows are hidden from layout and AX."""
    app = AppTest.from_file(APP, default_timeout=90)
    app.query_params["tab"] = TAB_LABELS[2]
    app.run()
    text = "\n".join(node.value for node in app.markdown)
    assert '<div class="cockpit-table-wrap" role="region" aria-label="Context layers" tabindex="0">' in text
    assert 'class="cockpit-table" data-page="1"' in text
    assert re.search(r"Page 1 / \d+ · 25 rows per page", text)
    page1_rows = re.findall(r'<tr[^>]*data-page="1"[^>]*>', text)
    off_rows = re.findall(r'<tr[^>]*data-page="(?!1")\d+"[^>]*>', text)
    assert len(page1_rows) == 25
    assert all("hidden" not in row for row in page1_rows)
    assert off_rows and all('hidden aria-hidden="true"' in row for row in off_rows)

    next_btn = next(btn for btn in app.button if btn.label == "Next page")
    next_btn.click().run()
    text2 = "\n".join(node.value for node in app.markdown)
    assert 'class="cockpit-table" data-page="2"' in text2
    assert re.search(r"Page 2 / \d+ · 25 rows per page", text2)
    page2_rows = re.findall(r'<tr[^>]*data-page="2"[^>]*>', text2)
    page1_after = re.findall(r'<tr[^>]*data-page="1"[^>]*>', text2)
    assert len(page2_rows) == 25
    assert all("hidden" not in row for row in page2_rows)
    assert len(page1_after) == 25 and all('hidden aria-hidden="true"' in row for row in page1_after)


def test_shell_starts_with_mock_and_four_tabs() -> None:
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == list(TAB_LABELS)

    text = "\n".join(node.value for node in app.markdown)
    assert "DEMONSTRATION DATA" in text
    assert "Dancing with the SARs: NISAR Interferometry Cockpit" in text
    assert "Median velocity" in text
    assert "Coherence floor" in text
    assert "Known caveat" in text
    assert "Known limitations" in text
    assert "A context class is not the Land use filter." in text
    assert "not a hazard assessment" in text
    assert "Inelastic" in text
    assert "SAR physics and regime classification" in text
    assert "Declared role:" in text
    # This used to assert "Zócalo Metro Station (synthetic)" — a literal that existed only while the context layer
    # was 12 invented features. The OSM layer publishes real names, so the property worth pinning is that a name
    # the artefact carries reaches the screen.
    names = published_feature_names("mexico-city")
    assert names, "the artefact publishes no feature names at all"
    assert any(name in text for name in names), f"none of {names[:3]} rendered"
    captions = "\n".join(getattr(node, "value", "") for node in getattr(app, "caption", []))
    assert "Linear trend" in captions
    assert "Provenance ID" in captions
    # Tab 3: either empty-state copy or a delivered context summary (st.caption/json).
    hazard = "\n".join(
        [
            *(node.value for node in app.markdown),
            *(getattr(node, "value", "") for node in getattr(app, "caption", [])),
        ]
    )
    assert (
        "No context layers are available" in hazard
        or "Delivered layers" in hazard
        or "n_features" in hazard
        or "Context" in text
    )
    # The layer glossary lived as an import that was never rendered, while the video script promised one.
    assert any(expander.label == "What each layer means" for expander in app.expander), [
        expander.label for expander in app.expander
    ]
    for token in (*FORBIDDEN, "Field Dossier", "mitigaciones", "índices estructurales", "verificado"):
        assert token not in text

    # Streamlit AppTest may surface format_func labels, not raw CASE_IDS slugs.
    assert len(app.selectbox[0].options) == len(CASE_IDS)
    assert not app.sidebar.selectbox


def test_page_title_is_a_heading_and_map_focus_is_visible() -> None:
    from src.ui.theme import _CSS

    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    text = "\n".join(node.value for node in app.markdown)
    assert text.count('<h1 class="mission-title">') == 1
    assert '<p class="mission-title">' not in text
    assert '.st-key-map-slot canvas[role="region"]:focus-visible' in _CSS
    assert 'outline: 2px solid var(--accent)' in _CSS
    mobile_css = _CSS.split('@media (max-width: 640px)', 1)[1]
    assert '[role="tablist"]' in mobile_css
    assert 'flex-wrap: wrap !important' in mobile_css
    assert '[data-testid="stTabsScrollRight"]' in mobile_css
    assert 'display: none !important' in mobile_css


def test_url_params_seed_the_session_and_mirror_back() -> None:
    from src.data import loaders

    valid_cell = str(loaders.get_map_layer_df("jakarta", {})["cell_id"].iloc[0])
    app = AppTest.from_file(APP, default_timeout=60)
    app.query_params["case"] = "jakarta"
    app.query_params["risk"] = "critico"
    app.query_params["extrude"] = "1"
    app.query_params["scale"] = "shared"
    app.query_params["cell"] = valid_cell
    app.run()

    assert not app.exception
    assert app.session_state["filter_case_id"] == "jakarta"
    assert app.session_state["filter_risk_level"] == "critico"
    assert app.session_state["filter_extrude_3d"] is True
    assert app.session_state["scale_mode"] == "shared"
    assert app.session_state["selected_cell_id"] == valid_cell

    qp = app.query_params
    assert qp["case"] == "jakarta"
    assert qp["risk"] == "critico"
    assert qp["extrude"] == "1"
    assert qp["scale"] == "shared"
    assert qp["cell"] == valid_cell


def test_unknown_url_values_are_ignored_and_replaced() -> None:
    app = AppTest.from_file(APP, default_timeout=60)
    app.query_params["case"] = "atlantis"
    app.query_params["coh"] = "7"
    app.query_params["theme"] = "sepia"
    app.query_params["cell"] = "not-a-valid-h3-cell"
    app.run()

    assert not app.exception
    assert app.session_state["filter_case_id"] == CASE_IDS[0]
    assert app.session_state["ui_theme_mode"] == "system"
    assert app.session_state["selected_cell_id"] is None
    # The slider keeps the declared floor and the URL is rewritten to the live state.
    assert 0.0 <= float(app.query_params["coh"]) <= 1.0
    assert app.query_params["case"] == CASE_IDS[0]
    assert "cell" not in app.query_params


def test_active_tab_and_map_ramp_round_trip_in_query_params() -> None:
    app = AppTest.from_file(APP, default_timeout=90)
    app.query_params["tab"] = "3. Hazard and infrastructure"
    app.query_params["ramp"] = "colorblind"
    app.run()

    assert app.session_state["cockpit-tabs"] == "3. Hazard and infrastructure"
    assert app.session_state["map_color_ramp"] == "colorblind"
    assert app.query_params["tab"] == "3. Hazard and infrastructure"
    assert app.query_params["ramp"] == "colorblind"
    from urllib.parse import parse_qs, urlsplit

    share_link = next(item.value for item in app.code if "tab=" in item.value)
    share_query = parse_qs(urlsplit(share_link).query or share_link.lstrip("?"))
    assert share_query["case"] == ["mexico-city"]
    assert share_query["tab"] == ["3. Hazard and infrastructure"]
    assert share_query["ramp"] == ["colorblind"]
    assert not app.exception

    invalid = AppTest.from_file(APP, default_timeout=90)
    invalid.query_params["tab"] = "unknown"
    invalid.query_params["ramp"] = "rainbow"
    invalid.run()
    assert invalid.session_state["cockpit-tabs"] == "1. Map"
    assert invalid.session_state["map_color_ramp"] == "classic"
    assert invalid.query_params["tab"] == "1. Map"
    assert invalid.query_params["ramp"] == "classic"
    assert not invalid.exception


def test_explicit_theme_query_and_theme_selector_update_all_components() -> None:
    app = AppTest.from_file(APP, default_timeout=90)
    app.query_params["theme"] = "light"
    app.run()
    assert app.session_state["ui_theme_mode"] == "light"
    assert 'data-cockpit="light"' in "\n".join(item.value for item in app.markdown)

    theme = next(item for item in app.selectbox if item.label == "Theme")
    theme.set_value("dark").run()
    assert app.session_state["ui_theme_mode"] == "dark"
    assert app.query_params["theme"] == "dark"
    assert 'data-cockpit="dark"' in "\n".join(item.value for item in app.markdown)
    assert not app.exception


def test_tab4_reader_plus_technical_equals_loader_total() -> None:
    from src.data import loaders
    from src.ui.educational import split_caveat, split_technical

    limits = loaders.load_documented_limits()
    items = limits["section_13"]
    visible, technical = split_technical(items)
    assert len(visible) + len(technical) == len(items)
    assert visible and technical, "the fixture must exercise both buckets"
    for text in technical:
        assert len(text) > 220 or "`" in text or re.search(r"O-\d\d", text)

    caveat = limits["section_8_caveat"]
    lead, rest = split_caveat(caveat)
    assert lead and rest
    assert lead.count(". ") < 2
    assert caveat.startswith(lead.rstrip(".")) and caveat.endswith(rest)

    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception
    text = "\n".join(node.value for node in app.markdown)
    n_visible = text.count('class="limit-line"')
    n_tech_items = text.count('class="tech-line item"')
    n_tech_caveat = text.count('class="tech-line caveat"')
    assert n_visible == len(visible)
    assert n_tech_items == len(technical)
    assert n_tech_caveat == 1
    labels = [exp.label for exp in app.expander]
    assert f"Technical notes ({n_tech_items + n_tech_caveat})" in labels


def test_every_figure_declares_a_unit_on_the_y_axis() -> None:
    """Fase 2 (dataviz): no figure ships with a bare 'value' axis."""
    from src.data import loaders
    from src.ui.charts import bars_figure, line_figure, three_cities_figure

    series = loaders.get_case_series("malaga", {})
    bars = loaders.get_land_use_bars("malaga", {})
    meta = loaders.load_meta("malaga")
    frame = loaders.load_timeseries("malaga")
    rows = frame.to_dict(orient="records")

    figures = {
        "line": line_figure(series),
        "three-cities": three_cities_figure({"malaga": rows}, {"malaga": "Málaga, ES"}),
        "bars": bars_figure(bars, meta),
    }
    for name, figure in figures.items():
        y_title = str(figure.layout.yaxis.title.text or "")
        assert "mm" in y_title, (name, y_title)
    # Lines use unified hover; bars use per-mark hover (dataviz skill).
    assert figures["line"].layout.hovermode == "x unified"
    assert figures["three-cities"].layout.hovermode == "x unified"
    assert figures["bars"].layout.hovermode in (None, "closest")
    assert figures["line"].layout.xaxis.rangeslider.visible is True

    # The fitted seasonal term is drawn, never invented when absent.
    assert any(trace.name == "Seasonal fit" for trace in figures["line"].data)
    # Malaga declares a detection limit; the bars must show it as a reference.
    annotations = " ".join(str(a.text) for a in figures["bars"].layout.annotations)
    assert "Detection limit" in annotations
    # One Y axis only, in every figure.
    for name, figure in figures.items():
        assert not any(key.startswith("yaxis") and key != "yaxis" for key in figure.layout), name


def test_compact_query_param_closes_the_filter_strip() -> None:
    compact = AppTest.from_file(APP, default_timeout=60)
    compact.query_params["compact"] = "1"
    compact.run()
    filters = next(e for e in compact.expander if e.label.startswith("Filters"))
    assert filters.proto.expanded is False

    normal = AppTest.from_file(APP, default_timeout=60)
    normal.run()
    # The redesign keeps the filters folded by default so the map owns the first
    # screen; the header chips carry the active-filter summary.
    assert next(e for e in normal.expander if e.label.startswith("Filters")).proto.expanded is False

    opened = AppTest.from_file(APP, default_timeout=60)
    opened.query_params["filters"] = "open"
    opened.run()
    assert next(e for e in opened.expander if e.label.startswith("Filters")).proto.expanded is True


def test_filter_counts_presets_and_removable_chips() -> None:
    from src.data import loaders

    unfiltered = loaders.get_layer_counts(CASE_IDS[0], {})
    dense = loaders.get_layer_counts(CASE_IDS[0], {"land_use": "urban-dense"})
    full_label = f"{unfiltered['shown']} of {unfiltered['total']} cells"
    dense_label = f"{dense['shown']} of {dense['total']} cells"

    app = AppTest.from_file(APP, default_timeout=90)
    app.run()
    assert not app.exception
    assert any(full_label in item.label for item in app.expander)

    land = next(item for item in app.selectbox if item.label == "Land use")
    land.set_value("urban-dense").run()
    assert app.session_state["filter_land_use"] == "urban-dense"
    assert any(dense_label in item.label for item in app.expander)
    next(item for item in app.button if item.label.startswith("× Land")).click().run()
    assert app.session_state["filter_land_use"] == ""
    assert any(full_label in item.label for item in app.expander)

    next(item for item in app.button if item.label == "Reliable signal · ≥ 0.5").click().run()
    assert app.session_state["filter_coherence_min"] >= 0.5
    next(item for item in app.button if item.label == "High risk only").click().run()
    assert app.session_state["filter_risk_level"] == "critico"
    next(item for item in app.button if item.label == "Reset filters").click().run()
    assert app.session_state["filter_coherence_min"] == 0.35
    assert app.session_state["filter_risk_level"] == ""
    assert not app.exception


def test_zero_cell_state_offers_filter_recovery() -> None:
    from src.data import loaders

    total = loaders.get_layer_counts(CASE_IDS[0], {})["total"]
    app = AppTest.from_file(APP, default_timeout=90).run()
    slider = next(item for item in app.slider if item.label == "Minimum coherence")
    slider.set_value(1.0).run()

    assert app.session_state["filter_coherence_min"] == 1.0
    assert any(f"0 of {total} cells" in item.label for item in app.expander)
    assert "No cells match these filters" in "\n".join(item.value for item in app.markdown)
    next(item for item in app.button if item.label == "Lower minimum coherence").click().run()
    assert app.session_state["filter_coherence_min"] == 0.35
    assert not app.exception


def test_case_level_null_state_cites_bound_and_explains_filter_scope() -> None:
    app = AppTest.from_file(APP, default_timeout=90)
    app.query_params["case"] = "malaga"
    app.run()

    text = "\n".join(item.value for item in app.markdown)
    captions = "\n".join(getattr(item, "value", "") for item in app.caption)
    assert (
        "No detectable signal above the detection limit (the neutral band above) of 1.5 mm/year."
        in text
    )
    assert "not an empty filter result" in captions
    assert sum("DEMONSTRATION DATA" in item.value for item in app.markdown) == 1
    assert not app.exception


def test_colorblind_map_ramp_is_selectable_without_changing_case_state() -> None:
    app = AppTest.from_file(APP, default_timeout=90).run()
    ramp = next(item for item in app.radio if item.label == "Ramp")
    ramp.set_value("colorblind").run()
    assert app.session_state["map_color_ramp"] == "colorblind"
    assert app.session_state["filter_case_id"] == CASE_IDS[0]
    assert not app.exception


def test_clear_selection_resets_cell_and_url() -> None:
    from src.data import loaders

    cell = str(loaders.get_map_layer_df(CASE_IDS[0], {})["cell_id"].iloc[0])
    app = AppTest.from_file(APP, default_timeout=60)
    app.query_params["cell"] = cell
    app.run()
    assert app.session_state["selected_cell_id"] == cell

    clear = next(button for button in app.button if button.label == "Clear selection")
    clear.click().run()
    assert app.session_state["selected_cell_id"] is None
    assert "cell" not in app.query_params


def test_h3_selector_updates_the_shareable_cell_state() -> None:
    app = AppTest.from_file(APP, default_timeout=90).run()
    selector = next(item for item in app.selectbox if item.label == "H3 cell")
    cell_id = selector.options[1]
    selector.set_value(cell_id).run()

    assert app.session_state["selected_cell_id"] == cell_id
    assert app.query_params["cell"] == cell_id
    from urllib.parse import parse_qs, urlsplit

    share_link = next(item.value for item in app.code if "cell=" in item.value)
    share_query = parse_qs(urlsplit(share_link).query or share_link.lstrip("?"))
    assert share_query["cell"] == [cell_id]
    assert not app.exception


def test_series_tab_explains_when_selected_cell_has_no_own_series() -> None:
    from src.data import loaders

    cell_id = str(loaders.get_map_layer_df(CASE_IDS[0], {})["cell_id"].iloc[0])
    app = AppTest.from_file(APP, default_timeout=90)
    app.query_params["cell"] = cell_id
    app.query_params["tab"] = "2. Series and KPIs"
    app.run()

    blob = _tab_text(app)
    assert f"Selected H3 cell {cell_id} has no per-cell series" in blob
    assert "showing the whole-area aggregate" in blob
    assert app.session_state["selected_cell_id"] == cell_id
    assert not app.exception


def test_pydeck_selection_event_extracts_the_selected_h3_id() -> None:
    from types import SimpleNamespace

    from src.ui.map_view import LAYER_ID, _selected_cell

    state = SimpleNamespace(selection={"objects": {LAYER_ID: [{"cell_id": "8928308280fffff"}]}})
    assert _selected_cell(state) == "8928308280fffff"
    assert _selected_cell(SimpleNamespace(selection={"objects": {LAYER_ID: []}})) is None


def test_number_format_is_half_up_and_trimmed() -> None:
    from src.ui.formatters import format_number

    assert format_number(-62.065) == "-62.07"
    assert format_number(-62.065, 2) != "-62.06"
    assert format_number(41.3767) == "41.38"
    assert format_number(11694.0) == "11694"
    assert format_number(0.0) == "0"
    assert format_number(None) == "None"


def test_median_velocity_is_one_figure_across_tabs() -> None:
    """P0-3: the same magnitude must not read -62.07 in one tab and -62.06 in another."""
    from src.data import loaders
    from src.ui.formatters import format_number

    expected = format_number(loaders.load_meta(CASE_IDS[0])["stats"]["median_velocity_mm_yr"])
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    text = "\n".join(node.value for node in app.markdown)
    assert text.count(expected) >= 2, (expected, text.count(expected))
    # The raw artefact record may still print -62.065 verbatim; no card may print -62.06.
    assert "-62.06 mm" not in text
    assert ">-62.06<" not in text


def test_tab4_cites_real_nisar_availability() -> None:
    """The demo must prove the real catalogue was searched, without claiming a download."""
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception
    text = "\n".join(node.value for node in app.markdown)
    assert "Real NISAR GUNW availability" in text
    assert "Recommended stack" in text
    assert "Nothing was downloaded for this demo" in text
    assert "granules catalogued" in text


def test_reading_panel_separates_series_scope_from_grid_statistics() -> None:
    """Empty state: the AOI series and the grid medians must not read as one scope."""
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception
    text = "\n".join(node.value for node in app.markdown)
    captions = "\n".join(getattr(node, "value", "") for node in getattr(app, "caption", []))
    blob = text + "\n" + captions
    assert "No cell selected" in blob
    assert "Whole-area aggregate series" in captions
    assert "Grid statistics for the current filter" in captions
    # One provenance line per block: the standalone card is gone in the empty state.
    assert '<p class="kicker">Provenance</p>' not in text


def test_export_buttons_exist_for_grid_context_and_cell() -> None:
    from src.data import loaders

    cell = str(loaders.get_map_layer_df(CASE_IDS[0], {})["cell_id"].iloc[0])
    app = AppTest.from_file(APP, default_timeout=60)
    app.query_params["cell"] = cell
    app.run()
    labels = [button.label for button in app.get("download_button")]
    assert "Export filtered cells (CSV)" in labels
    assert "Export context (CSV)" in labels
    assert "Export selected cell (JSON)" in labels
    assert "Export selected cell series (CSV)" not in labels


def test_selected_cell_series_csv_serializes_only_delivered_rows() -> None:
    from src.ui.map_view import _series_csv

    rows = [
        {
            "case_id": "demo-case",
            "cell_id": "8928308280fffff",
            "date": "2026-01-01",
            "value": -1.25,
            "unit": "mm",
            "provenance_id": "demo-case+mock+20260101+abcdef01",
        }
    ]
    csv = _series_csv(rows)
    assert csv.splitlines()[0] == "case_id,cell_id,date,value,unit,provenance_id"
    assert csv.splitlines()[1].endswith(",-1.25,mm,demo-case+mock+20260101+abcdef01")


def test_context_tab_cross_references_nearest_cell_risk() -> None:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception
    assert any(multiselect.label == "Layer" for multiselect in app.multiselect)
    assert any(select.label == "Nearest cell risk" for select in app.selectbox)
    assert any(button.label == "Jump to cell on Map" for button in app.button)
    text = "\n".join(node.value for node in app.markdown)
    assert "Nearest filtered H3 cell per feature" in text
    assert "not a hazard assessment" in text


def test_physics_topics_cover_roughness_dielectric_and_bands() -> None:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    radio = next(r for r in app.radio if r.label == "Physics topic")
    topics = list(radio.options)
    assert any("L-Band vs C-Band" in topic for topic in topics)
    assert any("Surface Roughness & Dielectric Constant" in topic for topic in topics)
    assert any("Elastic vs Inelastic" in topic for topic in topics)

    radio.set_value(topics[1]).run()
    text = "\n".join(node.value for node in app.markdown)
    assert "Surface roughness." in text
    assert "Dielectric constant." in text


def _render_map_tab_only() -> None:
    """Render Tab 1 alone so per-tab duplication can be counted without the other tabs."""
    import streamlit as st

    from src.data import loaders
    from src.ui.map_view import render_map_tab

    meta = loaders.load_meta("malaga")
    st.session_state.setdefault("ui_theme_mode", "system")
    filters = {
        "case_id": "malaga",
        "land_use": None,
        "coherence_min": 0.35,
        "risk_level": None,
        "extrude_3d": False,
        "scale_mode": "independent",
    }
    render_map_tab(filters, loaders, meta, {"malaga": "Málaga, ES"})


def test_map_tab_shows_provenance_and_kpis_exactly_once() -> None:
    """One visible source per datum inside Tab 1: provenance 1x, each KPI label 1x."""
    from src.data import loaders

    app = AppTest.from_function(_render_map_tab_only, default_timeout=90)
    app.run()
    assert not app.exception

    text = "\n".join(node.value for node in app.markdown)
    captions = "\n".join(getattr(node, "value", "") for node in getattr(app, "caption", []))
    blob = text + "\n" + captions
    provenance_id = loaders.load_meta("malaga")["provenance"]["provenance_id"]

    assert blob.count(provenance_id) == 1, blob.count(provenance_id)
    assert blob.count("Provenance ID") == 1, blob.count("Provenance ID")
    for label in ("Median velocity", "Median displacement", "Minimum coherence"):
        assert blob.count(label) == 1, (label, blob.count(label))
    # Tab 1 no longer duplicates these: seasonal amplitude lives in Tab 2, and the
    # header fields are not repeated inside the map tab.
    assert "Median seasonal amplitude" not in blob
    assert "Sensor nisar" not in blob
    assert "Unit mm" not in blob
    assert "Dates 2024-11-10" not in blob
    assert "Source mock" in blob


def _render_map_tab_with_cell_selected() -> None:
    import streamlit as st

    from src.data import loaders
    from src.ui.map_view import render_map_tab

    case_id = "malaga"
    st.session_state.ui_theme_mode = "system"
    st.session_state.selected_cell_id = str(loaders.get_map_layer_df(case_id, {}).iloc[0]["cell_id"])
    render_map_tab(
        {
            "case_id": case_id,
            "land_use": None,
            "coherence_min": 0.35,
            "risk_level": None,
            "extrude_3d": False,
            "scale_mode": "independent",
        },
        loaders,
        loaders.load_meta(case_id),
        {case_id: "Málaga, ES"},
    )


def test_selected_map_cell_keeps_one_source_and_one_value_for_each_readout() -> None:
    from src.data import loaders

    app = AppTest.from_function(_render_map_tab_with_cell_selected, default_timeout=90).run()
    assert not app.exception
    blob = _tab_text(app)
    source_id = loaders.load_meta("malaga")["provenance"]["provenance_id"]
    assert blob.count(source_id) == 1
    assert blob.count("Provenance ID") == 1
    stats = next(node.value for node in app.markdown if "reading-stats" in node.value)
    inspector = next(node.value for node in app.markdown if 'class="cockpit-card inspector"' in node.value)
    for label in ("Velocity", "Coherence", "Ratio R"):
        assert stats.count(f'class="stat-label">{label}</span>') == 1
        assert f"{label}:" not in inspector


def _render_series_tab_only() -> None:
    from src.data import loaders
    from src.ui.charts import render_series_tab

    case_id = "mexico-city"
    filters = {
        "case_id": case_id,
        "land_use": None,
        "coherence_min": 0.35,
        "risk_level": None,
        "extrude_3d": False,
    }
    render_series_tab(filters, loaders, loaders.load_meta(case_id))


def _render_context_tab_only() -> None:
    from src.data import loaders
    from src.ui.context_view import render_hazard_tab

    render_hazard_tab(
        {
            "case_id": "mexico-city",
            "land_use": None,
            "coherence_min": 0.35,
            "risk_level": None,
            "extrude_3d": False,
        },
        loaders,
    )


def _render_provenance_tab_only() -> None:
    from src.data import loaders
    from src.ui.educational import render_physics_tab

    render_physics_tab(loaders, loaders.load_meta("mexico-city"))


def _tab_text(app) -> str:
    text = "\n".join(
        node.value for node in app.markdown if 'class="cockpit-json"' not in node.value
    )
    captions = "\n".join(getattr(node, "value", "") for node in app.caption)
    return text + "\n" + captions


def test_series_tab_has_one_visible_provenance_and_one_of_each_kpi_label() -> None:
    from src.data import loaders

    app = AppTest.from_function(_render_series_tab_only, default_timeout=90).run()
    assert not app.exception
    blob = _tab_text(app)
    source_id = loaders.load_meta("mexico-city")["provenance"]["provenance_id"]
    assert blob.count(source_id) == 1
    assert blob.count("Provenance ID") == 1
    for label in (
        "Median velocity",
        "Cells above threshold",
        "Critical cells",
        "Coherent coverage",
        "Median seasonal amplitude",
    ):
        assert blob.count(label) == 1, (label, blob.count(label))


def test_context_and_provenance_tabs_show_one_visible_case_source() -> None:
    from src.data import loaders

    for render in (_render_context_tab_only, _render_provenance_tab_only):
        app = AppTest.from_function(render, default_timeout=90).run()
        assert not app.exception
        blob = _tab_text(app)
        source_id = loaders.load_meta("mexico-city")["provenance"]["provenance_id"]
        assert blob.count(source_id) == 1, (render.__name__, blob.count(source_id))
        assert blob.count("Provenance ID") == 1, (render.__name__, blob.count("Provenance ID"))
        if render is _render_provenance_tab_only:
            assert blob.count("Median velocity") == 1


def _render_comparison_only() -> None:
    from src.ui.map_view import _render_comparison

    _render_comparison(
        {
            "mixed_units": False,
            "mixed_sensors": True,
            "mixed_products": True,
            "sensors": ["nisar", "sentinel-1"],
            "products": ["mock", "opera-disp-s1"],
            "cases": [{"id": "mexico-city", "unit": "mm/year", "peak": 1.0, "share": 1.0}],
        },
        "independent",
    )


def _render_comparison_homogeneous() -> None:
    from src.ui.map_view import _render_comparison

    _render_comparison(
        {
            "mixed_units": False,
            "mixed_sensors": False,
            "mixed_products": False,
            "sensors": ["nisar"],
            "products": ["mock"],
            "cases": [{"id": "mexico-city", "unit": "mm/year", "peak": 1.0, "share": 1.0}],
        },
        "independent",
    )


def test_comparison_declares_mixed_sensors_and_products() -> None:
    """`docs/requests.md` asks the UI to surface `mixed_sensors`, not to infer it."""
    app = AppTest.from_function(_render_comparison_only, default_timeout=60).run()
    assert not app.exception
    text = "\n".join(node.value for node in app.markdown)
    assert "mix declared sensors (nisar, sentinel-1)" in text
    assert "mix declared SAR products (mock, opera-disp-s1)" in text

    quiet = AppTest.from_function(_render_comparison_homogeneous, default_timeout=60).run()
    assert not quiet.exception
    assert "mix declared" not in "\n".join(node.value for node in quiet.markdown)
