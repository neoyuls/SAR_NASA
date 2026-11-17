"""Keep `docs/handoff-mock.md` §2b honest about the loader it tells pozo to copy.

The handoff page is the only thing Rol 1 codes against, so its snippet, its signatures and its
return shapes are part of the contract: a stale `processed=` default or a map payload described as
"a dict with seven keys" costs a teammate an hour. `tests/test_reference_loader.py` already pins the
loader's *behaviour*; this module pins the *document* to that behaviour, by parsing the page instead
of restating it:

* the fenced snippet must import the public API, and every backticked signature in the prose is
  compared parameter-by-parameter against ``inspect.signature`` (names, order, keyword-only markers,
  defaults);
* the "exactly seven keys" sentence is parsed and compared with a real ``map_payload`` call and with
  the stored ``velocity_mm_yr`` / ``delta_change`` values — so the doc cannot promise rounding or a
  recomputation the loader does not do;
* the filter rule is executed: filters intersect, only remove rows, and an emptied frame raises;
* ``aoi_series`` / ``kpis`` shapes are called for real, including Málaga's ``detection_limit_mm_yr``;
* the cwd rule is exercised by chdir'ing away and asserting the error names ``<cwd>/data/processed``;
* the copy instruction is followed: the module is copied to ``src/data/loaders.py`` in ``tmp_path``
  and must still load the repo's artefacts, with no ``__file__`` or ``sys.path`` dependence.

Hermetic: reads ``docs/handoff-mock.md`` and ``data/processed/`` only, writes inside ``tmp_path``,
no network, no Streamlit import. Every behavioural test skips with a reason when no case exists.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import inspect
import pathlib
import re
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/handoff-mock.md"
if not DOC.is_file():
    pytest.skip(
        "docs/handoff-mock.md is not shipped in the submitted repository",
        allow_module_level=True,
    )
PROCESSED = ROOT / "data/processed"
EXAMPLES = ROOT / "examples"

for _path in (ROOT, EXAMPLES):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402

import reference_loader as R  # noqa: E402
from src.domain import contracts as C  # noqa: E402

PUBLIC = ("load_case", "grid_frame", "map_payload", "aoi_series", "kpis")
#: The seven map keys, spelled once here and nowhere else in this module's assertions.
MAP_KEYS = {"lat", "lon", "cell_id", "color_value", "height", "category", "risk"}
REQUIRED_FILES = ("nisar_grid.parquet", "timeseries.csv", "context_layers.geojson", "meta.json")

INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
PYTHON_BLOCK_RE = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)
SIGNATURE_TOKEN_RE = re.compile(r"^([a-z_][a-z0-9_]*)\((.*)\)$")
#: "exactly seven keys**: `a`, `b`, ..., `g` — ..." — the em dash ends the enumeration.
SEVEN_KEYS_RE = re.compile(r"exactly seven keys\*\*:(.+?)\u2014", re.DOTALL)


def _case_dirs() -> dict[str, pathlib.Path]:
    if not PROCESSED.is_dir():
        return {}
    return {
        p.name: p
        for p in sorted(PROCESSED.iterdir())
        if p.is_dir() and not p.name.startswith(("_", ".")) and all(
            (p / name).is_file() for name in REQUIRED_FILES
        )
    }


CASES = _case_dirs()
needs_data = pytest.mark.skipif(
    not CASES,
    reason=(
        "no case artefacts under data/processed/ — generate them with "
        "`./scripts/python.sh pipeline/generate_mock.py` before checking the handoff snippets"
    ),
)


@functools.lru_cache(maxsize=1)
def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _flat_doc() -> str:
    """The page with line wrapping collapsed, for phrase checks that span lines."""
    return re.sub(r"\s+", " ", _doc())


def _loader_snippet() -> str:
    candidates = [block for block in PYTHON_BLOCK_RE.findall(_doc()) if "from reference_loader" in block]
    assert len(candidates) == 1, (
        f"docs/handoff-mock.md must carry exactly one python snippet importing the loader, "
        f"found {len(candidates)}"
    )
    return candidates[0]


def _documented_signatures() -> dict[str, str]:
    found: dict[str, str] = {}
    for token in INLINE_CODE_RE.findall(_doc()):
        match = SIGNATURE_TOKEN_RE.match(token.strip())
        if match and match.group(1) in PUBLIC:
            # A bare `kpis()` mention elsewhere in the prose is not a signature; keep the
            # spelling that actually lists parameters.
            previous = found.get(match.group(1))
            if previous is None or len(token) > len(previous):
                found[match.group(1)] = token.strip()
    return found


def _split_params(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current = ""
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def _parse_documented(text: str) -> list[tuple[str, str | None, bool]]:
    """``name(a, *, b=None)`` -> ``[(name, default-text-or-None, keyword_only)]``."""
    match = SIGNATURE_TOKEN_RE.match(text)
    assert match, f"not a signature: {text!r}"
    parsed: list[tuple[str, str | None, bool]] = []
    keyword_only = False
    for part in _split_params(match.group(2)):
        if part == "*":
            keyword_only = True
            continue
        name, _, default = part.partition("=")
        parsed.append((name.strip(), default.strip() or None, keyword_only))
    return parsed


@functools.lru_cache(maxsize=None)
def _case(case_id: str) -> R.Case:
    return R.load_case(case_id)


def _roster() -> list[str]:
    return sorted(CASES)


# ---------------------------------------------------------------------------------------------
# The snippet: what it imports, and the signatures the prose promises
# ---------------------------------------------------------------------------------------------


def test_the_snippet_imports_the_documented_public_api() -> None:
    tree = ast.parse(_loader_snippet())
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert len(imports) == 1, "the snippet must import from the loader in exactly one statement"
    statement = imports[0]
    assert statement.level == 0, "the snippet must use an absolute import"
    assert statement.module == "reference_loader", (
        f"the snippet imports {statement.module!r}; the copyable module is 'reference_loader'"
    )
    names = [alias.name for alias in statement.names]
    assert sorted(names) == sorted(PUBLIC), f"snippet imports {names}, the public API is {list(PUBLIC)}"
    for name in names:
        assert callable(getattr(R, name)), f"documented name {name!r} is not callable in the loader"
        assert name in R.__all__, f"{name!r} is documented but missing from the loader's __all__"


def test_every_documented_public_function_is_in_the_snippet() -> None:
    tree = ast.parse(_loader_snippet())
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert set(PUBLIC) <= called, f"the snippet never calls {sorted(set(PUBLIC) - called)}"


def test_documented_signatures_match_the_loader() -> None:
    """Parameter names, order, keyword-only markers and defaults, read from the prose."""
    documented = _documented_signatures()
    assert set(documented) == set(PUBLIC), (
        f"docs/handoff-mock.md documents {sorted(documented)}; every public function needs a "
        f"backticked signature: {list(PUBLIC)}"
    )
    for name, text in documented.items():
        signature = inspect.signature(getattr(R, name))
        parsed = _parse_documented(text)
        assert [param.name for param in signature.parameters.values()] == [p[0] for p in parsed], (
            f"`{text}` in the doc does not match loaders.{name}{signature}"
        )
        for param_name, default, keyword_only in parsed:
            parameter = signature.parameters[param_name]
            is_keyword_only = parameter.kind is inspect.Parameter.KEYWORD_ONLY
            assert is_keyword_only == keyword_only, (
                f"`{text}`: {param_name!r} is "
                f"{'keyword-only' if is_keyword_only else 'positional-or-keyword'} in the loader"
            )
            if default is None:
                assert parameter.default is inspect.Parameter.empty, (
                    f"`{text}`: {param_name!r} has default {parameter.default!r} in the loader"
                )
            else:
                assert ast.literal_eval(default) == parameter.default, (
                    f"`{text}`: {param_name} default {default} != {parameter.default!r} in the loader"
                )


def test_documented_kwargs_are_accepted_by_the_loader() -> None:
    """Every keyword the snippet passes must exist in the signature the doc printed."""
    signatures = {name: inspect.signature(getattr(R, name)) for name in PUBLIC}
    for node in ast.walk(ast.parse(_loader_snippet())):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in signatures:
            continue
        signature = signatures[node.func.id]
        assert len(node.args) == 1, f"{node.func.id}() is called with {len(node.args)} positional args"
        for keyword in node.keywords:
            assert keyword.arg in signature.parameters, (
                f"the snippet passes {keyword.arg}=... to {node.func.id}(), "
                f"which accepts {list(signature.parameters)}"
            )


def test_the_doc_states_the_filter_and_no_recompute_rules() -> None:
    flat = _flat_doc()
    for phrase in ("Filters are ANDed and only REMOVE rows", "raises", "never `[]`",
                   "Nothing is recomputed"):
        assert phrase in flat, f"docs/handoff-mock.md no longer states {phrase!r}"


# ---------------------------------------------------------------------------------------------
# map_payload: one dict per published cell, exactly the seven documented keys
# ---------------------------------------------------------------------------------------------


def _documented_map_keys() -> set[str]:
    match = SEVEN_KEYS_RE.search(_doc())
    assert match, "docs/handoff-mock.md no longer says the payload has 'exactly seven keys'"
    keys = INLINE_CODE_RE.findall(match.group(1))
    assert len(keys) == 7, f"the doc lists {len(keys)} map keys, not 7: {keys}"
    return set(keys)


def test_documented_map_keys_are_the_seven_the_loader_returns() -> None:
    assert _documented_map_keys() == MAP_KEYS


@needs_data
def test_map_payload_is_one_dict_per_cell_with_the_documented_keys() -> None:
    documented = _documented_map_keys()
    for case_id in _roster():
        case = _case(case_id)
        rows = R.map_payload(case)
        assert isinstance(rows, list), f"{case_id}: map_payload returned {type(rows).__name__}"
        assert len(rows) == len(case.grid), (
            f"{case_id}: {len(rows)} dicts for {len(case.grid)} published cells"
        )
        for row in rows:
            assert isinstance(row, dict), f"{case_id}: row is {type(row).__name__}, not a dict"
            assert set(row) == documented, f"{case_id}: keys {sorted(row)} != documented {sorted(documented)}"


@needs_data
def test_map_payload_carries_the_stored_columns_verbatim() -> None:
    for case_id in _roster():
        case = _case(case_id)
        stored = case.grid.set_index(case.grid["cell_id"].astype(str))
        for row in R.map_payload(case):
            origin = stored.loc[row["cell_id"]]
            assert row["color_value"] == origin["velocity_mm_yr"], (
                f"{case_id}/{row['cell_id']}: colour is not the stored velocity_mm_yr"
            )
            assert row["height"] == origin["delta_change"], (
                f"{case_id}/{row['cell_id']}: height is not the stored delta_change"
            )
            assert row["category"] == origin["land_use"] and row["risk"] == origin["risk_level"]
            assert row["lat"] == origin["lat"] and row["lon"] == origin["lon"]


@needs_data
def test_filters_are_anded_and_only_remove_rows() -> None:
    for case_id in _roster():
        case = _case(case_id)
        everything = {row["cell_id"] for row in R.map_payload(case)}
        by_coherence = {row["cell_id"] for row in R.map_payload(case, coherence_min=0.9)}
        by_land_use = {row["cell_id"] for row in R.map_payload(case, land_use=["urban-dense"])}
        both = {
            row["cell_id"]
            for row in R.map_payload(case, coherence_min=0.9, land_use=["urban-dense"])
        }
        assert by_coherence <= everything and by_land_use <= everything, (
            f"{case_id}: a filter added rows"
        )
        assert both == by_coherence & by_land_use, f"{case_id}: filters are not ANDed"


@needs_data
def test_a_filter_that_empties_the_frame_raises_instead_of_returning_empty() -> None:
    for case_id in _roster():
        case = _case(case_id)
        absent = sorted(set(C.LAND_USE) - set(case.grid["land_use"].astype(str)))
        if absent:
            kwargs, needle = {"land_use": absent[0]}, "land_use"
        else:  # every declared label exists: push coherence above the published maximum
            ceil = min(1.0, float(case.grid["coherence"].max()) + 0.01)
            kwargs, needle = {"coherence_min": ceil}, "coherence_min"
        with pytest.raises(R.LoaderError) as excinfo:
            R.map_payload(case, **kwargs)
        message = str(excinfo.value)
        assert case_id in message and needle in message, (
            f"{case_id}: the error must name the case and the filter, got {message!r}"
        )
        assert not isinstance(excinfo.value, AssertionError)


# ---------------------------------------------------------------------------------------------
# grid_frame / aoi_series / kpis: shapes and the no-recompute promise
# ---------------------------------------------------------------------------------------------


@needs_data
def test_grid_frame_is_a_copy_with_the_documented_dtypes() -> None:
    case = _case(_roster()[0])
    frame = R.grid_frame(case)
    assert isinstance(frame, pd.DataFrame) and frame is not case.grid
    assert len(frame) == len(case.grid)
    for field_ in C.GRID_FIELDS:
        if field_.dtype == "float64":
            assert str(frame[field_.name].dtype) == "float64", f"{field_.name} is not float64"
    frame.loc[frame.index[0], "velocity_mm_yr"] = 1234.5
    assert case.grid["velocity_mm_yr"].iloc[0] != 1234.5, "grid_frame returned a view, not a copy"


@needs_data
def test_aoi_series_returns_the_stored_aoi_rows_in_meta_order() -> None:
    for case_id in _roster():
        case = _case(case_id)
        dates, values = R.aoi_series(case)
        assert isinstance(dates, list) and isinstance(values, list)
        assert dates == [str(value) for value in case.meta["dates"]]
        stored = (
            case.series.loc[case.series["cell_id"].astype(str) == "aoi"]
            .assign(date=lambda frame: frame["date"].astype(str))
            .set_index("date")
        )
        assert values == [float(stored.loc[date, "value"]) for date in dates], (
            f"{case_id}: the chart is not the stored aoi series verbatim"
        )
        assert values[0] == 0.0, f"{case_id}: the aoi series must start at 0 mm"
        with pytest.raises(R.LoaderError):
            R.aoi_series(case, chart_unit="mm/yr")


@needs_data
def test_kpis_copy_meta_stats_and_surface_the_detection_limit() -> None:
    for case_id in _roster():
        case = _case(case_id)
        cards = R.kpis(case)
        stats = case.meta["stats"]
        assert cards["cells"] == stats["n_cells"]
        assert cards["median_velocity_mm_yr"] == stats["median_velocity_mm_yr"]
        assert cards["p05"] == stats["p05_velocity_mm_yr"]
        assert cards["p95"] == stats["p95_velocity_mm_yr"]
        assert cards["spread"] == pytest.approx(cards["p95"] - cards["p05"])
        published = "detection_limit_mm_yr" in stats
        assert ("detection_limit_mm_yr" in cards) is published, (
            f"{case_id}: the KPI dict must mirror meta.stats on detection_limit_mm_yr"
        )
        if published:
            assert cards["detection_limit_mm_yr"] == stats["detection_limit_mm_yr"]
            assert abs(cards["median_velocity_mm_yr"]) < cards["detection_limit_mm_yr"], (
                f"{case_id}: the doc claims Málaga is the flat case"
            )


def test_the_doc_explains_the_below_detection_state() -> None:
    flat = _flat_doc()
    assert "detection_limit_mm_yr = 1.5" in flat, "the doc must quote Málaga's 1.5 mm/yr limit"
    assert "below detection" in flat
    assert 'cards["detection_limit_mm_yr"]' in flat, (
        "the doc must say kpis() surfaces the detection limit, not just meta.json"
    )


@needs_data
def test_malaga_flat_case_surfaces_its_detection_limit() -> None:
    if "malaga" not in CASES:
        pytest.skip("malaga absent from data/processed/")
    cards = R.kpis(_case("malaga"))
    assert cards["detection_limit_mm_yr"] == 1.5
    assert abs(cards["median_velocity_mm_yr"]) < cards["detection_limit_mm_yr"]


# ---------------------------------------------------------------------------------------------
# Path resolution and the copy instruction
# ---------------------------------------------------------------------------------------------


def test_the_doc_tells_the_caller_to_run_from_the_repo_root() -> None:
    flat = _flat_doc()
    assert "caller's cwd" in flat, "the doc must say processed resolves against the caller's cwd"
    assert "run from the repo root or pass `processed=`" in flat
    assert "__file__" in flat, "the doc must say the default is *not* resolved against __file__"


@needs_data
def test_the_default_root_follows_the_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    case_id = _roster()[0]
    monkeypatch.chdir(ROOT)
    assert _case(case_id).path == (PROCESSED / case_id).resolve()

    monkeypatch.chdir(tmp_path)
    with pytest.raises(R.LoaderError) as excinfo:
        R.load_case(case_id)
    assert str((tmp_path / "data" / "processed" / case_id).resolve()) in str(excinfo.value), (
        "a wrong cwd must be reported with the path that was actually tried"
    )
    assert R.load_case(case_id, processed=PROCESSED).path == (PROCESSED / case_id).resolve()


def test_the_doc_names_the_reference_module_and_its_copy_target() -> None:
    """The doc must name both loaders and must not tell a reader to overwrite the backend one.

    2026-11-14: `src/data/loaders.py` arrived with the backend merge while this page still said
    "it does not exist yet, so copy the reference instead". Following that instruction literally
    destroyed the authoritative implementation, so the guard now asserts the safe direction: the
    reference may be copied only into a scratch tree.
    """
    text = _doc()
    assert "`examples/reference_loader.py`" in text
    assert "`src/data/loaders.py`" in text
    assert "cp examples/reference_loader.py src/data/loaders.py" not in text, (
        "the handoff doc must never instruct copying the reference over src/data/loaders.py: that "
        "file is the authoritative backend loader and the copy would silently replace it"
    )
    assert "cp examples/reference_loader.py /tmp/scratch/loaders.py" in text, (
        "the doc must still show where a scratch copy may go, or readers will improvise a "
        "destination and may pick src/data/loaders.py"
    )


def test_the_loader_does_not_depend_on_living_in_examples() -> None:
    tree = ast.parse(inspect.getsource(R))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not ({"sys"} & names and "path" in attributes), (
        "the loader must not edit sys.path: the doc copies it under src/data/"
    )
    assert "__file__" not in names, (
        "the loader must resolve artefacts from the cwd, never from __file__"
    )
    assert "from src.domain import contracts" in inspect.getsource(R)


@needs_data
def test_a_copy_under_src_data_loads_the_repository_artefacts(tmp_path: pathlib.Path) -> None:
    """Prove a copy of the reference module still loads artefacts, from a scratch tree.

    The doc's copy example targets /tmp, so this builds the same shape under tmp_path rather than
    touching `src/data/loaders.py`, whose presence is asserted separately.
    """
    copy = tmp_path / "src" / "data" / "loaders.py"
    copy.parent.mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copytree(ROOT / "src" / "domain", tmp_path / "src" / "domain")
    shutil.copy(EXAMPLES / "reference_loader.py", copy)

    spec = importlib.util.spec_from_file_location("copied_loader", copy)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        case_id = _roster()[0]
        case = module.load_case(case_id)
        assert case.path == (PROCESSED / case_id).resolve()
        assert len(module.map_payload(case)) == len(case.grid)
    finally:
        sys.modules.pop("copied_loader", None)
