"""Pin every constant `docs/first-granule-runbook.md` quotes.

The runbook is what an operator reads at the highest-stakes moment (the first real granule). It
quotes numbers that live somewhere else: exit codes, a stack cap, a fit minimum, a coverage
threshold, a coherence floor, a date window and a published rate. When one of them drifts, the
operator does not get an error -- they get the wrong conclusion. This module is the tripwire.

Rules it follows:

* **Never re-type a number.** Every expectation is resolved from the code the runbook cites
  (imported module, frozen profile, or `config/study_cases.yaml`). The only literals here are the
  *labels* the runbook uses ("credentials", "budget", ...) and the mapping from label to constant.
* **Fail closed.** If a quoted phrase disappears from the runbook, the extraction fails with the
  pattern it was looking for: a vanished quote is drift too, not "nothing to check".
* **Tolerance is explicit.** The only rounded/derived quote is the §7 `p05` band, which the runbook
  itself declares as a "factor-2 band on -450": the test recomputes that band from the YAML rate and
  from the factor the runbook states, so the rounding is checked rather than loosened.
* **Hermetic.** No network, no download. Flags are checked against each module's own `--help` in a
  subprocess; the one executed behaviour is a refusal against a `tmp_path` mock tree.
* **Report, never edit.** Nothing here rewrites the runbook or any module.

Known imprecision reported but *not* asserted as a failure (the runbook's claims are correct, only
one symbol name is stale): §2 attributes the product policy to a `PRODUCT_POLICY` table. No such
symbol exists in `pipeline/ingest/02_search_download.py`; the policy lives in `BANNED` + `OPT_IN`
(the test below pins those two against the runbook's lists).

Run: `./scripts/python.sh -m pytest tests/test_runbook_constants.py -q`
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # running pytest from another cwd
    sys.path.insert(0, str(ROOT))

RUNBOOK_PATH = ROOT / "docs" / "first-granule-runbook.md"
# The operator runbook is internal documentation and is not shipped in the submitted repository;
# it lives in the team checkout. Nothing else in this module is readable without it.
if not RUNBOOK_PATH.is_file():
    pytest.skip(
        f"{RUNBOOK_PATH.name} is not part of the submitted repository",
        allow_module_level=True,
    )
RUNBOOK = RUNBOOK_PATH.read_text(encoding="utf-8")
LINES = RUNBOOK.splitlines()
CONFIG = yaml.safe_load((ROOT / "config" / "study_cases.yaml").read_text(encoding="utf-8"))

# `02_search_download.py` cannot be imported by name (numeric prefix): load it by path.
_SPEC = importlib.util.spec_from_file_location(
    "runbook_search_download", ROOT / "pipeline" / "ingest" / "02_search_download.py"
)
assert _SPEC is not None and _SPEC.loader is not None
S = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = S
_SPEC.loader.exec_module(S)

from pipeline import process_case as P  # noqa: E402
from pipeline.mock import cases as MOCK  # noqa: E402
from pipeline.science import transforms as V  # noqa: E402
from src.domain import contracts as C  # noqa: E402

SEARCH_DOWNLOAD = "pipeline/ingest/02_search_download.py"
PROCESS_CASE = "pipeline/process_case.py"

#: The runbook types U+2212 MINUS SIGN; accept an ASCII hyphen too so a re-typeset doc still parses.
_MINUS = "[\u2212-]"

_HEADING = re.compile(r"^## (\d+)\.")


# =============================================================================================
# Runbook parsing helpers -- every failure quotes the line it judged
# =============================================================================================
def _stale(lineno: int, line: str, constant: str, doc_value: object, code_value: object,
           source: str) -> str:
    """One failure format: line, quote, constant, both values, and where the code value lives."""
    return (
        f"{RUNBOOK_PATH.name} line {lineno} is stale\n"
        f'  quoted:   "{line.strip()}"\n'
        f"  constant: {constant}\n"
        f"  runbook:  {doc_value!r}\n"
        f"  code:     {code_value!r}  [{source}]"
    )


def _iter_section(number: str):
    """(lineno, line) for one `## <number>.` section; the preamble is section "0"."""
    current = "0"
    for lineno, line in enumerate(LINES, start=1):
        heading = _HEADING.match(line)
        if heading:
            current = heading.group(1)
            continue
        if current == number:
            yield lineno, line


def _find(pattern: str, section: str, *, what: str):
    """First match of `pattern` inside a section, or fail closed with the pattern that vanished."""
    regex = re.compile(pattern)
    for lineno, line in _iter_section(section):
        match = regex.search(line)
        if match:
            return lineno, line, match
    raise AssertionError(
        f"{RUNBOOK_PATH.name} no longer quotes {what}\n"
        f"  looked for: {pattern!r} in section {section!r}\n"
        "Update tests/test_runbook_constants.py to follow the new wording -- a vanished quote is "
        "drift too, so this is a deliberate failure, not a skip."
    )


def _logical_lines():
    """(first lineno, line) with shell/CLI continuations joined, so a wrapped flag is not lost."""
    pending = ""
    start = 0
    for lineno, line in enumerate(LINES, start=1):
        if not pending:
            start = lineno
            pending = line
        else:
            pending = f"{pending} {line.strip()}"
        if pending.rstrip().endswith("\\"):
            pending = pending.rstrip()[:-1].rstrip()
            continue
        yield start, pending
        pending = ""


_SCRIPT = re.compile(r"\./scripts/python\.sh\s+(pipeline/[A-Za-z0-9_/]+\.py)\b")
_SUBCOMMANDS = ("search", "download", "report")
_FLAG = re.compile(r"(?<![\w-])(--[a-z0-9][a-z0-9-]*)")


def _runbook_commands():
    """(lineno, line, module, subcommand) for every `./scripts/python.sh pipeline/....py` line."""
    for lineno, line in _logical_lines():
        match = _SCRIPT.search(line)
        if not match:
            continue
        rest = line[match.end():].split()
        subcommand = rest[0] if rest and rest[0] in _SUBCOMMANDS else None
        yield lineno, line, match.group(1), subcommand


@lru_cache(maxsize=None)
def _help(module: str, subcommand: str | None) -> str:
    """That module's own `--help` (one subprocess per module/subcommand, cached for the session)."""
    argv = [sys.executable, str(ROOT / module)]
    if subcommand:
        argv.append(subcommand)
    argv.append("--help")
    proc = subprocess.run(  # noqa: S603 - argv is built here from the runbook, never from input
        argv, cwd=ROOT, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, (
        f"`{' '.join(argv[1:])}` failed (exit {proc.returncode}); its --help is not parseable:\n"
        f"{proc.stderr.strip()}"
    )
    return f"{proc.stdout}\n{proc.stderr}"


# =============================================================================================
# 1. Exit codes
# =============================================================================================
#: The runbook's prose label -> the constant that must carry that number.
_EXIT_CODE_CONSTANTS: tuple[tuple[str, str], ...] = (
    ("usage", "RC_USAGE"),
    ("credentials", "RC_CREDENTIALS"),
    ("product/geometry guard", "RC_PRODUCT_GUARD"),
    ("budget", "RC_BUDGET_GUARD"),
    ("foreign partial", "RC_PARTIAL_GUARD"),
    ("HTTP 403", "RC_ACCESS"),
)


def test_exit_code_table_in_the_preamble_matches_the_module():
    lineno, line, match = _find(r"S's exit codes:\s*(.+)$", "0", what="the S exit-code table")
    pairs = re.findall(r"(\d+)\s+([^,]+)", match.group(1))
    declared = {label.strip().rstrip("."): int(code) for code, label in pairs}

    module_codes = {
        name: getattr(S, name) for name in dir(S) if re.fullmatch(r"RC_[A-Z_]+", name)
    }
    assert set(module_codes) - {"RC_OK"} == {constant for _, constant in _EXIT_CODE_CONSTANTS}, (
        f"{SEARCH_DOWNLOAD} defines exit codes {sorted(module_codes)} but "
        f"{RUNBOOK_PATH.name} line {lineno} documents "
        f"{sorted(constant for _, constant in _EXIT_CODE_CONSTANTS)}; a new code is undocumented "
        f'or a documented one was renamed. Quoted: "{line.strip()}"'
    )
    assert set(declared) == {label for label, _ in _EXIT_CODE_CONSTANTS}, (
        f"{RUNBOOK_PATH.name} line {lineno} labels the exit codes {sorted(declared)}, the test "
        f"knows {sorted(label for label, _ in _EXIT_CODE_CONSTANTS)}. Quoted: \"{line.strip()}\""
    )

    for label, constant in _EXIT_CODE_CONSTANTS:
        code_value = getattr(S, constant)
        assert declared[label] == code_value, _stale(
            lineno, line, constant, f"exit {declared[label]} = {label}", code_value,
            SEARCH_DOWNLOAD,
        )


#: (section, pattern, constant, what the exit code is used for)
_INLINE_EXIT_CODES: tuple[tuple[str, str, str, str], ...] = (
    ("1", r"Expect \*\*exit (\d+)\*\* for either failure", "RC_CREDENTIALS",
     "missing credentials / missing EDL grant"),
    ("2", r"PASS exit (\d+): every id", "RC_OK", "a clean dry-run plan"),
    ("2", r"FAIL exit (\d+) `REFUSED: this plan mixes acquisition geometries`", "RC_PRODUCT_GUARD",
     "the mixed-geometry refusal"),
    ("2", r"FAIL exit (\d+) on one id ⇒ identity guard", "RC_PRODUCT_GUARD",
     "the product-identity refusal"),
    ("2", r"FAIL exit (\d+) `planned size ... exceeds --max-gb 6`", "RC_BUDGET_GUARD",
     "the budget refusal"),
    ("2", r"so that mistake exits (\d+)", "RC_PRODUCT_GUARD", "the identity guard on a 123 GB L0"),
)


@pytest.mark.parametrize("section,pattern,constant,meaning", _INLINE_EXIT_CODES)
def test_inline_exit_codes_name_the_right_constant(section, pattern, constant, meaning):
    lineno, line, match = _find(pattern, section, what=meaning)
    code_value = getattr(S, constant)
    assert int(match.group(1)) == code_value, _stale(
        lineno, line, f"{constant} ({meaning})", f"exit {match.group(1)}", code_value,
        SEARCH_DOWNLOAD,
    )


def test_every_exit_code_written_as_a_number_is_one_the_cli_can_return():
    """Typo net: an `exit 8` (or `exit 1`) anywhere in the runbook is not a code the CLI returns."""
    known = {getattr(S, name) for name in dir(S) if re.fullmatch(r"RC_[A-Z_]+", name)}
    known.add(0)  # RC_OK is defined; process_case/validate_artifacts also use 0 for success
    seen = 0
    for lineno, line in _logical_lines():
        for match in re.finditer(r"\*{0,2}exit(?:s)? \*{0,2}(\d+)", line):
            seen += 1
            assert int(match.group(1)) in known, (
                f"{RUNBOOK_PATH.name} line {lineno} documents a bare exit code that no module "
                f"returns\n  quoted: \"{line.strip()}\"\n  runbook: exit {match.group(1)}\n"
                f"  code:    {sorted(known)}  [{SEARCH_DOWNLOAD}]"
            )
    assert seen >= 6, f"only {seen} exit codes found in {RUNBOOK_PATH.name}: the parse is stale"


def test_process_case_refusal_exit_code_is_two(tmp_path):
    """§6: `MockOverwriteError`, exit 2, tree untouched -- pinned by running the refusal."""
    lineno, line, match = _find(
        r"\(`MockOverwriteError`, exit (\d+), tree untouched\)", "6",
        what="the mock-overwrite refusal exit code",
    )
    out_dir = tmp_path / "mexico-city"
    out_dir.mkdir()
    meta = out_dir / "meta.json"
    meta.write_text(json.dumps({"product": "mock", "case_id": "mexico-city"}), encoding="utf-8")
    before = meta.read_bytes()

    assert issubclass(P.MockOverwriteError, P.ProcessCaseError), (
        f"MockOverwriteError must stay a ProcessCaseError so main() maps it to the runbook's exit "
        f"{match.group(1)}; quoted: \"{line.strip()}\""
    )
    returncode = P.main(
        ["--case", "mexico-city", "--out", str(out_dir), "--granule", str(tmp_path / "absent.h5")]
    )
    assert returncode == int(match.group(1)), _stale(
        lineno, line, "process_case main() refusal status", f"exit {match.group(1)}", returncode,
        f"{PROCESS_CASE} main()",
    )
    assert meta.read_bytes() == before, (
        f"{RUNBOOK_PATH.name} line {lineno} promises 'tree untouched'; the committed mock "
        f"meta.json changed after the refusal. Quoted: \"{line.strip()}\""
    )


# =============================================================================================
# 2. STACK_GRANULE_LIMIT
# =============================================================================================
def test_stack_granule_limit_in_section_2():
    lineno, line, match = _find(
        r"`STACK_GRANULE_LIMIT = (\d+)`", "2", what="the STACK_GRANULE_LIMIT constant"
    )
    doc_value = int(match.group(1))
    assert doc_value == S.STACK_GRANULE_LIMIT, _stale(
        lineno, line, "STACK_GRANULE_LIMIT", doc_value, S.STACK_GRANULE_LIMIT, SEARCH_DOWNLOAD
    )

    lineno2, line2, match2 = _find(r"≤(\d+) ids", "2", what="the stack id cap ('≤ N ids')")
    doc_cap = int(match2.group(1))
    assert doc_cap == S.STACK_GRANULE_LIMIT, _stale(
        lineno2, line2, "STACK_GRANULE_LIMIT (the '≤ N ids' bound)", doc_cap,
        S.STACK_GRANULE_LIMIT, SEARCH_DOWNLOAD,
    )


# =============================================================================================
# 3. MIN_FIT_POINTS (and the minimum chain that reaches it)
# =============================================================================================
def test_min_fit_points_in_section_4():
    lineno, line, match = _find(
        r"`MIN_FIT_POINTS = (\d+)`", "4", what="the MIN_FIT_POINTS constant"
    )
    doc_value = int(match.group(1))
    assert doc_value == V.MIN_FIT_POINTS, _stale(
        lineno, line, "MIN_FIT_POINTS", doc_value, V.MIN_FIT_POINTS,
        "pipeline/science/transforms.py",
    )

    lineno2, line2, match2 = _find(
        r"P refuses < (\d+) epochs", "4", what="the 'refuses < N epochs' minimum"
    )
    doc_epochs = int(match2.group(1))
    assert doc_epochs == V.MIN_FIT_POINTS, _stale(
        lineno2, line2, "MIN_FIT_POINTS (the '< N epochs' refusal)", doc_epochs, V.MIN_FIT_POINTS,
        "pipeline/science/transforms.py",
    )


def test_the_minimum_probe_chain_reaches_min_fit_points():
    lineno, line, match = _find(
        r"≥(\d+) chained (\d+)-day pairs", "4", what="the minimum connected probe chain"
    )
    pairs, step_days = int(match.group(1)), int(match.group(2))
    epochs = pairs + 1  # N chained interferometric pairs give N+1 acquisition dates
    assert epochs >= V.MIN_FIT_POINTS, (
        f"{RUNBOOK_PATH.name} line {lineno} proposes a chain that cannot be fitted\n"
        f'  quoted:   "{line.strip()}"\n'
        f"  runbook:  {pairs} pairs -> {epochs} epochs\n"
        f"  code:     MIN_FIT_POINTS = {V.MIN_FIT_POINTS}  [pipeline/science/transforms.py]"
    )
    revisit = CONFIG["cases"]["mexico-city"]["revisit_days"]
    assert step_days == revisit, _stale(
        lineno, line, "cases['mexico-city'].revisit_days (the pair spacing)", step_days, revisit,
        "config/study_cases.yaml",
    )
    processing_step = CONFIG["processing"]["dates_step_days"]
    assert step_days == processing_step, _stale(
        lineno, line, "processing.dates_step_days (the pair spacing)", step_days, processing_step,
        "config/study_cases.yaml",
    )


# =============================================================================================
# 4. COVERAGE_WARNING_FRACTION and the -> 50 % decision rule
# =============================================================================================
def _coverage(fraction: float) -> P.Coverage:
    covered = round(fraction * 100)
    return P.Coverage(
        aoi_cells=100,
        covered_cells=covered,
        covered_in_aoi=covered,
        covered_outside_aoi=0,
        fraction=fraction,
    )


def test_coverage_warning_fraction_in_section_4():
    lineno, line, match = _find(
        r"`COVERAGE_WARNING_FRACTION = ([\d.]+)`", "4",
        what="the COVERAGE_WARNING_FRACTION constant",
    )
    doc_value = float(match.group(1))
    assert doc_value == P.COVERAGE_WARNING_FRACTION, _stale(
        lineno, line, "COVERAGE_WARNING_FRACTION", doc_value, P.COVERAGE_WARNING_FRACTION,
        PROCESS_CASE,
    )


def test_coverage_pass_bar_is_the_same_fraction():
    lineno, line, match = _find(
        r"Coverage .*?≥ \*\*(\d+(?:\.\d+)?) ?%\*\*", "4", what="the coverage PASS bar ('≥ N %')"
    )
    doc_fraction = float(match.group(1)) / 100
    assert math.isclose(doc_fraction, P.COVERAGE_WARNING_FRACTION), _stale(
        lineno, line, "COVERAGE_WARNING_FRACTION (the '≥ N %' PASS bar)", doc_fraction,
        P.COVERAGE_WARNING_FRACTION, PROCESS_CASE,
    )


def test_coverage_decision_rule_threshold_and_strictness():
    lineno, line, match = _find(
        r"coverage < (\d+(?:\.\d+)?) ?% ⇒ do not claim", "4",
        what="the 'coverage < N % => do not claim' decision rule",
    )
    doc_fraction = float(match.group(1)) / 100
    assert math.isclose(doc_fraction, P.COVERAGE_WARNING_FRACTION), _stale(
        lineno, line, "COVERAGE_WARNING_FRACTION (the decision-rule threshold)", doc_fraction,
        P.COVERAGE_WARNING_FRACTION, PROCESS_CASE,
    )

    # The runbook says ≥ 50 % passes and < 50 % warns, i.e. the comparison is strict `<`.
    at_threshold = _coverage(P.COVERAGE_WARNING_FRACTION)
    assert not at_threshold.below_threshold, (
        f"{RUNBOOK_PATH.name} line {lineno} promises that exactly "
        f"{P.COVERAGE_WARNING_FRACTION:.0%} passes, but Coverage.below_threshold fires at it\n"
        f'  quoted:   "{line.strip()}"\n'
        f"  code:     fraction < {P.COVERAGE_WARNING_FRACTION}  [{PROCESS_CASE} Coverage]"
    )
    just_below = _coverage(math.nextafter(P.COVERAGE_WARNING_FRACTION, 0.0))
    assert just_below.below_threshold, (
        f"{RUNBOOK_PATH.name} line {lineno} promises that anything below "
        f"{P.COVERAGE_WARNING_FRACTION:.0%} warns, but Coverage.below_threshold does not fire\n"
        f'  quoted:   "{line.strip()}"\n'
        f"  code:     fraction < {P.COVERAGE_WARNING_FRACTION}  [{PROCESS_CASE} Coverage]"
    )


# =============================================================================================
# 5. coherence_min for the frozen nisar-gunw profile
# =============================================================================================
def test_coherence_floor_in_section_4():
    lineno, line, match = _find(
        r"Coherence median ≥ \*\*([\d.]+)\*\*", "4", what="the coherence median floor"
    )
    doc_value = float(match.group(1))
    profile = "nisar-gunw"
    assert profile in C.SENSOR_PROFILES, (
        f"{RUNBOOK_PATH.name} line {lineno} cites SENSOR_PROFILES[\"{profile}\"] but "
        f"src/domain/contracts.py declares {sorted(C.SENSOR_PROFILES)}\n"
        f'  quoted: "{line.strip()}"'
    )
    code_value = C.SENSOR_PROFILES[profile].coherence_min
    assert doc_value == code_value, _stale(
        lineno, line, f'SENSOR_PROFILES["{profile}"].coherence_min', doc_value, code_value,
        "src/domain/contracts.py",
    )


# =============================================================================================
# 6. The date window quoted in section 4
# =============================================================================================
def test_date_window_in_section_4():
    lineno, line, match = _find(
        r"`dates` inside `([^`]+)` … `([^`]+)`", "4", what="the date window"
    )
    doc_start, doc_end = match.group(1).strip(), match.group(2).strip()

    processing = CONFIG["processing"]
    # Ask the code that actually builds `meta.dates`; never re-derive the grid by hand.
    dates = MOCK.build_dates(processing)
    assert doc_start == dates[0], _stale(
        lineno, line, "processing.dates_start (first date of the window)", doc_start, dates[0],
        "config/study_cases.yaml -> pipeline/mock/cases.py:build_dates",
    )
    assert doc_end == dates[-1], _stale(
        lineno, line,
        "processing.dates_start + dates_step_days * (dates_count - 1) (last date of the window)",
        doc_end, dates[-1],
        "config/study_cases.yaml -> pipeline/mock/cases.py:build_dates",
    )

    for name, pattern in (("dates_step_days", r"`dates_step_days: (\d+)`"),
                          ("dates_count", r"`dates_count: (\d+)`")):
        _, _, stated = _find(pattern, "4", what=f"the quoted {name}")
        doc_value = int(stated.group(1))
        assert doc_value == processing[name], _stale(
            lineno, line, f"processing.{name}", doc_value, processing[name],
            "config/study_cases.yaml",
        )


# =============================================================================================
# 7. The flags the runbook tells the operator to type
# =============================================================================================
#: §2/§4/§5: (section, flag, module, subcommand) pairs the runbook must keep using.
_QUOTED_FLAGS: tuple[tuple[str, str, str, str | None], ...] = (
    ("2", "--stack", SEARCH_DOWNLOAD, "download"),
    ("2", "--max-gb", SEARCH_DOWNLOAD, "download"),
    ("2", "--dry-run", SEARCH_DOWNLOAD, "download"),
    ("4", "--incidence", PROCESS_CASE, None),
    ("4", "--heading", PROCESS_CASE, None),
    ("5", "--force", PROCESS_CASE, None),
)


def _has_flag(help_text: str, flag: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text) is not None


@pytest.mark.parametrize("section,flag,module,subcommand", _QUOTED_FLAGS)
def test_named_flag_is_both_quoted_and_accepted(section, flag, module, subcommand):
    quoted = [
        (lineno, line)
        for lineno, line, cmd_module, cmd_sub in _runbook_commands()
        if cmd_module == module
        and (subcommand is None or cmd_sub == subcommand)
        and flag in _FLAG.findall(line)
    ]
    assert quoted, (
        f"{RUNBOOK_PATH.name} section {section} no longer uses `{flag}` in a `{module}` command; "
        "the runbook or the CLI moved -- update this test's quote list rather than dropping the "
        "check"
    )
    help_text = _help(module, subcommand)
    lineno, line = quoted[0]
    assert _has_flag(help_text, flag), (
        f"{RUNBOOK_PATH.name} line {lineno} tells the operator to pass `{flag}`, which "
        f"{module}{' ' + subcommand if subcommand else ''} does not accept\n"
        f'  quoted:   "{line.strip()}"\n'
        f"  constant: CLI flag {flag}\n"
        f"  runbook:  {flag}\n"
        f"  code:     not in `--help` of {module}  [subprocess {module} "
        f"{subcommand or ''} --help]"
    )


def test_every_flag_in_a_runbook_command_exists_in_that_modules_help():
    checked = 0
    for lineno, line, module, subcommand in _runbook_commands():
        flags = _FLAG.findall(line)
        if not flags:
            continue
        help_text = _help(module, subcommand)
        for flag in flags:
            checked += 1
            assert _has_flag(help_text, flag), (
                f"{RUNBOOK_PATH.name} line {lineno} runs a command with a flag the module does "
                f"not define\n"
                f'  quoted:   "{line.strip()}"\n'
                f"  constant: CLI flag {flag}\n"
                f"  runbook:  {flag}\n"
                f"  code:     not in `--help` of {module}  [subprocess {module} "
                f"{subcommand or ''} --help]"
            )
    assert checked >= 8, (
        f"only {checked} flags found across the runbook's python.sh command lines: the command "
        "parse is stale, not the runbook"
    )


# =============================================================================================
# Extra. Product policy claimed in section 2 (BANNED / OPT_IN, cited as `PRODUCT_POLICY`)
# =============================================================================================
def _granule_id(level: str, product: str, track: str = "079") -> str:
    return (
        f"NISAR_{level}_PR_{product}_032_113_D_{track}_033_4000_SH_"
        "20261008T011329_20261008T011403_20261020T011329_20261020T011403_P05023_N_F_J_001"
    )


def test_product_policy_lists_in_section_2():
    lineno, line, match = _find(
        r"`PRODUCT_POLICY`: ([A-Za-z/]+) reject; ([A-Za-z/]+) only via `--allow-product`", "2",
        what="the PRODUCT_POLICY product lists",
    )
    doc_rejected = set(match.group(1).split("/"))
    doc_opt_in = set(match.group(2).split("/"))

    banned_by_product = {product: level for level, product in S.BANNED}
    assert doc_rejected == set(banned_by_product), _stale(
        lineno, line, "BANNED (products rejected outright)", sorted(doc_rejected),
        sorted(banned_by_product), f"{SEARCH_DOWNLOAD} BANNED (no symbol named PRODUCT_POLICY)",
    )
    assert doc_opt_in == set(S.OPT_IN), _stale(
        lineno, line, "OPT_IN (products accepted only with --allow-product)", sorted(doc_opt_in),
        sorted(S.OPT_IN), f"{SEARCH_DOWNLOAD} OPT_IN (no symbol named PRODUCT_POLICY)",
    )

    # "reject" means no opt-in escape hatch; "only via --allow-product" means exactly that.
    for product, level in banned_by_product.items():
        decision = S.evaluate_granule(_granule_id(level, product), "nisar_gunw", [product])
        assert not decision.accepted, (
            f"{RUNBOOK_PATH.name} line {lineno} says `{product}` is rejected, but the guard "
            f"accepts it once listed in --allow-product\n"
            f'  quoted:   "{line.strip()}"\n'
            f"  code:     evaluate_granule(..., allow_products=[{product!r}]).accepted is True"
        )
    for product in S.OPT_IN:
        refused = S.evaluate_granule(_granule_id("L2", product), "nisar_gunw", [])
        accepted = S.evaluate_granule(_granule_id("L2", product), "nisar_gunw", [product])
        assert not refused.accepted and accepted.accepted, (
            f"{RUNBOOK_PATH.name} line {lineno} says `{product}` needs `--allow-product`, but the "
            f"guard behaves differently (without: {refused.accepted}, with: {accepted.accepted})\n"
            f'  quoted: "{line.strip()}"'
        )


# =============================================================================================
# 8. The published rate and the p05 band of section 7
# =============================================================================================
def test_published_rate_in_section_7():
    lineno, line, match = _find(
        rf"published \*\*{_MINUS}(\d+) mm/yr\*\*", "7", what="the published rate"
    )
    doc_value = -int(match.group(1))
    code_value = CONFIG["cases"]["mexico-city"]["published_rate_mm_yr"]
    assert doc_value == code_value, _stale(
        lineno, line, "cases['mexico-city'].published_rate_mm_yr", doc_value, code_value,
        "config/study_cases.yaml",
    )


def test_p05_factor_band_in_section_7_is_internally_consistent():
    # The runbook declares its own tolerance: "factor-2 band on -450". Recompute that band from the
    # YAML rate and the stated factor instead of trusting (or loosening) the two endpoints.
    lineno, line, match = _find(
        rf"`p05` within \*\*{_MINUS}(\d+) … {_MINUS}(\d+) mm/yr\*\* \(factor-(\d+) band on "
        rf"{_MINUS}(\d+)\)",
        "7",
        what="the p05 factor band",
    )
    doc_low, doc_high = -int(match.group(1)), -int(match.group(2))
    factor, anchor = int(match.group(3)), -int(match.group(4))

    rate = CONFIG["cases"]["mexico-city"]["published_rate_mm_yr"]
    assert anchor == rate, _stale(
        lineno, line, "cases['mexico-city'].published_rate_mm_yr (the band's anchor)", anchor, rate,
        "config/study_cases.yaml",
    )
    expected_low, expected_high = rate * factor, rate / factor
    assert (doc_low, doc_high) == (expected_low, expected_high), _stale(
        lineno, line, f"factor-{factor} band around published_rate_mm_yr {rate}",
        (doc_low, doc_high), (expected_low, expected_high), "config/study_cases.yaml",
    )
    assert doc_low < doc_high < 0, (
        f"{RUNBOOK_PATH.name} line {lineno} quotes a p05 band that is not an ordered subsidence "
        f"range\n  quoted: \"{line.strip()}\"\n  runbook: {doc_low} … {doc_high} mm/yr"
    )


def test_null_result_threshold_in_section_7():
    lineno, line, match = _find(
        r"`NULL_RESULT_MM_YR = ([\d.]+)`", "7", what="the NULL_RESULT_MM_YR constant"
    )
    doc_value = float(match.group(1))
    assert doc_value == C.NULL_RESULT_MM_YR, _stale(
        lineno, line, "NULL_RESULT_MM_YR", doc_value, C.NULL_RESULT_MM_YR,
        "src/domain/contracts.py",
    )

    lineno2, line2, match2 = _find(
        r"`\|median\| ≥ (\d+(?:\.\d+)?) mm/yr`", "7",
        what="the '|median| >= N mm/yr' non-null floor",
    )
    doc_floor = float(match2.group(1))
    assert doc_floor == C.NULL_RESULT_MM_YR, _stale(
        lineno2, line2, "NULL_RESULT_MM_YR (the '|median| ≥ N' floor)", doc_floor,
        C.NULL_RESULT_MM_YR, "src/domain/contracts.py",
    )
    assert C.RISK_THRESHOLDS_MM_YR[0] == (C.NULL_RESULT_MM_YR, "estable"), (
        f"{RUNBOOK_PATH.name} line {lineno2} treats {doc_floor} mm/yr as the `estable` boundary, "
        f"but RISK_THRESHOLDS_MM_YR starts at {C.RISK_THRESHOLDS_MM_YR[0]}\n"
        f'  quoted: "{line2.strip()}"'
    )
    assert "estable" in {label for _, label in C.RISK_THRESHOLDS_MM_YR}, (
        f"{RUNBOOK_PATH.name} line {lineno2} names the risk band `estable`, which "
        f"RISK_THRESHOLDS_MM_YR no longer contains: "
        f"{[label for _, label in C.RISK_THRESHOLDS_MM_YR]}"
    )

    rate = CONFIG["cases"]["mexico-city"]["published_rate_mm_yr"]
    assert abs(rate) >= C.NULL_RESULT_MM_YR and C.risk_level_from_velocity(rate) != "estable", (
        f"{RUNBOOK_PATH.name} line {lineno2} claims the case is not a null result, but "
        f"published_rate_mm_yr={rate} would be classified "
        f"{C.risk_level_from_velocity(rate)!r} against NULL_RESULT_MM_YR="
        f"{C.NULL_RESULT_MM_YR}"
    )


def test_case_ids_the_runbook_switches_between_exist():
    """§4 says flip `primary: mexico-city` -> `primary: malaga`; both must exist."""
    lineno, line, match = _find(
        r"Flip `primary: ([a-z-]+)` → `primary: ([a-z-]+)`", "4",
        what="the primary-case fallback line",
    )
    current, fallback = match.group(1), match.group(2)
    assert current == CONFIG["primary"], _stale(
        lineno, line, "primary (the case the runbook calls current)", current, CONFIG["primary"],
        "config/study_cases.yaml",
    )
    for case_id in (current, fallback):
        assert case_id in CONFIG["cases"], (
            f"{RUNBOOK_PATH.name} line {lineno} names a case that config/study_cases.yaml does not "
            f"declare\n  quoted:   \"{line.strip()}\"\n  runbook:  {case_id}\n"
            f"  code:     {sorted(CONFIG['cases'])}  [config/study_cases.yaml]"
        )
