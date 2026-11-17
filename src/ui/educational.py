"""Tab 4. Quotes README text and the case meta. Does not invent science or a DAAC check."""

from __future__ import annotations

import html
import re
from typing import Any, Mapping

import streamlit as st

from src.ui.formatters import (
    NOT_DECLARED,
    format_json_block,
    format_number,
    humanize,
    safe_inline,
)


def _public_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    return {key: value for key, value in meta.items() if "verif" not in key.lower()}


def _shown(value: Any) -> str:
    if value is None or value == "":
        return NOT_DECLARED
    if isinstance(value, bool):
        return "emitted" if value else "not emitted"
    return format_number(value)


def _stat_card(column: Any, label: str, value: Any, unit: str | None) -> None:
    unit_text = f" {unit}" if unit and value not in (None, "") else ""
    column.markdown(
        '<div class="cockpit-card">'
        f'<p class="kicker">{html.escape(humanize(label))}</p>'
        f'<p class="kpi-value">{html.escape(_shown(value))}{html.escape(unit_text)}</p>'
        "</div>",
        unsafe_allow_html=True,
    )


# Presentation triage (P0-2): the README §13 lines are verbatim backend copy; the UI only
# decides what a jury reads first. Nothing here edits or paraphrases the text.
_TECHNICAL_ID = re.compile(r"O-\d\d")
_TECHNICAL_MAX_CHARS = 220
_CAVEAT_LEAD_SENTENCES = 2


def split_technical(items: list[str] | None) -> tuple[list[str], list[str]]:
    """(reader items, technical items). Technical: >220 chars, backticks, or O-NN ids."""
    visible: list[str] = []
    technical: list[str] = []
    for item in items or []:
        text = str(item)
        if (
            len(text) <= _TECHNICAL_MAX_CHARS
            and "`" not in text
            and not _TECHNICAL_ID.search(text)
        ):
            visible.append(text)
        else:
            technical.append(text)
    return visible, technical


def split_caveat(caveat: str | None) -> tuple[str, str]:
    """First two sentences lead; the rest goes to the technical notes. No text is lost."""
    text = str(caveat or "")
    if not text:
        return "", ""
    segments = text.split(". ")
    if len(segments) <= _CAVEAT_LEAD_SENTENCES:
        return text, ""
    lead = ". ".join(segments[:_CAVEAT_LEAD_SENTENCES]).rstrip(".")
    rest = ". ".join(segments[_CAVEAT_LEAD_SENTENCES:]).strip()
    return f"{lead}.", rest


def _median_from_bridge(loaders: Any, meta: dict[str, Any] | None) -> tuple[Any, Any]:
    """Same key as tab 1: the 'Median velocity' item of `get_map_kpis`, unfiltered."""
    case_id = (meta or {}).get("case_id")
    function = getattr(loaders, "get_map_kpis", None)
    if function is None or not case_id:
        return None, None
    try:
        items = function(str(case_id), {})
    except TypeError:
        return None, None
    for item in items or []:
        if isinstance(item, Mapping) and str(item.get("label", "")).strip().lower() == "median velocity":
            return item.get("value"), item.get("unit")
    return None, None


def _case_block(
    meta: dict[str, Any],
    case_roles: Mapping[str, Any] | None = None,
    median: Any = None,
    median_unit: Any = None,
) -> None:
    stats = meta.get("stats") if isinstance(meta.get("stats"), Mapping) else {}
    cards: list[tuple[str, Any, str | None]] = []
    if isinstance(stats, dict):
        if "dominant_regime" in stats:
            regime = stats.get("dominant_regime")
            cards.append(("dominant_regime", humanize(regime) if regime else regime, None))
        if "median_ratio_R" in stats:
            cards.append(("median_ratio_R", stats.get("median_ratio_R"), None))
        if "median_velocity_mm_yr" in stats:
            # One figure for one magnitude: read the bridge key when available.
            value = median if median is not None else stats.get("median_velocity_mm_yr")
            unit = median_unit if isinstance(median_unit, str) else "mm/year"
            cards.append(("median_velocity_mm_yr", value, unit))
        if "median_seasonal_amp_mm" in stats:
            cards.append(("median_seasonal_amp_mm", stats.get("median_seasonal_amp_mm"), "mm"))
        if "detection_limit_mm_yr" in stats:
            cards.append(("detection_limit_mm_yr", stats.get("detection_limit_mm_yr"), "mm/year"))
        if isinstance(stats.get("n_cells"), int) and not isinstance(stats.get("n_cells"), bool):
            cards.append(("n_cells", stats.get("n_cells"), None))
        series = stats.get("per_cell_series")
        if isinstance(series, dict) and "enabled" in series:
            cards.append(("per_cell_series.enabled", series.get("enabled"), None))
    # The DEMONSTRATION DATA banner is the single mock notice; no prose repetition.
    case_note = "Values come from the delivered artefact."
    case_id = str(meta.get("case_id") or "")
    role_info = (case_roles or {}).get(case_id) if isinstance(case_roles, Mapping) else None
    role_lines = ""
    if isinstance(role_info, Mapping):
        role_text = role_info.get("role")
        exp_regime = role_info.get("expected_regime")
        pub_rate = role_info.get("published_rate_mm_yr")
        details: list[str] = []
        if role_text:
            details.append(f"Declared role: {role_text}")
        if exp_regime:
            details.append(f"Expected regime: {humanize(exp_regime)}")
        if isinstance(pub_rate, (int, float)) and not isinstance(pub_rate, bool):
            details.append(f"Literature reference rate: {format_number(pub_rate)} mm/year")
        if details:
            role_lines = f'<p class="kpi-note">{" · ".join(html.escape(part) for part in details)}</p>'
    st.markdown(
        '<div class="cockpit-card">'
        '<p class="kicker">Case</p>'
        f'<p class="kpi-note">{html.escape(case_note)}</p>'
        f"{role_lines}"
        "</div>",
        unsafe_allow_html=True,
    )
    if cards:
        columns = st.columns(len(cards))
        for column, (label, value, unit) in zip(columns, cards):
            _stat_card(column, label, value, unit)
        provenance = meta.get("provenance") if isinstance(meta.get("provenance"), Mapping) else {}
        source_id = meta.get("provenance_id") or provenance.get("provenance_id") or NOT_DECLARED
        st.caption(f"Provenance ID {source_id}")
    null_policy = meta.get("null_policy")
    if null_policy:
        with st.expander("How missing data is recorded", expanded=False):
            st.markdown(f"<p>{safe_inline(null_policy)}</p>", unsafe_allow_html=True)
    limitations = meta.get("limitations")
    if isinstance(limitations, list) and limitations:
        st.markdown(
            '<div class="cockpit-card">'
            '<p class="kicker">Limits of this artefact</p>'
            + "".join(f"<p>- {safe_inline(item)}</p>" for item in limitations)
            + "</div>",
            unsafe_allow_html=True,
        )


def _availability_block(loaders: Any, meta: dict[str, Any] | None) -> None:
    """Cite the ASF search record: real stacks exist, nothing was downloaded."""
    function = getattr(loaders, "load_availability", None)
    case_id = (meta or {}).get("case_id")
    if function is None or not case_id:
        return
    try:
        info = function(str(case_id))
    except TypeError:
        return
    if not isinstance(info, Mapping):
        return
    available = bool(info.get("available"))
    product = str((meta or {}).get("product") or NOT_DECLARED)
    state = "available" if available else "not available"
    if product == "mock":
        headline = f"From the ASF search record ({state}). Nothing was downloaded for this demo."
    else:
        headline = f"From the ASF search record ({state}). Published artefact: {product}."
    lines: list[str] = []
    if available:
        stacks = [s for s in info.get("stacks") or [] if isinstance(s, Mapping)]
        recommended = next((s for s in stacks if s.get("recommended")), stacks[0] if stacks else None)
        if recommended:
            date_range = recommended.get("date_range")
            window = ""
            if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
                window = f" · {str(date_range[0])[:10]} → {str(date_range[1])[:10]}"
            lines.append(
                f"Recommended stack: track {recommended.get('track')} "
                f"{str(recommended.get('direction') or '').lower()}"
                f" · frame {recommended.get('frame')} · {recommended.get('n_granules')} granules"
                f"{window}"
            )
        if len(stacks) > 1:
            others = ", ".join(
                f"{s.get('track')} {str(s.get('direction') or '').lower()[:4]}" for s in stacks if s is not recommended
            )
            lines.append(f"{len(stacks)} stacks catalogued in total · also {others}")
    else:
        lines.append(f"Search result: {info.get('error') or 'no intersecting NISAR GUNW stack declared'}")
    run = str(info.get("generated_utc") or NOT_DECLARED)
    http_status = info.get("http_status")
    granules = info.get("n_granules")
    summary = f"Search {run} · HTTP {http_status if http_status is not None else NOT_DECLARED}"
    if isinstance(granules, int) and not isinstance(granules, bool):
        summary += f" · {granules} granules catalogued"
    coverage = info.get("coverage_note")
    coverage_html = f'<p class="kpi-note">{safe_inline(coverage)}</p>' if coverage else ""
    body = "".join(f'<p class="detail-line">{safe_inline(line)}</p>' for line in lines)
    st.markdown(
        '<div class="cockpit-card">'
        '<p class="kicker">Real NISAR GUNW availability</p>'
        f'<p class="kpi-note">{html.escape(headline)}</p>'
        f"{body}{coverage_html}"
        f'<p class="kpi-note">{html.escape(summary)}</p>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_physics_tab(loaders: Any, meta: dict[str, Any] | None) -> None:
    limits = getattr(loaders, "load_documented_limits", lambda: {})()
    has_meta = isinstance(meta, dict) and bool(meta)
    has_docs = isinstance(limits, dict) and bool(limits.get("section_8_caveat") or limits.get("section_13"))
    if not has_meta and not has_docs:
        st.markdown(
            '<div class="cockpit-card is-empty">'
            '<p class="kicker">Education</p>'
            '<p class="empty-prompt">Educational notes are not available for this case yet.</p>'
            "</div>",
            unsafe_allow_html=True,
        )
        return

    if has_meta:
        case_roles = limits.get("case_roles") if isinstance(limits, Mapping) else None
        median, median_unit = _median_from_bridge(loaders, meta)
        _case_block(
            meta,
            case_roles if isinstance(case_roles, Mapping) else None,
            median,
            median_unit,
        )
        _availability_block(loaders, meta)
    else:
        st.markdown(
            '<div class="cockpit-card is-empty">'
            '<p class="kicker">Case</p>'
            '<p class="empty-prompt">The loader did not return case meta.</p>'
            "</div>",
            unsafe_allow_html=True,
        )

    science_summary = limits.get("science_section_1") if isinstance(limits, Mapping) else None
    physics = limits.get("physics") if isinstance(limits, Mapping) else None
    if science_summary or physics:
        with st.expander("How this measurement works (SAR physics)", expanded=False):
            st.markdown(
                '<p class="kpi-note"><strong>SAR physics and regime classification</strong> · from '
                "docs/science-guide.md §1, README.md and the frozen contract in "
                "src/domain/contracts.py.</p>",
                unsafe_allow_html=True,
            )
            if science_summary:
                st.markdown(f"<p>{safe_inline(science_summary)}</p>", unsafe_allow_html=True)
            if isinstance(physics, list) and physics:
                by_title = {
                    str(item.get("title", "")).lower(): str(item.get("text", ""))
                    for item in physics
                    if isinstance(item, Mapping)
                }
                topics = (
                    "1. L-Band vs C-Band Penetration",
                    "2. Surface Roughness & Dielectric Constant",
                    "3. Elastic vs Inelastic Regime R",
                )
                topic = st.radio(
                    "Physics topic",
                    options=list(topics),
                    horizontal=True,
                    key=f"physics-topic-{(meta or {}).get('case_id') or 'case'}",
                )
                if topic.startswith("1."):
                    st.markdown(
                        f'<p>{safe_inline(by_title.get("l-band vs c-band", ""))}</p>',
                        unsafe_allow_html=True,
                    )
                elif topic.startswith("2."):
                    st.markdown(
                        f'<p><strong>Surface roughness.</strong> '
                        f'{safe_inline(by_title.get("surface roughness", ""))}</p>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<p><strong>Dielectric constant.</strong> '
                        f'{safe_inline(by_title.get("dielectric constant", ""))}</p>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<p>A <strong>secular</strong> trend is motion that does not come back; a '
                        "<strong>seasonal</strong> term is the part that does. The regime index compares "
                        "them; the class says which one dominates the cell.</p>",
                        unsafe_allow_html=True,
                    )
            st.markdown(
                '<p class="detail-line"><strong>Regime index R = |velocity| / seasonal amplitude:</strong> '
                "R &gt; 2 Inelastic (secular trend dominates, permanent compaction) · "
                "1 &le; R &le; 2 Transitional (mixed regime) · "
                "R &lt; 1 Elastic (seasonal cycle dominates, recoverable motion).</p>",
                unsafe_allow_html=True,
            )

    caveat = limits.get("section_8_caveat") if isinstance(limits, dict) else None
    caveat_lead, caveat_rest = split_caveat(caveat)
    items = limits.get("section_13") if isinstance(limits, dict) else None
    visible, technical = split_technical(items)
    note_lines = [f'<p class="tech-line caveat">{safe_inline(caveat_rest)}</p>'] if caveat_rest else []
    note_lines += [f'<p class="tech-line item">- {safe_inline(item)}</p>' for item in technical]
    notes_count = len(note_lines)
    st.markdown(
        '<div class="cockpit-card">'
        '<p class="kicker">Known caveat</p>'
        '<p class="kpi-note">From the project documentation, not from the case artefact.</p>'
        + (f'<p class="caveat-lead">{safe_inline(caveat_lead)}</p>' if caveat_lead
           else "<p>No documented caveat for this case.</p>")
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="cockpit-card">'
        '<p class="kicker">Known limitations</p>'
        '<p class="kpi-note">From the project documentation, not from the case artefact.</p>'
        + ("".join(f'<p class="limit-line">- {safe_inline(item)}</p>' for item in visible)
           or "<p>No reader-level limitations; see the technical notes below.</p>")
        + "</div>",
        unsafe_allow_html=True,
    )
    if notes_count:
        with st.expander(f"Technical notes ({notes_count})", expanded=False):
            st.caption(
                "Same loader text, not trimmed. Internal ids, file paths and long method notes "
                "live here."
            )
            st.markdown("".join(note_lines), unsafe_allow_html=True)

    shown = _public_meta(meta)
    if not shown:
        meta_note = "The loader did not return meta.json."
    else:
        meta_note = "The case identifier is shown above and omitted from the record below."
    with st.expander("Other meta.json fields", expanded=False):
        st.caption(meta_note)
        st.markdown(
            format_json_block(shown, "meta.json contents"),
            unsafe_allow_html=True,
        )
