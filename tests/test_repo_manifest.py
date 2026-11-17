"""Tripwire for silently lost files.

On 2026-11-14 a `git reset --hard` reverted every tracked file to HEAD and deleted a staged-only
script. `git` reported **no deletion** — HEAD had never seen the file — and the loss was only
noticed because a documentation test asked for it. This module makes that failure loud and instant:
the critical paths are listed here, so losing one fails a test rather than surfacing days later.

Keeping this list short is deliberate. It is not a file inventory; it is the set of files whose
absence would break another person's work or a documented command.
"""

from __future__ import annotations

import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Files whose disappearance breaks a documented workflow, the handoff, or the gate itself.
CRITICAL = (
    # the gates and the environment wrapper — a staged-only file was lost from here once
    "scripts/check_phase_a.sh",
    "scripts/preflight.sh",
    "scripts/python.sh",
    # the frozen contract: the code is the source of truth and ships on its own
    "src/domain/contracts.py",
    # the case definition of record and the dependency list a fresh clone needs
    "config/study_cases.yaml",
    # the AOIs the pipeline actually resolves. A clone without these silently falls back to the
    # YAML rectangle and regenerates different cell counts — which is exactly what happened on
    # 2026-11-14, when the commit tracked the unused MultiPolygon exports instead.
    "config/aoi/mexico-city.geojson",
    "config/aoi/jakarta.geojson",
    "config/aoi/malaga.geojson",
    "requirements.txt",
    "pytest.ini",
    # The public-submission licence. Without it the repo is "all rights reserved", and its
    # attribution block is the only place the data licences (NASA/ASF, ESA Copernicus, OSM) are
    # stated, so losing this file silently un-licences the whole submission.
    "LICENSE",
    # the artefact gate and the mock generator: without these there are no artefacts
    "pipeline/validate_artifacts.py",
    "pipeline/generate_mock.py",
    # the guards themselves: losing one removes a check without failing anything else, which is
    # exactly how the 2026-11-14 reset stayed quiet until a documentation test asked for a file.
    "tests/test_docs_links.py",
    "tests/test_preflight.py",
    "tests/test_readme_numbers.py",
    "tests/test_pipeline_readme_numbers.py",
    # guards the study area itself: it fails if an AOI ever becomes a MultiPolygon (the pipeline
    # builds cells from a single ring) or if the retired metro exports reappear in config/aoi/.
    "tests/test_aoi_geometry.py",
    # guards added 2026-11-14: determinism of the mock, the documented loader API, the cross-document
    # physics constants, and the ignore policy (a blanket `.*` once hid `.github/`).
    "tests/test_mock_reproducibility.py",
    "tests/test_handoff_snippets.py",
    "tests/test_science_constants_consistency.py",
    "tests/test_gitignore_policy.py",
    # the contract's own guard and the artefact gate's guard: losing either removes the check that
    # catches a contract or artefact regression, and nothing else in the suite would notice.
    "tests/test_contracts.py",
    "tests/test_validate_artifacts.py",
    "tests/test_fingerprint_consistency.py",
)

#: Scripts a caller executes directly; losing the executable bit breaks the documented command.
EXECUTABLE = (
    "scripts/check_phase_a.sh",
    "scripts/preflight.sh",
    "scripts/python.sh",
)


@pytest.mark.parametrize("relative", CRITICAL, ids=lambda p: p.replace("/", ":"))
def test_critical_file_exists(relative: str) -> None:
    path = ROOT / relative
    assert path.is_file(), (
        f"{relative} is missing. It is listed in tests/test_repo_manifest.py as critical, so its "
        f"absence breaks a documented workflow — check `git status` and restore it before committing."
    )


@pytest.mark.parametrize("relative", EXECUTABLE, ids=lambda p: p.replace("/", ":"))
def test_critical_script_is_executable(relative: str) -> None:
    path = ROOT / relative
    assert path.is_file(), f"{relative} is missing"
    assert os.access(path, os.X_OK), f"{relative} exists but lost its executable bit"


def test_no_critical_file_is_empty() -> None:
    """A truncated or zero-byte file is as broken as a missing one, and harder to spot."""
    empty = [p for p in CRITICAL if (ROOT / p).is_file() and (ROOT / p).stat().st_size == 0]
    assert not empty, f"these critical files are empty: {empty}"


def test_documents_the_team_is_told_to_read_are_reachable() -> None:
    """Every `docs/*.md` linked from README must exist — a dangling link is a broken instruction."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    import re

    linked = set(re.findall(r"\]\((docs/[A-Za-z0-9._-]+\.md)\)", readme))
    missing = sorted(target for target in linked if not (ROOT / target).is_file())
    assert not missing, f"README links to missing documents: {missing}"
