"""Guard every quoted contract fingerprint against silent drift.

The contract lives in ``src.domain.contracts``; its fingerprint is copied *by hand* into prose
(README, CONTEXT, ``pipeline/README.md`` and several ``docs/*.md``) and into the test suite that
pins those documents.  A contract change (say v1.0 -> v1.1 with a new digest) therefore rewrites
a value in a dozen places at once.  Nothing in the code says which copies exist, so a merge that
updates half of them leaves the rest quoting a hash of a contract that no longer ships.

This module is the single inventory of those quotes.  For every file in :data:`FIXED_FILES`,
every ``docs/*.md`` and every ``tests/*.py`` it finds:

* full 64-hex tokens (a complete fingerprint); and
* abbreviated quotes: at least 8 hex chars, an ellipsis (the ``…`` character or three dots),
  optionally followed by a hex suffix -- for example an 8-char prefix plus a 7-char suffix.

Each match must agree with ``contract_fingerprint()``: a full token must equal it, an abbreviation
must be a genuine prefix (and, when a suffix is present, a genuine suffix) of it.  The values are
not copied here; :func:`authoritative_fingerprint` imports them from the contract module.

Deliberate historical quotes (a document that *intends* to record an older digest, with a reason)
belong in :data:`HISTORICAL`, path -> reason.  It is empty today: there is no such quote in this
tree, and it must never be used to excuse a stale live quote. Re-enabling it is a deliberate edit:
``test_the_guard_scans_a_non_empty_quote_surface`` asserts that nothing was skipped, so adding an
entry also means saying so there, and ``test_a_bad_allowlist_entry_is_reported`` proves the entry
checks (file exists, reason non-blank) actually run.

Hermetic by construction: local files only, no network, no subprocess.  The sample strings used to
prove the checker rejects bad input are assembled at runtime, so this module does not quote a
fingerprint itself and does not trip its own scan.
"""

from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import dataclass

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `python -m pytest` puts the cwd on the path; be explicit anyway
    sys.path.insert(0, str(ROOT))

#: The action every failure asks for, because a fingerprint change is never a one-file edit.
ACTION = (
    "the contract moved; update every quoted fingerprint (a contract change requires bumping "
    "SCHEMA_VERSION, a CHANGELOG line, and all three roles' agreement)"
)

#: Always scanned, even if a future tree drops one of them: these three are entry points.
FIXED_FILES: tuple[pathlib.Path, ...] = (
    pathlib.Path("README.md"),
    pathlib.Path("CONTEXT.md"),
    pathlib.Path("pipeline/README.md"),
)

#: Globs for the rest of the quote surface.  ``docs/documentation.md`` is covered by the glob when
#: it exists; it is not required, because a missing document is not a fingerprint drift.
DOC_GLOB = "docs/*.md"
TEST_GLOB = "tests/*.py"

#: Intentional historical quotes: repo-relative path -> why that old digest is preserved.
#: Empty on purpose.  Add an entry only with a reason (e.g. "documents the v1.0 -> v1.1 migration
#: and must keep the retired digest"); never add one because a live quote failed to be updated.
HISTORICAL: dict[str, str] = {}

#: A complete fingerprint.  The lookarounds stop a 64-char window from being carved out of a longer
#: hex run (a 40-char commit id is shorter, but a 72-char blob id is not).
FULL_HASH_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{64})(?![0-9a-fA-F])")

#: An abbreviated fingerprint: >= 8 hex chars, an ellipsis, an optional hex suffix.
ABBREV_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{8,64})(?:\u2026|\.{3})([0-9a-fA-F]+)?")


# ---------------------------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------------------------
def authoritative_fingerprint() -> str:
    """Return ``src.domain.contracts.contract_fingerprint()``, failing loudly if unavailable.

    No fallback value and no ``pytest.skip``: a guard that cannot find its authority must be a
    red test, never a silently green one.
    """
    try:
        from src.domain.contracts import contract_fingerprint
    except Exception as exc:  # pragma: no cover - only hit when the tree is broken
        pytest.fail(
            "cannot import src.domain.contracts.contract_fingerprint(); the fingerprint drift "
            f"guard cannot run without its authority: {exc!r}",
            pytrace=False,
        )
    value = contract_fingerprint()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        pytest.fail(
            f"contract_fingerprint() returned {value!r}, not 64 lowercase hex characters; the "
            "contract module changed shape and this guard's patterns must be revised",
            pytrace=False,
        )
    return value


# ---------------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Claim:
    """One quoted fingerprint found in a file."""

    path: str
    line: int
    quoted: str
    prefix: str
    suffix: str | None
    full: bool

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.quoted!r}"


#: A line carrying this marker is a DELIBERATE historical quote (e.g. "the default branch moved
#: to <other hash>"), not a claim about this tree. Line-level on purpose: a whole-file exception
#: would blind the guard to every other quote in that file.
LINE_MARKER = "fingerprint-historical"


def _line_at(text: str, position: int) -> str:
    """The full source line containing ``position``."""
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return text[start : end if end != -1 else len(text)]


def fingerprint_claims(relative: str, text: str) -> list[Claim]:
    """Every full or abbreviated fingerprint quote in ``text``, ordered by position."""
    found: dict[int, Claim] = {}
    for match in FULL_HASH_RE.finditer(text):
        if LINE_MARKER in _line_at(text, match.start()):
            continue
        found[match.start()] = Claim(
            path=relative,
            line=text.count("\n", 0, match.start()) + 1,
            quoted=match.group(1),
            prefix=match.group(1).lower(),
            suffix=None,
            full=True,
        )
    for match in ABBREV_RE.finditer(text):
        if match.start() in found:  # a 64-hex token followed by an ellipsis is already "full"
            continue
        if LINE_MARKER in _line_at(text, match.start()):
            continue
        prefix, suffix = match.group(1), match.group(2)
        found[match.start()] = Claim(
            path=relative,
            line=text.count("\n", 0, match.start()) + 1,
            quoted=match.group(0),
            prefix=prefix.lower(),
            suffix=suffix.lower() if suffix else None,
            full=False,
        )
    return [found[start] for start in sorted(found)]


def scanned_paths(root: pathlib.Path = ROOT) -> list[tuple[str, pathlib.Path]]:
    """``(repo-relative path, absolute path)`` for every file the guard inspects."""
    paths: list[tuple[str, pathlib.Path]] = []
    seen: set[pathlib.Path] = set()
    candidates = [root / relative for relative in FIXED_FILES]
    candidates += sorted(root.glob(DOC_GLOB)) + sorted(root.glob(TEST_GLOB))
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        paths.append((path.relative_to(root).as_posix(), path))
    return paths


def scan(root: pathlib.Path = ROOT) -> tuple[list[Claim], list[str], list[str]]:
    """Return ``(claims, scanned, skipped)`` for the tree rooted at ``root``.

    ``skipped`` lists the :data:`HISTORICAL` paths that were present, so a run can say how much it
    ignored instead of quietly dropping files.
    """
    claims: list[Claim] = []
    scanned: list[str] = []
    skipped: list[str] = []
    for relative, path in scanned_paths(root):
        if not path.is_file():
            continue
        scanned.append(relative)
        if relative in HISTORICAL:
            skipped.append(relative)
            continue
        claims.extend(fingerprint_claims(relative, path.read_text(encoding="utf-8")))
    return claims, scanned, skipped


# ---------------------------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------------------------
def _mismatch(claim: Claim, authoritative: str) -> str:
    return (
        f"{claim.path}:{claim.line}: quoted fingerprint {claim.quoted!r} does not agree with "
        f"contract_fingerprint() {authoritative!r}\n  {ACTION}"
    )


def consistency_problems(claims: list[Claim], authoritative: str) -> list[str]:
    """Human-readable failures, one per quote that disagrees with ``authoritative``."""
    expected = authoritative.lower()
    problems: list[str] = []
    for claim in claims:
        if claim.full:
            if claim.prefix != expected:
                problems.append(_mismatch(claim, authoritative))
        elif not expected.startswith(claim.prefix):
            problems.append(_mismatch(claim, authoritative))
        elif claim.suffix and not expected.endswith(claim.suffix):
            problems.append(_mismatch(claim, authoritative))
    return problems


# ---------------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------------
def test_every_quoted_fingerprint_matches_the_contract() -> None:
    """The whole quote surface must agree with the fingerprint of the code it describes."""
    authoritative = authoritative_fingerprint()
    claims, _scanned, _skipped = scan()
    problems = consistency_problems(claims, authoritative)
    assert not problems, "\n\n".join(problems)


def test_the_guard_scans_a_non_empty_quote_surface() -> None:
    """Non-vacuity: a green run must mean files and quotes were actually inspected."""
    claims, scanned, skipped = scan()
    files_with_quotes = sorted({claim.path for claim in claims})
    assert len(scanned) >= 20, f"only {len(scanned)} files scanned; the quote surface vanished"
    for required in FIXED_FILES:
        if not (ROOT / required).is_file():
            continue  # internal document, not shipped in this repository
        assert required.as_posix() in scanned, f"{required} is not in the scan"
    assert claims, (
        "no full or abbreviated fingerprint quote found in any document or test; the guard "
        "would pass vacuously"
    )
    # Nothing may be excused from the scan. `skipped` is the files listed in HISTORICAL; asserting
    # it is empty keeps the allowlist from becoming a hole nobody notices (an entry is a deliberate
    # two-file change: this assertion *and* HISTORICAL). It was computed and only printed before,
    # which meant the exemption could be granted without the guard saying so.
    assert not skipped, (
        f"{skipped} were excused from the quote scan by HISTORICAL; no file may be silently skipped "
        "— if a historical quote is genuinely needed, remove the entry from HISTORICAL or say here "
        "why this file is exempt (and keep the reason in HISTORICAL)"
    )
    # Only the shipped documents are scanned; the README and the test suite are the quote surface
    # that must stay non-empty. A docs page need not quote a fingerprint to satisfy this guard.
    assert any(path.startswith("tests/") for path in files_with_quotes), (
        f"no tests/*.py quotes a fingerprint; scanned: {files_with_quotes}"
    )
    print(
        f"fingerprint guard: {len(claims)} quote(s) in {len(files_with_quotes)} file(s), "
        f"{len(scanned)} file(s) scanned, {len(skipped)} historical file(s) skipped"
    )


def allowlist_problems(historical: dict[str, str], root: pathlib.Path = ROOT) -> list[str]:
    """Problems with a HISTORICAL allowlist: an entry must name a real file and carry a reason.

    A function rather than an inline loop because the live allowlist is empty, so the loop body
    would never execute; the synthetic allowlists in the tests below exercise it.
    """
    problems: list[str] = []
    for relative, reason in historical.items():
        if not (root / relative).is_file():
            problems.append(f"HISTORICAL names a missing file: {relative}")
        elif not reason.strip():
            problems.append(f"HISTORICAL entry {relative!r} needs a reason")
    return problems


def test_historical_allowlist_entries_are_existing_and_justified() -> None:
    """A HISTORICAL entry must name a real file and carry a reason, so it cannot rot into a hole."""
    problems = allowlist_problems(HISTORICAL)
    assert not problems, "\n".join(problems)


def test_a_bad_allowlist_entry_is_reported(tmp_path: pathlib.Path) -> None:
    """Proof the allowlist checks bite: an absent file and a blank reason are both refused.

    The live allowlist is empty (see HISTORICAL), so without this the checks above would never
    run. `README.md` is copied in so the *blank reason* case is reachable too.
    """
    (tmp_path / "README.md").write_text("quotes no fingerprint\n", encoding="utf-8")

    missing = allowlist_problems({"does-not-exist.md": "why not"}, root=tmp_path)
    assert missing and "does-not-exist.md" in missing[0], missing

    blank = allowlist_problems({"README.md": "   "}, root=tmp_path)
    assert blank and "needs a reason" in blank[0], blank

    assert allowlist_problems({"README.md": "records the retired digest"}, root=tmp_path) == []


def test_a_wrong_abbreviation_is_reported(tmp_path: pathlib.Path) -> None:
    """Proof of non-vacuity: an 8-char prefix that is not the contract's is rejected."""
    authoritative = authoritative_fingerprint()
    evidence = tmp_path / "sample.md"
    evidence.write_text("fingerprint: " + "dead" + "beef" + "\u2026" + "\n", encoding="utf-8")

    claims = fingerprint_claims("sample.md", evidence.read_text(encoding="utf-8"))
    assert len(claims) == 1, f"the sample should yield exactly one quote, got {claims}"

    problems = consistency_problems(claims, authoritative)
    assert problems, "a wrong 8-char prefix was accepted; the guard is vacuous"
    message = "\n".join(problems)
    assert "sample.md:1" in message
    assert "deadbeef" in message
    assert authoritative in message
    assert ACTION in message


def test_a_wrong_full_token_is_reported(tmp_path: pathlib.Path) -> None:
    """Proof of non-vacuity: a complete but different digest is rejected."""
    authoritative = authoritative_fingerprint()
    wrong = "dead" * 16  # 64 hex chars, assembled so this module quotes no hash of its own
    evidence = tmp_path / "sample.md"
    evidence.write_text(f"fingerprint: {wrong}\n", encoding="utf-8")

    claims = fingerprint_claims("sample.md", evidence.read_text(encoding="utf-8"))
    assert len(claims) == 1 and claims[0].full, f"expected one full token, got {claims}"

    problems = consistency_problems(claims, authoritative)
    assert problems, "a wrong 64-hex token was accepted; the guard is vacuous"
    assert "sample.md:1" in problems[0]
    assert wrong in problems[0]
    assert authoritative in problems[0]
    assert ACTION in problems[0]


def test_a_correct_abbreviation_with_prefix_and_suffix_is_accepted() -> None:
    """The guard must not be a blanket failure: a genuine prefix + suffix quote passes."""
    authoritative = authoritative_fingerprint()
    sample = authoritative[:8] + "\u2026" + authoritative[-7:]

    claims = fingerprint_claims("sample.md", f"fingerprint: {sample}\n")
    assert len(claims) == 1 and not claims[0].full
    assert consistency_problems(claims, authoritative) == []
