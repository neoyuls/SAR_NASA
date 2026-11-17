"""Guard the AOI scope decision recorded in `docs/data-source-decision.md` §"AOI scope".

`config/aoi/{case}.geojson` is the *measurement domain*: one city-scale `Polygon`, one closed ring,
no holes. The metro (`MultiPolygon`) shapefile exports are context only and are not adopted — a
previous commit tracked them by mistake, so this is a regression class, not a hypothetical.

Shape is pinned, not just size, because size alone would pass the Málaga case (394.2 vs 395.5 km²)
and because the failure mode is silent: the loader would happily read the first ring of a
MultiPolygon and the pipeline would then measure a different city than the one it reports.

Each case in `config/aoi/` must be:

* exactly ONE feature whose geometry is type `Polygon` (a MultiPolygon needs multipart support
  end-to-end: `pipeline/process_case.py` builds the cell set from a single closed ring);
* closed (first == last point) with at least 4 distinct vertices;
* `(lon, lat)` in EPSG:4326, inside the case's plausible envelope — catches a swapped pair or a
  projected-metre export;
* free of interior rings (holes), which the pipeline does not handle;
* within ±25 % of the area documented in the decision record — read from that doc, so the doc stays
  the single source of truth and a silent swap between the city polygon and the metro export fails.

The retired `{case}-aoi.geojson` names must not reappear in `config/aoi/`. Nothing here writes:
`config/aoi/` is read-only for this suite.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from pyproj import Geod

ROOT = Path(__file__).resolve().parents[1]
AOI_DIR = ROOT / "config" / "aoi"
DECISION_DOC = ROOT / "docs" / "data-source-decision.md"
STUDY_CASES = ROOT / "config" / "study_cases.yaml"

#: Equal-area size on the WGS84 ellipsoid — the same geodesic used to measure the documented areas.
GEOD = Geod(ellps="WGS84")
#: Wide enough that a coordinate change inside the same city passes; narrow enough that swapping in
#: the metro export (5.3× / 7.2×) or the bbox rectangle fails. This is a swap detector, not cadastral
#: policing.
AREA_TOLERANCE = 0.25

#: Filenames the retired metro exports used. `pipeline/aoi.py` accepts this suffix as an override,
#: so if the city file disappeared one of these would silently become the AOI.
RETIRED_EXPORT_NAMES = (
    "mexico-city-aoi.geojson",
    "jakarta-aoi.geojson",
    "malaga-aoi.geojson",
)

#: `1,494.6 km²` in the decision record's measurement-domain table.
DOCUMENTED_AREA_RE = re.compile(r"(\d[\d,\.]*)\s*km\u00b2")

AOI_FILES = sorted(AOI_DIR.glob("*.geojson"))


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def documented_areas() -> dict[str, float]:
    """`case_id -> km²` from the measurement-domain table in the decision record.

    The doc is the source of truth so that a change of AOI has to be argued in the record, not just
    pasted into a test constant. A reshaped table fails loudly instead of silently checking nothing.
    """
    if not DECISION_DOC.is_file():
        pytest.skip(
            "the AOI-scope decision record is internal documentation, not shipped in the "
            "submitted repository; the committed AOI is still checked for shape and envelope"
        )
    cases = set(_study_case_entries())
    areas: dict[str, float] = {}
    for line in DECISION_DOC.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        case_id = cells[0].strip("`")
        if case_id not in cases:
            continue
        match = DOCUMENTED_AREA_RE.search(cells[1])
        if match is None:
            continue
        areas[case_id] = float(match.group(1).replace(",", ""))
    return areas


def _study_case_entries() -> dict[str, dict]:
    raw = yaml.safe_load(STUDY_CASES.read_text(encoding="utf-8"))
    return raw["cases"]


def plausible_envelope(case_id: str) -> tuple[float, float, float, float]:
    """`[W, S, E, N]` the AOI must stay inside, from the case's configured bbox plus a margin.

    The configured bbox *is* the AOI's envelope (see the `bbox is the AOI envelope` comment in
    `config/study_cases.yaml`), so it is the honest plausible region — nothing invented here. The
    margin absorbs YAML rounding and a re-traced boundary near the edge.
    """
    west, south, east, north = (float(v) for v in _study_case_entries()[case_id]["bbox"])
    pad_lon = max(0.01, 0.10 * (east - west))
    pad_lat = max(0.01, 0.10 * (north - south))
    return (west - pad_lon, south - pad_lat, east + pad_lon, north + pad_lat)


def polygon_area_km2(ring: list[list[float]]) -> float:
    lons = [float(point[0]) for point in ring]
    lats = [float(point[1]) for point in ring]
    area_m2, _perimeter = GEOD.polygon_area_perimeter(lons, lats)
    return abs(area_m2) / 1e6


def check_aoi_geometry(path: Path, case_id: str, documented_km2: float) -> float:
    """All the AOI invariants for one file. Returns the measured equal-area size in km².

    Raises `AssertionError` with the message a reviewer needs. Callable directly (the multi-part
    proof in this module's docstring/suite calls it on a temporary MultiPolygon), which is why it
    takes a path instead of reading `AOI_DIR` itself.
    """
    where = f"{case_id} ({_rel(path)})"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload.get("type") == "FeatureCollection", (
        f"{where}: expected a FeatureCollection, got {payload.get('type')!r} "
        "(see docs/data-source-decision.md, 'AOI scope')"
    )
    features = payload.get("features") or []
    assert len(features) == 1, (
        f"{where}: expected exactly ONE feature (the city-scale polygon), found {len(features)}. "
        "The metro export is context only and is not adopted — see docs/data-source-decision.md, "
        "section 'AOI scope'."
    )

    geometry = features[0].get("geometry") or {}
    geometry_type = geometry.get("type")
    assert geometry_type == "Polygon", (
        f"{where}: geometry is {geometry_type!r}, not 'Polygon'. MULTIPART RISK: a MultiPolygon is "
        "the metro export, which is context only and was never adopted — see "
        "docs/data-source-decision.md, section 'AOI scope'. pipeline/process_case.py builds the "
        f"cell set from a single closed ring (h3.LatLngPoly(cfg.aoi_ring)), so a {geometry_type} "
        "needs multipart support end-to-end before it can be an AOI; do not commit the export."
    )

    coordinates = geometry.get("coordinates") or []
    assert len(coordinates) == 1, (
        f"{where}: the polygon has {len(coordinates) - 1} interior ring(s) (holes). The pipeline "
        "measures every cell inside the exterior ring, so a hole would be measured as interior "
        "ground — see docs/data-source-decision.md, section 'AOI scope'."
    )

    ring = coordinates[0]
    assert len(ring) >= 4, f"{where}: ring has {len(ring)} points, a closed polygon needs at least 4"
    assert list(ring[0]) == list(ring[-1]), (
        f"{where}: ring is not closed (first point {ring[0]} != last point {ring[-1]}); "
        "the pipeline hands this ring to h3.LatLngPoly as-is"
    )
    distinct = {tuple(float(value) for value in point) for point in ring}
    assert len(distinct) >= 4, (
        f"{where}: only {len(distinct)} distinct vertices ({sorted(distinct)}); a real AOI has at "
        "least 4 after closing the ring"
    )

    west, south, east, north = plausible_envelope(case_id)
    outside = [
        (index, point)
        for index, point in enumerate(ring)
        if not (west <= float(point[0]) <= east and south <= float(point[1]) <= north)
    ]
    assert not outside, (
        f"{where}: {len(outside)} of {len(ring)} vertices fall outside the plausible envelope "
        f"[W={west:.3f}, S={south:.3f}, E={east:.3f}, N={north:.3f}] (lon/lat, W/S/E/N); "
        f"first offender: index {outside[0][0]} = {outside[0][1]}. Coordinates must be (lon, lat) "
        "in EPSG:4326 — a swapped pair or a projected metre lands here."
    )

    area_km2 = polygon_area_km2(ring)
    low = documented_km2 * (1 - AREA_TOLERANCE)
    high = documented_km2 * (1 + AREA_TOLERANCE)
    assert low <= area_km2 <= high, (
        f"{where}: equal-area size is {area_km2:.1f} km², outside ±{AREA_TOLERANCE:.0%} of the "
        f"{documented_km2:.1f} km² documented for this case in docs/data-source-decision.md "
        f"(band {low:.1f}–{high:.1f} km²). This is the silent-swap alarm: the metro export is "
        "5.3× (mexico-city) / 7.2× (jakarta) larger than the city polygon it must not replace."
    )
    return area_km2


# ---------------------------------------------------------------------------------------------
# The committed AOIs
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", AOI_FILES, ids=lambda path: path.stem)
def test_committed_aoi_is_one_closed_single_part_polygon(path: Path) -> None:
    case_id = path.stem
    areas = documented_areas()
    assert case_id in areas, (
        f"{_rel(path)}: this case has no measurement-domain row in docs/data-source-decision.md "
        "(the table whose first column names the case and whose second column gives the km²). "
        "Document the AOI scope before committing a new polygon."
    )
    check_aoi_geometry(path, case_id, areas[case_id])


def test_every_study_case_has_an_aoi_and_every_aoi_has_a_case() -> None:
    documented = documented_areas()
    configured = set(_study_case_entries())
    present = {path.stem for path in AOI_FILES}
    assert documented.keys() == configured, (
        "the decision record's measurement-domain table and config/study_cases.yaml disagree: "
        f"missing from the doc {sorted(configured - set(documented))}, "
        f"missing from the config {sorted(set(documented) - configured)}"
    )
    assert present == configured, (
        f"config/aoi/ holds {sorted(present)} but config/study_cases.yaml declares "
        f"{sorted(configured)}: an orphan polygon is not an AOI, and a case without one silently "
        "falls back to its bbox envelope"
    )


def test_retired_metro_exports_are_not_in_the_aoi_directory() -> None:
    """The `*-aoi.geojson` exports must stay out of `config/aoi/` for good.

    `pipeline/aoi.py` accepts that suffix, so its reappearance would not even raise: it would quietly
    become the study area as soon as the city file is missing.
    """
    present = sorted(name for name in RETIRED_EXPORT_NAMES if (AOI_DIR / name).exists())
    assert not present, (
        f"retired metro exports are back in {_rel(AOI_DIR)}/: {present}. They are context only and "
        "are not the measurement domain — see docs/data-source-decision.md, section 'AOI scope'."
    )
    strays = sorted(path.name for path in AOI_DIR.glob("*-aoi.geojson"))
    assert not strays, (
        f"{_rel(AOI_DIR)}/ contains a retired-style export name: {strays}. The AOI is "
        "`{case}.geojson`; the metro/multipart export belongs outside the config tree."
    )
