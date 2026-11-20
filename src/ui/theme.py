"""Palette, type and the only CSS injection point. No data and no science."""

from __future__ import annotations

from typing import Any

import streamlit as st

# Dark is the locked cockpit. Light is the same instrument on paper: same roles,
# high-contrast inks (AAA body & secondary text, 6.7:1 accent).
DARK = {
    "bg": "#0B0F19",
    "surface": "#0F172A",
    "border": "#1E293B",
    # Delimiting boundaries (cards, inputs, tabs, tracks) must clear 3:1
    # against both bg and surface: WCAG 2.2 1.4.11.
    "border-strong": "#64748B",
    "accent": "#06B6D4",
    "coherence": "#10B981",
    "alert": "#F59E0B",
    "coral": "#F43F5E",
    # Tinted chip inks: the base hue on a 14% tint does not always clear 4.5:1.
    "coherence-ink": "#34D399",
    "alert-ink": "#FBBF24",
    "coral-ink": "#FDA4AF",
    "text": "#F8FAFC",
    "muted": "#CBD5E1",
    "focus": "#141F36",
    "on-accent": "#0B0F19",
}
LIGHT = {
    "bg": "#F1F5F9",
    "surface": "#FFFFFF",
    "border": "#94A3B8",
    "border-strong": "#64748B",
    "accent": "#0B647D",
    "coherence": "#047857",
    "alert": "#9A3412",
    "coral": "#BE123C",
    "coherence-ink": "#046C4E",
    "alert-ink": "#9A3412",
    "coral-ink": "#9F1239",
    "text": "#0B1220",
    "muted": "#334155",
    "focus": "#E0F2FE",
    "on-accent": "#FFFFFF",
}
BG = DARK["bg"]
SURFACE = DARK["surface"]
BORDER = DARK["border"]
ACCENT = DARK["accent"]
COHERENCE = DARK["coherence"]
ALERT = DARK["alert"]
CORAL = DARK["coral"]
TEXT = DARK["text"]
MUTED = "#94A3B8"
FOCUS = DARK["focus"]
RADIUS = "4px"

# Design tokens: dimensions, typography, borders, shadow and motion are declared
# here so the presentation layer has one source of visual values.
DESIGN_TOKENS = {
    "space-0": "0",
    "space-1": "4px",
    "space-2": "8px",
    "space-3": "12px",
    "space-4": "16px",
    "space-6": "24px",
    "space-8": "32px",
    "space-12": "48px",
    "radius-sm": "2px",
    "radius-md": RADIUS,
    "border-width": "1px",
    "shadow-menu": "0 4px 12px rgba(0, 0, 0, 0.14)",
    # One 12 -> 28 px scale (seven steps, ~1.15-1.2 apart). Every text size in
    # the cockpit resolves to one of these; 12 px is the floor.
    "type-xs": "0.75rem",
    "type-sm": "0.875rem",
    "type-md": "1rem",
    "type-lg": "1.125rem",
    "type-xl": "1.25rem",
    "type-2xl": "1.5rem",
    "type-3xl": "1.75rem",
    "weight-regular": "400",
    "weight-medium": "500",
    "weight-semibold": "600",
    "leading-tight": "1.2",
    "leading-snug": "1.35",
    "leading-normal": "1.5",
    "leading-relaxed": "1.6",
    "measure": "72ch",
    "motion-fast": "180ms",
    "motion-standard": "200ms",
}

#: Categorical identity slots for the three cities, fixed order, validated with
#: `dataviz/scripts/validate_palette.py` on both cockpit surfaces. Every slot clears
#: 3:1 against both `surface` (`paper_bgcolor`) and `bg` (`plot_bgcolor`), and every
#: line still carries a direct end label so color is never the sole channel.
CASE_COLORS = {
    "light": {"mexico-city": "#2a78d6", "jakarta": "#e26432", "malaga": "#189a6b"},
    "dark": {"mexico-city": "#3987e5", "jakarta": "#d95926", "malaga": "#199e70"},
}

# Diverging velocity ramps, all stops at the same normalized positions.
# `colorblind` uses a blue / neutral / vermilion sequence (not red vs green).
MAP_RAMPS = {
    "classic": (
        (0.0, (244, 63, 94, 200)),
        (0.5, (245, 158, 11, 200)),
        (1.0, (6, 182, 212, 200)),
    ),
    "colorblind": (
        (0.0, (0, 114, 178, 200)),
        (0.5, (225, 225, 225, 200)),
        (1.0, (213, 94, 0, 200)),
    ),
}
MAP_RAMP_LABELS = {
    "classic": "Original · contract ramp",
    "colorblind": "Colorblind-friendly · blue / neutral / orange",
}
# Light basemaps are pale: the raw ramp (vermilion/amber/cyan) sits below 3:1 on
# paper. Shade the same hues, never the data, so every non-neutral cell keeps its
# boundary while the legend draws the identical gradient.
MAP_LIGHT_SHADE = 0.60
MAP_DARK_LIFT = 0.18


def map_ramp(ramp: str, scheme: str | None = None) -> tuple[tuple[float, tuple[int, int, int, int]], ...]:
    """Return the ramp the map and its legend paint for a scheme."""
    stops = MAP_RAMPS.get(ramp, MAP_RAMPS["classic"])
    if scheme == "light":
        return tuple(
            (
                position,
                (
                    round(red * MAP_LIGHT_SHADE),
                    round(green * MAP_LIGHT_SHADE),
                    round(blue * MAP_LIGHT_SHADE),
                    alpha,
                ),
            )
            for position, (red, green, blue, alpha) in stops
        )
    if scheme == "dark" and ramp == "colorblind":
        return tuple(
            (
                position,
                (
                    round(red + (255 - red) * MAP_DARK_LIFT),
                    round(green + (255 - green) * MAP_DARK_LIFT),
                    round(blue + (255 - blue) * MAP_DARK_LIFT),
                    alpha,
                ),
            )
            for position, (red, green, blue, alpha) in stops
        )
    return stops

FONT_DISPLAY = '"Space Grotesk", "Segoe UI", system-ui, sans-serif'
FONT_BODY = '"Inter", "Segoe UI", system-ui, sans-serif'
FONT_MONO = '"JetBrains Mono", "DejaVu Sans Mono", ui-monospace, monospace'
_CHART_FONT = "JetBrains Mono, ui-monospace, monospace"


def _decls(tokens: dict[str, str]) -> str:
    return "\n".join(f"  --{name}: {value};" for name, value in tokens.items())


def reported_scheme() -> str | None:
    """Resolve active scheme from user override first, then Streamlit system context."""
    try:
        chosen = st.session_state.get("ui_theme_mode")
    except Exception:
        chosen = None
    if chosen in ("light", "dark"):
        return str(chosen)
    try:
        kind = st.context.theme.type
    except Exception:
        return None
    if kind in ("light", "dark"):
        return kind
    return None


def active_palette() -> dict[str, str]:
    """Palette for server-rendered figures. Chrome CSS does not need this."""
    if reported_scheme() == "light":
        return LIGHT
    return DARK


def case_color(case_id: str) -> str:
    """Identity color for a case (fixed slot, never by rank or filter order)."""
    scheme = "light" if reported_scheme() == "light" else "dark"
    palette = CASE_COLORS[scheme]
    return palette.get(str(case_id), active_palette()["muted"])


def style_figure(
    figure: Any,
    *,
    height: int,
    x_title: str,
    y_title: str,
    margin: dict[str, int] | None = None,
) -> None:
    """Paint a Plotly figure with the active palette. No data transform."""
    palette = active_palette()
    figure.update_layout(
        height=height,
        margin=margin or {"l": 52, "r": 18, "t": 20, "b": 42},
        paper_bgcolor=palette["surface"],
        plot_bgcolor=palette["bg"],
        font={"color": palette["text"], "family": _CHART_FONT, "size": 11},
        hoverlabel={
            "bgcolor": palette["surface"],
            "bordercolor": palette["border"],
            "font": {"color": palette["text"], "family": _CHART_FONT, "size": 11},
        },
    )
    axis_border = palette.get("border-strong", palette["border"])
    axis = {
        "gridcolor": palette["border"],
        "zerolinecolor": axis_border,
        "linecolor": axis_border,
        "tickfont": {"color": palette["text"], "family": _CHART_FONT, "size": 11},
        "title_font": {"color": palette["muted"], "family": _CHART_FONT, "size": 11},
        "automargin": True,
        "title_standoff": 8,
    }
    figure.update_xaxes(title=x_title, **axis)
    figure.update_yaxes(title=y_title, **axis)


_CSS = f"""
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap");

:root {{
  --radius: var(--radius-md);
  --card-pad-y: var(--space-2);
  --card-pad-x: var(--space-4);
  --gap: var(--space-3);
  --map-height: clamp(415px, calc(100vh - 485px), 700px);
  --font-display: {FONT_DISPLAY};
  --font-body: {FONT_BODY};
  --font-mono: {FONT_MONO};
{_decls(DESIGN_TOKENS)}
{_decls(DARK)}
  color-scheme: dark;
}}

@media (prefers-color-scheme: light) {{
  :root {{
{_decls(LIGHT)}
    color-scheme: light;
  }}
}}

:root:has([data-cockpit="dark"]),
.stApp:has([data-cockpit="dark"]) {{
{_decls(DARK)}
  color-scheme: dark;
}}

:root:has([data-cockpit="light"]),
.stApp:has([data-cockpit="light"]) {{
{_decls(LIGHT)}
  color-scheme: light;
}}

html,
body,
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {{
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: var(--font-body);
}}

[data-testid="stHeader"] {{
  background: transparent !important;
  height: 1.75rem !important;
}}

[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] {{
  display: none !important;
}}

.block-container {{
  padding-top: var(--space-6) !important;
  padding-bottom: var(--space-4) !important;
  padding-left: clamp(var(--space-3), 2.2vw, var(--space-8)) !important;
  padding-right: clamp(var(--space-3), 2.2vw, var(--space-8)) !important;
  width: 100% !important;
  max-width: none !important;
  box-sizing: border-box;
}}

[data-testid="stVerticalBlock"] {{
  gap: var(--space-3) !important;
}}

.mission-bar {{
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  background: var(--surface);
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius);
  padding: var(--space-1) var(--space-4);
  margin: 0;
  box-sizing: border-box;
}}

.mission-bar .mission-title {{
  flex: 1 1 24rem;
  min-width: 0;
}}

.mission-line {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}}

.mission-facts {{
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--space-2);
  min-width: 0;
}}

.mission-chip {{
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 var(--space-2);
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text) !important;
  font-family: var(--font-body);
  font-size: var(--type-xs);
  font-weight: var(--weight-medium);
  line-height: var(--leading-tight);
  white-space: nowrap;
}}

.mission-chip.is-active {{
  border-color: var(--accent);
  color: var(--accent) !important;
}}

/* Mobile telemetry: the full line is hidden on small screens (media query below),
   so a compact chip carries the same artefact-sourced values one tap away. */
.telemetry-disclosure {{
  display: none;
}}

.telemetry-chip {{
  cursor: pointer;
  list-style: none;
}}
.telemetry-chip::-webkit-details-marker {{
  display: none;
}}
.telemetry-chip:focus-visible {{
  outline: 2px solid var(--focus) !important;
  outline-offset: 2px !important;
}}
.telemetry-disclosure .telemetry-detail {{
  margin-top: var(--space-1);
}}

/* Streamlit's element container carries margin-bottom: -1rem; with that native
   pull the banner started 4 px inside the header box. Neutralise it for the two
   chrome blocks and keep a clean 7 px separation. */
/* Streamlit's markdown container carries margin-bottom: -1rem natively; that is
   what pulled the banner 4 px inside the header box. Neutralise it on the two
   chrome blocks and keep a clean ~8 px separation. */
[data-testid="stMarkdownContainer"]:has(> .mission-bar),
[data-testid="stMarkdownContainer"]:has(> .demo-banner) {{
  margin-bottom: calc(-1 * var(--space-1)) !important;
}}

.mission-bar .mission-title,
.mission-bar .mission-title span {{
  font-family: var(--font-display) !important;
  font-size: clamp(var(--type-xl), 2vw, var(--type-2xl)) !important;
  font-weight: var(--weight-semibold) !important;
  letter-spacing: -0.02em;
  line-height: var(--leading-tight) !important;
  color: var(--text) !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: visible !important;
  white-space: normal !important;
  height: auto !important;
  max-height: none !important;
  max-width: none;
}}

.mission-bar .mission-title .case-pill {{
  display: inline-flex;
  vertical-align: middle;
  margin-left: var(--space-3) !important;
  padding: var(--space-1) var(--space-2) !important;
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--accent) !important;
  font-family: var(--font-mono) !important;
  font-size: var(--type-xs) !important;
  font-weight: var(--weight-medium) !important;
  letter-spacing: 0;
  line-height: var(--leading-tight);
}}

.mission-bar .telemetry {{
  margin: 0;
}}

.telemetry {{
  font-family: var(--font-mono);
  font-size: var(--type-xs);
  letter-spacing: 0.02em;
  color: var(--muted) !important;
  margin: 0;
  line-height: var(--leading-normal);
  overflow: visible;
  word-break: break-word;
  overflow-wrap: anywhere;
  white-space: normal;
}}

.demo-banner {{
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  margin: 0;
  padding: var(--space-1) var(--space-3);
  border: var(--border-width) solid var(--alert);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--alert) 12%, var(--surface));
  color: var(--alert) !important;
  font-family: var(--font-mono);
  font-size: var(--type-xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.08em;
  line-height: var(--leading-tight);
  box-sizing: border-box;
}}

.cockpit-card,
.viewport {{
  background: var(--surface);
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius);
  padding: var(--card-pad-y) var(--card-pad-x);
  box-shadow: none;
  min-width: 0;
  width: 100%;
  box-sizing: border-box;
}}

.cockpit-card {{
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  height: 100%;
  overflow: visible;
  margin-bottom: 0;
}}

.cockpit-card.is-empty {{
  min-height: 6.5rem;
  justify-content: center;
  gap: var(--space-1);
}}

.viewport {{
  min-height: var(--map-height);
}}

.kicker {{
  font-family: var(--font-body);
  font-size: var(--type-xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--accent) !important;
  margin: 0;
  line-height: var(--leading-tight);
}}

.section-head {{
  font-family: var(--font-display);
  font-size: var(--type-xl);
  font-weight: var(--weight-semibold);
  line-height: var(--leading-tight);
  color: var(--text) !important;
  margin: 0;
}}

.group-head {{
  font-family: var(--font-display);
  font-size: var(--type-lg);
  font-weight: var(--weight-semibold);
  line-height: var(--leading-snug);
  color: var(--text) !important;
  margin: 0 0 var(--space-1);
  padding-bottom: var(--space-1);
  border-bottom: var(--border-width) solid var(--border-strong);
}}

.limits-grid p {{
  font-family: var(--font-body);
  font-size: var(--type-xs);
  line-height: var(--leading-normal);
  color: var(--text) !important;
  margin: 0 0 var(--space-1);
  max-width: var(--measure);
  break-inside: avoid;
}}

@media (min-width: 900px) {{
  .limits-grid {{
    column-count: 2;
    column-gap: var(--space-6);
  }}
}}

.cockpit-card p,
.viewport p {{
  font-family: var(--font-body);
  font-size: var(--type-md);
  color: var(--text) !important;
  margin: 0;
  line-height: var(--leading-normal);
  max-width: var(--measure);
  overflow-wrap: anywhere;
}}

.cockpit-card .kicker {{
  font-family: var(--font-body);
  font-size: var(--type-xs);
  color: var(--accent) !important;
}}

.cockpit-card .empty-prompt {{
  font-family: var(--font-body);
  font-size: var(--type-md);
  line-height: var(--leading-normal);
  color: var(--text) !important;
  margin: 0;
}}

.cockpit-card .kpi-value {{
  font-family: var(--font-mono);
  font-size: var(--type-2xl);
  font-weight: var(--weight-semibold);
  line-height: var(--leading-tight);
  color: var(--text) !important;
  margin: 0;
  word-break: break-word;
}}

.cockpit-card .kpi-note {{
  font-family: var(--font-body);
  font-size: var(--type-xs);
  line-height: var(--leading-normal);
  color: var(--muted) !important;
  margin: 0;
}}

.cockpit-card p code,
.cockpit-card li code {{
  background: var(--bg);
  color: var(--accent);
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1);
  font-family: var(--font-mono);
  font-size: var(--type-xs);
}}

.cockpit-card .detail-head {{
  font-family: var(--font-body);
  font-size: var(--type-xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--accent) !important;
  margin: var(--space-2) 0 var(--space-1) !important;
}}

.cockpit-card .detail-head:first-of-type {{
  margin-top: 0 !important;
}}

.cockpit-card .detail-line {{
  font-family: var(--font-mono);
  font-size: var(--type-sm);
  line-height: var(--leading-normal);
  color: var(--text) !important;
  margin: 0;
  padding: var(--space-1) 0;
  border-bottom: var(--border-width) solid color-mix(in srgb, var(--border) 55%, transparent);
  word-break: break-word;
  overflow-wrap: anywhere;
}}

.cockpit-card.inspector {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: var(--space-1) var(--space-3);
  align-content: start;
}}

.cockpit-card.inspector .detail-line {{
  font-size: var(--type-sm);
  line-height: var(--leading-normal);
  padding: var(--space-1) 0;
}}

.cockpit-card.inspector .detail-head {{
  grid-column: 1 / -1;
  margin-top: var(--space-2);
}}

.cockpit-card.inspector .detail-head:first-child {{
  margin-top: 0;
}}

.cockpit-card .detail-line:last-child {{
  border-bottom: 0;
}}

.cockpit-card .chip {{
  align-self: flex-start;
  margin: var(--space-1) 0 var(--space-1);
}}

.chip {{
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  border: var(--border-width) solid var(--border-strong);
  background: color-mix(in srgb, var(--coherence) 14%, var(--surface));
  color: var(--coherence-ink) !important;
  font-family: var(--font-body);
  font-size: var(--type-xs);
  font-weight: var(--weight-semibold);
  line-height: var(--leading-tight);
}}

.chip-alert {{
  border-color: var(--border-strong);
  background: color-mix(in srgb, var(--alert) 14%, var(--surface));
  color: var(--alert-ink) !important;
}}

.chip-coral {{
  border-color: var(--border-strong);
  background: color-mix(in srgb, var(--coral) 14%, var(--surface));
  color: var(--coral-ink) !important;
}}

.swatch {{
  display: inline-block;
  width: var(--space-3);
  height: var(--space-3);
  margin-right: var(--space-2);
  border: var(--border-width) solid var(--border-strong);
  vertical-align: middle;
}}

.chip-muted {{
  border-color: var(--border-strong);
  background: var(--bg);
  color: var(--text) !important;
}}

.cockpit-json {{
  margin: var(--space-2) 0 0;
  padding: var(--space-3) var(--space-4);
  background-color: var(--bg) !important;
  color: var(--text) !important;
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: var(--type-sm);
  line-height: var(--leading-relaxed);
  overflow-x: auto;
  box-sizing: border-box;
  opacity: 1 !important;
}}

.cockpit-json .json-line {{
  font-family: var(--font-mono) !important;
  font-size: var(--type-sm) !important;
  line-height: var(--leading-relaxed) !important;
  color: var(--text) !important;
  white-space: pre-wrap;
  word-break: break-word;
}}

.cockpit-json .json-key,
[data-testid="stMarkdownContainer"] .cockpit-json .json-key {{
  color: var(--accent) !important;
  -webkit-text-fill-color: var(--accent) !important;
  font-weight: var(--weight-semibold) !important;
}}

.cockpit-json .json-punct,
.cockpit-json .json-val,
[data-testid="stMarkdownContainer"] .cockpit-json .json-punct,
[data-testid="stMarkdownContainer"] .cockpit-json .json-val {{
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
}}

[data-testid="stMarkdownPre"],
[data-testid="stCode"],
[data-testid="stMarkdownPre"] pre,
[data-testid="stMarkdownPre"] code {{
  background-color: var(--bg) !important;
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  border-color: var(--border) !important;
}}

.cockpit-table-wrap {{
  width: 100%;
  overflow: auto;
  max-height: min(70vh, 640px);
  margin-top: var(--space-2);
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius);
  background-color: var(--bg) !important;
  color: var(--text) !important;
  color-scheme: inherit;
}}

.context-pager {{
  margin: 0;
  text-align: center;
  font-family: var(--font-mono);
  font-size: var(--type-xs);
  color: var(--muted) !important;
  line-height: var(--leading-normal);
}}

.cockpit-table {{
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: var(--type-sm);
  background-color: var(--bg) !important;
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
}}

.cockpit-table th,
.cockpit-table td,
[data-testid="stMarkdownContainer"] table th,
[data-testid="stMarkdownContainer"] table td {{
  padding: var(--space-2) var(--space-3) !important;
  text-align: left;
  border: var(--border-width) solid color-mix(in srgb, var(--border) 65%, transparent) !important;
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  background-color: var(--bg) !important;
  vertical-align: top;
}}

.cockpit-table th,
[data-testid="stMarkdownContainer"] table th {{
  background-color: color-mix(in srgb, var(--accent) 12%, var(--surface)) !important;
  color: var(--accent) !important;
  -webkit-text-fill-color: var(--accent) !important;
  font-weight: var(--weight-semibold) !important;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 2;
}}

.cockpit-table tr:last-child td {{
  border-bottom: 0;
}}

.cockpit-table tbody tr.row-alert > td {{
  background: color-mix(in srgb, var(--coral) 12%, transparent) !important;
}}

.cockpit-table tbody tr.row-alert > td:first-child {{
  border-left: 3px solid var(--coral) !important;
  font-weight: var(--weight-medium);
}}

.cockpit-table tbody tr.row-alert > td:first-child::before {{
  content: "▲ ";
  color: var(--coral);
  font-weight: var(--weight-semibold);
}}

.cockpit-table tbody tr.row-warn > td:first-child::before {{
  content: "▲ ";
  color: var(--alert);
  font-weight: var(--weight-semibold);
}}

.cockpit-table tbody tr.row-warn > td {{
  background: color-mix(in srgb, var(--alert) 10%, transparent) !important;
}}

.cockpit-table tbody tr.row-warn > td:first-child {{
  border-left: 3px solid var(--alert) !important;
}}

.cockpit-table tbody tr:hover td {{
  background: color-mix(in srgb, var(--accent) 8%, var(--surface)) !important;
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
}}

/* Compact strip under the map (plan Fase 1): ramp + ticks + mode + provenance. */
/* Compact ramp row for the reading panel: label, gradient, range, scale mode. */
.legend-inline {{
  display: flex;
  flex-direction: row;
  flex-wrap: nowrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  min-height: 0;
}}

@media (max-width: 640px) {{
  [data-testid="stTabs"] [role="tablist"] {{
    display: flex !important;
    flex-wrap: wrap !important;
    overflow: visible !important;
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    gap: var(--space-2) !important;
    padding-inline: 0 !important;
  }}
  [data-testid="stTabs"] [data-testid="stTabsScrollLeft"],
  [data-testid="stTabs"] [data-testid="stTabsScrollRight"] {{
    display: none !important;
  }}
  .legend-inline {{
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
  }}
  .legend-inline-label {{
    grid-column: 1 / -1;
    white-space: normal;
  }}
  .legend-inline .legend-bar {{
    grid-column: 1 / -1;
    width: 100%;
    flex: none;
    order: 0;
  }}
  .legend-inline-range {{
    grid-column: 1;
    margin-left: 0;
    white-space: normal;
  }}
  .legend-flag {{
    grid-column: 2;
    justify-self: end;
  }}
}}

.legend-inline .legend-bar {{
  flex: 1 1 auto;
  min-width: 70px;
  height: 8px;
  margin: 0;
}}

.legend-inline-label,
.legend-inline-range {{
  font-family: var(--font-mono);
  font-size: var(--type-xs);
  letter-spacing: 0.02em;
  color: var(--muted) !important;
  white-space: nowrap;
  min-width: 0;
}}

.legend-inline-label {{
  text-transform: uppercase;
  overflow: visible;
  text-overflow: clip;
  max-width: none;
  flex: 0 0 auto;
}}

.legend-flag {{
  color: var(--alert) !important;
}}

.legend-details {{
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}}

.legend-details .legend-meta,
.legend-details .kpi-note {{
  margin: 0;
}}

.legend-meta {{
  margin: 0;
  font-family: var(--font-body);
  font-size: var(--type-xs);
  color: var(--muted) !important;
  line-height: var(--leading-normal);
  max-width: var(--measure);
}}

/* Reading panel (right column). */
.reading-head .reading-title {{
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--type-xl);
  font-weight: var(--weight-semibold);
  color: var(--text) !important;
  line-height: var(--leading-tight);
  word-break: break-all;
}}

.reading-stats {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-2);
  padding: var(--space-3) var(--card-pad-x);
}}

.reading-stat {{
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}}

.reading-stat .stat-value {{
  font-family: var(--font-mono);
  font-size: var(--type-xl);
  font-weight: var(--weight-semibold);
  line-height: var(--leading-tight);
  color: var(--text) !important;
  white-space: normal;
}}

.reading-stat .stat-unit {{
  font-size: var(--type-xs);
  font-weight: var(--weight-medium);
  color: var(--muted) !important;
}}

.reading-stat .stat-label {{
  font-family: var(--font-body);
  font-size: var(--type-xs);
  letter-spacing: 0.01em;
  line-height: var(--leading-snug);
  color: var(--muted) !important;
  text-transform: none;
}}

.legend-bar {{
  height: 12px;
  width: 100%;
  border-radius: var(--radius);
  border: var(--border-width) solid var(--border-strong);
  box-sizing: border-box;
}}

.null-note {{
  margin: 0;
  padding: var(--space-3) var(--space-4);
  background: var(--surface);
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius);
  color: var(--text) !important;
  font-family: var(--font-body);
  font-size: var(--type-md);
  line-height: var(--leading-normal);
  max-width: var(--measure);
  box-sizing: border-box;
}}

/* Streamlit 1.67 React Aria Selectbox & VirtualDropdown (Selectbox.7rsxE6LC.js) */
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label,
[data-testid="stWidgetLabel"] span {{
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
  font-weight: var(--weight-medium) !important;
  letter-spacing: 0;
  text-transform: none;
  color: var(--muted) !important;
  background: transparent !important;
  opacity: 1 !important;
}}

[data-testid="stSelectbox"] div:has(> input),
[data-testid="stSelectbox"] .equpb2c0,
[data-baseweb="select"] > div {{
  background-color: var(--bg) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  color: var(--text) !important;
}}

[data-testid="stSelectbox"] div:has(> input):focus-within,
[data-testid="stSelectbox"] .equpb2c0[data-focus-within] {{
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px var(--accent) !important;
}}

[data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] .equpb2c4 {{
  background-color: transparent !important;
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  caret-color: var(--text) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
  font-weight: var(--weight-medium) !important;
  opacity: 1 !important;
}}

[data-testid="stSelectbox"] input::placeholder {{
  color: var(--muted) !important;
  -webkit-text-fill-color: var(--muted) !important;
  opacity: 1 !important;
}}

[data-testid="stSelectbox"] button,
[data-testid="stSelectbox"] svg {{
  color: var(--text) !important;
  fill: var(--text) !important;
  background: transparent !important;
}}

/* Virtualized dropdown popup portal */
[data-testid="stSelectboxVirtualDropdown"],
[data-testid="stSelectboxVirtualDropdown"] [role="listbox"],
[data-testid="stSelectboxVirtualDropdown"] ul,
[data-baseweb="popover"],
[data-baseweb="menu"],
ul[data-baseweb="menu"] {{
  background-color: var(--surface) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  color: var(--text) !important;
  box-shadow: var(--shadow-menu) !important;
}}

[data-testid="stSelectboxVirtualDropdown"] [role="option"],
[data-testid="stSelectboxVirtualDropdown"] [data-item-hl],
[data-testid="stSelectboxVirtualDropdown"] li,
[data-baseweb="popover"] [role="option"],
ul[data-baseweb="menu"] li {{
  background-color: var(--surface) !important;
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
  font-weight: var(--weight-regular) !important;
  opacity: 1 !important;
}}

[data-testid="stSelectboxVirtualDropdown"] [role="option"] *,
[data-testid="stSelectboxVirtualDropdown"] [data-item-hl] * {{
  color: inherit !important;
  -webkit-text-fill-color: inherit !important;
}}

[data-testid="stSelectboxVirtualDropdown"] [role="option"][data-hovered] [data-item-hl],
[data-testid="stSelectboxVirtualDropdown"] [role="option"][data-focused] [data-item-hl],
[data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover [data-item-hl],
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"] [data-item-hl],
[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="popover"] [aria-selected="true"] {{
  background-color: color-mix(in srgb, var(--accent) 16%, var(--surface)) !important;
  color: var(--accent) !important;
  -webkit-text-fill-color: var(--accent) !important;
  font-weight: var(--weight-semibold) !important;
}}

/* Multiselect (tab 3 layer picker) uses the same input and tag tokens. */
[data-testid="stMultiSelect"] div:has(> input),
[data-testid="stMultiSelect"] [data-baseweb="select"] > div {{
  background-color: var(--bg) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  color: var(--text) !important;
}}

[data-testid="stMultiSelect"] input {{
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
}}

[data-testid="stMultiSelect"] [data-baseweb="tag"] {{
  background-color: var(--surface) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  color: var(--text) !important;
}}

[data-testid="stMultiSelect"] [data-baseweb="tag"] * {{
  color: var(--text) !important;
  -webkit-text-fill-color: var(--text) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-xs) !important;
}}

/* Deck.gl / Mapbox attribution: legal text must stay legible over either basemap. */
.mapboxgl-ctrl-attrib,
.maplibregl-ctrl-attrib {{
  background: var(--surface) !important;
  color: var(--text) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius-sm) !important;
}}

.mapboxgl-ctrl-attrib a,
.maplibregl-ctrl-attrib a,
.mapboxgl-ctrl-attrib-inner,
.maplibregl-ctrl-attrib-inner {{
  color: var(--text) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-xs) !important;
  text-decoration: underline;
}}

/* Radio, Toggle, Slider, Captions, Markdown */
/* Toggle: Streamlit 1.67 renders it as stCheckbox with role="switch". The off
   track, the on track and the thumb each clear 3:1 against the surface, and the
   clickable label + track clear the 24x24 CSS px target floor (WCAG 2.2 2.5.8). */
[data-testid="stCheckbox"] label {{
  min-height: 24px !important;
  display: inline-flex !important;
  align-items: center !important;
}}

[data-testid="stCheckbox"] label:has(input[role="switch"]) > div:nth-of-type(1) {{
  min-width: 36px !important;
  min-height: 24px !important;
  height: 24px !important;
  border-radius: 12px !important;
  display: inline-flex !important;
  align-items: center !important;
  background-color: var(--border-strong) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  opacity: 1 !important;
}}

[data-testid="stCheckbox"] label:has(input[role="switch"]:checked) > div:nth-of-type(1) {{
  background-color: var(--accent) !important;
  border-color: var(--accent) !important;
}}

[data-testid="stCheckbox"] label:has(input[role="switch"]) > div:first-of-type > div {{
  width: 18px !important;
  height: 18px !important;
  background-color: var(--text) !important;
  border: var(--border-width) solid var(--border-strong) !important;
}}

[data-testid="stCheckbox"] label:has(input[role="switch"]:checked) > div:first-of-type > div {{
  background-color: var(--on-accent) !important;
  border-color: var(--on-accent) !important;
}}

/* Slider (React Aria in 1.67): rail, thumb and value bubble all tokenized.
   The thumb is 20 px + 2 px border = 24x24 CSS px (WCAG 2.2 2.5.8). */
[data-testid="stSlider"] [role="group"] > div > div:first-child {{
  background-color: var(--border-strong) !important;
  border-radius: var(--radius-sm);
}}

[data-testid="stSlider"] [role="group"] div[style*="translate"] {{
  width: 20px !important;
  height: 20px !important;
  min-width: 24px !important;
  min-height: 24px !important;
  background-color: var(--on-accent) !important;
  border: 2px solid var(--accent) !important;
  box-sizing: border-box !important;
}}

[data-testid="stSliderThumbValue"] {{
  background: var(--accent) !important;
  color: var(--on-accent) !important;
  border-radius: var(--radius-sm) !important;
  padding: 0 var(--space-1) !important;
}}

[data-testid="stSliderThumbValue"] * {{
  color: var(--on-accent) !important;
  font-family: var(--font-mono) !important;
  font-size: var(--type-xs) !important;
  font-weight: var(--weight-medium) !important;
  opacity: 1 !important;
}}

[data-testid="stSliderThumbValue"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSliderThumbValue"] [data-testid="stMarkdownContainer"] span {{
  color: var(--on-accent) !important;
  -webkit-text-fill-color: var(--on-accent) !important;
}}

[data-testid="stSliderTickBar"],
[data-testid="stSliderTickBar"] * {{
  color: var(--muted) !important;
  font-family: var(--font-mono) !important;
  font-size: var(--type-xs) !important;
  opacity: 1 !important;
}}

/* Compact expander header so the filter strip does not push the map down.
   Closed details must also hide their body from hit-testing under 1.4.12 spacing. */
[data-testid="stExpander"] details {{
  border: var(--border-width) solid var(--border-strong) !important;
  background: var(--surface) !important;
  border-radius: var(--radius) !important;
}}

[data-testid="stExpander"] details:not([open]) > :not(summary) {{
  display: none !important;
}}

[data-testid="stExpander"] summary {{
  min-height: 24px !important;
  background: var(--surface) !important;
  padding: var(--space-2) var(--space-3) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
  font-weight: var(--weight-medium) !important;
  letter-spacing: 0;
  text-transform: none;
  color: var(--text) !important;
}}

[data-testid="stExpander"] summary p {{
  color: var(--text) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
  font-weight: var(--weight-medium) !important;
  margin-bottom: 0 !important;
}}

[data-testid="stRadioOption"] {{
  min-height: 24px !important;
  min-width: 24px !important;
  display: inline-flex !important;
  align-items: center !important;
}}

[data-testid="stRadio"] label,
[data-testid="stRadio"] label *,
[data-testid="stCheckbox"] label,
[data-testid="stCheckbox"] label *,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span {{
  color: var(--text) !important;
  opacity: 1 !important;
}}

/* Segmented scale control: outlined segments, never a full-width solid fill.
   Streamlit 1.67 renders each segment as <button role="radio" data-variant="segmented_control">.
   The unselected native background is the light theme's #F1F5F9 even when our CSS tokens follow
   ?theme=dark, so it must be overridden explicitly to keep the label at >= 4.5:1 in both themes. */
[data-variant="segmented_control"] {{
  min-height: 24px !important;
  min-width: 24px !important;
  background: var(--bg) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius-sm) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
}}
[data-variant="segmented_control"] p,
[data-variant="segmented_control"] [data-testid="stMarkdownContainer"] {{
  color: var(--text) !important;
}}
[data-variant="segmented_control"][aria-checked="true"] {{
  border-color: var(--accent) !important;
}}
[data-variant="segmented_control"][aria-checked="true"] p,
[data-variant="segmented_control"][aria-checked="true"] [data-testid="stMarkdownContainer"] {{
  color: var(--accent) !important;
}}
[data-variant="segmented_control"]:focus-visible {{
  outline: 2px solid var(--focus) !important;
  outline-offset: 2px !important;
}}

[data-testid="stRadioOption"] > div > div:first-child {{
  border-color: var(--border-strong) !important;
  background-color: var(--bg) !important;
}}

[data-testid="stRadioOption"][data-selected] > div > div:first-child {{
  border-color: var(--accent) !important;
  background-color: var(--accent) !important;
}}

[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] * {{
  color: var(--muted) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-xs) !important;
  line-height: var(--leading-normal) !important;
  opacity: 1 !important;
}}

[data-testid="stCaptionContainer"] {{
  max-width: var(--measure);
}}

.kpi-note {{
  max-width: var(--measure);
}}

[data-testid="stMarkdownContainer"] code,
.cockpit-json code,
[data-testid="stCaptionContainer"] code {{
  background: var(--bg) !important;
  color: var(--accent) !important;
  -webkit-text-fill-color: var(--accent) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius-sm) !important;
  padding: 0 var(--space-1) !important;
  font-family: var(--font-mono) !important;
  font-size: var(--type-xs) !important;
}}

/* Plotly & Deck.gl tooltips */
[data-testid="stPlotlyChart"] {{
  background: var(--surface) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  padding: var(--space-2) var(--space-3) !important;
  color: var(--text) !important;
  box-sizing: border-box;
  overflow: hidden;
}}

[data-testid="stPlotlyChart"] svg text {{
  fill: var(--text) !important;
}}

.deck-tooltip {{
  background: var(--surface) !important;
  color: var(--text) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  font-family: var(--font-mono) !important;
  font-size: var(--type-xs) !important;
  line-height: var(--leading-normal) !important;
  padding: var(--space-1) var(--space-3) !important;
  box-shadow: none !important;
  pointer-events: auto !important;
}}

.deck-tooltip:hover {{
  display: block !important;
}}

.deck-tooltip[data-dismissed="true"] {{
  display: none !important;
}}

/* Tabs: force resting text color on inner <p>/<span> so it never hides until hover */
[data-testid="stTabs"] [role="tablist"] {{
  display: flex;
  flex-wrap: nowrap;
  overflow-x: auto;
  gap: var(--space-2);
  padding: var(--space-1) 0 var(--space-3);
  border-bottom: var(--border-width) solid var(--border-strong);
  background: transparent !important;
  scrollbar-width: thin;
}}

[data-testid="stTabs"] [role="tab"] {{
  flex: 0 0 auto;
  padding: var(--space-2) var(--space-3) !important;
  min-height: 2.5rem !important;
  background: var(--surface) !important;
  color: var(--text) !important;
  border: var(--border-width) solid var(--border-strong) !important;
  border-radius: var(--radius) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
  font-weight: var(--weight-medium) !important;
  letter-spacing: 0;
  white-space: nowrap;
  opacity: 1 !important;
  transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease,
    border-color var(--motion-fast) ease;
}}

[data-testid="stTabs"] [role="tab"] *,
[data-testid="stTabs"] [role="tab"] p,
[data-testid="stTabs"] [role="tab"] span {{
  color: var(--text) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
  opacity: 1 !important;
}}

[data-testid="stTabs"] [role="tab"]:hover {{
  border-color: var(--accent) !important;
  color: var(--accent) !important;
}}

[data-testid="stTabs"] [role="tab"]:hover *,
[data-testid="stTabs"] [role="tab"]:hover p,
[data-testid="stTabs"] [role="tab"]:hover span {{
  color: var(--accent) !important;
}}

[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
  background: color-mix(in srgb, var(--accent) 14%, var(--surface)) !important;
  color: var(--accent) !important;
  border-color: var(--accent) !important;
}}

[data-testid="stTabs"] [role="tab"][aria-selected="true"] *,
[data-testid="stTabs"] [role="tab"][aria-selected="true"] p,
[data-testid="stTabs"] [role="tab"][aria-selected="true"] span {{
  color: var(--accent) !important;
  font-weight: var(--weight-semibold) !important;
}}

.stButton > button,
[data-testid="stPopoverButton"],
[data-testid="stPopover"] > button,
[data-testid="stDownloadButton"] button,
[data-testid="stBaseButton-secondary"] {{
  width: auto;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
  background: color-mix(in srgb, var(--accent) 10%, var(--surface)) !important;
  color: var(--accent) !important;
  border: var(--border-width) solid var(--accent) !important;
  border-radius: var(--radius) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
  font-weight: var(--weight-medium) !important;
  text-transform: none;
  letter-spacing: 0;
  line-height: var(--leading-tight);
  transition: color var(--motion-fast) ease, background-color var(--motion-fast) ease,
    border-color var(--motion-fast) ease;
}}

.stButton > button *,
[data-testid="stPopoverButton"] *,
[data-testid="stPopover"] > button *,
[data-testid="stDownloadButton"] button *,
[data-testid="stBaseButton-secondary"] * {{
  color: var(--accent) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
}}

.stButton > button:hover,
[data-testid="stPopoverButton"]:hover,
[data-testid="stPopover"] > button:hover,
[data-testid="stDownloadButton"] button:hover,
[data-testid="stBaseButton-secondary"]:hover {{
  background: var(--accent) !important;
  color: var(--on-accent) !important;
  border-color: var(--accent) !important;
}}

.stButton > button:hover *,
[data-testid="stPopoverButton"]:hover *,
[data-testid="stPopover"] > button:hover *,
[data-testid="stDownloadButton"] button:hover *,
[data-testid="stBaseButton-secondary"]:hover * {{
  color: var(--on-accent) !important;
}}

.stButton > button:focus-visible,
[data-testid="stPopoverButton"]:focus-visible,
[data-testid="stDownloadButton"] button:focus-visible,
[data-testid="stTabs"] [role="tab"]:focus-visible {{
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}}

/* Keep chrome above the map. Deck.gl canvases are position:absolute. */
.mission-bar,
.demo-banner,
.st-key-filters,
[data-testid="stTabs"] [role="tablist"] {{
  position: relative;
  z-index: 6;
}}

/* Responsive flex grid across all column blocks */
[data-testid="stHorizontalBlock"] {{
  display: flex !important;
  flex-wrap: wrap !important;
  align-items: stretch !important;
  gap: var(--space-3) !important;
  width: 100% !important;
  min-width: 0;
}}

[data-testid="stColumn"],
[data-testid="column"] {{
  min-width: 13rem !important;
  flex: 1 1 13rem !important;
  max-width: 100%;
  box-sizing: border-box;
}}

.st-key-filters [data-testid="stHorizontalBlock"] {{
  align-items: center !important;
}}

.st-key-filters [data-testid="stColumn"],
.st-key-filters [data-testid="column"] {{
  min-width: 10.5rem !important;
  flex: 1 1 10.5rem !important;
}}

.st-key-filter-actions [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
.st-key-filter-actions [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {{
  flex: 0 0 12rem !important;
  min-width: 12rem !important;
}}

.st-key-filter-actions [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
.st-key-filter-actions [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {{
  flex: 0 0 10rem !important;
  min-width: 10rem !important;
  margin-left: auto;
}}

.st-key-filter-actions [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:not(:first-child):not(:last-child),
.st-key-filter-actions [data-testid="stHorizontalBlock"] > [data-testid="column"]:not(:first-child):not(:last-child) {{
  flex: 1 1 8rem !important;
  min-width: 8rem !important;
}}

.st-key-filters [data-testid="stHorizontalBlock"]:has([data-testid="stPopover"]) {{
  margin-top: calc(-1 * var(--space-1));
}}

.st-key-filters [data-testid="stPopover"] > button,
.st-key-filters .stButton > button {{
  min-height: var(--space-8) !important;
  padding: 0 var(--space-2) !important;
  font-size: var(--type-xs) !important;
  line-height: var(--leading-tight) !important;
}}

button[aria-label^="Help for"],
.st-key-filters button[aria-label^="Help for"] {{
  min-width: 24px !important;
  min-height: 24px !important;
  width: 24px !important;
  height: 24px !important;
  padding: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  color: var(--muted) !important;
  background: transparent !important;
}}

[data-testid="stMultiSelect"] button,
[data-testid="stSelectbox"] button {{
  min-width: 24px !important;
  min-height: 24px !important;
}}

.st-key-filters button[aria-label^="Help for"] svg,
.st-key-filters button[aria-label^="Help for"] svg * {{
  color: var(--muted) !important;
  stroke: var(--muted) !important;
  fill: none !important;
}}

/* Plan Fase 1: the map row is 2:1, not the flat equal split of the global rule. */
.st-key-map-grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
.st-key-map-grid [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child {{
  flex: 2 1 0 !important;
  min-width: 0 !important;
}}

.st-key-map-grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
.st-key-map-grid [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {{
  flex: 1 1 0 !important;
  min-width: 0 !important;
}}

.st-key-map-grid {{
  margin-top: calc(-1 * var(--space-3)) !important;
}}

.st-key-reading-slot [data-testid="stHorizontalBlock"] {{
  flex-wrap: nowrap !important;
  gap: var(--space-2) !important;
}}

.st-key-reading-slot [data-testid="stColumn"],
.st-key-reading-slot [data-testid="column"] {{
  min-width: 0 !important;
}}

.st-key-map-slot {{
  position: relative;
  z-index: 0;
  isolation: isolate;
  width: 100%;
  max-width: 100%;
  height: var(--map-height) !important;
  min-height: var(--map-height) !important;
  max-height: var(--map-height) !important;
  flex: 0 0 auto !important;
  overflow: hidden !important;
  padding: 0 !important;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-sizing: border-box;
  contain: layout paint;
}}

.st-key-map-slot [data-testid="stVerticalBlock"],
.st-key-map-slot [data-testid="stElementContainer"],
.st-key-map-slot [data-testid="stDeckGlJsonChart"] {{
  position: relative !important;
  width: 100% !important;
  max-width: 100% !important;
  height: var(--map-height) !important;
  max-height: var(--map-height) !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
  gap: 0 !important;
}}

.st-key-map-slot #deckgl-wrapper,
.st-key-map-slot .maplibregl-map,
.st-key-map-slot .mapboxgl-map {{
  position: absolute !important;
  inset: 0 !important;
  width: 100% !important;
  height: 100% !important;
  max-height: var(--map-height) !important;
  overflow: hidden !important;
}}

.st-key-map-slot canvas {{
  max-width: 100% !important;
  max-height: var(--map-height) !important;
}}

.st-key-map-slot canvas[role="region"]:focus-visible {{
  outline: 2px solid var(--accent) !important;
  outline-offset: -4px !important;
  border-radius: var(--radius);
}}

.st-key-map-slot [data-testid="stElementToolbar"] {{
  right: 3rem !important;
  top: var(--space-2) !important;
}}

/* KPI cards in one row must share a height: stretch the column chain and let
   the card grow, so a two-line note no longer leaves a ragged bottom. */
[data-testid="stHorizontalBlock"]:has(.kpi-value) {{
  align-items: stretch !important;
}}

[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="stColumn"],
[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="column"] {{
  align-self: stretch !important;
}}

[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="stColumn"],
[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="stColumn"] > div,
[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="stColumn"] [data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="stColumn"] [data-testid="stElementContainer"],
[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="stColumn"] [data-testid="stMarkdown"],
[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="stColumn"] [data-testid="stMarkdown"] > div,
[data-testid="stHorizontalBlock"]:has(.kpi-value) > [data-testid="stColumn"] [data-testid="stMarkdownContainer"] {{
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  height: 100%;
  min-height: 0;
}}

[data-testid="stHorizontalBlock"]:has(.kpi-value) [data-testid="stMarkdownContainer"] {{
  margin-bottom: 0 !important;
}}

/* Six-up rows (the case stats) are single-line notes: a shorter equal card keeps
   tab 4 under 1.5 screens without breaking the 5/3-up rows. */
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(6)) .cockpit-card:has(.kpi-value) {{
  min-height: 96px;
}}

[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(6))
  .cockpit-card:has(.kpi-value) .kpi-value {{
  font-size: var(--type-xl);
}}

.cockpit-card:has(.kpi-value) {{
  flex: 1 1 auto;
  /* Above the tallest note in the three tabs (2-line notes reach 112 px, the
     layer-count list 121 px), so every card in a row ends at the same edge. */
  min-height: 124px;
  justify-content: space-between;
}}

.compare-card {{
  gap: var(--space-2);
}}

.compare-row {{
  display: grid;
  grid-template-columns: minmax(6.5rem, 8.5rem) minmax(5rem, 1fr) minmax(11rem, auto);
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-1) 0;
  font-family: var(--font-mono);
  font-size: var(--type-sm);
  color: var(--text) !important;
  min-width: 0;
}}

.compare-case {{
  color: var(--text) !important;
  font-weight: var(--weight-semibold);
}}

.compare-meta {{
  color: var(--muted) !important;
  text-align: right;
  overflow-wrap: anywhere;
}}

.compare-track {{
  width: 100%;
  min-width: 0;
  height: 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}}

.compare-fill {{
  height: 100%;
  background: var(--accent);
}}

[data-baseweb="tab-panel"][aria-hidden="true"],
[data-baseweb="tab-panel"][hidden] {{
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
  overflow: hidden !important;
  pointer-events: none !important;
}}

[data-baseweb="tab-panel"][aria-hidden="true"] canvas,
[data-baseweb="tab-panel"][hidden] canvas {{
  display: none !important;
}}

.stApp {{
  scrollbar-color: var(--border) var(--bg);
}}

::selection {{
  background: color-mix(in srgb, var(--accent) 28%, transparent);
  color: var(--text);
}}

/* Tablet landscape / small laptop */
@media (max-width: 1180px) {{
  .st-key-filters [data-testid="stColumn"],
  .st-key-filters [data-testid="column"] {{
    flex: 1 1 calc(33.333% - 0.75rem) !important;
    min-width: 11.5rem !important;
  }}
}}

/* Phone: the header must not eat the first screen */
@media (max-width: 768px) {{
  .mission-bar {{
    padding: var(--space-1) 0 var(--space-2);
    gap: var(--space-1);
  }}
  .mission-bar .mission-title,
  .mission-bar .mission-title span {{
    font-size: var(--type-xl) !important;
    line-height: var(--leading-tight) !important;
  }}
  .mission-bar .telemetry,
  .telemetry {{
    font-size: var(--type-xs);
    line-height: var(--leading-normal);
  }}
  .mission-bar .telemetry:not(.telemetry-detail) {{
    display: none;
  }}
  .telemetry-disclosure {{
    display: block;
    margin-top: var(--space-1);
  }}
  [data-testid="stTabs"] [role="tab"] {{
    min-height: 2.25rem !important;
    padding: var(--space-1) var(--space-2) !important;
  }}
}}

/* Tablet portrait: stack map and inspector full width */
@media (max-width: 960px) {{
  :root {{
    --map-height: clamp(360px, 52vh, 520px);
  }}
  [data-testid="stHorizontalBlock"]:has(.st-key-map-slot) > [data-testid="stColumn"],
  [data-testid="stHorizontalBlock"]:has(.st-key-map-slot) > [data-testid="column"] {{
    flex: 1 1 100% !important;
    min-width: 100% !important;
    width: 100% !important;
  }}
  /* The 2:1 map row must stack too. The 2:1 rule wins on specificity because of
     :first-child, so the stacking override needs the same pseudo-classes. */
  .st-key-map-grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child,
  .st-key-map-grid [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child,
  .st-key-map-grid [data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child,
  .st-key-map-grid [data-testid="stHorizontalBlock"] > [data-testid="column"]:last-child {{
    flex: 1 1 100% !important;
    min-width: 100% !important;
    width: 100% !important;
  }}
  .compare-row {{
    grid-template-columns: minmax(6rem, auto) 1fr;
  }}
  .compare-meta {{
    grid-column: 1 / -1;
    text-align: left;
  }}
  .st-key-reading-slot [data-testid="stHorizontalBlock"] {{
    flex-wrap: wrap !important;
  }}
  .st-key-reading-slot [data-testid="stColumn"],
  .st-key-reading-slot [data-testid="column"] {{
    flex: 1 1 100% !important;
    width: 100% !important;
  }}
}}

/* Mobile phones */
@media (max-width: 640px) {{
  :root {{
    --card-pad-y: 0.75rem;
    --card-pad-x: 0.85rem;
    --map-height: clamp(300px, 46vh, 420px);
  }}
  .block-container {{
    padding-top: var(--space-6) !important;
    padding-left: var(--space-3) !important;
    padding-right: var(--space-3) !important;
  }}
  [data-testid="stColumn"],
  [data-testid="column"],
  .st-key-filters [data-testid="stColumn"],
  .st-key-filters [data-testid="column"] {{
    flex: 1 1 100% !important;
    min-width: 100% !important;
    width: 100% !important;
  }}
  .mission-bar {{
    padding: var(--space-3) var(--space-4) !important;
  }}
  .compare-row {{
    grid-template-columns: 1fr;
    gap: var(--space-1);
  }}
  .st-key-reading-slot [data-testid="stHorizontalBlock"] {{
    flex-wrap: wrap !important;
  }}
  .st-key-reading-slot [data-testid="stColumn"],
  .st-key-reading-slot [data-testid="column"] {{
    flex: 1 1 100% !important;
    width: 100% !important;
  }}
}}

/* Keyboard focus must be visible on every control (plan Fase 3). */
a:focus-visible,
button:focus-visible,
summary:focus-visible,
input:focus-visible,
[role="tab"]:focus-visible,
[role="switch"]:focus-visible,
[role="combobox"]:focus-visible,
.cockpit-table-wrap:focus-visible {{
  outline: 2px solid var(--accent) !important;
  outline-offset: 2px !important;
}}

[data-testid="stCheckbox"] label:has(input:focus-visible) > div:nth-of-type(1),
[data-testid="stSlider"] [role="group"]:has(input:focus-visible) div[style*="translate"] {{
  outline: 2px solid var(--accent) !important;
  outline-offset: 2px !important;
}}

[data-testid="stExpander"] summary:focus-visible {{
  outline: 2px solid var(--accent) !important;
  outline-offset: -2px !important;
}}

/* One animation only: the hero figure fades in when the selection changes. */
@keyframes cockpit-plot-in {{
  from {{ opacity: 0.35; }}
  to {{ opacity: 1; }}
}}

.js-plotly-plot {{
  animation: cockpit-plot-in var(--motion-fast) ease-out both;
}}

.kpi-unit {{
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: var(--type-sm);
  font-weight: var(--weight-medium);
  margin-left: var(--space-1);
}}

.status-chip {{
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 var(--space-2);
  border: var(--border-width) solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--type-xs);
  font-weight: var(--weight-semibold);
  line-height: var(--leading-tight);
}}

.status-coherence,
.status-quality {{
  border-color: var(--border-strong);
  color: var(--coherence-ink);
}}

.status-moderate {{
  border-color: var(--border-strong);
  color: var(--alert-ink);
}}

.status-critical {{
  border-color: var(--border-strong);
  color: var(--coral-ink);
}}

.empty-icon {{
  display: grid;
  place-items: center;
  width: 2rem;
  height: 2rem;
  flex: 0 0 2rem;
  border: var(--border-width) solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--accent);
  font: 600 var(--type-lg) var(--font-mono);
}}

.cockpit-card.is-empty {{
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
}}

.cockpit-skeleton {{
  gap: var(--space-2);
}}

.skeleton-bar {{
  display: block;
  height: 12px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--muted) 18%, var(--surface));
}}

.skeleton-bar:nth-of-type(2) {{ width: 76%; }}
.skeleton-bar:nth-of-type(3) {{ width: 58%; }}

[data-testid="stIconMaterial"] {{
  display: inline-block;
  width: 1em;
  height: 1em;
  overflow: hidden;
  line-height: 1;
}}

.sr-only {{
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}}

/* Last-word control polish: some Streamlit emotion rules paint widget labels and
   virtual dropdowns with the light theme's secondary background even when the
   cockpit is dark. These selectors are intentionally last in the sheet. */
[data-testid="stCheckbox"] label [data-testid="stWidgetLabel"],
[data-testid="stCheckbox"] label [data-testid="stWidgetLabel"] *,
[data-testid="stWidgetLabel"] {{
  background-color: transparent !important;
  color: var(--muted) !important;
}}

[data-testid="stMultiSelect"] > div,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div {{
  background-color: var(--bg) !important;
}}

[data-testid="stMultiSelectVirtualDropdown"],
[data-testid="stMultiSelectVirtualDropdown"] [role="listbox"],
[data-testid="stMultiSelectVirtualDropdown"] ul,
[data-testid="stMultiSelectVirtualDropdown"] li,
[data-testid="stMultiSelectVirtualDropdown"] [role="option"] {{
  background-color: var(--surface) !important;
  color: var(--text) !important;
  border-color: var(--border-strong) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-sm) !important;
}}

[data-testid="stMultiSelect"] [data-baseweb="tag"],
[data-testid="stMultiSelect"] [data-baseweb="tag"] span {{
  background-color: var(--surface) !important;
  color: var(--text) !important;
  border-color: var(--border-strong) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-xs) !important;
}}

/* Raw HTML chips live inside Streamlit's markdown container, whose generic
   span/p colours are more specific than the component class. Restore the
   semantic ink with an equally specific selector. */
[data-testid="stMarkdownContainer"] .chip,
.stApp .chip {{
  color: var(--coherence-ink) !important;
  font-family: var(--font-body) !important;
  font-size: var(--type-xs) !important;
}}

[data-testid="stMarkdownContainer"] .chip-alert,
.stApp .chip-alert {{
  color: var(--alert-ink) !important;
}}

[data-testid="stMarkdownContainer"] .chip-coral,
.stApp .chip-coral {{
  color: var(--coral-ink) !important;
}}

[data-testid="stMarkdownContainer"] .chip-muted,
.stApp .chip-muted {{
  color: var(--text) !important;
}}

[data-testid="stMarkdownContainer"] .status-chip,
.stApp .status-chip {{
  color: var(--text) !important;
  font-family: var(--font-mono) !important;
  font-size: var(--type-xs) !important;
}}

[data-testid="stMarkdownContainer"] .status-coherence,
[data-testid="stMarkdownContainer"] .status-quality,
.stApp .status-coherence,
.stApp .status-quality {{
  color: var(--coherence-ink) !important;
}}

[data-testid="stMarkdownContainer"] .status-moderate,
.stApp .status-moderate {{
  color: var(--alert-ink) !important;
}}

[data-testid="stMarkdownContainer"] .status-critical,
.stApp .status-critical {{
  color: var(--coral-ink) !important;
}}

[data-testid="stMarkdownContainer"] p.kicker,
.stApp p.kicker {{
  font-family: var(--font-body) !important;
  font-size: var(--type-xs) !important;
  font-weight: var(--weight-semibold) !important;
  letter-spacing: 0.06em;
  line-height: var(--leading-tight);
  color: var(--accent) !important;
}}

[data-testid="stElementContainer"]:has(iframe[title="st.iframe"]),
[data-testid="stElementContainer"]:has(iframe[height="0"]) {{
  position: fixed !important;
  width: 0 !important;
  height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  border: 0 !important;
  overflow: hidden !important;
  pointer-events: none !important;
}}

@media (prefers-reduced-motion: reduce) {{
  *,
  *::before,
  *::after {{
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }}
}}
"""

# Minimal parent-document shim (WCAG 1.4.13 Escape dismissal for `.deck-tooltip`,
# plus stripping MapLibre's invalid `role="list"` on `.mapboxgl-ctrl-attrib-inner`).
_A11Y_SHIM = """<script>
(function () {
  try {
    if (window.frameElement) {
      window.frameElement.setAttribute("aria-hidden", "true");
      window.frameElement.setAttribute("tabindex", "-1");
      window.frameElement.setAttribute("title", "Accessibility keyboard helper");
    }
    var doc = window.parent && window.parent.document;
    if (!doc) return;
    if (!doc.__cockpitA11yBound) {
      doc.__cockpitA11yBound = true;
      doc.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
          doc.querySelectorAll(".deck-tooltip").forEach(function (t) {
            t.setAttribute("data-dismissed", "true");
          });
        }
      });
      doc.addEventListener("pointermove", function (e) {
        if (e.target && e.target.tagName === "CANVAS") {
          doc.querySelectorAll(".deck-tooltip[data-dismissed]").forEach(function (t) {
            t.removeAttribute("data-dismissed");
          });
        }
      });
    }
    var fixAttrib = function () {
      doc.querySelectorAll(".mapboxgl-ctrl-attrib-inner[role='list'], .maplibregl-ctrl-attrib-inner[role='list']").forEach(function (el) {
        el.removeAttribute("role");
      });
    };
    fixAttrib();
    if (!doc.__cockpitAttribObserver && typeof MutationObserver !== "undefined") {
      doc.__cockpitAttribObserver = new MutationObserver(fixAttrib);
      doc.__cockpitAttribObserver.observe(doc.body, { childList: true, subtree: true });
    }
  } catch (err) {}
})();
</script>"""


def inject_css() -> None:
    """Inject cockpit CSS. Call once per run, after set_page_config."""
    compact = "\n".join(line for line in _CSS.splitlines() if line.strip())
    st.markdown(f"<style>\n{compact}\n</style>", unsafe_allow_html=True)
    try:
        import streamlit.components.v1 as components

        components.html(_A11Y_SHIM, height=0)
    except Exception:
        pass


def apply_theme_marker() -> None:
    """Apply only the selected-scheme marker; safe to refresh inside a fragment."""
    chosen = st.session_state.get("ui_theme_mode")
    if chosen in ("light", "dark"):
        st.markdown(f'<div data-cockpit="{chosen}" hidden></div>', unsafe_allow_html=True)
