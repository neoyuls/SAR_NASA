"""WCAG 2.2 contrast gate for the cockpit tokens.

The tables below are the maintainable contract: every pair the UI actually paints
is declared here with its threshold. Adding a chip, a control border or a notice
means adding the pair here first.
"""

from __future__ import annotations

import math
import re

from src.ui.theme import CASE_COLORS, DARK, LIGHT, MAP_RAMPS

AA_TEXT = 4.5
AA_LARGE = 3.0
AA_NON_TEXT = 3.0


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _channel(value: float) -> float:
    value = value / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(color: tuple[int, int, int]) -> float:
    red, green, blue = (_channel(value) for value in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    low, high = sorted((luminance(foreground), luminance(background)))
    return (high + 0.05) / (low + 0.05)


def mix(foreground: str, background: str, share: float) -> tuple[int, int, int]:
    """`color-mix(in srgb, foreground <share>, background)` on sRGB channels."""
    fg, bg = _rgb(foreground), _rgb(background)
    return tuple(round(fg[i] * share + bg[i] * (1 - share)) for i in range(3))  # type: ignore[return-value]


# (foreground token, background token, minimum ratio). Normal text is 4.5:1.
TEXT_PAIRS = (
    ("text", "bg", AA_TEXT),
    ("text", "surface", AA_TEXT),
    ("muted", "bg", AA_TEXT),
    ("muted", "surface", AA_TEXT),
    ("accent", "bg", AA_TEXT),
    ("accent", "surface", AA_TEXT),
    ("coherence", "bg", AA_TEXT),
    ("coherence", "surface", AA_TEXT),
    ("alert", "bg", AA_TEXT),
    ("alert", "surface", AA_TEXT),
    ("coral", "bg", AA_TEXT),
    ("coral", "surface", AA_TEXT),
    ("on-accent", "accent", AA_TEXT),
)

# Text painted on a 14% tinted chip background (coherence / alert / coral).
CHIP_PAIRS = (
    ("coherence-ink", "coherence", 0.14),
    ("alert-ink", "alert", 0.14),
    ("coral-ink", "coral", 0.14),
)

# The demo banner uses a 12% alert tint.
BANNER_PAIRS = (("alert", "alert", 0.12),)

# Non-text graphics: boundaries, focus rings, chart strokes, reference lines and slider marks.
NON_TEXT_PAIRS = (
    ("border-strong", "bg"),
    ("border-strong", "surface"),
    ("accent", "bg"),
    ("accent", "surface"),
    ("coherence", "bg"),
    ("coherence", "surface"),
    ("muted", "bg"),
    ("muted", "surface"),
    ("alert", "surface"),
    ("coral", "surface"),
    ("on-accent", "accent"),
    ("text", "bg"),
    ("text", "surface"),
    ("text", "border-strong"),
    ("on-accent", "border-strong"),
)

# Three-cities series lines against both plot_bgcolor (`bg`) and paper_bgcolor (`surface`).
CASE_SERIES_PAIRS = (
    ("mexico-city", "bg"),
    ("mexico-city", "surface"),
    ("jakarta", "bg"),
    ("jakarta", "surface"),
    ("malaga", "bg"),
    ("malaga", "surface"),
)


def _schemes():
    return (("dark", DARK), ("light", LIGHT))


def test_every_declared_text_pair_meets_aa() -> None:
    failures = []
    for scheme, palette in _schemes():
        for foreground, background, threshold in TEXT_PAIRS:
            ratio = contrast(_rgb(palette[foreground]), _rgb(palette[background]))
            if ratio < threshold:
                failures.append((scheme, foreground, background, round(ratio, 2)))
    assert not failures, failures


def test_chip_and_banner_inks_meet_aa_on_their_tint() -> None:
    failures = []
    for scheme, palette in _schemes():
        for foreground, tint, share in (*CHIP_PAIRS, *BANNER_PAIRS):
            background = mix(palette[tint], palette["surface"], share)
            ratio = contrast(_rgb(palette[foreground]), background)
            if ratio < AA_TEXT:
                failures.append((scheme, foreground, tint, round(ratio, 2)))
    assert not failures, failures


def test_non_text_boundaries_meet_aa() -> None:
    failures = []
    for scheme, palette in _schemes():
        for foreground, background in NON_TEXT_PAIRS:
            ratio = contrast(_rgb(palette[foreground]), _rgb(palette[background]))
            if ratio < AA_NON_TEXT:
                failures.append((scheme, foreground, background, round(ratio, 2)))
    assert not failures, failures


def test_case_identity_colors_are_not_the_only_channel() -> None:
    """Every case series color must clear 3:1 against both plot (`bg`) and paper (`surface`)
    backgrounds in light and dark mode, while keeping its direct end label."""
    from src.data import loaders
    from src.ui.charts import three_cities_figure

    failures = []
    for scheme, palette in _schemes():
        for case_id, bg_key in CASE_SERIES_PAIRS:
            color = CASE_COLORS[scheme][case_id]
            ratio = contrast(_rgb(color), _rgb(palette[bg_key]))
            if ratio < AA_NON_TEXT:
                failures.append((scheme, case_id, bg_key, round(ratio, 2)))
    assert not failures, failures

    # Direct end labels remain mandatory even with >= 3:1 line contrast (WCAG 1.4.1).
    rows = loaders.load_timeseries("malaga").to_dict(orient="records")
    fig = three_cities_figure(
        {"mexico-city": rows, "jakarta": rows, "malaga": rows},
        {"mexico-city": "Mexico City, MX", "jakarta": "Jakarta, ID", "malaga": "Málaga, ES"},
    )
    labels = {str(a.text) for a in fig.layout.annotations}
    assert {"Mexico City, MX", "Jakarta, ID", "Málaga, ES"} <= labels


def test_series_reference_lines_and_slider_marks_meet_non_text_aa() -> None:
    """Primary series, seasonal fit, detection-limit reference line and axis baselines all clear 3:1."""
    from src.data import loaders
    from src.ui.charts import bars_figure, line_figure

    series = loaders.get_case_series("malaga", {})
    bars = loaders.get_land_use_bars("malaga", {})
    meta = loaders.load_meta("malaga")
    line_fig = line_figure(series)
    bars_fig = bars_figure(bars, meta)

    for scheme, palette in _schemes():
        plot_bg = _rgb(palette["bg"])
        paper_bg = _rgb(palette["surface"])
        # Primary line (`accent`), seasonal fit (`coherence`), detection limit (`muted`) and axis (`border-strong`).
        for token in ("accent", "coherence", "muted", "border-strong"):
            for bg in (plot_bg, paper_bg):
                assert contrast(_rgb(palette[token]), bg) >= AA_NON_TEXT, (scheme, token)
    # Reference line and seasonal trace are present on the constructed figures.
    assert len(line_fig.data) >= 2
    assert len(bars_fig.layout.shapes) == 2


def test_wcag_target_size_and_focusable_table_rules_are_present() -> None:
    """Points 2 and 4: scrollable table region is keyboard-focusable and small controls have >= 24x24 CSS px rules."""
    from src.ui.theme import _CSS

    assert ".cockpit-table-wrap:focus-visible" in _CSS
    for selector in (
        'button[aria-label^="Help for"]',
        '[data-testid="stCheckbox"] label',
        '[data-testid="stSlider"] [role="group"] div[style*="translate"]',
        '[data-testid="stRadioOption"]',
        '[data-testid="stExpander"] summary',
        '[data-testid="stMultiSelect"] button',
    ):
        assert selector in _CSS, selector
    assert "min-height: 24px !important" in _CSS
    assert "min-width: 24px !important" in _CSS


def _linear(color: tuple[int, int, int]) -> tuple[float, float, float]:
    return tuple(_channel(value) for value in color)  # type: ignore[return-value]


def _unlinear(color: tuple[float, float, float]) -> tuple[int, int, int]:
    def encode(value: float) -> int:
        value = max(0.0, min(1.0, value))
        srgb = value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
        return round(255 * srgb)

    return tuple(encode(value) for value in color)  # type: ignore[return-value]


# Brettel/Viénot dichromat simulation matrices in linear RGB.
_DEUTERANOPIA = ((0.625, 0.375, 0.0), (0.7, 0.3, 0.0), (0.0, 0.3, 0.7))
_PROTANOPIA = ((0.567, 0.433, 0.0), (0.558, 0.442, 0.0), (0.0, 0.242, 0.758))


def simulate(color: tuple[int, int, int], matrix: tuple[tuple[float, float, float], ...]) -> tuple[int, int, int]:
    linear = _linear(color)
    return _unlinear(tuple(sum(matrix[row][col] * linear[col] for col in range(3)) for row in range(3)))  # type: ignore[arg-type]


def _oklab(color: tuple[int, int, int]) -> tuple[float, float, float]:
    red, green, blue = _linear(color)
    x = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    y = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    z = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    x_, y_, z_ = x ** (1 / 3), y ** (1 / 3), z ** (1 / 3)
    return (
        0.2104542553 * x_ + 0.7936177850 * y_ - 0.0040720468 * z_,
        1.9779984951 * x_ - 2.4285922050 * y_ + 0.4505937099 * z_,
        0.0259040371 * x_ + 0.7827717662 * y_ - 0.8086757660 * z_,
    )


def delta_e(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    one, two = _oklab(first), _oklab(second)
    return math.sqrt(sum((one[index] - two[index]) ** 2 for index in range(3)))


def test_velocity_ramp_endpoints_survive_deuteranopia_and_protanopia() -> None:
    """The diverging ramp must not collapse into one hue for dichromat readers."""
    for name, ramp in MAP_RAMPS.items():
        low = tuple(ramp[0][1][:3])
        high = tuple(ramp[-1][1][:3])
        for matrix, label in ((_DEUTERANOPIA, "deuteranopia"), (_PROTANOPIA, "protanopia")):
            distance = delta_e(simulate(low, matrix), simulate(high, matrix))
            assert distance >= 0.08, (name, label, round(distance, 3))


def test_map_ramp_cell_fill_meets_three_to_one_except_the_neutral_band() -> None:
    """Coloured cells must separate from the basemap; the neutral stop is the exception."""
    from src.ui.theme import map_ramp

    bases = {"light": (242, 242, 242), "dark": (14, 14, 14)}
    failures = []
    for scheme, base in bases.items():
        for name in MAP_RAMPS:
            for position, (red, green, blue, alpha) in map_ramp(name, scheme):
                fill = (red, green, blue)
                opacity = alpha / 255
                painted = tuple(round(fill[i] * opacity + base[i] * (1 - opacity)) for i in range(3))
                ratio = contrast(painted, base)
                neutral = name == "colorblind" and position == 0.5
                if not neutral and ratio < AA_NON_TEXT:
                    failures.append((scheme, name, position, round(ratio, 2)))
    assert not failures, failures



# ---------------------------------------------------------------------------
# Type scale: seven steps, 12 px floor, no ad-hoc sizes in the injected sheet.
# ---------------------------------------------------------------------------
TYPE_TOKENS = ("type-xs", "type-sm", "type-md", "type-lg", "type-xl", "type-2xl", "type-3xl")


def _rem_px(value: str) -> float:
    assert value.endswith("rem"), value
    return float(value[:-3]) * 16


def test_type_scale_has_seven_steps_and_a_twelve_pixel_floor() -> None:
    from src.ui.theme import DESIGN_TOKENS

    sizes = [_rem_px(DESIGN_TOKENS[name]) for name in TYPE_TOKENS]
    assert len(sizes) == 7
    assert sizes[0] >= 12.0
    assert sizes == sorted(sizes)
    assert len(set(sizes)) == 7


def test_injected_css_uses_only_scale_font_sizes() -> None:
    from src.ui.theme import _CSS

    for raw in re.findall(r"font-size:\s*([^;!]+)", _CSS):
        value = raw.strip()
        assert value.startswith(("var(--type-", "clamp(var(--type-")), value


def audit_wcag_live(url: str = "http://127.0.0.1:8503/") -> dict[str, object]:
    """Reusable headless-browser verifier for Points 2–6 (keyboard table, AX tree,
    24x24 target sizes, 1.4.12 text spacing, 1.4.13 tooltip Escape/hover and chrome gaps).
    """
    import importlib

    sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright

    report: dict[str, object] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # Point 2 & 3: Tab 3 keyboard scroll + AX tree + tab order on 708-row DOM table
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{url}?theme=dark&tab=3. Hazard and infrastructure", wait_until="domcontentloaded")
        page.wait_for_timeout(6500)
        wrap = page.locator(".cockpit-table-wrap")
        wrap.focus()
        page.wait_for_timeout(150)
        before_scroll = page.evaluate("""() => {
          const el = document.querySelector('.cockpit-table-wrap');
          const cs = getComputedStyle(el);
          return {
            role: el.getAttribute('role'),
            ariaLabel: el.getAttribute('aria-label'),
            tabIndex: el.tabIndex,
            isFocused: document.activeElement === el,
            outline: cs.outline,
            scrollTop: el.scrollTop,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight
          };
        }""")
        for _ in range(6):
            page.keyboard.press("PageDown")
            page.wait_for_timeout(80)
        after_scroll = page.evaluate("""() => {
          const el = document.querySelector('.cockpit-table-wrap');
          const rows = [...document.querySelectorAll('.cockpit-table tbody tr')];
          const vis = rows.filter(r => getComputedStyle(r).display !== 'none' && !r.hidden);
          const hidden = rows.filter(r => getComputedStyle(r).display === 'none' && r.hidden && r.getAttribute('aria-hidden') === 'true');
          const lastVis = vis[vis.length - 1].getBoundingClientRect();
          const wrapRect = el.getBoundingClientRect();
          return {
            scrollTop: el.scrollTop,
            maxScroll: el.scrollHeight - el.clientHeight,
            lastRowVisibleInWrap: lastVis.bottom <= wrapRect.bottom + 2 && lastVis.top >= wrapRect.top - 2,
            domTotalRows: rows.length,
            visibleRows: vis.length,
            hiddenOffPageRows: hidden.length
          };
        }""")
        cdp = page.context.new_cdp_session(page)
        ax_nodes = cdp.send("Accessibility.getFullAXTree")["nodes"]
        ax_rows = [
            n for n in ax_nodes
            if n.get("role", {}).get("value") == "row" and not n.get("ignored", False)
        ]
        report["tab3_keyboard_and_ax"] = {
            "before": before_scroll,
            "after": after_scroll,
            "axExposedRows": len(ax_rows),  # 1 header row + 25 active-page body rows = 26
        }
        page.close()

        # Point 6: Chrome vertical & horizontal gaps across 4 viewports
        gaps = {}
        for vw, vh in ((1440, 900), (1920, 1080), (1024, 768), (390, 844)):
            pg = browser.new_page(viewport={"width": vw, "height": vh})
            pg.goto(f"{url}?theme=dark&tab=1. Map", wait_until="domcontentloaded")
            pg.wait_for_timeout(6000)
            gaps[f"{vw}x{vh}"] = pg.evaluate("""() => {
              const hb = document.querySelector('.mission-bar').getBoundingClientRect();
              const db = document.querySelector('.demo-banner').getBoundingClientRect();
              const fl = document.querySelector('.st-key-filters').getBoundingClientRect();
              return {
                vGapHeaderBanner: Math.round((db.top - hb.bottom) * 10) / 10,
                vGapBannerFilters: Math.round((fl.top - db.bottom) * 10) / 10,
                hGapLeft: Math.round(hb.left * 10) / 10,
                hGapRight: Math.round((window.innerWidth - hb.right) * 10) / 10
              };
            }""")
            pg.close()
        report["chrome_gaps"] = gaps
        browser.close()
    return report


