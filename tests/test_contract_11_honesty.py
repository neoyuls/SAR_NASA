"""Acceptance guard for contract 1.1: the seasonal term must be *measured*, not asserted.

Why this file exists
--------------------
`origin/main` ships contract 1.1 and publishes, for each case, a `seasonal_amp_mm`, a `ratio_R`
and a `dominant_regime` — while that same artefact's own `meta.limitations` says a ~4.5-month
window "cannot separate seasonal from secular motion: do not publish seasonal_amp_mm from this
stack". The repo already knows the term is unidentifiable on that window: `harmonic_fit` gates the
amplitude on `MIN_SEASONAL_COVERAGE_PER_HARMONIC = 0.75` annual cycles and on a design condition
number below `MAX_DESIGN_CONDITION = 30`, and a 132-day / 12-date stack fails both (coverage 0.36,
condition ~67). So 1.1 on the 132-day stack is a contract that requires publishing a number the
pipeline itself refuses to publish. That is the failure mode this file freezes out.

The migration fixes it by widening the window to ~2 years (so the annual term *is* identifiable)
and by publishing a **fit** instead of a typed constant. This module encodes what "1.1 is honest"
means so it cannot silently regress:

1. the contract constants are actually 1.1 / revision 2, and that contract *declares* the seasonal
   fields it now requires;
2. every published grid carries `seasonal_amp_mm`, `ratio_R`, `regime`, with real (non-null, in
   range, declared-vocabulary) values;
3. `meta.stats` carries the three new aggregate keys;
4. the aoi time series carries the `trend_mm_yr` / `seasonal_mm` split it is now required to carry;
5. **identifiability**: re-running the repo's own `harmonic_fit` on the published aoi series says
   the amplitude is publishable — coverage and conditioning pass, the exact gates `origin/main`
   violates;
6. **no contradiction, and no silence either**: a case that *fits* the term must pass the gate and
   must not carry a limitation forbidding publication (that pair is the origin/main bug, verbatim);
   a case that fits *nothing* must publish the sentinel state — amplitude exactly 0, every `ratio_R`
   null, `regime == "transitional"`, `stats.median_ratio_R` null — **and** the limitation that says
   the term was not fitted, so the null travels with its reason. Each artefact is one branch or the
   other, and each branch is asserted positively, so drifting into neither fails loudly;
7. **internal consistency**: the published medians/mode in `meta.stats` are the medians/mode of the
   grid the reader actually gets;
8. the documents may keep the prohibition sentence, but only scoped to the short window it was
   true for, or explicitly tagged as the v1.0 history it is — never as a live claim about the
   artefacts this repo now publishes (`test_the_readme_does_not_publish_what_it_says_is_
   unpublishable` scans README + `docs/science-guide.md` + `docs/decisions.md` for that).

Everything here is read-only and offline. Artefact tests skip cleanly (and say why) when
`data/processed` holds no case directories, so the file is useful before the first artefact run;
the contract and README tests run either way.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `python -m pytest` puts the cwd on the path; be explicit anyway
    sys.path.insert(0, str(ROOT))

from pipeline.science import transforms as T  # noqa: E402
from src.domain import contracts as C  # noqa: E402

PROCESSED = ROOT / "data/processed"

#: One directory per published case, the same discovery rule the other artefact tests use.
CASES = sorted(
    p.name
    for p in PROCESSED.iterdir()
    if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "meta.json").exists()
) if PROCESSED.exists() else []

needs_artefacts = pytest.mark.skipif(
    not CASES,
    reason=(
        "no case artefacts under data/processed — run pipeline/generate_mock.py first; "
        "this assertion is about published artefacts, not about the schema alone"
    ),
)

#: Fields contract 1.1 adds. Named here so a *missing* field is reported by name; the contract's
#: own declaration of them is checked in `test_the_contract_is_11_and_declares_the_seasonal_fields`
#: so the names cannot drift away from `src/domain/contracts.py` unnoticed.
SEASONAL_GRID_FIELDS = ("seasonal_amp_mm", "ratio_R", "regime")
SEASONAL_SERIES_FIELDS = ("trend_mm_yr", "seasonal_mm")
SEASONAL_STAT_KEYS = ("median_seasonal_amp_mm", "median_ratio_R", "dominant_regime")

#: A prohibition is only honest while it is scoped to the window that cannot support the term.
SHORT_WINDOW_RE = re.compile(r"\b132\s*[- ]?\s*(?:day|d)\b|\b4\.5\s*[- ]?month|\b4\s*[- ]?month")


def _rel(path: pathlib.Path) -> str:
    """Path relative to the repo root, so a failure message is copy-pasteable."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:  # pragma: no cover - every path here is inside the repo
        return str(path)


def _flatten(text: str) -> str:
    """Lowercase, drop markdown emphasis/backticks, collapse whitespace.

    The phrases live inside `code spans` and **bold** in the README, and artefacts wrap sentences
    across list items; normalising both sides keeps the match about content, not formatting.
    """
    return re.sub(r"\s+", " ", text.replace("`", "").replace("*", "").replace("_", "")).strip().lower()


#: A limitation phrased like one of these is a *prohibition on publishing the amplitude*. Declared
#: **already flattened** (`_flatten`): it strips `_`, so a raw `seasonal_amp_mm` phrase could never
#: match the flattened text it is compared against — the matcher would be dead code and every
#: prohibition guard vacuous. Defining them through `_flatten` keeps both sides in one alphabet.
PROHIBITION_PHRASES = tuple(
    _flatten(phrase) for phrase in ("do not publish seasonal_amp_mm", "cannot separate seasonal")
)


def _prohibition_in(text: str) -> bool:
    """True when `text` contains one of `PROHIBITION_PHRASES` (already flattened both sides)."""
    flat = _flatten(text)
    return any(phrase in flat for phrase in PROHIBITION_PHRASES)


#: The documents that talk about publishing the seasonal amplitude. README is the published entry
#: point; the two docs are where the sentence actually survives today. The guard used to scan
#: README alone, and README §13 was reworded to "The seasonal amplitude is a published fit, not a
#: typed constant" — so every paragraph returned "no prohibition", `offending` was structurally
#: empty and the rule stopped policing anything. Scanning the documents that carry the phrase is
#: what makes the rule reachable again; the non-vacuity assert below keeps it that way.
PROHIBITION_DOCS = (
    pathlib.Path("README.md"),
    pathlib.Path("docs/science-guide.md"),
    pathlib.Path("docs/decisions.md"),
)

#: A paragraph carrying a prohibition is *history*, not a claim, when it says so in the document
#: itself. Same inline-comment convention `tests/test_fingerprint_consistency.py` uses for retired
#: digests (`<!-- fingerprint-historical: ... -->`, explained in docs/decisions.md §O-05), and
#: line/paragraph-level with a mandatory reason, so excusing one paragraph is a visible, reviewable
#: edit instead of a hole in the scan. It is deliberately NOT a word list ("v1.0", "origin/main",
#: a date...): those words also appear in paragraphs that make live claims.
PROHIBITION_HISTORICAL = "prohibition-historical"
HISTORICAL_MARKER_RE = re.compile(
    rf"<!--\s*{PROHIBITION_HISTORICAL}\s*:(?P<reason>[^>]*)-->", re.IGNORECASE
)


@dataclass(frozen=True)
class Prohibition:
    """One paragraph that forbids publishing the amplitude, and why it is allowed to."""

    doc: str
    paragraph: int
    text: str  # flattened, for the failure message
    #: "window" (scoped to the short stack), "history" (tagged as past), or "" (a live claim).
    scoped_by: str


def prohibition_hits(documents: dict[str, str]) -> list[Prohibition]:
    """Every paragraph in `documents` (path -> text) that carries one of the prohibitions."""
    hits: list[Prohibition] = []
    for doc, text in documents.items():
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        for index, paragraph in enumerate(paragraphs, start=1):
            flat = _flatten(paragraph)
            if not any(phrase in flat for phrase in PROHIBITION_PHRASES):
                continue
            if SHORT_WINDOW_RE.search(flat):
                scoped_by = "window"
            else:
                marker = HISTORICAL_MARKER_RE.search(paragraph)
                scoped_by = "history" if marker and marker.group("reason").strip() else ""
            hits.append(Prohibition(doc, index, flat, scoped_by))
    return hits

class Case:
    """One published case directory. Loads lazily so a missing file names itself in the failure.

    `directory` is overridable so the guards below can be pointed at an artefact built in
    `tmp_path` (a synthetic case), never only at the shipped `data/processed/` ones.
    """

    def __init__(self, case_id: str, directory: pathlib.Path | None = None) -> None:
        self.id = case_id
        self.directory = directory if directory is not None else PROCESSED / case_id

    @property
    def meta_path(self) -> pathlib.Path:
        return self.directory / "meta.json"

    @property
    def grid_path(self) -> pathlib.Path:
        return self.directory / "nisar_grid.parquet"

    @property
    def series_path(self) -> pathlib.Path:
        return self.directory / "timeseries.csv"

    @property
    def meta(self) -> dict:
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    @property
    def meta_text(self) -> str:
        """Raw text, used to recover the *printed* precision of a published statistic."""
        return self.meta_path.read_text(encoding="utf-8")

    def grid(self) -> pd.DataFrame:
        assert self.grid_path.exists(), (
            f"{self.id}: {_rel(self.grid_path)} is missing — a published case must ship its grid"
        )
        return pd.read_parquet(self.grid_path)

    def timeseries(self) -> pd.DataFrame:
        assert self.series_path.exists(), (
            f"{self.id}: {_rel(self.series_path)} is missing — a published case must ship its "
            "time series; regenerate the case rather than dropping the file"
        )
        return pd.read_csv(self.series_path, dtype={"cell_id": str})


@pytest.fixture(params=CASES, ids=CASES)
def case(request) -> Case:
    return Case(request.param)


# ---------------------------------------------------------------------------------------------
# 1. The contract itself: 1.1 / revision 2, and it declares the fields it now requires
# ---------------------------------------------------------------------------------------------


def test_the_contract_is_11_and_declares_the_seasonal_fields() -> None:
    """A 1.1 artefact published under a 1.0 contract has no normative source for its new fields."""
    assert C.SCHEMA_VERSION == "1.1", (
        f"src/domain/contracts.py still declares SCHEMA_VERSION={C.SCHEMA_VERSION!r}; the "
        "migration is to contract 1.1, and a 1.0 contract cannot validate a grid that carries "
        f"{SEASONAL_GRID_FIELDS}"
    )
    assert C.CONTRACT_REVISION == 2, (
        f"src/domain/contracts.py declares CONTRACT_REVISION={C.CONTRACT_REVISION!r}; contract 1.1 "
        "is revision 2 (a version bump without the revision bump is the drift the freeze record "
        "forbids)"
    )

    declared = {field.name for field in C.GRID_FIELDS}
    missing = [name for name in SEASONAL_GRID_FIELDS if name not in declared]
    assert not missing, (
        f"contract 1.1 requires grid field(s) {missing} but GRID_FIELDS does not declare them; the "
        "grid schema in src/domain/contracts.py must be the one place the new fields are defined"
    )

    declared_series = {field.name for field in C.TIMESERIES_FIELDS}
    missing_series = [name for name in SEASONAL_SERIES_FIELDS if name not in declared_series]
    assert not missing_series, (
        f"contract 1.1 requires timeseries field(s) {missing_series} but TIMESERIES_FIELDS does not "
        "declare them; add them to src/domain/contracts.py, not only to the generator"
    )
    assert set(SEASONAL_STAT_KEYS) <= set(C.STATS_REQUIRED_KEYS), (
        f"contract 1.1 requires meta.stats keys {list(SEASONAL_STAT_KEYS)} but "
        f"STATS_REQUIRED_KEYS is {list(C.STATS_REQUIRED_KEYS)}; the validator cannot enforce a key "
        "it does not declare"
    )


# ---------------------------------------------------------------------------------------------
# 2. The grid publishes real seasonal values, in the contract's own vocabulary
# ---------------------------------------------------------------------------------------------


@needs_artefacts
def test_the_grid_publishes_the_seasonal_fields(case: Case) -> None:
    """`seasonal_amp_mm`, `ratio_R`, `regime` must be present, populated, in range and declared."""
    grid = case.grid()
    path = _rel(case.grid_path)

    missing = [name for name in SEASONAL_GRID_FIELDS if name not in grid.columns]
    assert not missing, (
        f"{case.id}: {path} is missing contract-1.1 column(s) {missing} (columns present: "
        f"{list(grid.columns)}). Regenerate the case under contract 1.1 — do not patch the parquet."
    )

    for column in SEASONAL_GRID_FIELDS:
        values = grid[column]
        assert values.notna().any(), (
            f"{case.id}: {path} column {column!r} is present but entirely null. A required 1.1 "
            "field that is null for every cell is a schema placeholder, not a published fit."
        )

    amplitude = pd.to_numeric(grid["seasonal_amp_mm"], errors="coerce").dropna()
    negative_amplitude = amplitude[amplitude < 0.0]
    assert negative_amplitude.empty, (
        f"{case.id}: {path} publishes {len(negative_amplitude)} negative seasonal_amp_mm value(s), "
        f"first {float(negative_amplitude.iloc[0])!r}: the contract's amplitude is a "
        "non-negative magnitude (hypot(A, B)), never a signed coefficient — a sign here usually "
        "means a raw cosine coefficient was published instead of the amplitude."
    )

    ratio = pd.to_numeric(grid["ratio_R"], errors="coerce").dropna()
    negative_ratio = ratio[ratio < 0.0]
    assert negative_ratio.empty, (
        f"{case.id}: {path} publishes {len(negative_ratio)} negative ratio_R value(s), first "
        f"{float(negative_ratio.iloc[0])!r}. README §6 defines R = |trend| / A_seasonal: the "
        "absolute value is part of the definition, so publish the magnitude."
    )

    observed = {str(value) for value in grid["regime"].dropna().unique()}
    undeclared = sorted(observed - set(C.REGIMES))
    assert not undeclared, (
        f"{case.id}: {path} publishes regime value(s) {undeclared}, which contract "
        f"contracts.REGIMES does not declare {list(C.REGIMES)}. Use the contract's vocabulary "
        "(and bump the contract first if a fourth regime is real)."
    )


# ---------------------------------------------------------------------------------------------
# 3. meta.stats carries the three 1.1 aggregates
# ---------------------------------------------------------------------------------------------


@needs_artefacts
def test_meta_stats_carries_the_seasonal_aggregates(case: Case) -> None:
    stats = case.meta.get("stats")
    assert isinstance(stats, dict), (
        f"{case.id}: {_rel(case.meta_path)} has no `stats` object, so it cannot carry "
        f"{list(SEASONAL_STAT_KEYS)}"
    )
    missing = [key for key in SEASONAL_STAT_KEYS if key not in stats]
    assert not missing, (
        f"{case.id}: {_rel(case.meta_path)} stats is missing contract-1.1 key(s) {missing} "
        f"(keys present: {sorted(stats)}). Regenerate the case; meta.stats is what the app reads."
    )

    for key in ("median_seasonal_amp_mm", "median_ratio_R"):
        assert isinstance(stats[key], (int, float)) and not isinstance(stats[key], bool), (
            f"{case.id}: stats.{key} is {stats[key]!r}, not a number. Contract 1.1 publishes a "
            "fitted statistic here; null means the case has nothing to publish and must say so "
            "with the identifiability gate instead (see test 5)."
        )
    assert stats["dominant_regime"] in C.REGIMES, (
        f"{case.id}: stats.dominant_regime is {stats['dominant_regime']!r}, which is not one of "
        f"{list(C.REGIMES)}; it must be the modal grid regime, so it uses the same vocabulary."
    )


# ---------------------------------------------------------------------------------------------
# 4. The aoi series carries its own trend/seasonal decomposition
# ---------------------------------------------------------------------------------------------


@needs_artefacts
def test_the_aoi_series_carries_the_trend_and_seasonal_split(case: Case) -> None:
    """1.1 makes `trend_mm_yr` / `seasonal_mm` required series columns — for the aoi rows too."""
    series = case.timeseries()
    path = _rel(case.series_path)
    assert "cell_id" in series.columns, (
        f"{case.id}: {path} has no `cell_id` column (columns present: {list(series.columns)}); "
        "the aoi rows cannot be selected without it"
    )

    aoi = series[series["cell_id"].astype(str) == "aoi"]
    assert not aoi.empty, (
        f"{case.id}: {path} has no rows with cell_id == 'aoi'; contract §5.2 requires the case "
        "aggregate, and it is the series this guard re-fits in test 5"
    )

    for column in SEASONAL_SERIES_FIELDS:
        assert column in series.columns, (
            f"{case.id}: {path} is missing contract-1.1 column {column!r} (columns present: "
            f"{list(series.columns)}). Regenerate the case under contract 1.1."
        )
        values = pd.to_numeric(aoi[column], errors="coerce")
        assert values.notna().any(), (
            f"{case.id}: {path} column {column!r} is present but null for every aoi row, so the "
            "decomposition was declared and never populated"
        )


# ---------------------------------------------------------------------------------------------
# 5. THE CORE INVARIANT: the repo's own identifiability gate must bless the published window
# ---------------------------------------------------------------------------------------------


@needs_artefacts
def test_the_aoi_seasonal_term_is_identifiable_by_the_repo_s_own_gate(case: Case) -> None:
    """Re-fit the published aoi series with `transforms.harmonic_fit` and obey its verdict.

    This is the assertion `origin/main` cannot pass: on a 132-day / 12-date stack the same function
    returns `seasonal_identifiable=False`, `annual_coverage≈0.36` and `design_condition≈67`, so the
    amplitude it publishes is a fitted artefact. Here the artefacts are the ones under test; the
    gate and its two constants are read from `transforms` so the artefact cannot drift from them.

    `n_harmonics=1` on purpose: it is `harmonic_fit`'s default and the term the pipeline publishes
    (`seasonal_amp_mm` is the *first* harmonic). Asking for a second harmonic would test a
    different claim — a 1-year window could never carry it.
    """
    series = case.timeseries()
    path = _rel(case.series_path)
    aoi = series[series["cell_id"].astype(str) == "aoi"]
    assert not aoi.empty, f"{case.id}: no aoi rows in {path}; nothing to re-fit"

    frame = (
        pd.DataFrame(
            {
                "date": pd.to_datetime(aoi["date"], format="%Y-%m-%d", errors="coerce"),
                "value": pd.to_numeric(aoi["value"], errors="coerce"),
            }
        )
        .dropna()
        .sort_values("date")
    )
    assert len(frame) >= T.MIN_FIT_POINTS, (
        f"{case.id}: {path} has only {len(frame)} usable aoi sample(s); harmonic_fit needs at "
        f"least {T.MIN_FIT_POINTS}. The window must be wide enough to identify the annual term, "
        "not merely wide enough to load."
    )

    # Same time axis as pipeline/mock/model.py: years since the first acquisition, 365.25 d/yr.
    days = (frame["date"] - frame["date"].min()).dt.days.to_numpy(dtype=float)
    fit = T.harmonic_fit(days / T.DAYS_PER_YEAR, frame["value"].to_numpy(dtype=float))

    span_days = float(days.max())
    context = (
        f"{case.id}: harmonic_fit on the aoi series in {path} "
        f"(span {span_days:.0f} d / {fit.annual_coverage:.2f} annual cycles, condition "
        f"{fit.design_condition:.3g})"
    )
    assert fit.seasonal_identifiable is True, (
        f"{context} reports seasonal_identifiable=False, so the pipeline itself forbids publishing "
        f"seasonal_amp_mm while the artefact publishes it. Warnings: {fit.warnings}. Widen the "
        "window until the annual term is identifiable (≥ "
        f"{T.MIN_SEASONAL_COVERAGE_PER_HARMONIC:g} annual cycles) — do not publish the fitted "
        "amplitude anyway."
    )
    assert fit.annual_coverage >= T.MIN_SEASONAL_COVERAGE_PER_HARMONIC, (
        f"{context} spans {fit.annual_coverage:.4f} annual cycles; "
        f"MIN_SEASONAL_COVERAGE_PER_HARMONIC requires ≥ "
        f"{T.MIN_SEASONAL_COVERAGE_PER_HARMONIC:g}. The seasonal amplitude is not separable from "
        "[1, t] on this window, so publishing it in the grid/stats is the origin/main defect."
    )
    assert fit.design_condition <= T.MAX_DESIGN_CONDITION, (
        f"{context} has a column-normalised design condition number "
        f"{fit.design_condition:.3g} > MAX_DESIGN_CONDITION "
        f"{T.MAX_DESIGN_CONDITION:g}: the harmonic columns are nearly collinear with [1, t] over "
        "these dates (clustered or irregular sampling), so the amplitude is a fitted parameter. "
        "Spread the acquisitions over the window, then regenerate."
    )


# ---------------------------------------------------------------------------------------------
# 6. THE NO-CONTRADICTION INVARIANT: the origin/main bug, verbatim — and its mirror image
# ---------------------------------------------------------------------------------------------


def _declared_harmonics(meta: dict) -> int | None:
    """The harmonic order the producer says it fitted, under either key spelling.

    `contracts.validate_meta` accepts `seasonal_n_harmonics` or `n_harmonics` so a rename cannot
    break validation; read both here for the same reason. `None` means neither key is present.
    """
    stats = meta.get("stats") or {}
    for key in ("seasonal_n_harmonics", "n_harmonics"):
        value = stats.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _refit_aoi(case: Case) -> tuple[T.HarmonicFit, str]:
    """Re-fit the published aoi series with the repo's own `harmonic_fit` (order 1).

    Same re-fit `test_the_aoi_seasonal_term_is_identifiable_by_the_repo_s_own_gate` performs; it is
    repeated here because the branch below must quote the gate's own numbers (coverage, condition)
    in its failure message, and the identifiability of the window is what makes publishing the
    amplitude honest in the first place.
    """
    series = case.timeseries()
    path = _rel(case.series_path)
    aoi = series[series["cell_id"].astype(str) == "aoi"]
    assert not aoi.empty, (
        f"{case.id}: {path} has no rows with cell_id == 'aoi', so the published amplitude cannot "
        "be re-derived from the series the case ships; regenerate the case with its aoi aggregate"
    )

    frame = (
        pd.DataFrame(
            {
                "date": pd.to_datetime(aoi["date"], format="%Y-%m-%d", errors="coerce"),
                "value": pd.to_numeric(aoi["value"], errors="coerce"),
            }
        )
        .dropna()
        .sort_values("date")
    )
    assert len(frame) >= T.MIN_FIT_POINTS, (
        f"{case.id}: {path} has only {len(frame)} usable aoi sample(s); harmonic_fit needs at "
        f"least {T.MIN_FIT_POINTS}, so the published amplitude cannot be re-derived at all"
    )

    # Same time axis as pipeline/mock/model.py: years since the first acquisition, 365.25 d/yr.
    days = (frame["date"] - frame["date"].min()).dt.days.to_numpy(dtype=float)
    fit = T.harmonic_fit(days / T.DAYS_PER_YEAR, frame["value"].to_numpy(dtype=float))
    context = (
        f"{case.id}: harmonic_fit on the aoi series in {path} "
        f"(span {float(days.max()):.0f} d / {fit.annual_coverage:.2f} annual cycles, condition "
        f"{fit.design_condition:.3g})"
    )
    return fit, context


@needs_artefacts
def _assert_two_honest_states(case: Case) -> None:
    """Every case is in the fitted state *or* the not-fitted state — and says so.

    `origin/main` publishes a fitted-looking amplitude while its own `meta.limitations` says
    "cannot separate seasonal from secular motion: do not publish seasonal_amp_mm from this
    stack". The bug is the *contradiction*: `meta.stats` published `median_seasonal_amp_mm=1.5`,
    `ratio_R=41.377`, `dominant_regime="inelastic"` beside that sentence. Contract 1.1 replaces it
    with a fit from a window the repo's gate blesses, so the honest artefact is one of two states
    and this helper asserts whichever one the case declares:

    1. **fitted** (`stats.seasonal_n_harmonics` > 0, the shipped reality): the grid carries a real
       amplitude (no `0.0` sentinel), `ratio_R` is populated and equal to `|trend| / A`, `regime`
       is in `contracts.REGIMES`, `harmonic_fit` on the published aoi series still clears both
       gates — and **no** limitation forbids publishing the amplitude it publishes;
    2. **not fitted** (`n_harmonics` == 0): the null must travel with its reason — amplitude
       exactly `0.0`, every `ratio_R` null, `regime == "transitional"`,
       `stats.median_ratio_R is None`, and a limitation saying the term was not fitted.

    Both branches are positive claims about the artefact, so a case cannot pass by declaring
    neither, and an artefact cannot forbid publishing what it publishes.

    Branch 2 is written here, not in the test, because the shipped cases are all fitted: the
    synthetic fixture in `test_a_not_fitted_artefact_passes_its_own_branch` (below) is what keeps
    the six not-fitted assertions executing instead of dead.
    """
    meta = case.meta
    stats = meta.get("stats") or {}
    grid = case.grid()
    grid_path = _rel(case.grid_path)
    meta_path = _rel(case.meta_path)

    assert "seasonal_amp_mm" in grid.columns, (
        f"{case.id}: {grid_path} has no seasonal_amp_mm column (columns present: "
        f"{list(grid.columns)}), so neither the fitted nor the not-fitted state can be checked. "
        "Regenerate the case under contract 1.1."
    )
    amplitude = pd.to_numeric(grid["seasonal_amp_mm"], errors="coerce").dropna()
    assert not amplitude.empty, (
        f"{case.id}: {grid_path} seasonal_amp_mm is entirely null. Contract 1.1 makes it a "
        "required column, and an all-null column is neither a fit nor a declared non-fit: publish "
        "0.0 (the 'not fitted' sentinel) with the limitation that explains it."
    )

    declared = _declared_harmonics(meta)
    # No declared order: fall back to what the grid actually shows, so an artefact cannot dodge the
    # guard by omitting the statistics key.
    fitted = declared > 0 if declared is not None else bool((amplitude > 0.0).any())
    prohibitions = [
        item for item in (meta.get("limitations") or []) if _prohibition_in(str(item))
    ]

    if fitted:
        # ---- branch 1: a seasonal term was fitted, so it must be a real, gate-blessed number ----
        order = f"stats.seasonal_n_harmonics/n_harmonics = {declared}" if declared else (
            "no declared harmonic order but a positive amplitude in the grid"
        )
        sentinel = amplitude[amplitude == 0.0]
        assert sentinel.empty, (
            f"{case.id}: {order} claims a fitted seasonal term, but {grid_path} publishes exactly "
            f"0.0 mm for {len(sentinel)} of {len(amplitude)} cell(s). 0.0 is the '*not fitted*' "
            "sentinel (README §13), never a measurement, so the case is in neither honest state: "
            "either fit the term on a window that clears the gate, or declare 0 harmonics and "
            "publish the null ratio_R, transitional regime and 'not fitted' limitation."
        )
        assert float(amplitude.median()) > 0.0, (
            f"{case.id}: {order} but the median seasonal_amp_mm in {grid_path} is "
            f"{float(amplitude.median())!r}; a fitted case must publish a positive amplitude"
        )

        ratio = (
            pd.to_numeric(grid["ratio_R"], errors="coerce") if "ratio_R" in grid.columns else None
        )
        assert ratio is not None, (
            f"{case.id}: {grid_path} has no ratio_R column (columns present: "
            f"{list(grid.columns)}); a fitted amplitude must ship the R = |trend| / A_seasonal "
            "that makes the regime interpretable"
        )
        null_ratio = int(ratio.isna().sum())
        assert null_ratio == 0, (
            f"{case.id}: {order} in {meta_path}, but {grid_path} has {null_ratio} null ratio_R "
            f"value(s). A null ratio is only legal when no harmonic was fitted (it is "
            "|trend| / 0 otherwise); beside a fitted amplitude it hides a computed number behind "
            "an 'undefined' marker."
        )

        velocity = pd.to_numeric(grid["velocity_mm_yr"], errors="coerce")
        pairs = pd.DataFrame(
            {"ratio": ratio, "velocity": velocity, "amplitude": grid["seasonal_amp_mm"]}
        ).apply(pd.to_numeric, errors="coerce").dropna()
        assert not pairs.empty, (
            f"{case.id}: {grid_path} has no row where ratio_R, velocity_mm_yr and seasonal_amp_mm "
            "are all numeric, so the published ratio cannot be checked against its definition"
        )
        expected = pairs["velocity"].abs() / pairs["amplitude"]
        disagree = pairs[(pairs["ratio"] - expected).abs() > 1e-6 * np.maximum(expected.abs(), 1.0)]
        if not disagree.empty:
            row = disagree.index[0]
            raise AssertionError(
                f"{case.id}: {grid_path} publishes ratio_R != |trend_mm_yr| / A_seasonal for "
                f"{len(disagree)} of {len(pairs)} cell(s); e.g. cell {row}: ratio_R = "
                f"{float(pairs.loc[row, 'ratio'])!r} but |{float(pairs.loc[row, 'velocity'])!r}| / "
                f"{float(pairs.loc[row, 'amplitude'])!r} = {float(expected.loc[row])!r}. README §6 "
                "defines R = |trend| / A_seasonal on the same fit; publish that ratio, or drop the "
                "regime it classifies."
            )

        regimes = grid["regime"].astype(str).where(grid["regime"].notna())
        assert int(regimes.isna().sum()) == 0, (
            f"{case.id}: {order} but {grid_path} leaves regime null for "
            f"{int(regimes.isna().sum())} cell(s); a fitted case can classify every cell against "
            "its own fitted amplitude"
        )
        undeclared = sorted(set(regimes.unique()) - set(C.REGIMES))
        assert not undeclared, (
            f"{case.id}: {grid_path} publishes regime value(s) {undeclared}, which "
            f"contracts.REGIMES does not declare {list(C.REGIMES)}"
        )

        # The gate itself: the same function that refuses the origin/main window must bless this
        # one, or the published amplitude is a fitted parameter rather than a measurement.
        fit, context = _refit_aoi(case)
        assert fit.seasonal_identifiable is True, (
            f"{context} reports seasonal_identifiable=False, so the pipeline itself forbids "
            f"publishing seasonal_amp_mm while {grid_path} publishes it. Warnings: {fit.warnings}. "
            "Widen the window until the annual term is identifiable (≥ "
            f"{T.MIN_SEASONAL_COVERAGE_PER_HARMONIC:g} annual cycles) — do not publish the fitted "
            "amplitude anyway."
        )
        assert fit.annual_coverage >= T.MIN_SEASONAL_COVERAGE_PER_HARMONIC, (
            f"{context} spans {fit.annual_coverage:.4f} annual cycles; "
            f"MIN_SEASONAL_COVERAGE_PER_HARMONIC requires ≥ "
            f"{T.MIN_SEASONAL_COVERAGE_PER_HARMONIC:g}. The seasonal amplitude is not separable "
            "from [1, t] on this window, so publishing it in the grid/stats is the origin/main "
            "defect."
        )
        assert fit.design_condition <= T.MAX_DESIGN_CONDITION, (
            f"{context} has a column-normalised design condition number "
            f"{fit.design_condition:.3g} > MAX_DESIGN_CONDITION {T.MAX_DESIGN_CONDITION:g}: the "
            "harmonic columns are nearly collinear with [1, t] over these dates (clustered or "
            "irregular sampling), so the amplitude is a fitted parameter. Spread the "
            "acquisitions over the window, then regenerate."
        )

        # ... and the artefact must not simultaneously tell the reader to ignore it.
        assert not prohibitions, (
            f"{case.id}: {meta_path} limitations say {prohibitions[0]!r} while the same case "
            f"publishes the amplitude ({order}, stats.median_seasonal_amp_mm = "
            f"{stats.get('median_seasonal_amp_mm')!r}, median grid amplitude "
            f"{float(amplitude.median())!r}), and {context} says the window *does* identify it. "
            "One of the two must go: either the term is identifiable (then rescope or delete the "
            "prohibition) or it is not (then stop publishing the amplitude, in the grid, in stats "
            "and in the series). Publishing both is the origin/main defect this migration exists "
            "to fix."
        )
        return

    # ---- branch 2: no harmonic was fitted, so the null must travel with its reason ----
    order = (
        f"stats.seasonal_n_harmonics/n_harmonics = {declared}"
        if declared is not None
        else "no declared harmonic order, and no positive amplitude in the grid"
    )
    non_sentinel = amplitude[amplitude != 0.0]
    assert non_sentinel.empty, (
        f"{case.id}: {order} says no seasonal term was fitted, but {grid_path} publishes "
        f"{len(non_sentinel)} non-zero seasonal_amp_mm value(s), first "
        f"{float(non_sentinel.iloc[0])!r}. An unfitted term is exactly 0.0 (the 'not fitted' "
        "sentinel, README §13) — a number here is an amplitude no fit produced, which is the "
        "origin/main defect in its most direct form."
    )

    ratio = pd.to_numeric(grid["ratio_R"], errors="coerce") if "ratio_R" in grid.columns else None
    assert ratio is not None, (
        f"{case.id}: {grid_path} has no ratio_R column (columns present: {list(grid.columns)}); "
        "the column is required even when it is entirely null"
    )
    populated = int(ratio.notna().sum())
    assert populated == 0, (
        f"{case.id}: {order} says no seasonal term was fitted, but {grid_path} carries "
        f"{populated} non-null ratio_R value(s), first {float(ratio.dropna().iloc[0])!r}. "
        "R = |trend| / 0 is undefined, not small and not infinite: publish null, never a sentinel."
    )

    assert stats.get("median_ratio_R") is None, (
        f"{case.id}: {meta_path} stats.median_ratio_R is {stats.get('median_ratio_R')!r} while "
        f"{order} says nothing was fitted. The aggregate must be JSON null too — otherwise the "
        "headline number the app reads is the one number no cell supports."
    )

    regimes = set(grid["regime"].dropna().astype(str).unique())
    assert regimes == {"transitional"}, (
        f"{case.id}: {order} says no seasonal term was fitted, so no cell can be classified "
        f"against one, but {grid_path} publishes regime(s) {sorted(regimes)}. Use the contract's "
        "cannot-classify value 'transitional' for every cell."
    )

    fitted_caveat = [
        item
        for item in (meta.get("limitations") or [])
        if "not fitted" in _flatten(str(item))
    ]
    assert fitted_caveat, (
        f"{case.id}: {meta_path} publishes the not-fitted state ({order}, seasonal_amp_mm == 0, "
        f"all ratio_R null, regime 'transitional', stats.median_ratio_R null) but no limitation "
        f"says the term was not fitted (limitations: {meta.get('limitations')!r}). A null ratio "
        "without its reason reads as 'no seasonality measured' — a claim about the ground — when "
        "it means 'no seasonal term was fitted'. Add the limitation that names the span and what "
        "would publish one."
    )


@needs_artefacts
def test_a_limitation_forbidding_publication_is_not_contradicted_by_the_artefact(case: Case) -> None:
    """Assert the two-honest-states rule on every shipped case (branch 1 today).

    The shipped tree is all-fitted (`stats.seasonal_n_harmonics == 2`), so this test only ever
    reaches branch 1 of `_assert_two_honest_states`. Branch 2 is exercised by the synthetic
    not-fitted artefact below; the rule itself is asserted positively on both paths.
    """
    _assert_two_honest_states(case)


#: The two not-fitted routes `pipeline/mock/model.py::seasonal_order` can take: no injected
#: seasonality, or a window too short for the annual gate. The synthetic artefact declares the
#: second, which is the one contract 1.1's "not fitted" state exists for.
NOT_FITTED_LIMITATION = (
    "The seasonal term was NOT fitted for this stack: its 36-day window (0.10 annual cycles) is "
    "below the 0.75-cycle-per-harmonic gate, so seasonal_amp_mm is published as 0.0 ('not "
    "fitted'), ratio_R is null and regime is 'transitional'. Widen the stack past one annual "
    "cycle to publish a fitted amplitude."
)


def _write_not_fitted_case(directory: pathlib.Path) -> Case:
    """Build the smallest artefact that declares the not-fitted state, in `tmp_path`.

    Hand-built rather than generated through `pipeline/generate_mock.py`: this fixture exists to
    drive the *guard*, and the producer's own not-fitted state is pinned separately in
    `tests/test_mock_not_fitted.py`. Only the files branch 2 reads are written (grid + meta), so the
    fixture cannot silently depend on a fitted-only column or on the producer's internals.
    """
    directory.mkdir(parents=True, exist_ok=True)
    grid = pd.DataFrame(
        {
            "cell_id": ["aoi", "8928308280fffff"],
            "velocity_mm_yr": [-62.0, -41.5],
            "seasonal_amp_mm": [0.0, 0.0],
            "ratio_R": [np.nan, np.nan],
            "regime": ["transitional", "transitional"],
        }
    )
    grid.to_parquet(directory / "nisar_grid.parquet", index=False)
    meta = {
        "schema_version": "1.1",
        "contract_revision": 2,
        "case_id": directory.name,
        "dates": ["2024-11-10", "2024-11-22", "2024-12-04", "2024-12-16"],
        "stats": {
            "seasonal_n_harmonics": 0,
            "median_seasonal_amp_mm": 0.0,
            "median_ratio_R": None,
            "dominant_regime": "transitional",
        },
        "limitations": [NOT_FITTED_LIMITATION],
    }
    (directory / "meta.json").write_text(
        json.dumps(meta, indent=2, allow_nan=False), encoding="utf-8"
    )
    return Case(directory.name, directory)


def test_a_not_fitted_artefact_passes_its_own_branch(tmp_path: pathlib.Path) -> None:
    """Branch 2 of the two-honest-states rule, exercised end to end on a synthetic artefact.

    Why this exists: every shipped case fits the term (`seasonal_n_harmonics == 2`), so the six
    not-fitted assertions (0.0 amplitude, null ratio_R, null median, transitional regime, and the
    'not fitted' limitation) never executed — the fold-back could have been deleted and every
    test would still have gone green. The shipped expectation is asserted explicitly below, so the
    day a case stops fitting is a visible edit here rather than a silent loss of coverage.
    """
    # The shipped expectation, stated explicitly: every published case fits the term, which is
    # exactly why branch 2 needs a synthetic fixture. Guarded by `if CASES` so this test still runs
    # (and still exercises branch 2) before the first artefact run.
    if CASES:
        shipped = {
            name: (Case(name).meta.get("stats") or {}).get("seasonal_n_harmonics") for name in CASES
        }
        assert all(value == 2 for value in shipped.values()), (
            "the shipped cases are expected to be in the fitted state (seasonal_n_harmonics == 2), "
            f"which is why branch 2 is covered by the synthetic fixture below; measured {shipped}. "
            "If a shipped case moved to the not-fitted state, update this expectation and make sure "
            "its branch is still asserted above."
        )

    case = _write_not_fitted_case(tmp_path / "not-fitted")
    assert _declared_harmonics(case.meta) == 0, "the fixture must declare 0 harmonics"
    _assert_two_honest_states(case)  # the branch-2 assertions, all of them


def test_the_not_fitted_branch_can_fail(tmp_path: pathlib.Path) -> None:
    """Proof of non-vacuity for branch 2: each violated rule is reported, not tolerated.

    Same fixture, mutated one rule at a time. If the assertions above could not fail, this test
    would be the only thing standing between the fold-back and a silent deletion.
    """
    directory = tmp_path / "mutated"
    case = _write_not_fitted_case(directory)

    # A number where the sentinel belongs: an amplitude no fit produced.
    grid = pd.read_parquet(case.grid_path)
    grid.loc[0, "seasonal_amp_mm"] = 1.5
    grid.to_parquet(case.grid_path, index=False)
    with pytest.raises(AssertionError, match="non-zero seasonal_amp_mm"):
        _assert_two_honest_states(case)

    # A populated ratio beside a 0.0 amplitude.
    case = _write_not_fitted_case(tmp_path / "ratio")
    grid = pd.read_parquet(case.grid_path)
    grid.loc[0, "ratio_R"] = 41.377
    grid.to_parquet(case.grid_path, index=False)
    with pytest.raises(AssertionError, match="non-null ratio_R"):
        _assert_two_honest_states(case)

    # A null ratio without its reason: the limitation that says "not fitted" is what makes the
    # null readable, so dropping it must fail even though every other field is still right.
    case = _write_not_fitted_case(tmp_path / "no-limitation")
    meta = json.loads(case.meta_path.read_text(encoding="utf-8"))
    meta["limitations"] = ["Rates are not transferable to the other two cities."]
    case.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    with pytest.raises(AssertionError, match="no limitation says the term was not fitted"):
        _assert_two_honest_states(case)


# ---------------------------------------------------------------------------------------------
# 7. Internal consistency: meta.stats must describe the grid the reader receives
# ---------------------------------------------------------------------------------------------


def _printed_tolerance(meta_text: str, key: str) -> tuple[float, int]:
    """Tolerance = one unit in the last digit the artefact actually *printed* for `key`.

    Why this choice: the pipeline rounds the published median to a few decimals (the 1.0 artefacts
    print `median_velocity_mm_yr: -62.065`, i.e. 3 decimals), so the published number and the
    median we recompute from the parquet differ in the last printed digit — rounding, not a
    disagreement. A tolerance any wider would stop distinguishing "median of the right column"
    from "median of a different estimator". A default of 3 decimals applies if the literal cannot
    be located, matching the pipeline's rounding convention.
    """
    literal = re.search(
        rf'"{re.escape(key)}"\s*:\s*(-?\d+(?:\.(\d+))?(?:[eE][+-]?\d+)?)', meta_text
    )
    decimals = len(literal.group(2) or "") if literal else 3
    return max(10.0**-decimals, 1e-9), decimals


@needs_artefacts
def test_meta_stats_describe_the_published_grid(case: Case) -> None:
    """`stats.median_*` and `stats.dominant_regime` must be the grid's statistics, not typed values."""
    meta = case.meta
    stats = meta.get("stats") or {}
    grid = case.grid()
    path = _rel(case.grid_path)

    assert "seasonal_amp_mm" in grid.columns, (
        f"{case.id}: {path} has no seasonal_amp_mm column, so stats.median_seasonal_amp_mm cannot "
        "be the grid's median (columns present: " f"{list(grid.columns)})"
    )
    amplitude = pd.to_numeric(grid["seasonal_amp_mm"], errors="coerce").dropna()
    assert not amplitude.empty, (
        f"{case.id}: {path} seasonal_amp_mm is entirely null; there is no grid median to compare"
    )
    published_amplitude = stats.get("median_seasonal_amp_mm")
    assert isinstance(published_amplitude, (int, float)), (
        f"{case.id}: {_rel(case.meta_path)} stats.median_seasonal_amp_mm is "
        f"{published_amplitude!r}, not a number, while {path} carries "
        f"{len(amplitude)} seasonal_amp_mm value(s)"
    )
    tolerance, decimals = _printed_tolerance(case.meta_text, "median_seasonal_amp_mm")
    grid_amplitude = float(amplitude.median())
    assert abs(float(published_amplitude) - grid_amplitude) <= tolerance, (
        f"{case.id}: stats.median_seasonal_amp_mm = {published_amplitude!r} but the median of "
        f"{path} seasonal_amp_mm is {grid_amplitude!r} (tolerance {tolerance:g} = one unit in the "
        f"{decimals} printed decimal(s)). meta.stats is the app's headline number: it must be "
        "computed from the published grid, not typed in separately."
    )

    assert "ratio_R" in grid.columns, (
        f"{case.id}: {path} has no ratio_R column, so stats.median_ratio_R cannot be the grid's "
        "median (columns present: " f"{list(grid.columns)})"
    )
    ratio = pd.to_numeric(grid["ratio_R"], errors="coerce").dropna()
    finite_ratio = ratio[np.isfinite(ratio)]
    assert not finite_ratio.empty, (
        f"{case.id}: {path} ratio_R has no finite value; a published median_ratio_R would have "
        "nothing to describe (R = |trend| / A_seasonal is finite whenever the amplitude is > 0)"
    )
    published_ratio = stats.get("median_ratio_R")
    assert isinstance(published_ratio, (int, float)), (
        f"{case.id}: {_rel(case.meta_path)} stats.median_ratio_R is {published_ratio!r}, not a "
        f"number, while {path} carries {len(finite_ratio)} finite ratio_R value(s)"
    )
    ratio_tolerance, ratio_decimals = _printed_tolerance(case.meta_text, "median_ratio_R")
    grid_ratio = float(finite_ratio.median())
    assert abs(float(published_ratio) - grid_ratio) <= ratio_tolerance, (
        f"{case.id}: stats.median_ratio_R = {published_ratio!r} but the median of {path} ratio_R is "
        f"{grid_ratio!r} (tolerance {ratio_tolerance:g} = one unit in the {ratio_decimals} printed "
        "decimal(s)). Recompute stats from the grid the app renders."
    )

    regimes = grid["regime"].dropna().astype(str)
    assert not regimes.empty, (
        f"{case.id}: {path} regime is entirely null; stats.dominant_regime has no mode to report"
    )
    modes = {str(value) for value in regimes.mode()}
    published_regime = stats.get("dominant_regime")
    assert str(published_regime) in modes, (
        f"{case.id}: stats.dominant_regime = {published_regime!r} but the modal regime of {path} is "
        f"{sorted(modes)} (counts: {regimes.value_counts().to_dict()}). A tie may be broken either "
        "way, but a published mode must be one of the tied values."
    )


# ---------------------------------------------------------------------------------------------
# 8. Doc-level guard: the documents may keep the prohibition only as a past-window statement
#    (or explicitly tagged as history — see PROHIBITION_HISTORICAL / docs/decisions.md §O-05)
# ---------------------------------------------------------------------------------------------


def test_the_readme_does_not_publish_what_it_says_is_unpublishable() -> None:
    """A live "do not publish seasonal_amp_mm" contradicts a tree that publishes one.

    The rule in force: a paragraph that forbids publishing `seasonal_amp_mm` is honest only while
    it is scoped — either to the short window the prohibition was true for (132-day / 4.5-month /
    4-month, `SHORT_WINDOW_RE`), or, for a document that records it as history, by an explicit
    `<!-- prohibition-historical: reason -->` marker on that paragraph. Anything else reads as a
    live claim about the 1.1 artefacts, which publish the amplitude from a ~2-year window, and a
    live prohibition would make the documents and the data disagree in the same repository.

    Where the sentence lives, and why this test moved: README §13 used to carry the prohibition
    verbatim, but it was reworded to "The seasonal amplitude is a published fit, not a typed
    constant". A README-only scan therefore matched 0 of 155 paragraphs — the guard could not fail
    for any edit to the tree, only for an edit that reintroduced the sentence. The phrase survives
    in `docs/science-guide.md` (the `harmonic_fit` warning block, and the blockquote that explains
    the v1.0 boundary) and in `docs/decisions.md` (D-... and O-05, which quote `origin/main`'s
    limitation). Those are the documents this test now reads: a prohibition correctly scoped as
    history is not a claim, so the scan must not demand its absence — it demands its *scope*.

    Non-vacuity is asserted, not assumed (house idiom: `tests/test_fingerprint_consistency.py`
    ``assert claims, "...the guard would pass vacuously"``). If the phrase is ever reworded
    everywhere, this test fails and asks for the scan to be retargeted instead of quietly passing.
    """
    present = [path for path in PROHIBITION_DOCS if (ROOT / path).is_file()]
    if not present:
        pytest.skip("the documents this prohibition scan reads are internal and not shipped")
    documents = {path.as_posix(): (ROOT / path).read_text(encoding="utf-8") for path in present}
    hits = prohibition_hits(documents)

    by_doc: dict[str, int] = {doc: 0 for doc in documents}
    for hit in hits:
        by_doc[hit.doc] += 1
    print(
        f"seasonal prohibition guard: {len(hits)} paragraph(s) carry the phrase "
        f"({', '.join(f'{doc}: {count}' for doc, count in by_doc.items())})"
    )
    assert hits, (
        f"no paragraph in {list(documents)} states a prohibition on publishing `seasonal_amp_mm` "
        f"(phrases: {list(PROHIBITION_PHRASES)}). Either the sentence was reworded again — in which "
        "case retarget PROHIBITION_PHRASES/PROHIBITION_DOCS at where it moved — or it is gone from "
        "the tree, in which case retire this test with a comment saying where the claim went. As "
        "written it would pass vacuously."
    )

    offending = [hit for hit in hits if not hit.scoped_by]
    assert not offending, (
        f"{offending[0].doc} paragraph {offending[0].paragraph} forbids publishing "
        f"`seasonal_amp_mm` without saying which window it is about and without being tagged as "
        f"history. Offending text: {offending[0].text!r}. The 1.1 artefacts publish the amplitude "
        "from a ~2-year window, so a live prohibition contradicts them. Either name the window the "
        "prohibition is about (e.g. 'the 132-day / ~4.5-month window could not separate seasonal "
        "from secular motion'), tag the paragraph `<!-- prohibition-historical: <reason> -->` if it "
        "records the v1.0 rule, or drop the prohibition — but do not leave one in the present "
        f"tense next to a published amplitude ({', '.join(hit.doc for hit in offending)})."
    )

    scoped_counts: dict[str, int] = {}
    for hit in hits:
        scoped_counts[hit.scoped_by] = scoped_counts.get(hit.scoped_by, 0) + 1
    print(f"  scoped by window: {scoped_counts.get('window', 0)}, tagged as history: "
          f"{scoped_counts.get('history', 0)}, live claims: {scoped_counts.get('', 0)}")


def test_an_unscoped_prohibition_is_reported_and_a_scoped_one_is_not() -> None:
    """Proof of non-vacuity: the rule above rejects a live prohibition and accepts a scoped one.

    Synthetic text on purpose — the shipped tree is honest today, so the only way to show that the
    scan can fail is to feed it the shapes it is supposed to separate: an unscoped claim, a claim
    scoped to the short window, and a claim tagged as history. Mirrors
    `test_fingerprint_consistency.test_a_wrong_abbreviation_is_reported`.
    """
    unscoped = (
        "The seasonal term is a nuisance parameter. Do not publish `seasonal_amp_mm` from this "
        "stack: the three cities disagree."
    )
    windowed = (
        "On the 132-day window the gate could not separate seasonal from secular motion, so its "
        "warnings said *do not publish `seasonal_amp_mm`*."
    )
    marked = (
        "v1.0 dropped the field, and the `limitations` line said do not publish "
        "`seasonal_amp_mm` <!-- prohibition-historical: records the v1.0 boundary, where the field "
        "did not exist; not a claim about the 1.1 artefacts -->."
    )
    hits = prohibition_hits({"synthetic.md": "\n\n".join([unscoped, windowed, marked])})

    assert [hit.scoped_by for hit in hits] == ["", "window", "history"], (
        f"the scan classified the three synthetic paragraphs as {[hit.scoped_by for hit in hits]}; "
        "expected ['', 'window', 'history'] (unscoped, scoped-by-window, tagged-as-history)"
    )
    offending = [hit for hit in hits if not hit.scoped_by]
    assert offending, "an unscoped prohibition was accepted; the guard would be vacuous"
    assert offending[0].paragraph == 1 and "seasonalampmm" in offending[0].text

    # The failure message the real test emits must name the doc and paragraph, so a live claim is
    # reported where a reader can find it. (Rebuilt here because the assertion above lives in the
    # test; this pins the identifier the message is built from.)
    assert (offending[0].doc, offending[0].paragraph) == ("synthetic.md", 1)
