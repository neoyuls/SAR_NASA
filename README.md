# Three Cities, One Pump

**An interactive SAR subsidence & land-change explorer — NISAR + Sentinel-1.**

NASA Space Apps Challenge 2026 — *Dancing with the SARs*.
**Deliverable: a deployed web application**, not a report.

## ▶ Live demo: <https://noteam.cloud.run>

No install, no account, no NASA credentials. Open it in any browser; it boots on the committed
artefacts.

| | |
|---|---|
| Demo | **Live: <https://noteam.cloud.run>** (verified 2026-11-15: `/_stcore/health` → 200, root → 200, four tabs and the `DEMONSTRATION DATA` banner render at 1440×900). Local fallback: `./scripts/python.sh -m streamlit run app.py`, then open <http://localhost:8501> |
| Repository | `github.com/neoyuls/SAR_NASA` — the default branch **`main`** carries the artefacts, the pipeline, the tests and **contract v1.1** (62 acquisition dates per case). `yuls` is the older contract-1.0 line (12 dates); `main` already contains it, so nothing is waiting on it |
| Video | script ready in [`docs/video-script.md`](docs/video-script.md); recording pending |
| Team | **yuls** SAR science, GIS, product · **pozo** geospatial backend, deployment · **fradiaz** frontend, interaction |
| Challenge | NASA Space Apps 2026 — *Dancing with the SARs* |

> **What works today (2026-11-14, ~hour 41 of 48).** Contract v1.1 shipped and enforced by tests
> (its Rol 1 + Rol 2 sign-off is still outstanding — §10 and `docs/decisions.md` O-05) ·
> three contract-conformant **mock** artefact sets · the whole offline pipeline, rehearsed on
> synthetic granules · a Streamlit shell (`app.py`) that boots on the committed mock with no
> credentials · loaders, validation, filters and the PyDeck adapter (`src/data/`, `src/domain/`)
> with their own tests · `Dockerfile` and `.github/workflows/ci.yml` in the tree ·
> `./scripts/check_phase_a.sh` → PASS, `./scripts/preflight.sh` → `VERDICT: READY` (7/7 gates),
> and a fresh clone of the default branch, `main`, runs the full suite green.
>
> **What does not exist yet:** any run on a real granule. The public demo
> <https://noteam.cloud.run> is up: Cloud Run builds the root `Dockerfile`, validates the contract
> and the artefacts during the image build, and serves the same committed mock set with no
> credentials. **Every displacement value in `data/processed/` is synthetic** — `product: "mock"`,
> and every artefact says so in its own `provenance` and `limitations`. The context geometry is
> **not** synthetic: it is derived from an OpenStreetMap extract and offered under the ODbL 1.0
> (§17).
>
> **Language.** This README is the entry point (English). The operative role/workflow document
> [`flujo_trabajo_y_responsabilidades.md`](flujo_trabajo_y_responsabilidades.md) is in Spanish and
> prevails on anything about responsibilities, branches and phases; the data contract itself lives
> in [`docs/data-contract-v1.md`](docs/data-contract-v1.md) and `src/domain/contracts.py`.

---

## 1. What it is

A web app that lets anyone compare three cities over the same two-year window and understand why one of
them barely moves at all — with the 62-date series drawn whole, because the app has no time control.

| Capability | What the user does |
|---|---|
| **Series across the window** | The series tab draws all 62 dates at once. The **map** shows the first/last snapshot only (the contract carries `val_t1`/`val_t2`, not a per-date grid). There is **no date slider** — the only slider filters on minimum coherence |
| **Click to interrogate** | Click a cell → displacement series, trend, quality (needs `--per-cell-series` artefacts; the committed set carries only the AOI aggregate) |
| **Shared scale (opt-in)** | A **Scale** radio switches from per-case colouring (the default) to one shared cross-city scale, so the three cities can be read against each other |
| **Filter** | Case, land use, minimum coherence, risk level, 3D extrusion and theme — six controls; there is no velocity-threshold filter |
| **Evidence** | Every rendered number carries a unit, or the app says the unit is not declared; each group of figures prints one `Provenance ID` line, and the full source, date range and revisit interval sit in the provenance tab |
| **Learn** | Tab 4, **Provenance and limits**, carries a collapsed expander explaining NISAR, what SAR measures, and what it cannot |

### The thesis the app must make visible

Subsidence is set by **interbed compressibility**, not by how much water is pumped.

| | **Mexico City** | **Jakarta** | **Málaga** |
|---|---|---|---|
| Aquifer | Lacustrine clay, closed basin | Deltaic soft clay, coastal | Thin detrital cover, confined karst |
| Regime | Mostly **inelastic** | Mixed | Mostly **elastic** |
| Subsidence | **−45 cm/yr** (published) | ~5 cm/yr avg; >1 m cumulative | mm–cm/yr |
| Failure mode | Land loss, faulting, drainage inversion | Inundation, capital relocation | Salinization, reservoir depletion |

> **The product insight:** on a shared legend, Málaga renders nearly flat. **That blankness is the
> finding** — and it is a data decision (one scale, honest units, published detection limit), not a
> paragraph of prose.

![Velocity on one shared scale](docs/figures/velocity_shared_scale.png)

*The three cases on one symmetric ±425 mm/yr scale, drawn straight from the **synthetic mock**
artefacts (`product: mock`) —
Mexico City's bowl, Jakarta's coastal edge, and Málaga essentially blank. Generated by
`scripts/make_figures.py`; the numbers behind it are pinned by `tests/test_handoff_numbers.py`.*

---

### Verify in 15 seconds

Both gates need the venv first — the two setup lines are in the setup section below. On a fresh
clone without it, `check_phase_a.sh` fails with four `.venv/bin/python missing` errors.

```bash
./scripts/check_phase_a.sh     # ~15 s → PHASE A/B: PASS · 3 cases · 0 problems · 4.740 MB / 15 MB
./scripts/preflight.sh         # fuller: seven gates, per-gate table, ends in a VERDICT line
```

| case | cells | window | median mm/yr | product | source |
|---|---:|---|---:|---|---|
| `mexico-city` | 11,600 | 2024-11-10 → 2026-11-12 | −64.7 | mock | synthetic |
| `jakarta` | 4,936 | same window | −25.9 | mock | synthetic |
| `malaga` | 2,758 | same window | −1.3 | mock | synthetic |

The full suite (`./scripts/python.sh -m pytest tests`, ~4.5 min) is the thorough check; the gate is
what a judge should run first. `scripts/demo_numbers.py` prints every number a presenter may say,
derived from the artefacts rather than typed into a slide.

`./scripts/preflight.sh` is the fuller pre-submission check behind that gate: it runs the seven hard
gates from `docs/submission-checklist.md` — contract self-check, pytest suite, artefact gate, phase
A/B handoff, clone reproduction, figures regenerate, demo numbers — keeps going after a failure,
and prints a per-gate table ending in `VERDICT: READY` or `VERDICT: NOT READY`. Our last full run
printed `VERDICT: READY`, with notes that the tree was dirty and that the committed artefacts
differ in size from the working tree — so run it on the commit you submit, and fix whatever a red
verdict names before submitting.

If the app is not runnable when the demo is recorded, [`docs/demo-fallback.md`](docs/demo-fallback.md)
is the backup plan using only the committed figures and `scripts/demo_numbers.py`.

---

## 2. Scope: what we build in 48 h, and what we refuse to build
### In scope

- **One primary case executed properly** (+ a second site pre-loaded if time allows); Málaga is the
  declared **negative control**, and its null result ships with its detection limit.
- A **documented, reproducible offline Python pipeline** that uses real NISAR L2 products, or a
  **declared fallback source** recorded in `provenance`.
- A **modular Streamlit app**: 2D/3D map, reactive KPIs, time series, filters, educational tab.
- **Full traceability**: every number carries source, sensor, product, unit, dates and method.

### Out of scope (do not spend time here)

- ❌ Live HDF5 download/processing on click or on app start.
- ❌ Raw L1 (`RSLC`) InSAR processing with ISCE2 when L2 or a processed product exists.
- ❌ **PMTiles, CDN, MapLibre/deck.gl** as MVP requirements. The static Option B architecture is
  documented and reproducible later (`docs/route-contract.md`) because the data contract does not
  change when we migrate — but it is **not** on the critical path tonight.
- ❌ PostgreSQL/PostGIS, a separate FastAPI backend, user authentication.

### Cut lines, in order

1. Change-event pins → 2. third city → 3. everything except Málaga via EGMS.
**Never cut:** `provenance`.

---

## 3. Architecture — compute offline, ship artefacts, render in Streamlit

The highest-risk failure mode in a 48 h demo is *live InSAR*. So the heavy work happens **before**
the app starts, and the app only reads small local artefacts.

```
┌──────────────────────────────────────────────────────────────┐
│ LAYER 1 — OFFLINE PIPELINE            (yuls, Rol 3)          │
│                                                              │
│  ASF / EGMS / HyP3                                           │
│        ↓  discover + download (resumable, size-guarded)      │
│  clip → reproject → physical conversion → quality filter     │
│        ↓  H3 res 9 aggregation, GIS enrichment               │
│  nisar_grid.parquet · timeseries.csv                         │
│  context_layers.geojson · meta.json        ← FROZEN contract │
└──────────────────────────┬───────────────────────────────────┘
                           │  stable, versioned data interface
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ LAYER 2 — STREAMLIT APP      (pozo Rol 1 + fradiaz Rol 2)    │
│                                                              │
│  loaders → validation → filters → map → KPIs → charts        │
│                                                              │
│  No NASA downloads. No heavy processing. No science in the UI │
└──────────────────────────────────────────────────────────────┘
```

**Why this shape:** no server to fall over, no cold start mid-judging, no token expiry, and the
frontend never blocks on the pipeline — the mock respects the same schema, so swapping mock for
real data is a file replacement, not a code change.

### Layer rules (enforced by the contract and by review)

- `app.py` only composes; no science, no file parsing logic inline.
- The pipeline **never** imports Streamlit.
- The UI **never** computes a geospatial quantity: if a number is not in an artefact, it does not
  exist.
- Scientific parameters (thresholds, units, revisit intervals) live in `src/domain/contracts.py`
  and `meta.json`, never duplicated in a component.

---

## 4. Data contract v1.1 — frozen

Four artefacts per case, under `data/processed/`. This is the whole interface between pipeline and
app; it is versioned, validated in code and locked by a regression suite.

| Artefact | Contents |
|---|---|
| `nisar_grid.parquet` | One row per H3 res-9 cell (~200 m): `cell_id`, `lat`, `lon`, `val_t1`, `val_t2`, `delta_change` (mm, cumulative), `velocity_mm_yr`, `coherence`, `land_use`, `risk_level`, `case_id`, `sensor`, `product`, `unit`, `velocity_unit`, `source`, `acquisition_date`, `provenance_id` |
| `timeseries.csv` | `case_id`, `cell_id` (`"aoi"` = aggregate, H3 index = drill-down), `date`, `value` (mm), `unit`, `sensor`, `product`, `quality`, `provenance_id` |
| `context_layers.geojson` | `FeatureCollection` in EPSG:4326: land use, infrastructure, hydrology, boundaries — each feature carries `layer`, `class`, `case_id`, `crs`, `source`, `provenance_id`. © OpenStreetMap contributors, ODbL 1.0; a Derivative Database, not MIT (§17) |
| `meta.json` | `schema_version`, `case_id`, `name`, `bbox`, `crs`, `reference_point`, `dates`, `revisit_days`, `sensor`, `product`, `thresholds`, `provenance`, `stats`, `limitations`, `null_policy` (nested objects `thresholds{}`/`provenance{}`/`stats{}`; `limitations` is a list) |

Normative details: **[`docs/data-contract-v1.md`](docs/data-contract-v1.md)**.
Source of truth (code): **[`src/domain/contracts.py`](src/domain/contracts.py)**.

### What "frozen" costs and buys

| | |
|---|---|
| Version | `1.1`, revision 2, frozen 2026-11-14 |
| Fingerprint | `ed92be80…` (`contract_fingerprint()`) |
| Changing it | bump `SCHEMA_VERSION` + `CHANGELOG` entry + PR section `Impacto sobre el contrato:` + review by all three roles |
| Enforced by | the contract, mock-plausibility and gate suites (`./scripts/python.sh -m pytest tests -q`); any silent rename, retype or enum drift fails the suite **and** the gate |

Four rules that exist because they were ambiguous in the source documents:

1. **Cumulative vs rate.** `delta_change` is cumulative **mm**; the rate lives in `velocity_mm_yr`.
   One field cannot honestly be both.
2. **Product is declared, not assumed.** Closed enum, and it must be the product actually used —
   `nisar-gunw` or `mock` tonight (§5). Labelling mock data `opera-disp-s1` would be a lie.
3. **Nothing is pooled across sensors.** Thresholds and `revisit_days` are per
   `(sensor, product)`; NISAR's 12-day coherence is not Sentinel-1's 6-day coherence.
4. **No sentinel values.** A cell without data is **absent**; it is never written as `0`. In
   Málaga, zero is a legitimate velocity and confusing it with nodata destroys the message.

### Validate it

```bash
./scripts/python.sh -m src.domain.contracts           # self-check: positives + negatives
./scripts/python.sh -m pytest tests -q                # contract + artefact suites
./scripts/python.sh pipeline/validate_artifacts.py --processed data/processed   # file-level gate
./scripts/check_phase_a.sh                            # all of the above + a handoff summary
```

The gate is **fail-closed**: zero cases validated is a failure, and a `--case` filter that matches
nothing is a failure. `--allow-empty` exists for pre-mock CI and says so loudly when used.

---

## 5. Data sources — and what we actually verified

`✓` = live-checked. All open/free unless noted.

| Source | URL | Status |
|---|---|---|
| NISAR product summary (ASF) | `asf.alaska.edu/datasets/daac/nisar` | ✓ |
| NISAR Data User Guide | `nisar-docs.asf.alaska.edu` | ✓ |
| ASF Search API / Vertex | `api.daac.asf.alaska.edu` · `search.asf.alaska.edu` | ✓ |
| **HyP3** (on-demand cloud InSAR) | `hyp3-docs.asf.alaska.edu` | ✓ |
| OPERA DISP-S1 | `displacement.asf.alaska.edu` | ✓ (absent for our AOIs) |
| **Copernicus EGMS** (EU, mm/yr) | `egms.land.copernicus.eu` | ✓ (Málaga only) |
| Hydrology | GRACE-FO mascons (PO.DAAC ✓) · GLDAS ✓ · IGRAC ✓ · USGS NWIS ✓ · SAIH · CONAGUA/SACMEX |
| Urban context | GHSL ✓ · WorldPop ✓ · DLR WSF 2019 ✓ · Copernicus EMS ✓ · Overture/OSM |

### Availability probe — 2026-11-14 (reproducible, no credentials needed)

`pipeline/ingest/02_search_download.py search` → `data/processed/_availability/{case}.json`. Those
files are **tracked**, so re-running the probe rewrites three committed files and leaves the tree
dirty; restore them with `git checkout -- data/processed/_availability`.

| Source | Mexico City | Jakarta | Málaga |
|---|---|---|---|
| **NISAR GUNW** (ASF) | 69 granules, 2025-10-25 → 2026-10-08 | 25 granules, 2026-06-26 → 2026-10-01 | 26 granules, 2026-06-20 → 2026-10-06 |
| **OPERA DISP-S1** | **0** | **0** | **0** |
| Sentinel-1 SLC (5 y window) | 250+ granules, ~1.07 TB | 250+ granules, ~1.18 TB | 250+ granules, ~0.96 TB |
| EGMS | not eligible | not eligible | manual portal download |

Each report also derives `stacks` per (track, frame, flight direction) plus a `recommended_stack`
(largest single-geometry stack, sampled evenly across its window). `download --stack recommended`
plans from it, so a fetch is one geometry by construction instead of a preview of everything ASF
returned — which is what the mixed-geometry guard would otherwise refuse.

**Every recommended stack clears the fit minimum.** Counted from the same JSON, the recommended
stack per case is `mexico-city` track 113 / frame 079 descending (33 granules, 22 epochs in one
connected run, 13 of them in the download window), `jakarta` 018 / 092 descending (8 granules, 9
epochs) and `malaga` 095 / 070 descending (9 granules, 10 epochs) — all above
`MIN_FIT_POINTS = 4`, so all three carry `epoch_sufficient: true`. This paragraph used to report
`malaga` as **2**, an insufficiency that turned out to be an artefact of grouping by frame where the
grammar says track: two orbits sat under one frame label. The grammar is reconciled (O-06) and the
reports were re-derived from their unchanged granule lists, so the number is 10. Intersecting the AOI
is still not the same as having a chain long enough to fit — here it is, and Málaga is the negative
control for signal, not for fittability.

**Consequences, decided now and written into the contract:**

- `meta.product` for the first integration is **`nisar-gunw`** (with an explicit urban-coverage
  caveat) **or `mock`** — never `opera-disp-s1`.
- NISAR GUNW is provisional and **cryosphere-derived**; SME2 excludes urban areas. An intersecting
  granule must be visually verified before we claim city-wide displacement. If it fails, the
  fallback chain is HyP3 Sentinel-1 → OPERA DISP-S1 → EGMS → local ISCE2+MintPy from GSLC, and
  **the provenance line shows which one won**.
- Sentinel-1 archives are deep enough that an HyP3 on-demand stack is always feasible — at 6-day
  revisit, so its coherence thresholds must never be pooled with NISAR's.

> **The provenance rule.** Each group of figures prints one `Provenance ID` line, and the full
> `provenance.source` record is in the provenance tab. If the demo runs on mock data, the app says so.
> Judges reward that; they punish the alternative.

The full decision record — options, evidence, the verification checklist a GUNW granule must pass
before it may be labelled `nisar-gunw`, and the accepted consequences:
**[`docs/data-source-decision.md`](docs/data-source-decision.md)**. The HDF5 paths behind that
checklist are in **[`docs/nisar-gunw-layout.md`](docs/nisar-gunw-layout.md)**.

---

## 6. Science pipeline (offline)

The step names below are the **design**, not a status report. Each line says what the code does
today, because at ~hour 40 of 48 the difference between "designed" and "shipped" is the difference
between a roadmap and a claim.

```
P0  Scope      AOI polygon, EPSG:326xx, reference pixel
P1  Ingest     asf_search → NISAR GUNW / HyP3 / DISP-S1 / EGMS   (record provenance + revisit)
P2  Interfero  only if needed: ISCE2 + SNAPHU → GUNW/RUNW
P3  Correct    RAiDER/GACOS troposphere; MintPy DEM error + ramps      designed, not implemented
P4  Series     connected pairs chained → cumulative cube               implemented (no inversion)
P5  Decompose  LOS → vertical, ONE geometry, v_north≈0                 implemented
P6  Separate   trend + seasonal harmonic(s) → secular vs seasonal      implemented
P7  Metrics    velocity, compaction volume                             implemented
               |∇v|, S* = Δb/Δh                                        designed, not implemented
P8  Aggregate  H3 res 9 mean, coherence filter, land use + risk join
P9  Join       buildings, population, reservoirs, groundwater head
P10 Emit       nisar_grid.parquet · timeseries.csv · context_layers.geojson · meta.json
```

**What actually ships** (`pipeline/process_case.py`, rehearsed on synthetic granules):
coherence mask → LOS→vertical from **one** geometry (sign convention recorded, not yet validated
against GNSS) → per-cell trend + annual harmonic, centred on the window in the mock generator →
cumulative `delta_change` → `velocity_mm_yr` → frozen risk bands → H3 res 9 aggregate → the four
contract artefacts.

### Equations

Each equation carries one of three states: **implemented and used** (module named), **computed but
not published**, or **designed, not implemented**. Read the last two as roadmap, not as results.

**LOS projection** (incidence `θ`, heading `α`) — *implemented and used*
(`transforms.los_unit_vector` / `vertical_from_los`, called once per pair):

```
d_LOS = u · [v_up, v_east, v_north]ᵀ ,   u = [cosθ, −sinθ·cosα, −sinθ·sinα]
```

**The asc+desc two-geometry inversion is designed, not implemented.** Two geometries would give 2
equations for 3 unknowns and let `v_north` go free; the shipped pipeline instead **refuses** a stack
that mixes flight directions (`_check_stack_identity` → `TrackMismatchError`, "process each
direction separately") and inverts a **single** geometry: `v_up = d_LOS/cosθ + tanθ·(cosα·v_east +
sinα·v_north)` with `v_north = 0` unless a GNSS model is supplied. One pass cannot separate the
horizontals from vertical — `u_up = cosθ` is heading-independent, so the `platform` and `look`
azimuth conventions give identical numbers here — and "purely vertical" is an assumption, not a
measurement.

**Sign and heading conventions are recorded, not validated.** `--los-sign` (default
`toward-sensor`: `d_LOS = -λ/4π·φ` with a **positive** value meaning the ground moved toward the
sensor, i.e. uplift, because up is positive and `u_up = cos θ > 0` — the same direction
`project_to_los` computes; `away-from-sensor` is the `+λ/4π` flip) and `--heading-convention` (default
`platform`) are written into `provenance`, and `provenance.method` keeps its "NOT yet validated
against GNSS" hedge; passing the flags restates the convention, it does not check it. **O-08 is
closed by renaming, not by re-deriving:** the default factor is still -1.0, so no published number
moved — only the label (and the prose derived from it) now matches the projection. Validate the
convention against GNSS before publishing real numbers.
**Axis/sign conventions differ between ISCE2, MintPy and SNAP.**

**Time-series model** (drives the trend/seasonal split) — *harmonic part implemented, step part
not*:

```
v(t) = v₀ + ṫ·t + Σₖ [Aₖcos(2πkt/T) + Bₖsin(2πkt/T)]      implemented (transforms.harmonic_fit)
     + Σⱼ Δvⱼ·H(t−tⱼ)                                      designed, not implemented
```

`ṫ` → secular, shipped as `velocity_mm_yr`; `A_seasonal` → elastic/recoverable. The annual harmonic
sits **inside** the fitted basis, which is what stops a 12-day-sampled subsiding city from labelling
its seasonal swing as a trend — that collinearity is the point of P6, and the observable order is
the one the span can identify (`_harmonic_order`). **There is no step code anywhere in the tree:**
`harmonic_fit` says so in its docstring ("step detection is deliberately out of scope"), and a
step-date search would overfit a 12-date window. Nothing publishes a step duration or date.

**Regime index** — *computed and published*:

```
R = |ṫ| / A_seasonal     →  "inelastic" > 2, "transitional" 1–2, "elastic" < 1
```

`transforms.classify_regime` computes it and `HarmonicFit.regime` carries it; the contract freezes the enum in
`REGIMES` and **transports it**: `regime` is a required grid column, and `stats.median_ratio_R` /
`stats.dominant_regime` carry the case-level summary, so the band is a published artefact field rather than an
internal number. What the app *colours* on the map is the frozen risk band below — a velocity threshold, a different
quantity — while the regime reaches the reader as a value and a card.

The reason that field can be trusted is the gate in front of it: `transforms` refuses to fit below
`MIN_SEASONAL_COVERAGE_PER_HARMONIC` cycles per harmonic and `MAX_DESIGN_CONDITION`, and a case under either publishes
`seasonal_amp_mm = 0` ("not fitted"), `ratio_R = null` and `regime = "transitional"` instead of a recovered band.
The field therefore never asserts recoverability the window cannot resolve.

**Storage loss** — *volume implemented, coefficient designed*:

```
dV/dt = Σ_px v_up · A_px / 1000   →  meta.stats compaction_volume_m3_yr / storage_loss_m3_yr
S_skv = Δb / (b₀·Δh)                 skeletal specific storage — designed, not implemented
```

`transforms.velocity_metrics` computes `dV/dt` as a signed `compaction_volume_m3_yr` and publishes
`storage_loss_m3_yr = −dV/dt` (positive = volume lost) on the real `process_case.py` path; the
committed **mock** `meta.stats` carries only the frozen contract keys, so the demo artefacts
themselves do not show it. `S_skv` appears nowhere in the tree — it needs `b₀` and `Δh` per aquifer
from hydrogeology, which we do not have per cell, so the skeletal storage coefficient stays a
reference concept (§16), not a product.

**Velocity gradient** — *designed, not published*:

```
|∇v| = hypot(∂v/∂x, ∂v/∂y)     branch exists for 2-D fields only; the caller passes 1-D cells
```

`transforms.velocity_metrics` has the forward-difference branch, but it is skipped unless the input
is a 2-D raster, and `process_case.py` hands it the per-cell 1-D velocity vector — no `gradient_*`
key reaches any `meta.stats`, and no layer shows a gradient.

**Risk band** — *implemented and used* (frozen in `contracts.py`, `risk_level_from_velocity`,
sign-agnostic): `|v| < 5` → `estable`, `5–25` → `moderado`, `≥ 25 mm/yr` → `critico`.

### Scattering physics: surface roughness, dielectric constant, L-band vs C-band

Three controls decide whether a surface can be measured at all, before any displacement is
estimated. They are brightness effects, not motion: this cockpit publishes `delta_change` and
`velocity_mm_yr` from phase, and never turns amplitude into a moisture or biomass claim.

- **Surface roughness.** A radar pixel returns a strong echo when the surface is rough at the scale
  of the wavelength and a weak, specular one when it is smooth: flat water sends the pulse away from
  the antenna, which is why open water decorrelates and is masked instead of measured. Roughness
  therefore gates observability; it does not enter the displacement arithmetic.
- **Dielectric constant.** The surface's complex dielectric constant sets how much of the pulse is
  reflected and how much penetrates. Liquid water raises it sharply, so wet soil and vegetation
  scatter more strongly than dry ground. That contrast is backscatter — useful for reading coherence
  and land cover, never converted into a stored-water number here.
- **L-band vs C-band.** NISAR's L-band wavelength (λ ≈ 0.2384 m, about 24 cm) is roughly four times
  longer than Sentinel-1's C-band (about 5.6 cm). The longer wavelength penetrates canopy and dry
  soil better and decorrelates more slowly, so a 12-day pair stays usable over a vegetated or dusty
  city; the cost is scale, since one fringe spans a larger displacement. Coherence is comparable
  only within one revisit interval and one band — never pool L-band and C-band numbers.

---

## 7. Roles & responsibilities

Three people, three verticals, one frozen contract. Source of truth (Spanish, prevails):
[`flujo_trabajo_y_responsabilidades.md`](flujo_trabajo_y_responsabilidades.md).

| | **Rol 3 — yuls** | **Rol 1 — pozo** | **Rol 2 — fradiaz** |
|---|---|---|---|
| Scope | SAR science, GIS, product | Geospatial backend & maps | Frontend & interaction |
| Produces | `pipeline/`, the four artefacts, provenance, narrative | `src/data/*`, `src/domain/{filters,metrics}.py`, CI/CD, deployment | `app.py`, `src/ui/*`, `.streamlit/config.toml` |
| Never | writes UI components | changes scientific parameters | computes geospatial quantities |

### Handoffs

- **Rol 3 → Rol 1:** four artefacts + `meta.json` + provenance ids. Rol 1 guarantees schema,
  units, CRS and null handling via loaders/validation.
- **Rol 1 ↔ Rol 2:** map-ready datasets (coordinates, H3 geometry, colour value, column height,
  risk category, context layers) and the interaction contract. The UI style never decides a
  threshold; the backend never decides a colour.
- **Rol 3 ↔ Rol 2:** legends, wording, and the rule that results are not over-interpreted —
  Málaga must read as a negative control, not as a failure.

### Shared duties

- Define and review the data schema; validate units, CRS and provenance.
- Agree field names and types before coding against them.
- Keep `main` runnable; review every contract change as a group.
- Confirm PyDeck can render each layer before promising it.

---

## 8. Repository layout

**[`CONTEXT.md`](CONTEXT.md)** is the concise project orientation. Its detailed companions cover
[science](docs/science-guide.md), [pipeline internals](docs/pipeline-internals.md), and
[verification](docs/verification.md); the frozen contract remains in `docs/data-contract-v1.md`.
The choices made along the way, each with its evidence and the condition that would reverse it, are
recorded in **[`docs/decisions.md`](docs/decisions.md)**.

```
├── README.md                          ← this file (entry point)
├── flujo_trabajo_y_responsabilidades.md   ← operative doc: roles, branches, phases (Spanish)
├── docs/
│   ├── data-contract-v1.md            ← FROZEN contract, normative for the four artefacts
│   ├── data-source-decision.md        ← which product we process, and the evidence
│   ├── nisar-gunw-layout.md           ← verified HDF5 paths inside a GUNW granule
│   ├── handoff-mock.md                ← what pozo and fradiaz can rely on tonight
│   ├── first-granule-runbook.md        ← step-by-step for the first real granule (with pass/fail)
│   ├── video-script.md                 ← 20 s / 90 s / 30 s script, numbers derived from the artefacts
│   └── route-contract.md              ← post-MVP Option B: PMTiles routes (not built yet)
├── src/
│   ├── domain/contracts.py            ← frozen schema, enums, thresholds, validators
│   ├── domain/{filters,metrics,map_adapter}.py  ← Rol 1 (done): filtering, KPIs, PyDeck payload
│   ├── data/{loaders,ui_bridge,validation}.py    ← Rol 1 (done): cached loaders, cockpit bridge, fail-closed gate
│   └── ui/                            ← Rol 2 (not built): the shell lives in app.py for now
├── app.py                             ← Rol 2 (done, local only): Streamlit shell, composition only
├── pipeline/
│   ├── ingest/02_search_download.py   ← availability probe + guarded, resumable download (done)
│   ├── ingest/aois.json               ← AOI bboxes, CRS, reference points (done)
│   ├── ingest/README.md               ← probe/download usage + credential setup (done)
│   ├── ingest/inspect_hdf5.py         ← prints a granule's tree, units and candidate layers (done)
│   ├── ingest/nisar_gunw.py           ← reads phase/coherence/mask from a GUNW granule (done)
│   ├── generate_mock.py               ← Rol 3 (done): mock respecting the contract
│   ├── mock/                           ← case specs, invented geography, field model, writers
│   ├── science/transforms.py          ← Rol 3 (done): LOS→vertical, harmonic fit, H3 aggregation
│   ├── enrich_context.py              ← maps OSM-style features to the frozen land_use vocabulary (done)
│   ├── aoi.py                         ← resolves config/aoi/{case}.geojson → the AOI ring + H3 cells
│   ├── process_case.py                ← granule stack → the four artefacts (done)
│   ├── validate_artifacts.py          ← Rol 3 (done): fail-closed file-level contract gate
│   └── README.md                      ← judge-facing methods + limitations (done)
├── tests/                             ← contract, doc-drift, config-drift, mock-plausibility, gate suites
├── scripts/
│   ├── python.sh                      ← run Python through the venv with the NixOS libs on the path
│   ├── check_phase_a.sh               ← contract → suites → artefact gate → handoff summary
│   ├── make_figures.py                ← the three pitch figures, straight from the artefacts
│   ├── demo_numbers.py                ← every number the presenter may say, derived not typed
│   ├── export_grid_geojson.py         ← grid → GeoJSON cell polygons (H3 rings) for QGIS / kepler.gl
│   ├── style_qgis_layers.py           ← the same palette as generated QGIS .qml styles (no colour declared here)
│   └── rehearse_first_granule.py      ← runs the runbook's offline steps on a synthetic stack
├── requirements.txt                   ← full workspace: pipeline + backend + Streamlit app + tests
├── pytest.ini
├── data/
│   ├── raw/                           ← downloads, gitignored
│   └── processed/                     ← the four artefacts + `_availability/` evidence
└── config/study_cases.yaml            ← primary case + AOI polygon (done; primary = mexico-city)
```

`data/raw/` never enters Git. `data/processed/` stays under **15 MB**.

---

## 9. Getting started

```bash
# 1. Environment (Python 3.11+; this repo's dev box runs 3.14 in a venv)
python3 -m venv .venv
./scripts/python.sh -m pip install -r requirements.txt
#   on NixOS you may prefer: nix shell nixpkgs#uv -c uv pip install --python .venv/bin/python -r requirements.txt

# 2. Prove the contract is intact
./scripts/python.sh -m src.domain.contracts
./scripts/python.sh -m pytest tests -q

# 3. Ask ASF what actually exists for our three AOIs (no credentials needed)
./scripts/python.sh pipeline/ingest/02_search_download.py search
./scripts/python.sh pipeline/ingest/02_search_download.py report

# 4. Plan a download first — the guard refuses L0 RRSD / L1 RSLC and any unrecognised name
#    before a socket is opened; `--stack recommended` plans ONE geometry, not a preview of
#    everything ASF returned.
./scripts/python.sh pipeline/ingest/02_search_download.py download \
    --city mexico-city --source nisar_gunw --stack recommended --max-gb 6 --dry-run
#    Offline and reproducible: no credentials, no writes (a guard executes this exact line).
#    But NISAR GUNW arrives SIZELESS from the ASF SearchAPI, so this plan cannot refuse on budget:
#    it sums 0 MB and says the cap was not preflighted, rather than pretending it was.
#    Details: docs/first-granule-runbook.md.

# 4b. The same plan with sizes resolved, which is what makes `--max-gb` real: one unauthenticated
#     HEAD per planned granule (~2.34 GB each) reads Content-Length before any granule byte moves.
./scripts/python.sh pipeline/ingest/02_search_download.py download \
    --city mexico-city --source nisar_gunw --stack recommended --max-gb 6 --probe-sizes --dry-run
#    exits 5: the 12-granule CDMX plan sums 28.23 GB against the 6 GB cap and refuses.
#    Raise `--max-gb` only to the size the probe printed (a deliberate act, recorded in
#    `provenance.json.max_gb`), never blind — see step 5.

# 4c. Spend one granule first, not the stack: `--max-granules N` keeps the FIRST N granules in
#     reference-date order (O-01), which is the cheapest way to prove the HDF5 reader against a
#     real file before paying for a whole chain. Note that `--max-granules` does not lift the budget
#     guard: the default `--max-gb 2.0` is smaller than one GUNW granule (~2.3 GB), so without a
#     budget the command is REFUSED with exit 5. Once the budget covers the granule, a plan below
#     `MIN_FIT_POINTS` epochs proceeds and warns: one granule is for inspecting the file, not for
#     fitting a case.
./scripts/python.sh pipeline/ingest/02_search_download.py download \
    --city mexico-city --source nisar_gunw --stack recommended --max-granules 1 --max-gb 3 --probe-sizes --dry-run

# 5. Download (needs Earthdata credentials AND the one-time ASF application approval;
#    fails closed, with an actionable message, when either is missing)
export EARTHDATA_USER=... EARTHDATA_PASS=...
./scripts/python.sh pipeline/ingest/02_search_download.py download \
    --city mexico-city --source nisar_gunw --stack recommended --max-gb 30 --probe-sizes
#    Raise `--max-gb` only to the size the probe actually printed (a deliberate act, recorded in
#    `provenance.json.max_gb`), never blind. A 4-epoch minimum stack (MIN_FIT_POINTS) is already
#    ~9.4 GB, so the old `--max-gb 6` could never have fetched a fittable stack.

# 6. Never trust a granule you have not looked inside. `data/raw/` is gitignored and therefore
#    absent in a fresh clone: this step only works after step 5 has actually downloaded, and with
#    no granules it exits 2 with "path does not exist".
./scripts/python.sh pipeline/ingest/inspect_hdf5.py data/raw/mexico-city/nisar_gunw/*.h5 --product nisar-gunw

# 7. Granule stack -> the four artefacts, then gate what you produced. `a.h5`/`b.h5` are
#    placeholders: pass one `--granule` per downloaded epoch, from
#    `data/raw/mexico-city/nisar_gunw/`.
./scripts/python.sh pipeline/process_case.py --case mexico-city \
    --granule a.h5 --granule b.h5 --out data/processed/mexico-city --force
./scripts/python.sh pipeline/validate_artifacts.py --processed data/processed
```

`scripts/python.sh` exists because the Nix interpreter does not put `libstdc++`/`libz` on the
default search path that pip wheels expect. **Use it instead of `.venv/bin/python`** so everyone
gets identical behaviour. Register at <https://urs.earthdata.nasa.gov> and accept the ASF EULA
before downloading anything.

---

## 10. Git workflow

Short branches off `main`, one objective each, merged by PR (full detail in the flujo doc §6).
`main` must always run.

```
main
├── feat/data-contract          ✅ merged — contract v1.1
├── feat/pipeline-mock          ← next: unblocks the app
├── feat/gis-context
├── feat/backend-map-data
├── feat/ui-shell → feat/ui-map → feat/ui-charts
├── feat/pipeline-real-source
├── chore/ci-validation
└── release/mvp
```

Merge order (flujo §6.2): `data-contract` → `pipeline-mock` → `gis-context` → `backend-map-data` →
`ui-shell` → `ui-map`/`ui-charts` → `pipeline-real-source` → `ci-validation` → `release/mvp`.
Nothing merges ahead of the mock: it is what lets Rol 1 and Rol 2 work in parallel.

Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`. Every PR states **Objetivo / Archivos /
Dependencias nuevas / Impacto sobre el contrato / Validaciones ejecutadas / Riesgos**. Contract
changes need all three roles; backend+data needs Rol 1 + Rol 3; UI needs Rol 2 + Rol 1.

**Keep `main` true.** `main` is both the default branch and the integration branch: it carries the
artefacts, the pipeline, the tests and contract v1.1, and `origin/yuls` — the frozen contract-1.0
line, 12 acquisition dates — is already an **ancestor** of it. So the integration is not pending and
there is no fast-forward waiting to happen: `main` is ahead of every work line, which makes an
`--ff-only` fast-forward *onto* `yuls` impossible rather than merely unwise. Work merges **into**
`main` from a short-lived branch off it (flujo §6), and nothing here undoes `main`.

Two facts live in that paragraph, and conflating them is how this section went wrong. **v1.1 is on
`main`** — reachable, measurable, and the commands below check it. **v1.1 is not yet approved** — the
contract's own rule needs Rol 1 + Rol 2 sign-off for a `SCHEMA_VERSION` bump and no sign-off record
exists, so what shipped is a merged proposal, kept in `docs/decisions.md` O-05. Do not read "it is on
the default branch" as "the other two roles agreed".

Do not restate the commit or file **distance** here — it rots on the next push (this sentence used to
quote a commit count and a diffstat, and was stale within a day). Run `git fetch origin` first, then
ask git: these commands describe the **GitHub** remote, and in a clone whose remote refs are stale
`origin/HEAD` can still point at a work branch, `origin/main` can be behind, and
`git show origin/main:data/processed/…` exits 128 — every answer below would then be wrong.
`git rev-list --count origin/yuls..origin/main` and `git diff --stat origin/yuls..origin/main`. The
acquisition-date counts are the one exception, and they are safe to print because they are artefact
data, re-derived by `tests/test_readme_numbers.py` from `data/processed/*/meta.json` on every suite
run — so they cannot silently go stale. Measure the claims above rather than trusting this file:

```bash
git rev-parse origin/HEAD origin/main       # same commit: the default branch is main
git merge-base --is-ancestor origin/yuls origin/main && echo "yuls is contained in main: exit 0"
git show origin/main:data/processed/mexico-city/meta.json | grep -E '"schema_version"|"n_dates"'
git show origin/yuls:data/processed/mexico-city/meta.json | grep -E '"schema_version"|"n_dates"'
```

Everything under `data/processed/` is 5.02 MB (4.740 MB of artefacts plus the `_availability/`
evidence), so it belongs in the repo; `data/raw/` never does.

**Working safely with uncommitted work.** On 2026-11-14 a `git reset --hard` silently reverted every
tracked file to HEAD and deleted a staged-only script — and `git` reported *no deletion*, because
HEAD had never seen that file. With several people (and agents) writing in parallel: commit early,
and avoid `git reset --hard`, `git checkout -- .` and `git stash` while anything is uncommitted.
Use `git status` and `git diff` to inspect — they cannot lose work.

---

## 11. Plan & definition of done

| Phase | Goal | Exit criterion |
|---|---|---|
| **0 — sync** (H0) | case, source, contract, branches | ✅ contract frozen; all three can run the tests |
| **1 — mock** (H0–2) | the four artefacts, fake values, real schema | app starts locally on mock only |
| **2 — parallel build** (H2–30) | loaders/filters (Rol 1), UI (Rol 2), real source + physics (Rol 3) | map, KPIs and filters react to mock data |
| **3 — real data** (H30–40) | replace mock with real, same schema | app runs unchanged on real artefacts |
| **4 — validate & deploy** (H40–46) | clean-room run, sizes, cache, public URL | pipeline reproducible from scratch; URL up |
| **5 — freeze** (H46+) | code freeze, docs, video | only critical fixes after this point |

**Tonight's checklist** (flujo §10, condensed)

- [x] Contract v1.1 shipped on `main` and enforced by the suite; **Rol 1 + Rol 2 sign-off on the
      1.1 bump is still outstanding** (`docs/decisions.md` O-05), so it is merged, not approved
- [x] NISAR / OPERA / Sentinel-1 / EGMS coverage confirmed and written to `_availability/`
- [x] Mock artefacts generated and contract-conformant (`./scripts/check_phase_a.sh` → PASS)
- [x] Real-data path implemented end to end (`02_search_download` → `inspect_hdf5` → `nisar_gunw` →
      `process_case` → `validate_artifacts`) and tested on synthetic granules
- [ ] Real-data path **run on an actual granule** (blocked on Earthdata credentials + ASF approval)
- [x] Mock artefacts committed and pushed once (`01de89e`, now contained in `main`) — pozo and
      fradiaz can pull them
- [x] **AOI refresh committed** — `config/aoi/*.geojson` plus the artefacts regenerated from them; a
      fresh clone resolves the current rings, and `tests/test_aoi_geometry.py` holds the single-ring rule
- [x] The app boots on the committed mock alone (`/_stcore/health` → 200, `/` → 200, no credentials)
- [x] **Public demo up** at <https://noteam.cloud.run> (Cloud Run, root `Dockerfile`); rendered in a
      headless browser on 2026-11-15: four tabs, the `DEMONSTRATION DATA` banner, no horizontal
      overflow at 1440×900
- [ ] CI is committed (`.github/workflows/ci.yml` runs the contract self-check, the artefact gate and
      the suite); no red/green CI run has been observed from this machine
- [x] `config/study_cases.yaml` with the primary case and the AOI polygon
- [ ] Local install verified by each member, independently of the others
- [ ] Units, thresholds and `provenance` confirmed **before** real data replaces the mock

**Definition of done**

- **Rol 3:** `meta.json` validates for all published cases; artefacts < 15 MB; every artefact
  carries `provenance` + `revisit_days`; limitations documented; Málaga ships with its detection
  limit.
- **Rol 1:** loaders + validation reject malformed artefacts before the UI sees them; filters and
  metrics computed once, server-side; CI reproduces artefacts from a clean checkout.
- **Rol 2:** the four views that exist are reachable — map, series and KPIs, hazard and
  infrastructure, provenance and limits (`tests/test_ui_smoke.py` pins exactly four tabs); a fifth is
  **not implemented**; **the app starts with no NASA credentials**; the URL round-trips case,
  filters, tab, ramp and the selected cell (`case`, `land`, `risk`, `coh`, `extrude`, `theme`,
  `scale`, `cell`, `tab`, `ramp`) but not the open/closed state of the expanders; every rendered
  number carries a unit; the `H3 cell` selectbox gives a keyboard path to the map's numbers;
  `?compact=1` collapses the filter panel on a phone.
- **Everyone:** `main` runnable, PR reviewed, `./scripts/python.sh -m pytest tests -q` green.

---

## 12. Risks & mitigations

| Risk | Mitigation | Owner |
|---|---|---|
| NISAR urban coverage absent | Verified fallback chain (§5); the provenance line shows the source that won | yuls |
| Live InSAR too slow | Never on the critical path; artefacts pre-built | yuls / pozo |
| Málaga signal ≤ noise | Render flat **deliberately**; publish the detection limit | yuls / fradiaz |
| Frontend blocked on data | Mock frozen at H0; contract never changes to unblock a UI | yuls / pozo |
| Thresholds wrong after a sensor swap | `revisit_days` + per-product profiles in the contract | yuls |
| Demo URL dies | Static artefacts + CI publish; rehearsal before presenting | pozo |
| "Just pretty maps?" | Every number carries trend, risk band, unit and provenance | fradiaz |
| Silent schema drift | 61 contract tests + `validate_artifacts.py` in CI | pozo |

---

## 13. Validation & limitations

| Check | Method |
|---|---|
| Velocity accuracy | GNSS / levelling; target < 5 mm/yr RMSE |
| Unwrapping | closure phase on redundant triplets |
| Atmosphere | diff against GACOS/ERA5-corrected run |
| Event precision (post-MVP) | 50-event sample vs OSM edits / historical imagery / Copernicus EMS |
| Málaga null | detection-limit analysis — publish the upper bound |

Error budget, largest first: **unwrapping ≫ troposphere ≫ orbital ≫ DEM ≫ noise**.

![Cumulative displacement series](docs/figures/timeseries_three_cities.png)

*Cumulative displacement since the first acquisition, with Málaga's detection floor shaded (±1.5
mm/yr over the window). The series are referenced to the first epoch, so they start at exactly 0 mm
— and the seasonal bulge is visible mid-window rather than masquerading as secular motion. **The
seasonal amplitude is a published fit, not a typed constant:** the window now spans two full annual
cycles and the design sits well inside its conditioning limit, so `seasonal_amp_mm`, `ratio_R` and
`regime` come from `harmonic_fit`. On the earlier, much shorter window the gate could not identify
the annual harmonic at all, and the artefacts of that era published an amplitude anyway while
their own `limitations` said not to — the contradiction the two-year window removes.*

**Limitations.** The per-case subset also ships inside each artefact's `meta.limitations`; the rest
are project-level statements that no single artefact carries.

1. Málaga may sit at the detection floor — the bound *is* the result.
2. CDMX is not coastal; do not claim a coastal framing across all three cities.
3. NISAR GUNW posting is 80 m — city scale, not building scale.
4. NISAR urban coverage is not guaranteed (§5).
5. Urban SAR flood mapping is confounded by double-bounce and shadow; use coherence-loss change
   detection, not thresholding.
6. Coherence depends on revisit interval; **NISAR 12-day ≠ Sentinel-1 6-day**. Never pool them.
7. "Changes in imagery" ≠ "changes on the ground" — layover/shadow move with acquisition geometry.
8. Velocity is the calibrated claim; change detection is a supporting layer, not the headline.
9. **Vertical comes from one geometry, with the horizontal components assumed zero**
   (`v_north = 0`, `v_east = 0`, so `v_up = d_LOS/cosθ`). Real horizontal motion is therefore folded
   into the vertical rate — the east sensitivity reaches ±0.63 — and the LOS sign/heading convention
   is **recorded but not validated**: with zero horizontals no vertical rate can validate it (§6, and
   the runbook's Step 6 note).
10. **No real granule has been downloaded or processed.** All three cases are `product: "mock"` and
    every artefact's own `limitations` says so; what this submission demonstrates is the schema, the
    pipeline and the map logic — not NISAR velocities.
11. **The two granule parsers now agree with the ASF filename census (O-06, fixed 2026-11-14).**
    Token 4 is a 12-day *repeat-cycle bin* of the reference acquisition, not the track; after the
    product token the order is `cycle, track, A|D, frame, secondary cycle` (tokens 4–8).
    `pipeline/process_case.py` (`_GRANULE_RE`, `parse_granule_identity`) and
    `pipeline/ingest/02_search_download.py` (`parse_granule`, which `derive_stacks` groups by) both
    read track = token 5 and frame = token 7, and the availability reports were re-derived from
    their unchanged raw granule lists under that grammar. Until then the science parser read
    track/frame one token left and the ingest parser read the frame *as* the track, so a genuinely
    connected multi-date stack could be refused as "mixes relative orbits" and two orbits could be
    merged under one frame label. Nothing published was affected either way: the mock path never
    parses a granule name, and its provenance digest hashes `case|product|seed|window`.
12. **The LOS sign label contradicted the projection arithmetic (O-08, closed by renaming).**
    `project_to_los` builds `u = [cosθ, −sinθcosα, −sinθsinα]`, so with zero horizontals **uplift
    gives positive LOS** (toward-sensor-positive) and subsidence negative. The phase conversion's
    default factor has always been -1.0 — exactly that arithmetic — but it was labelled
    `away-from-sensor`, and that label landed in `meta.provenance.method`. The label and its prose
    now say `toward-sensor`, the default factor stays -1.0, and **no published number changed**
    (the mock synthesises millimetres directly, so none was ever at risk). What remains open is
    validation, not naming: the convention is still unvalidated against GNSS (`--validated-against`).
13. **A stack shorter than three quarters of a year fits no annual harmonic, and still publishes a
    grid.** `harmonic_order` returns 0 below `MIN_SEASONAL_COVERAGE_PER_HARMONIC` (0.75 yr), so the
    case is a plain trend: `seasonal_amp_mm` is exactly 0.0 — meaning *"not fitted"*, never *"no
    seasonality measured"*, which would be a claim about the ground — `ratio_R` is **null** (the
    column is still required, but `|trend| / 0` is undefined, so no number is invented), and
    `regime` is `"transitional"`, the contract's cannot-classify value, because the
    secular-vs-seasonal comparison has no seasonal term to compare against. Where no cell in the
    case fitted a harmonic, `stats.median_ratio_R` is null too, and `meta.limitations` says the term
    was not fitted and what would publish one. A ~132-day real stack — the planned fetch — is
    therefore schema-valid but seasonally unfitted: a fitted amplitude needs a chain spanning at
    least 0.75 yr for one harmonic (≈276 d) or 1.5 yr for two. The two-year mock is unaffected — it
    spans two annual cycles and does publish a fitted amplitude.

---

## 14. Study areas

| Case | City | bbox `[W,S,E,N]` (envelope of the AOI ring) | Publication CRS | Projected CRS | Reference point | AOI area |
|---|---|---|---|---|---|---|
| `mexico-city` | Mexico City, MX | −99.3649, 19.0487, −98.9403, 19.5928 | EPSG:4326 | EPSG:32614 | −99.13, 19.43 | 1,498 km² |
| `jakarta` | Jakarta, ID | 106.6856, −6.3745, 106.9740, −6.0700 | EPSG:4326 | EPSG:32748 | 106.85, −6.21 | 748 km² |
| `malaga` | Málaga, ES | −4.5879, 36.6358, −4.2605, 36.8939 | EPSG:4326 | EPSG:32630 | −4.42, 36.72 | 394 km² |

The AOI is a QGIS-traced polygon per case in [`config/aoi/`](config/aoi/) — one closed ring, EPSG:4326,
no holes — and the bbox above is its envelope, derived rather than typed. `pipeline/aoi.py --all`
prints each ring's area and H3 cell count. The areas agree with published municipal areas to within
1 % (Mexico City, Málaga) and 13 % (Jakarta, whose boundary includes the bay fringe), which is the
check that these are city footprints and not metro regions — the point of using them instead of
rectangles, whose coastal cases included open water.

Primary case is a **configuration** decision (`config/study_cases.yaml`), not part of the contract.
Recommendation: `mexico-city` primary (strongest, most legible signal) with `malaga` as the explicit
negative control; the informe suggests the opposite emphasis, so confirm as a team.

---

## 15. Post-MVP roadmap

Documented now so the MVP is not designed against it:

1. **Static Option B site** — PMTiles + MapLibre/deck.gl, range requests, CDN caching; route
   contract already written in [`docs/route-contract.md`](docs/route-contract.md).
2. **Change-event pins** — coherence/amplitude z-scores → persistence → polygons → pre-rendered
   chips, with the Δγ/ΔB classifier table (each type's evidence card).
3. **EGMS cross-check** for Málaga, and a fourth city.
4. **GNSS validation** run, and a published error budget per case.
5. **Sensor cross-calibration** note: what changes when the same city is measured by NISAR L-band
   and Sentinel-1 C-band.
6. **The machinery §6 labels *designed*** — ascending/descending decomposition (needs two flight
   directions, which the pipeline currently refuses), step terms in the time-series model (needs a
   stack longer than ~4.5 months and a step-date search), the skeletal storage coefficient `S_skv`
   (needs `b₀`/`Δh` per aquifer), and `|∇v|` (needs a 2-D velocity raster). Each is gated on a real
   stack, not on time in the hackathon.

---

## 16. Key references

| Topic | Cite | DOI |
|---|---|---|
| Global subsidence threat | Herrera-García et al. 2021, *Science* | 10.1126/science.abb8549 |
| Global subsidence → storage loss | Hasan et al. 2023, *Nat Commun* | 10.1038/s41467-023-41933-z |
| Mexico City −45 cm/yr | Cigna & Tapete 2022, *GRL* | 10.1029/2022gl098923 |
| 99 coastal cities, uniform PS-InSAR | Wu et al. 2022, *GRL* | 10.1029/2022gl098477 |
| Method review | Galloway & Burbey 2011, *Hydrogeol J* | 10.1007/s10040-011-0775-5 |
| Indonesia sinking cities | Chaussard et al. 2013, *RSE* | 10.1016/j.rse.2012.10.015 |
| Jakarta 2017–22 multi-track SBAS | 2024, *Geocarto Int* | 10.1080/10106049.2024.2364726 |
| Jakarta: piped water → abstraction | 2022, *Water* | 10.3390/w14203197 |
| Málaga/Torremolinos | Ruiz-Constán et al. 2018, *STOTEN* | 10.1016/j.scitotenv.2018.04.280 |
| Axarquía water crisis | Junquera et al. 2025, *PNAS* | 10.1073/pnas.2508055122 |
| NISAR Data User Guide | Kristenson et al. 2026 | 10.5281/ZENODO.20075813 |

*Jakarta rates vary by method and period — quote the source actually used in the provenance record.*

---

## 17. Licence & attribution

Code, docs and figures are **MIT** (`LICENSE`). That licence does **not** relicense the data:

- **NISAR L2 GUNW** — NASA/JPL-Caltech, distributed by the Alaska Satellite Facility DAAC under
  NASA Earthdata terms of use. Credit *"NISAR (NASA/JPL-Caltech), processed and distributed by
  ASF DAAC"* when reusing a product.
- **Sentinel-1** — ESA Copernicus, free and open under the Copernicus data policy. Needed the moment
  the C-band path runs; its coherence is never pooled with NISAR's (6-day vs 12-day revisit).
- **Map context and place names** — © OpenStreetMap contributors (ODbL), fetched via Nominatim into
  `data/staging/`.
- **Context layers** (`data/processed/<case>/context_layers.geojson`, pinned by
  `config/context/<case>.json`) — © OpenStreetMap contributors, **ODbL 1.0**
  (<https://opendatacommons.org/licenses/odbl/1-0/>), read from an Overpass API extract
  (`pipeline/ingest/fetch_context.py`; the raw extract stays gitignored). The committed GeoJSON is a
  **Derivative Database**, offered under the ODbL and not under the MIT licence above. A rendered
  map, screenshot or figure is a **Produced Work**: no share-alike, but the attribution notice
  travels with it — *"Contains information from OpenStreetMap, which is made available here under
  the Open Database License (ODbL). © OpenStreetMap contributors"*. The Derivative/Produced split,
  the `unknown`-share measured per case and the open question of mixing OSM polygons with building
  footprints are in [`docs/context-sources.md`](docs/context-sources.md) §5.
- **Published subsidence rates** — cite the paper actually used in the provenance record (§16), not
  the closest headline number.
