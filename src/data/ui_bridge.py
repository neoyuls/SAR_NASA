"""Exact Rol 1 -> Rol 2 adapter functions requested by `app.py` & `docs/ui-data-needs.md`.

Re-exported from `src.data.loaders` so `app.py._loaders()` automatically switches away from
`src.ui._stubs` to real validated artefacts under `data/processed/{case_id}/` with zero UI edits.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.data.loaders import (
    DEFAULT_PROCESSED_DIR,
    DEFAULT_STUDY_CASES_PATH,
    ROOT_DIR,
    list_available_cases,
    load_all_available_bundles,
    load_case_bundle,
    load_study_cases_config,
)
from src.domain import contracts as C
from src.domain.filters import FilterCriteria, apply_filters
from src.domain.map_adapter import (
    COLUMN_AMPLITUDE_M,
    COLUMN_BASELINE_M,
    ScaleMode,
    build_map_payload,
    compute_view_state,
)
from src.domain.metrics import (
    cell_velocity_context,
    coherence_bounds,
    compute_kpis,
    context_row_counts,
    distance_summary,
    threshold_counts,
    velocity_distribution,
)

_SHARED_LABELS = frozenset(
    {"shared", "común a todos los casos", "comun a todos los casos", "compartida"}
)


def _resolve_scale_mode(raw_mode: Any) -> ScaleMode:
    if str(raw_mode or "").strip().lower() in _SHARED_LABELS:
        return "shared"
    return "independent"


def _dict_to_criteria(filters: Mapping[str, Any] | None) -> FilterCriteria:
    if not isinstance(filters, Mapping):
        return FilterCriteria(coherence_min=0.0)
    lu = filters.get("land_use")
    rl = filters.get("risk_level")
    coh = filters.get("coherence_min")
    coh_val = (
        float(coh)
        if isinstance(coh, (int, float)) and not isinstance(coh, bool)
        else 0.0
    )
    return FilterCriteria(
        coherence_min=coh_val,
        land_uses=(str(lu),) if lu not in (None, "") else None,
        risk_levels=(str(rl),) if rl not in (None, "") else None,
    )


def _case_provenance_id(bundle: Any) -> str:
    prov = bundle.meta.get("provenance") or {}
    if prov.get("provenance_id"):
        return str(prov["provenance_id"])
    if not bundle.grid.empty and "provenance_id" in bundle.grid.columns:
        return str(bundle.grid["provenance_id"].iloc[0])
    return ""


def load_study_cases(
    config_path: pathlib.Path | str = DEFAULT_STUDY_CASES_PATH,
) -> list[dict[str, str]]:
    """Return `[{'id': slug, 'label': name}, ...]` in frozen `CASE_IDS` order."""
    cfg_file = pathlib.Path(config_path)
    if cfg_file.is_file():
        cfg = load_study_cases_config(cfg_file)
        return [
            {"id": slug, "label": cfg.cases[slug].name if slug in cfg.cases else slug}
            for slug in C.CASE_IDS
        ]
    return [{"id": slug, "label": slug} for slug in C.CASE_IDS]


def load_meta(
    case_id: str,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any]:
    """Return validated `meta.json` enriched with top-level display & provenance telemetry keys.

    Additive only (no contract change): surfaces `provenance.source`, `method`, `license`,
    `reference`, `processing_date`, `product_id` and `retrieved_utc` both as a normalised
    `provenance_fields` mapping and via `setdefault` at top level so Tab 4 and header chrome
    can render every published provenance field without reading raw `meta.json` directly.
    """
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    meta = dict(bundle.meta)
    meta.setdefault("unit", C.UNIT)
    prov_id = _case_provenance_id(bundle)
    if prov_id:
        meta.setdefault("provenance_id", prov_id)

    prov_raw = bundle.meta.get("provenance")
    prov = prov_raw if isinstance(prov_raw, Mapping) else {}
    prov_fields: dict[str, str | None] = {
        "provenance_id": prov_id or None,
    }
    for key in (
        "source",
        "method",
        "license",
        "reference",
        "processing_date",
        "product_id",
        "retrieved_utc",
    ):
        raw_val = prov.get(key)
        clean_val = str(raw_val).strip() if raw_val not in (None, "") else None
        prov_fields[key] = clean_val
        if clean_val is not None:
            meta.setdefault(key, clean_val)
    meta.setdefault("provenance_fields", prov_fields)
    return meta


def load_land_use_options(
    case_id: str | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> tuple[str, ...]:
    """Return distinct `land_use` categories actually present in the published grid(s)."""
    present: set[str] = set()
    if case_id:
        bundle = load_case_bundle(case_id, processed_dir=processed_dir)
        present.update(bundle.grid["land_use"].astype(str).unique())
    else:
        for bundle in load_all_available_bundles(processed_dir=processed_dir).values():
            present.update(bundle.grid["land_use"].astype(str).unique())
    if not present:
        return C.LAND_USE
    return tuple(lu for lu in C.LAND_USE if lu in present)


def load_risk_levels(
    case_id: str | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> tuple[str, ...]:
    """Return distinct `risk_level` bands present in the published grid(s) (or frozen tuple)."""
    if case_id:
        bundle = load_case_bundle(case_id, processed_dir=processed_dir)
        present = set(bundle.grid["risk_level"].astype(str).unique())
        if present:
            return tuple(lvl for lvl in C.RISK_LEVELS if lvl in present)
    return C.RISK_LEVELS


def get_map_layer_df(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> pd.DataFrame:
    """Return H3 map DataFrame with pre-computed `color` (RGBA) and `height` (3D metres)."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    crit = _dict_to_criteria(filters)
    mode = _resolve_scale_mode((filters or {}).get("scale_mode"))
    extrude = bool((filters or {}).get("extrude_3d", False))

    payload = build_map_payload(
        bundle,
        crit,
        metric="velocity_mm_yr",
        scale_mode=mode,
        extrude_3d=extrude,
        include_h3_polygons=False,
    )
    columns = [
        "cell_id",
        "lat",
        "lon",
        "delta_change",
        "signed_delta_mm",
        "motion_direction",
        "velocity_mm_yr",
        "coherence",
        "land_use",
        "risk_level",
        "unit",
        "velocity_unit",
        "color",
        "height",
    ]
    if payload.is_empty:
        return pd.DataFrame(columns=columns)

    df = payload.grid_frame.copy()
    df["color"] = df["fill_color"]
    # Final O-07 decision: `height` binds to `elevation_m` (two-sided signed extrusion around
    # `COLUMN_BASELINE_M = MAX_EXTRUDE_METERS / 2 = 1500 m` when `extrude_3d=True`, `0.0` in flat
    # mode), while `signed_delta_mm` keeps exact unrounded `delta_change` [mm].
    df["signed_delta_mm"] = pd.to_numeric(bundle.grid.set_index("cell_id")["delta_change"], errors="raise").reindex(df["cell_id"]).to_numpy(dtype=np.float64)
    df["height"] = df["elevation_m"]
    # v1.1 thesis metrics for tooltip/inspector parity; additive if absent on legacy fixtures.
    for extra in ("regime", "ratio_R", "seasonal_amp_mm"):
        if extra in bundle.grid.columns:
            if extra not in df.columns:
                lookup = bundle.grid.set_index("cell_id")[extra]
                df[extra] = df["cell_id"].map(lookup)
            columns.append(extra)
    # Round float columns for clean PyDeck tooltips (no 15-digit IEEE-754 noise on hover).
    for col, decimals in (
        ("delta_change", 2),
        ("velocity_mm_yr", 2),
        ("coherence", 3),
        ("ratio_R", 2),
        ("seasonal_amp_mm", 2),
    ):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(decimals)
    return df[columns]


def get_color_scale(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any]:
    """Return the active colour scale domain `[min, max]` and saturation status."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    crit = _dict_to_criteria(filters)
    mode = _resolve_scale_mode((filters or {}).get("scale_mode"))
    payload = build_map_payload(
        bundle, crit, metric="velocity_mm_yr", scale_mode=mode, include_h3_polygons=False
    )
    vmin = float(payload.legend.domain_min or -425.0)
    vmax = float(payload.legend.domain_max or 425.0)
    if payload.is_empty:
        saturated = False
    else:
        vels = payload.grid_frame["velocity_mm_yr"].to_numpy(dtype=np.float64)
        saturated = bool(((vels < vmin) | (vels > vmax)).any())
    return {
        "min": vmin,
        "max": vmax,
        "unit": payload.legend.unit,
        "saturated": saturated,
        "fallback": False,
        "mixed_units": False,
        # Legend parity hooks for `src/ui/map_view.py`; additive, never remove the keys above.
        "metric": payload.legend.metric,
        "caption": payload.legend.caption,
        "stops": [stop.color_hex for stop in payload.legend.stops],
    }


def get_layer_counts(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, int]:
    """Return `{'shown': filtered_count, 'total': total_count}` without UI-side aggregation."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    return {
        "shown": len(view.grid),
        "total": view.total_grid_cells,
    }


def get_velocity_distribution(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any]:
    """p05 / median / p95 of the filtered view, from `meta.stats` for the whole case."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    distribution = velocity_distribution(view.grid, bundle.meta.get("stats"))
    return {
        "n_cells": distribution.n_cells,
        "p05_mm_yr": distribution.p05_mm_yr,
        "median_mm_yr": distribution.median_mm_yr,
        "p95_mm_yr": distribution.p95_mm_yr,
        "min_mm_yr": distribution.min_mm_yr,
        "max_mm_yr": distribution.max_mm_yr,
        "source": distribution.source,
        "unit": distribution.unit,
        "provenance_id": _case_provenance_id(bundle),
    }


def get_cell_velocity_context(
    case_id: str,
    cell_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any] | None:
    """Descriptive position of one cell in the view's velocity distribution."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    return cell_velocity_context(view.grid, str(cell_id), bundle.meta.get("stats"))


def get_coherence_summary(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any]:
    """Observed min/max coherence of the view, plus the declared published floor."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    observed = coherence_bounds(view.grid)
    thresholds = bundle.meta.get("thresholds") or {}
    floor = thresholds.get("coherence_min")
    return {
        **observed,
        "declared_min": floor if isinstance(floor, (int, float)) and not isinstance(floor, bool) else None,
        "provenance_id": _case_provenance_id(bundle),
    }


def summarize_context_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Count the context rows the UI is about to show, in the domain layer."""
    return context_row_counts(rows)


def get_distance_summary(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any]:
    """Descriptive distance statistics for the exposure cross-reference (no far threshold)."""
    exposure = get_context_exposure(case_id, filters, processed_dir=processed_dir)
    rows = exposure.get("features") if isinstance(exposure, dict) else None
    summary = distance_summary(rows or [])
    summary["provenance_id"] = _case_provenance_id(load_case_bundle(case_id, processed_dir=processed_dir))
    return summary


def get_extrusion_presentation() -> dict[str, Any]:
    """Map-adapter presentation constants: column height is a camera choice, not a measurement."""
    return {
        "baseline_m": COLUMN_BASELINE_M,
        "amplitude_m": COLUMN_AMPLITUDE_M,
        "unit": "m",
    }


def get_view_state(
    case_id: str,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, float] | None:
    """Return `{'latitude', 'longitude', 'zoom'}` computed from `meta.bbox`."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    vs = compute_view_state(bundle.meta, extrude_3d=False)
    return {
        "latitude": vs.latitude,
        "longitude": vs.longitude,
        "zoom": vs.zoom,
    }


def get_signal_status(
    case_id: str,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any]:
    """Return null-result detection status echoed directly from `meta.stats`."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    kpis = compute_kpis(bundle, FilterCriteria(coherence_min=0.0))
    return {
        "above_limit": not kpis.is_null_result,
        "detection_limit": kpis.detection_limit_mm_yr,
        "detection_limit_unit": C.VELOCITY_UNIT if kpis.detection_limit_mm_yr is not None else None,
    }


def get_map_kpis(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> list[dict[str, Any]]:
    """Return summary KPI cards displayed above the PyDeck viewport."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    kpis = compute_kpis(view)
    prov_id = _case_provenance_id(bundle)
    coherence = coherence_bounds(view.grid)
    coh_min = coherence["min"]
    return [
        {
            "label": "Median velocity",
            "value": round(kpis.median_velocity_mm_yr, 2) if kpis.median_velocity_mm_yr is not None else None,
            "unit": C.VELOCITY_UNIT,
            "provenance_id": prov_id,
        },
        {
            "label": "Median displacement",
            "value": round(kpis.median_delta_mm, 2) if kpis.median_delta_mm is not None else None,
            "unit": C.UNIT,
            "provenance_id": prov_id,
        },
        {
            "label": "Minimum coherence",
            "value": round(coh_min, 3) if coh_min is not None else None,
            "unit": None,
            "provenance_id": prov_id,
        },
        {
            # v1.1: fitted, not typed — `seasonal_amp_mm` comes from the harmonic fit of each
            # cell's own series, so the card and the parquet can never disagree.
            "label": "Median seasonal amplitude",
            "value": (
                round(kpis.median_seasonal_amp_mm, 2)
                if kpis.median_seasonal_amp_mm is not None
                else None
            ),
            "unit": C.UNIT,
            "provenance_id": prov_id,
        },
    ]


def _series_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Normalise a `timeseries.csv` slice for the inspector without touching the contract."""
    if frame.empty:
        return []
    return [
        {
            "case_id": str(r.case_id),
            "cell_id": str(r.cell_id),
            "date": str(r.date),
            "value": float(r.value),
            "trend_mm_yr": float(r.trend_mm_yr) if hasattr(r, "trend_mm_yr") else None,
            "seasonal_mm": float(r.seasonal_mm) if hasattr(r, "seasonal_mm") else None,
            "unit": str(r.unit),
            "sensor": str(r.sensor),
            "product": str(r.product),
            "quality": str(r.quality),
            "provenance_id": str(r.provenance_id),
        }
        for r in frame.itertuples(index=False)
    ]


def get_cell_detail(
    case_id: str,
    cell_id: str,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any] | None:
    """Return attributes of one selected H3 cell plus its per-cell series (when emitted)."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    matches = bundle.grid.loc[bundle.grid["cell_id"].astype(str) == str(cell_id)]
    if matches.empty:
        return None
    row = matches.iloc[0]
    detail: dict[str, Any] = {
        "cell_id": str(row["cell_id"]),
        "case_id": str(row["case_id"]),
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "val_t1": float(row["val_t1"]),
        "val_t2": float(row["val_t2"]),
        "delta_change": float(row["delta_change"]),
        "velocity_mm_yr": float(row["velocity_mm_yr"]),
        # v1.1: the fitted seasonal pair. Present only when the artefact carries it, so a v1.0
        # tree still renders instead of raising a KeyError in the detail panel. A not-fitted cell
        # publishes amplitude 0.0 with a *null* ratio (|trend|/0 is undefined), which is reported
        # as None rather than as NaN — NaN is not valid JSON and would poison a JSON consumer.
        "seasonal_amp_mm": float(row["seasonal_amp_mm"]) if "seasonal_amp_mm" in row else None,
        "ratio_R": (
            float(row["ratio_R"])
            if "ratio_R" in row and pd.notna(row["ratio_R"])
            else None
        ),
        "regime": str(row["regime"]) if "regime" in row else None,
        "coherence": float(row["coherence"]),
        "land_use": str(row["land_use"]),
        "risk_level": str(row["risk_level"]),
        "sensor": str(row["sensor"]),
        "product": str(row["product"]),
        "unit": str(row["unit"]),
        "velocity_unit": str(row["velocity_unit"]),
        "source": str(row["source"]),
        "provenance_id": str(row["provenance_id"]),
        "acquisition_date": (
            str(row["acquisition_date"])
            if "acquisition_date" in row and pd.notna(row["acquisition_date"])
            else None
        ),
    }
    cell_ts = bundle.timeseries.loc[bundle.timeseries["cell_id"].astype(str) == str(cell_id)]
    series = _series_rows(cell_ts)
    if series:
        detail["series_scope"] = "cell"
    else:
        # Contract §4 emits only the AOI aggregate by default. Show that instead of an
        # empty chart, and say so in the UI; do not invent a per-cell series.
        aoi_ts = bundle.timeseries.loc[bundle.timeseries["cell_id"].astype(str) == "aoi"]
        series = _series_rows(aoi_ts)
        detail["series_scope"] = "aoi" if series else "none"
    detail["series"] = series
    return detail


def load_timeseries(
    case_id: str,
    cell_id: str | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> pd.DataFrame:
    """Return `timeseries.csv` filtered to `cell_id` (or full case series if `cell_id is None`)."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    if cell_id is None:
        return bundle.timeseries.copy()
    return bundle.timeseries.loc[
        bundle.timeseries["cell_id"].astype(str) == str(cell_id)
    ].reset_index(drop=True)


def get_series_kpis(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> list[dict[str, Any]]:
    """Return the four KPI cards rendered in Tab 2 (`Series y KPIs`)."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    kpis = compute_kpis(view)
    prov_id = _case_provenance_id(bundle)
    coh_floor = float((bundle.meta.get("thresholds") or {}).get("coherence_min", 0.35))

    total = len(view.grid)
    # Counts and shares belong to src.domain.metrics; this bridge only formats the cards.
    above = threshold_counts(view.grid["velocity_mm_yr"], C.NULL_RESULT_MM_YR)
    pct_above = above.percentage
    coherent = threshold_counts(view.grid["coherence"], coh_floor, absolute=False)
    pct_coh = coherent.percentage

    return [
        {
            "label": "Median velocity",
            "value": round(kpis.median_velocity_mm_yr, 2) if kpis.median_velocity_mm_yr is not None else None,
            "unit": C.VELOCITY_UNIT,
            "provenance_id": prov_id,
            "note": "median of the filtered subset",
        },
        {
            "label": "Cells above threshold",
            "value": pct_above,
            "unit": "%",
            "provenance_id": prov_id,
            "note": f"threshold {C.NULL_RESULT_MM_YR:g} mm/year",
        },
        {
            "label": "Critical cells",
            "value": kpis.critical_cells_count,
            "unit": "cells",
            "provenance_id": prov_id,
            "note": "cells in contract band critico (|velocity| >= 25 mm/year)",
        },
        {
            "label": "Coherent coverage",
            "value": pct_coh,
            "unit": "%",
            "provenance_id": prov_id,
            "note": f"coherence >= {coh_floor:g}",
        },
        {
            "label": "Median seasonal amplitude",
            "value": (
                round(kpis.median_seasonal_amp_mm, 2)
                if kpis.median_seasonal_amp_mm is not None
                else None
            ),
            "unit": C.UNIT,
            "provenance_id": prov_id,
            "note": (
                f"harmonic fit, R = |trend|/A; dominant regime {kpis.dominant_regime}"
                if kpis.dominant_regime
                else "harmonic fit, not a typed constant"
            ),
        },
    ]


def get_case_series(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> list[dict[str, Any]]:
    """Return the published `cell_id == 'aoi'` series (`mm`) for Tab 2's line chart.

    v1.1 adds the fitted ``trend_mm_yr`` / ``seasonal_mm`` columns of each row (``None`` when a
    v1.0 tree is on disk), so the chart can draw the decomposition without re-fitting anything.
    Includes ``scaled`` / ``scale_factor`` additive metadata requested in ``docs/requests.md``.
    """
    del filters  # AOI series is a case-level artefact; per-cell series are optional (contract §4)
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    aoi = bundle.timeseries.loc[bundle.timeseries["cell_id"].astype(str) == "aoi"]
    return [
        {
            "date": str(r.date),
            "value": float(r.value),
            "trend_mm_yr": float(r.trend_mm_yr) if hasattr(r, "trend_mm_yr") else None,
            "seasonal_mm": float(r.seasonal_mm) if hasattr(r, "seasonal_mm") else None,
            "unit": str(r.unit),
            "provenance_id": str(r.provenance_id),
            "scaled": False,
            "scale_factor": 1.0,
        }
        for r in aoi.itertuples(index=False)
    ]


def get_land_use_bars(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> list[dict[str, Any]]:
    """Return median `velocity_mm_yr` per present `land_use` category (no absent classes filled)."""
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    if view.grid.empty:
        return []
    prov_id = _case_provenance_id(bundle)
    grouped = view.grid.groupby("land_use", sort=False)["velocity_mm_yr"].median()
    ordered_lus = [lu for lu in C.LAND_USE if lu in grouped.index]
    return [
        {
            "land_use": lu,
            "value": round(float(grouped[lu]), 2),
            "unit": C.VELOCITY_UNIT,
            "provenance_id": prov_id,
        }
        for lu in ordered_lus
    ]


def get_scale_comparison(
    scale_mode: str = "shared",
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any]:
    """Compare peak `|velocity_mm_yr|` across all published cases on one shared physical axis."""
    shared = _resolve_scale_mode(scale_mode) == "shared"
    bundles = load_all_available_bundles(processed_dir=processed_dir)
    peaks: list[tuple[str, float, str, str, str, str]] = []
    units: set[str] = set()
    sensors: set[str] = set()
    products: set[str] = set()
    for slug in C.CASE_IDS:
        if slug not in bundles:
            continue
        b = bundles[slug]
        peak = float(b.grid["velocity_mm_yr"].abs().max()) if not b.grid.empty else 0.0
        vel_unit = (
            str(b.grid["velocity_unit"].iloc[0])
            if not b.grid.empty and "velocity_unit" in b.grid.columns
            else C.VELOCITY_UNIT
        )
        sensor = str(b.meta.get("sensor") or "")
        product = str(b.meta.get("product") or "")
        units.add(vel_unit)
        if sensor:
            sensors.add(sensor)
        if product:
            products.add(product)
        peaks.append((slug, round(peak, 2), _case_provenance_id(b), vel_unit, sensor, product))

    span = max((p for _, p, *_ in peaks), default=0.0)
    cases = [
        {
            "id": slug,
            "unit": vel_unit,
            "sensor": sensor,
            "product": product,
            "peak": peak,
            "share": (0.0 if span == 0.0 else peak / span) if shared else (1.0 if peak > 0 else 0.0),
            "provenance_id": prov_id,
        }
        for slug, peak, prov_id, vel_unit, sensor, product in peaks
    ]
    return {
        "reference_unit": C.VELOCITY_UNIT if (shared and len(units) <= 1) else None,
        "mixed_units": len(units) > 1,
        "mixed_sensors": len(sensors) > 1,
        "mixed_products": len(products) > 1,
        "sensors": sorted(sensors),
        "products": sorted(products),
        "cases": cases,
    }


def load_context_layers(
    case_id: str | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any] | None:
    """Return summary and GeoJSON for `context_layers.geojson` of `case_id` (or primary case)."""
    available = list_available_cases(processed_dir=processed_dir)
    if not available:
        return None
    target = case_id if (case_id and case_id in available) else available[0]
    bundle = load_case_bundle(target, processed_dir=processed_dir)
    features = bundle.context.get("features") or []
    layer_counts: dict[str, int] = {}
    for feat in features:
        lname = str(((feat or {}).get("properties") or {}).get("layer", "unknown"))
        layer_counts[lname] = layer_counts.get(lname, 0) + 1
    ctx_path = bundle.source_dir / "context_layers.geojson"
    try:
        rel_path = ctx_path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        rel_path = str(ctx_path)
    return {
        "path": rel_path,
        "geojson": bundle.context,
        "summary": {
            "case_id": target,
            "n_features": len(features),
            "layers": layer_counts,
        },
    }


def get_context_exposure(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any] | None:
    """Context features joined to their nearest filtered H3 cell — informative only.

    For every feature of `context_layers.geojson` this returns the closest cell of the
    *filtered* grid and that cell's `risk_level` and `land_use`. It is a proximity
    cross-reference for the reader, **not** a hazard assessment: it says "this feature
    sits next to a cell whose velocity band is X", never "this asset is at risk".
    """
    payload = load_context_layers(case_id, processed_dir=processed_dir)
    if not payload:
        return None
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    grid = view.grid
    if grid.empty:
        return {"case_id": case_id, "features": [], "summary": {"n_features": 0, "by_risk": {}}}
    lats = grid["lat"].to_numpy(dtype=np.float64)
    lons = grid["lon"].to_numpy(dtype=np.float64)
    cells = grid["cell_id"].astype(str).to_numpy()
    risks = grid["risk_level"].astype(str).to_numpy()
    land = grid["land_use"].astype(str).to_numpy()
    earth_radius_m = 6_371_000.0
    rows: list[dict[str, Any]] = []
    by_risk: dict[str, int] = {}
    for feature in payload.get("geojson", {}).get("features") or []:
        if not isinstance(feature, Mapping):
            continue
        props = feature.get("properties") if isinstance(feature.get("properties"), Mapping) else {}
        point = _feature_point(feature.get("geometry"))
        row = {
            "layer": props.get("layer"),
            "class": props.get("class"),
            "name": props.get("name"),
            "source": props.get("source"),
            "provenance_id": props.get("provenance_id"),
            "nearest_cell_id": None,
            "risk_level": None,
            "land_use": None,
            "distance_m": None,
        }
        if point is not None:
            lat0, lon0 = point
            phi0 = np.radians(lat0)
            phi = np.radians(lats)
            dphi = phi - phi0
            dlam = np.radians(lons - lon0)
            hav = np.sin(dphi / 2.0) ** 2 + np.cos(phi0) * np.cos(phi) * np.sin(dlam / 2.0) ** 2
            dist = 2.0 * earth_radius_m * np.arcsin(np.sqrt(np.clip(hav, 0.0, 1.0)))
            nearest = int(np.argmin(dist))
            row["nearest_cell_id"] = str(cells[nearest])
            row["risk_level"] = str(risks[nearest])
            row["land_use"] = str(land[nearest])
            row["distance_m"] = round(float(dist[nearest]), 1)
            by_risk[row["risk_level"]] = by_risk.get(row["risk_level"], 0) + 1
        rows.append(row)
    return {
        "case_id": case_id,
        "features": rows,
        "summary": {"n_features": len(rows), "by_risk": by_risk},
    }


def _feature_point(geometry: Any) -> tuple[float, float] | None:
    """Representative (lat, lon) of a GeoJSON geometry: the point, or the vertex mean."""
    if not isinstance(geometry, Mapping):
        return None
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        return float(coords[1]), float(coords[0])
    pairs: list[tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)) and len(node) >= 2 and all(
            isinstance(value, (int, float)) for value in node[:2]
        ):
            pairs.append((float(node[0]), float(node[1])))
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(coords)
    if not pairs:
        return None
    lon = sum(pair[0] for pair in pairs) / len(pairs)
    lat = sum(pair[1] for pair in pairs) / len(pairs)
    return lat, lon


_EXPORT_COLUMNS: tuple[str, ...] = tuple(field.name for field in C.GRID_FIELDS)


def get_filtered_export_csv(
    case_id: str,
    filters: Mapping[str, Any] | None = None,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> str:
    """CSV of the filtered H3 cells with contract columns only (no `color`/`height`).

    The column list is derived from `contracts.GRID_FIELDS`, not typed, so a schema bump cannot
    leave the download silently short of a new required column. Empty selects keep the header.
    """
    bundle = load_case_bundle(case_id, processed_dir=processed_dir)
    view = apply_filters(bundle, _dict_to_criteria(filters))
    frame = view.grid
    ordered = [column for column in _EXPORT_COLUMNS if column in frame.columns]
    return frame.loc[:, ordered].to_csv(index=False)


def get_cell_export(
    case_id: str,
    cell_id: str,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any] | None:
    """Attributes plus the series of one cell, ready to download as JSON."""
    return get_cell_detail(case_id, cell_id, processed_dir=processed_dir)


def load_availability(
    case_id: str,
    *,
    processed_dir: pathlib.Path | str = DEFAULT_PROCESSED_DIR,
) -> dict[str, Any] | None:
    """Declared NISAR search availability for `case_id` (catalogue metadata, no download).

    Reads `data/processed/_availability/{case_id}.json`, the record produced by the ASF
    search step. Nothing here is a measurement: it says which real stacks exist, whether
    they were downloaded (they are not) and what the query returned.
    """
    path = pathlib.Path(processed_dir) / "_availability" / f"{case_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    sources = data.get("sources") if isinstance(data, dict) else None
    nisar = sources.get("nisar_gunw") if isinstance(sources, dict) else None
    if not isinstance(nisar, dict):
        return None
    recommended = nisar.get("recommended_stack") if isinstance(nisar.get("recommended_stack"), dict) else None
    stacks: list[dict[str, Any]] = []
    for stack in nisar.get("stacks") or []:
        if not isinstance(stack, dict):
            continue
        stacks.append(
            {
                "track": stack.get("track"),
                "direction": stack.get("direction"),
                "frame": stack.get("frame"),
                "n_granules": stack.get("n_granules"),
                "date_range": stack.get("date_range"),
                "mean_interval_days": stack.get("mean_interval_days"),
                "recommended": bool(
                    recommended
                    and stack.get("track") == recommended.get("track")
                    and stack.get("direction") == recommended.get("direction")
                    and stack.get("frame") == recommended.get("frame")
                ),
            }
        )
    return {
        "case_id": case_id,
        "generated_utc": data.get("generated_utc"),
        "attempted": nisar.get("attempted"),
        "available": nisar.get("available"),
        "endpoint": nisar.get("endpoint"),
        "http_status": nisar.get("http_status"),
        "n_granules": nisar.get("n_granules"),
        "total_gb": nisar.get("total_gb"),
        "date_range": nisar.get("date_range"),
        "deltas_available": nisar.get("deltas_available"),
        "coverage_note": nisar.get("coverage_note"),
        "error": nisar.get("error"),
        "stacks": stacks,
    }


def _extract_science_section_1(science_path: pathlib.Path) -> str | None:
    """Extract §1 'The physics in one paragraph' verbatim from `docs/science-guide.md`."""
    if not science_path.is_file():
        return None
    text = science_path.read_text(encoding="utf-8")
    marker = "## 1. The physics in one paragraph"
    start = text.find(marker)
    if start == -1:
        return None
    body = text[start + len(marker) :]
    for stop in ("\n![", "\n---", "\n## "):
        idx = body.find(stop)
        if idx != -1:
            body = body[:idx]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return " ".join(lines) if lines else None


def _extract_case_roles(config_path: pathlib.Path) -> dict[str, dict[str, Any]]:
    """Return declared role, expected_regime and published_rate_mm_yr per case from `study_cases.yaml`."""
    if not config_path.is_file():
        return {}
    cfg = load_study_cases_config(config_path)
    out: dict[str, dict[str, Any]] = {}
    for slug, sc in cfg.cases.items():
        out[slug] = {
            "name": sc.name,
            "role": sc.role,
            "expected_regime": sc.expected_regime,
            "published_rate_mm_yr": sc.published_rate_mm_yr,
        }
    return out


_PHYSICS_HEADING = "### Scattering physics: surface roughness, dielectric constant, L-band vs C-band"


def _extract_physics(path: pathlib.Path) -> list[dict[str, str]]:
    """Read the three scattering bullets from `README.md` (title + verbatim text)."""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    start = text.find(_PHYSICS_HEADING)
    if start == -1:
        return []
    body = text[start + len(_PHYSICS_HEADING) :]
    stop = body.find("\n## ")
    if stop != -1:
        body = body[:stop]
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    bullet = re.compile(r"^-\s+\*\*(.+?)\*\*\s*(.*)$")
    for line in body.splitlines():
        stripped = line.strip()
        match = bullet.match(stripped)
        if match:
            if current is not None:
                items.append(current)
            current = {"title": match.group(1).rstrip("."), "text": match.group(2).strip()}
        elif current is not None and stripped:
            current["text"] = f"{current['text']} {stripped}".strip()
    if current is not None:
        items.append(current)
    return items


def load_documented_limits(
    readme_path: pathlib.Path | str = ROOT_DIR / "README.md",
    *,
    science_path: pathlib.Path | str = ROOT_DIR / "docs" / "science-guide.md",
    study_cases_path: pathlib.Path | str = DEFAULT_STUDY_CASES_PATH,
) -> dict[str, Any]:
    """Extract the GNSS caveat, §13 limitations, §1 science summary, case roles and physics."""
    path = pathlib.Path(readme_path)
    science_summary = _extract_science_section_1(pathlib.Path(science_path))
    case_roles = _extract_case_roles(pathlib.Path(study_cases_path))
    physics = _extract_physics(path)
    if not path.is_file():
        return {
            "section_8_caveat": None,
            "section_13": [],
            "science_section_1": science_summary,
            "case_roles": case_roles,
            "physics": physics,
        }
    text = path.read_text(encoding="utf-8")
    caveat: str | None = None
    paragraphs = [
        " ".join(line.strip() for line in block.splitlines() if line.strip())
        for block in re.split(r"\n\s*\n", text)
    ]
    gnss_re = re.compile(r"validat\w*\s+(?:the\s+convention\s+)?against\s+GNSS", re.IGNORECASE)
    for para in paragraphs:
        if gnss_re.search(para) and "Sign and heading conventions" in para:
            caveat = para
            break
    if caveat is None:
        for para in paragraphs:
            if gnss_re.search(para):
                caveat = para
                break

    start = text.find("## 13.")
    end = text.find("## 14.")
    numbered_re = re.compile(r"^(\d+)\.\s+(.*)$")
    items: list[str] = []
    if start != -1:
        block = text[start : end if end != -1 else None]
        current_parts: list[str] = []
        for line in block.splitlines():
            stripped = line.strip()
            match = numbered_re.match(stripped)
            if match:
                if current_parts:
                    items.append(" ".join(current_parts))
                current_parts = [match.group(2)]
            elif current_parts:
                if not stripped or stripped.startswith(("---", "#", "|", "![")):
                    items.append(" ".join(current_parts))
                    current_parts = []
                else:
                    current_parts.append(stripped)
        if current_parts:
            items.append(" ".join(current_parts))
    return {
        "section_8_caveat": caveat,
        "section_13": items,
        "science_section_1": science_summary,
        "case_roles": case_roles,
        "physics": physics,
    }


__all__ = [
    "get_case_series",
    "get_cell_detail",
    "get_cell_export",
    "get_cell_velocity_context",
    "get_color_scale",
    "get_context_exposure",
    "get_coherence_summary",
    "get_distance_summary",
    "get_extrusion_presentation",
    "get_filtered_export_csv",
    "get_land_use_bars",
    "get_layer_counts",
    "get_map_kpis",
    "get_map_layer_df",
    "get_scale_comparison",
    "get_series_kpis",
    "get_signal_status",
    "summarize_context_rows",
    "get_velocity_distribution",
    "get_view_state",
    "load_availability",
    "load_context_layers",
    "load_documented_limits",
    "load_land_use_options",
    "load_meta",
    "load_risk_levels",
    "load_study_cases",
    "load_timeseries",
]
