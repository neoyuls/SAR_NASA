"""Hermetic tests for ``scripts/preflight.sh`` — the pre-submission gate runner.

Every test shells out to the real script (subprocess, cwd=repo root) and only uses
``--fast`` so the deliberately slow pytest suite is exercised as a SKIP row instead of
costing minutes per test. ``--fast`` still runs the clone gate (it is overlapped with the
other gates and stays near 30 s), so the committed-doc guards are covered here too.
``TMPDIR`` is redirected into ``tmp_path`` so the script's own scratch directory is
observable: it must exist during the run and be gone afterwards (trap cleanup, nothing
written into the repo).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "preflight.sh"
PROCESSED = ROOT / "data" / "processed"

CASES = (
    sorted(
        path.name
        for path in PROCESSED.iterdir()
        if path.is_dir() and not path.name.startswith(("_", "."))
    )
    if PROCESSED.is_dir()
    else []
)

pytestmark = pytest.mark.skipif(
    not CASES, reason="data/processed has no case directories — nothing to preflight"
)

ALL_GATES = [
    "contract self-check",
    "pytest suite",
    "artefact gate",
    "phase A/B handoff",
    "clone reproduction",
    "figures regenerate",
    "demo numbers",
]

#: Files copied into the scratch repo used to prove the clone gate catches a broken committed doc.
#: `.venv` is symlinked instead (it is 500 MB and only needed for its interpreter).
COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".venv",
    ".venv*",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    # Generated scratch that must never travel with the worktree. When pytest's temp dir resolves
    # inside the checkout, the copy below carried the previous run's `pytest-of-yuls` into the
    # scratch repo; the nested run then created another one, and each generation carried the last.
    # That reached 133 GB. A .gitignore entry cannot help: copytree is not git-aware.
    "pytest-of-*",
    "make-figures-mpl-*",
    # mktemp's shape, `preflight.` + 10 characters. NOT a bare `preflight.*`: ignore_patterns
    # matches basenames at every level, so that also matched `scripts/preflight.sh` -- the script
    # the clone gate sources -- and silently dropped it from the copy.
    "preflight.??????????",
    "tmp*",
)


def run_preflight(
    *args: str, tmp_root: Path, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    """Run the real script from the repo root with all scratch data under ``tmp_root``."""
    env = dict(os.environ)
    # Keep the nested pytest inside check_phase_a.sh from racing the outer run on the repo's
    # .pytest_cache; this changes no gate, only where the cache would be written. The explicit
    # basetemp and TMPDIR keep the nested run's scratch out of the repo root: when gettempdir()
    # resolves inside the checkout, an inherited temp dir is exactly what makes the tree grow.
    env["PYTEST_ADDOPTS"] = f"-p no:cacheprovider --basetemp={tmp_root / 'pytest'}"
    env["TMPDIR"] = str(tmp_root)
    return subprocess.run(
        [str(PREFLIGHT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def table_rows(stdout: str) -> dict[str, str]:
    """Map gate name -> full table row line for the text table."""
    rows: dict[str, str] = {}
    for line in stdout.splitlines():
        for name in ALL_GATES:
            if line.startswith(("1 ", "2 ", "3 ", "4 ", "5 ", "6 ", "7 ")) and name in line:
                rows[name] = line
    return rows


def gate_status(row: str) -> str:
    """Status column of a table row (PASS / FAIL / SKIP), i.e. the first status word."""
    match = re.search(r"\b(PASS|FAIL|SKIP)\b", row)
    assert match is not None, f"row has no status column: {row!r}"
    return match.group(1)


def test_script_is_executable() -> None:
    assert PREFLIGHT.is_file(), "scripts/preflight.sh is missing"
    assert os.access(PREFLIGHT, os.X_OK), "scripts/preflight.sh is not executable"


def test_fast_mode_prints_all_seven_rows_and_verdict_matches_exit_code(
    tmp_path: Path,
) -> None:
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    result = run_preflight("--fast", tmp_root=tmp_root)

    context = result.stdout + result.stderr
    assert "preflight —" in result.stdout, context

    rows = table_rows(result.stdout)
    assert set(rows) == set(ALL_GATES), f"missing table rows: {set(ALL_GATES) - set(rows)}"
    order = [
        int(match.group(1))
        for line in result.stdout.splitlines()
        if (match := re.match(r"^([1-7])\s{2,}\S", line))
    ]
    assert order == [1, 2, 3, 4, 5, 6, 7], f"table rows are not 1..7: {order}"

    # --fast executes 1, 3, 4, 5, 6, 7 and skips only the slow pytest suite, with the reason shown.
    # Gate 5 runs in both modes: the doc guards are cheap and a committed doc break must be caught
    # just as early as a size break.
    assert gate_status(rows["pytest suite"]) == "SKIP", rows["pytest suite"]
    assert "--fast" in rows["pytest suite"], rows["pytest suite"]
    for executed in ("contract self-check", "artefact gate", "phase A/B handoff",
                     "clone reproduction", "figures regenerate", "demo numbers"):
        assert gate_status(rows[executed]) != "SKIP", f"{executed} must run under --fast: {rows[executed]}"

    # The verdict must agree with the rows: exit 0 iff no executed gate failed. On a healthy tree
    # that means exit 0 and READY; if another team's gate is red (docs/evidence mid-edit, say),
    # preflight must instead say NOT READY and name it rather than pretend the tree is fine.
    failed = [name for name in ALL_GATES if gate_status(rows[name]) == "FAIL"]
    if failed:
        assert result.returncode != 0, f"preflight claimed success with red gates: {failed}"
        assert "VERDICT: NOT READY" in result.stdout, result.stdout
        verdict = result.stdout.split("VERDICT:", 1)[1]
        for name in failed:
            assert name in verdict, f"verdict does not name failed gate {name!r}"
    else:
        assert result.returncode == 0, (
            "preflight --fast failed although every executed gate reported PASS:\n" + context
        )
        assert "VERDICT: READY" in result.stdout, result.stdout
        assert "failed:" not in result.stdout.split("VERDICT:", 1)[1], result.stdout

    # This used to assert that tmp_root was empty, but nothing ever wrote there: it could not fail,
    # and the `pytest-of-yuls` recursion grew underneath it. Watch the repo root instead -- a gate
    # that leaves scratch next to the checkout is the defect, and it has to be named.
    strays = sorted(
        entry.name
        for entry in ROOT.iterdir()
        if entry.name.startswith(("pytest-of-", "tmp", "make-figures-mpl-", "preflight."))
    )
    assert not strays, f"a gate wrote scratch into the repo root: {strays}"


def test_json_output_has_one_entry_per_gate_with_status_and_seconds(tmp_path: Path) -> None:
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    result = run_preflight("--fast", "--json", tmp_root=tmp_root)

    document = json.loads(result.stdout)  # raises if stdout is not clean JSON
    steps = document["steps"]
    assert len(steps) == 7, f"expected one entry per gate, got {len(steps)}"
    assert [step["id"] for step in steps] == [1, 2, 3, 4, 5, 6, 7]

    for step in steps:
        assert set(step) >= {"id", "name", "status", "exit", "seconds", "evidence"}
        assert step["status"] in {"PASS", "FAIL", "SKIP"}
        assert isinstance(step["seconds"], (int, float))
        assert step["seconds"] >= 0
        assert step["evidence"], f"gate {step['id']} has no evidence"

    by_id = {step["id"]: step for step in steps}
    assert by_id[2]["status"] == "SKIP"
    assert "--fast" in by_id[2]["evidence"], by_id[2]
    assert by_id[5]["status"] != "SKIP", by_id[5]
    assert "doc guards" in by_id[5]["evidence"] or "committed doc" in by_id[5]["evidence"], by_id[5]

    # JSON verdict must agree with the per-step statuses (see the text-table test above).
    failed = [step["name"] for step in steps if step["status"] == "FAIL"]
    assert document["failed"] == failed
    if failed:
        assert result.returncode != 0
        assert document["ready"] is False
        assert document["verdict"] == "NOT READY"
    else:
        assert result.returncode == 0
        assert document["ready"] is True
        assert document["verdict"] == "READY"


def test_empty_processed_dir_fails_and_names_the_gate(tmp_path: Path) -> None:
    empty = tmp_path / "processed"
    empty.mkdir()
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()

    result = run_preflight("--fast", "--processed", str(empty), tmp_root=tmp_root)

    assert result.returncode != 0, "an empty artefact root must not be reported as ready"
    # The NOT READY family: this is the tool's most important behaviour (refusing to claim
    # success), and it only ever runs when a gate is red. Without these assertions a preflight
    # that printed READY unconditionally would pass this test, so pin the verdict *word* here and
    # the machine-readable verdict/ready/failed triple right below.
    assert "VERDICT: NOT READY" in result.stdout, result.stdout
    verdict_line = next(
        (line for line in result.stdout.splitlines() if line.startswith("VERDICT:")), ""
    )
    assert verdict_line.startswith("VERDICT: NOT READY —"), (
        f"the verdict line must say NOT READY with its reason, got {verdict_line!r}"
    )
    assert "failed:" in result.stdout.split("VERDICT:", 1)[1], result.stdout

    rows = table_rows(result.stdout)
    assert gate_status(rows["artefact gate"]) == "FAIL", rows["artefact gate"]
    assert "total size" in rows["artefact gate"], "the row must show why the gate failed"
    # The verdict lists the failing steps by name.
    verdict = result.stdout.split("VERDICT:", 1)[1]
    assert "artefact gate (size)" in verdict
    # The failing gate's log tail is surfaced on stderr, together with the artefact root it read.
    assert "FAIL artefact gate (size)" in result.stderr
    assert str(empty) in result.stderr

    # Same failure, machine-readable: `verdict`/`ready`/`failed` must agree with the rows. This is
    # the pair the text output cannot show (`--json` prints no VERDICT line), and it is a second
    # run because the two formats are exclusive.
    as_json = run_preflight("--fast", "--json", "--processed", str(empty), tmp_root=tmp_root)
    assert as_json.returncode != 0, as_json.stdout
    document = json.loads(as_json.stdout)  # raises if stdout is not clean JSON
    assert document["verdict"] == "NOT READY", document
    assert document["ready"] is False, document
    assert "artefact gate (size)" in document["failed"], document
    assert [step["name"] for step in document["steps"] if step["status"] == "FAIL"] == document[
        "failed"
    ], document


def _scratch_repo_from_worktree(tmp_path: Path) -> Path:
    """Copy the working tree into a throwaway git repo and commit it.

    The real repo is never modified: the broken doc lives only in this copy, which the clone gate
    then treats exactly like a teammate's checkout.
    """
    repo = tmp_path / "repo"
    # symlinks=True: dereferencing `pytest-current` materialised a second full copy of the tree.
    shutil.copytree(ROOT, repo, ignore=COPY_IGNORE, symlinks=True)
    (repo / ".venv").symlink_to(ROOT / ".venv", target_is_directory=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c", "user.name=preflight-test",
            "-c", "user.email=preflight@example.invalid",
            "commit", "-q", "-m", "scratch tree for the clone gate",
        ],
        cwd=repo,
        check=True,
    )
    return repo


def _run_gate_clone_alone(
    repo: Path, tmp_root: Path, extra_env: dict[str, str] | None = None
) -> tuple[str, str, str]:
    """Source the real script (PREFLIGHT_LIB_ONLY=1) and call gate_clone() on ``repo``.

    Returns (status, evidence, combined output). This exercises the shipped gate function, not a
    copy of its logic, while leaving the caller's repo untouched.
    """
    driver = """\
set +e
export PREFLIGHT_LIB_ONLY=1
source scripts/preflight.sh
gate_clone
printf 'GATE_STATUS=%s\\nGATE_EXIT=%s\\nGATE_EVIDENCE=%s\\n' \
  "$G_STATUS" "$G_EXIT" "$G_EVIDENCE"
if [[ $G_STATUS == FAIL && -n $G_LOG && -f $G_LOG ]]; then
  grep -m1 -E 'README[.]md:[0-9]+ documents a command' "$G_LOG" || true
fi
"""
    env = dict(os.environ)
    env["PYTEST_ADDOPTS"] = f"-p no:cacheprovider --basetemp={tmp_root / 'pytest'}"
    env.update(extra_env or {})
    completed = subprocess.run(
        ["bash", "-c", driver, "scripts/preflight.sh"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    status = re.search(r"^GATE_STATUS=(.*)$", completed.stdout, re.MULTILINE)
    evidence = re.search(r"^GATE_EVIDENCE=(.*)$", completed.stdout, re.MULTILINE)
    assert status is not None and evidence is not None, output
    return status.group(1), evidence.group(1), output


def test_clone_gate_survives_a_relative_sar_python_override(tmp_path: Path) -> None:
    """A dev pinning `SAR_PYTHON=.venv/...` must not turn the clone gate red.

    The clone is a fresh `git clone`, so `.venv` is not in it: a relative override would resolve
    against the clone's own cwd and look like a missing interpreter — the gate then reports
    "doc guards failed" for a tree that is perfectly green. That is a false negative on the one
    gate that protects teammates' checkouts, so it gets its own regression test.
    """
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    repo = _scratch_repo_from_worktree(tmp_path)

    status, evidence, output = _run_gate_clone_alone(
        repo, tmp_root, extra_env={"SAR_PYTHON": ".venv/bin/python"}
    )

    assert status == "PASS", f"a relative SAR_PYTHON broke a green clone gate:\n{evidence}\n{output}"
    assert "doc guards ok" in evidence, evidence


def test_clone_gate_fails_on_a_committed_doc_that_breaks_the_guards(tmp_path: Path) -> None:
    """The blind spot: HEAD can carry a doc whose printed command no longer works.

    A temp copy of the working tree gets one deliberately broken documented command (an unknown
    flag on the artefact-gate line), is committed, and the real gate_clone() runs against that
    clone. The gate must report FAIL and name the doc and line, not merely the artefact
    fingerprint.
    """
    tmp_root = tmp_path / "tmp"
    tmp_root.mkdir()
    repo = _scratch_repo_from_worktree(tmp_path)

    readme = repo / "README.md"
    original = readme.read_text(encoding="utf-8")
    witness = "pipeline/validate_artifacts.py --processed data/processed"
    assert original.count(witness) >= 1, "the artefact-gate line moved; update this fixture"
    readme.write_text(
        original.replace(witness, f"{witness} --definitely-not-a-real-flag", 1),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c", "user.name=preflight-test",
            "-c", "user.email=preflight@example.invalid",
            "commit", "-q", "-m", "break one documented command",
        ],
        cwd=repo,
        check=True,
    )

    status, evidence, output = _run_gate_clone_alone(repo, tmp_root)

    assert status == "FAIL", f"the clone gate certified a broken committed doc:\n{output}"
    assert "committed doc breaks a guard" in evidence, evidence
    assert re.search(r"README\.md:\d+", evidence), f"evidence names no doc line: {evidence}"
    assert "fix the doc or the command it prints" in evidence, evidence
    # The failure tail on the gate log must carry the offending doc line too.
    assert re.search(r"README\.md:\d+ documents a command", output), output
