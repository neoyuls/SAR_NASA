"""Every provenance id quoted in prose must still name an artefact this tree ships.

Why this file exists
--------------------
`provenance_id` is the traceability handle the whole submission leans on: it appears in the grid,
in the series, in the context features, in `meta.provenance`, in every KPI card and in the footer
of every figure. It is therefore also the value most likely to be copied **by hand** into prose —
a narration script, a handoff table, a contract example — because prose cannot import it.

On 2026-11-15 the mock digest gained the acquisition window
(`pipeline/mock/artifacts.py::provenance_digest`, guarded by `tests/test_provenance_id.py`), so all
three ids moved at once:

    jakarta       57d20da8 -> 7176bda2
    malaga        bf460c19 -> 5cabe2c2
    mexico-city   cc912b7a -> 14fc3e1f

Nothing in the repository would have noticed a document left behind. `tests/test_make_figures.py`
compares a committed PNG against a fresh render (bytes and mtimes), so a figure whose footer draws
an id is covered — but only because the figure is regenerated, and not because anyone read its
footer. No test read an id quoted in a sentence. `docs/video-script.md` quoted
`mexico-city+mock+20261114+cc912b7a` for the whole narration and was repaired in the same commit
that moved the ids; the next digest change would have had to remember it again, by hand, again.

What is scanned
---------------
* `README.md`, `CONTEXT.md`, `pipeline/README.md` — the three entry points, always; and
* every `docs/**/*.md`, recursively, so a new guide is covered the day it is added.

**Full** ids only — ``<case>+<product>+<8 digits>+<8 hex>``, the shape `contracts.PROVENANCE_ID_RE`
freezes. An abbreviated quote (`provenance_id=mexico-city+mock+…`, `docs/demo-fallback.md`) names
no digest and cannot go stale; it is out of scope on purpose, and so are the ids drawn *inside* a
PNG, which only a re-render can verify.

Two ways a quoted id may be non-live, and **both are declared in the document, never inferred**:

* ``<!-- fingerprint-historical: reason -->`` — a retired id recorded as history, the convention
  `tests/test_fingerprint_consistency.py`, `tests/test_science_constants_consistency.py` and
  `docs/decisions.md` §O-05 already use for retired *contract digests*. A bare id that is no
  longer live must carry it, with a reason; "v1.0" or a date in the sentence is not a marker,
  because those words also appear in sentences making live claims.
* ``<!-- provenance-example: reason -->`` — an id that was **never** a claim about an artefact,
  only an illustration of the id's shape (`docs/data-contract-v1.md` §3/§6 show a synthetic
  `mexico-city+nisar-gunw+20261114+abc12345` row). This is a second marker rather than a broader
  "historical", because calling a placeholder historical would be the same small lie this file
  exists to prevent.

A marker is scoped tightly: the id's own line, the paragraph that contains it, or — for an id
rendered inside a fenced example — the fence (or table row) and the paragraph that introduces it.
There is no file-level allowlist and no list of ids anywhere: an exemption is always visible next
to the quote, carries a reason, and dies with the sentence it excuses.

A marker on a **live** id is itself a failure. That is the hole the marker convention would
otherwise open: mark today's correct quote "historical", and on the day the digest moves the guard
stays green for a document nobody re-checked.

Non-vacuity
-----------
The guard is exercised on a `tmp_path` copy of the real `docs/video-script.md` (the document the
incident broke): quoting the retired `jakarta+mock+20261114+57d20da8` must produce the exact
message below, and the *same bytes plus a marker* must pass. Blank reasons, unknown marker names
and a marker on a live id are each shown to be refused. The main scan additionally asserts it
found quotes at all, and names the files it inspected, so a green run cannot mean "nothing read".

Hermetic: local files only, no network, no subprocess, no writes outside `tmp_path`.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Mapping

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `python -m pytest` puts the cwd on the path; be explicit anyway
    sys.path.insert(0, str(ROOT))

from src.domain import contracts as C  # noqa: E402

#: Entry points people read first. Always scanned, so a tree that loses one is a red test rather
#: than a smaller scan.
FIXED_FILES: tuple[str, ...] = ("README.md", "CONTEXT.md", "pipeline/README.md")

#: The entry points must exist in the shipped tree; two of them are internal documentation that is
#: kept out of the submitted repository, so the guard runs only where the full set is present.
if not all((pathlib.Path(__file__).resolve().parents[1] / name).is_file() for name in FIXED_FILES):
    pytest.skip(
        "the internal entry points (CONTEXT.md, pipeline/README.md) are not shipped; "
        "the provenance-id scan would be a smaller run",
        allow_module_level=True,
    )

#: The rest of the quote surface: every guide, recursively (the fingerprint guard only walks
#: `docs/*.md`; a document in a subdirectory must not become an unscanned place to park an id).
DOCS_DIR = "docs"
DOC_GLOB = "**/*.md"

#: Where the live ids come from: one `meta.json` per committed case.
PROCESSED_DIR = pathlib.Path("data") / "processed"

#: A retired digest, declared as history. Matches `tests/test_fingerprint_consistency.py`.
HISTORICAL = "fingerprint-historical"

#: An id that illustrates the shape and never named an artefact.
EXAMPLE = "provenance-example"

MARKERS: tuple[str, ...] = (HISTORICAL, EXAMPLE)

#: Both markers take a **non-blank** reason: `<!-- marker: reason -->`. A marker without a reason
#: is not a declaration, it is a shrug, and it is refused (see `test_a_marker_without_a_reason_is_refused`).
MARKER_RE = re.compile(
    rf"<!--\s*(?P<marker>{'|'.join(MARKERS)})\s*:(?P<reason>[^>]*)-->", re.IGNORECASE
)

#: The contract's own shape, with the anchors removed so it can be searched for inside a line.
#: Reusing `C.PROVENANCE_ID_RE` rather than restating the pattern is what keeps this guard and the
#: artefact gate from disagreeing about what an id is; `test_the_id_pattern_agrees_with_the_contract`
#: pins the agreement. The lookarounds stop a 9-hex tail from being silently truncated into a match.
_ID_BODY = C.PROVENANCE_ID_RE.pattern.removeprefix("^").removesuffix("$")
ID_RE = re.compile(rf"(?<![a-z0-9-])(?:{_ID_BODY})(?![0-9a-f])")

#: A fenced code block opener/closer (up to three spaces of indent, ``` or ~~~).
FENCE_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^`~]*)$")

ACTION = f"<!-- {HISTORICAL}: reason -->"
EXAMPLE_ACTION = f"<!-- {EXAMPLE}: reason -->"


# ---------------------------------------------------------------------------------------------
# The live ids: read from the committed artefacts, never typed here
# ---------------------------------------------------------------------------------------------
def live_provenance_ids(root: pathlib.Path = ROOT) -> dict[str, str]:
    """``case directory -> meta.provenance.provenance_id`` for every committed case.

    The artefact is the authority, exactly as `contracts` is for the fingerprint guard: no id is
    copied into this module, so a regeneration that moves them cannot leave the guard stale.
    """
    found: dict[str, str] = {}
    for meta_path in sorted((root / PROCESSED_DIR).glob("*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        provenance = meta.get("provenance") or {}
        found[meta_path.parent.name] = str(provenance.get("provenance_id") or "")
    return found


def authoritative_live_ids(root: pathlib.Path = ROOT) -> dict[str, str]:
    """`live_provenance_ids` with the authority asserted: present, well-shaped, distinct.

    No `pytest.skip`: a guard that cannot read the artefacts must be red, never silently green.
    """
    live = live_provenance_ids(root)
    if not live:
        pytest.fail(
            f"no {PROCESSED_DIR.as_posix()}/*/meta.json under {root}: this guard compares quoted "
            "ids against the shipped artefacts, so without them it cannot establish anything",
            pytrace=False,
        )
    bad = {case: value for case, value in live.items() if not C.PROVENANCE_ID_RE.match(value)}
    if bad:
        pytest.fail(
            f"meta.provenance.provenance_id is missing or malformed for {sorted(bad)}: {bad}. "
            "A committed artefact without a traceable id is the defect, not a reason to skip.",
            pytrace=False,
        )
    return live


# ---------------------------------------------------------------------------------------------
# Marker scope: tight, declared, and reviewable
# ---------------------------------------------------------------------------------------------
def _paragraph(lines: list[str], index: int) -> range:
    """The blank-line-delimited paragraph containing ``index`` (0-based)."""
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return range(start, end + 1)


def _fence(lines: list[str], index: int) -> tuple[int, int] | None:
    """``(open, close)`` of the fenced block containing ``index``, or ``None``."""
    opened: int | None = None
    kind = ""
    for position, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if not match:
            continue
        token = match.group("fence")
        if opened is None:
            opened, kind = position, token[0]
        elif token[0] == kind and not match.group("info").strip():
            if opened <= index <= position:
                return opened, position
            opened = None
    return None


def marker_scope(lines: list[str], index: int) -> list[int]:
    """Line indices whose marker may legitimately excuse the quote on ``index``.

    Deliberately small, because an exemption that reaches further than the eye does is a hole:

    * a **table row** is its own scope (a marker anywhere in the table would excuse every row);
    * otherwise the id's blank-line paragraph;
    * if the id sits inside a fenced block, that whole block **and** the paragraph that introduces
      it (the lead-in line above the fence is where a reader, and this guard, expects the reason).
    """
    if lines[index].lstrip().startswith("|"):
        return [index]
    scope = set(_paragraph(lines, index))
    fence = _fence(lines, index)
    if fence is not None:
        open_at, close_at = fence
        scope.update(range(open_at, close_at + 1))
        lead = open_at - 1
        while lead >= 0 and not lines[lead].strip():
            lead -= 1
        if lead >= 0:
            scope.update(_paragraph(lines, lead))
    return sorted(scope)


# ---------------------------------------------------------------------------------------------
# Finding the quotes
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Quote:
    """One full provenance id quoted in a document, and the marker that declares it (if any)."""

    path: str
    line: int  # 1-based
    value: str
    line_text: str = ""  # the quoted source line, stripped (printed in the inventory)
    marker: str | None = None
    reason: str | None = None
    marker_line: int | None = None

    def verdict(self, live: Mapping[str, str]) -> str:
        """How to read this quote: a live claim, a declared exception, or a problem."""
        if self.value in live.values():
            return "live"
        if self.marker == HISTORICAL:
            return "historical"
        if self.marker == EXAMPLE:
            return "example"
        return "unmarked"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.value}"


def find_quotes(relative: str, text: str) -> list[Quote]:
    """Every full provenance id in ``text`` with the marker that applies to it, in file order."""
    lines = text.splitlines()
    quotes: list[Quote] = []
    for match in ID_RE.finditer(text):
        index = text.count("\n", 0, match.start())
        marker = reason = marker_line = None
        for candidate in marker_scope(lines, index):
            found = MARKER_RE.search(lines[candidate])
            if found and found.group("reason").strip():
                marker = found.group("marker").lower()
                reason = found.group("reason").strip()
                marker_line = candidate + 1
                break
        quotes.append(
            Quote(
                relative,
                index + 1,
                match.group(0),
                lines[index].strip() if index < len(lines) else "",
                marker,
                reason,
                marker_line,
            )
        )
    return quotes


def scanned_paths(root: pathlib.Path = ROOT) -> list[tuple[str, pathlib.Path]]:
    """``(repo-relative path, absolute path)`` for every document the guard reads."""
    candidates = [pathlib.Path(name) for name in FIXED_FILES]
    docs = root / DOCS_DIR
    if docs.is_dir():
        candidates += [path.relative_to(root) for path in sorted(docs.glob(DOC_GLOB))]
    seen: set[pathlib.Path] = set()
    paths: list[tuple[str, pathlib.Path]] = []
    for relative in candidates:
        if relative in seen or not (root / relative).is_file():
            continue
        seen.add(relative)
        paths.append((relative.as_posix(), root / relative))
    return paths


def scan(root: pathlib.Path = ROOT) -> tuple[list[Quote], list[str]]:
    """Return ``(quotes, scanned)`` for the documents under ``root``."""
    quotes: list[Quote] = []
    scanned: list[str] = []
    for relative, path in scanned_paths(root):
        scanned.append(relative)
        quotes.extend(find_quotes(relative, path.read_text(encoding="utf-8")))
    return quotes, scanned


# ---------------------------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------------------------
def quote_problems(quotes: list[Quote], live: Mapping[str, str]) -> list[str]:
    """One human-readable failure per quote that is neither live nor declared."""
    live_values = sorted(set(live.values()))
    problems: list[str] = []
    for quote in quotes:
        if quote.value in live_values:
            if quote.marker:
                problems.append(
                    f"{quote.path}:{quote.line} quotes the live provenance_id {quote.value!r} and "
                    f"carries a {quote.marker!r} marker at line {quote.marker_line} "
                    f"({quote.reason!r}). A marker on a live id is never justified: it would keep "
                    "this guard green on the day that id retires. Remove the marker."
                )
            continue
        if quote.marker:
            continue
        problems.append(
            f"{quote.path}:{quote.line} quotes provenance_id {quote.value!r} which no committed "
            f"artefact carries; live ids are {live_values}; if this is a deliberate historical "
            f"quote, add {ACTION}. If the id only illustrates the format and never named an "
            f"artefact, say so with {EXAMPLE_ACTION} instead."
        )
    return problems


def inventory(quotes: list[Quote], live: Mapping[str, str]) -> list[str]:
    """``path:line  id  verdict  «line»`` lines, printed so a green run names what it read."""
    lines: list[str] = []
    for quote in quotes:
        text = quote.line_text if len(quote.line_text) <= 160 else quote.line_text[:159] + "\u2026"
        lines.append(f"  {quote}  [{quote.verdict(live)}]  \u00ab{text}\u00bb")
    return lines


# ---------------------------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------------------------
def test_every_quoted_provenance_id_names_a_live_artefact() -> None:
    """A document may quote an id only while that id is in a committed `meta.json` — or declares
    why it does not (a retired digest, or a shape illustration)."""
    live = authoritative_live_ids()
    quotes, _scanned = scan()
    problems = quote_problems(quotes, live)
    assert not problems, "\n\n".join(problems)


def test_the_guard_reads_the_documented_surface() -> None:
    """Non-vacuity: a green run must mean documents *and* quotes were inspected."""
    live = authoritative_live_ids()
    quotes, scanned = scan()

    for required in FIXED_FILES:
        assert required in scanned, (
            f"{required} is not in the scan ({scanned}); the entry points are always scanned, so "
            "a green run cannot be a smaller run"
        )
    assert any(path.startswith(f"{DOCS_DIR}/") for path in scanned), (
        f"no {DOCS_DIR}/**/*.md was scanned: {scanned}"
    )
    assert len(scanned) >= len(FIXED_FILES) + 5, f"only {len(scanned)} document(s) scanned"

    assert quotes, (
        f"no full provenance id is quoted in any of the {len(scanned)} scanned documents. Either "
        "the ids left the prose — in which case retarget this guard at whatever replaced them, or "
        "retire it with a comment saying where the quoting went — or the scan is empty and would "
        "pass vacuously."
    )
    assert any(quote.value in live.values() for quote in quotes), (
        "every quoted id is an exception; the guard is not comparing anything against the "
        f"artefacts ({[str(quote) for quote in quotes]})"
    )
    print(f"provenance-id guard: {len(quotes)} quote(s) in {len(scanned)} document(s)")
    for line in inventory(quotes, live):
        print(line)


def test_the_live_ids_are_distinct_per_case() -> None:
    """The id names the case as well as the stack: two cases may not share one."""
    live = authoritative_live_ids()
    duplicates = {value for value in live.values() if list(live.values()).count(value) > 1}
    assert not duplicates, (
        f"one provenance_id is carried by more than one committed case ({sorted(duplicates)}); "
        f"the live set is {live}"
    )
    print(f"live ids: {live}")


# ---------------------------------------------------------------------------------------------
# Non-vacuity: the incident's own document, mutated in a /tmp copy
# ---------------------------------------------------------------------------------------------
#: The pre-window digest (`tests/test_provenance_id.py::PRE_FIX_IDS`). Retired, never live again:
#: the window is in the digest now.
RETIRED = "jakarta+mock+20261114+57d20da8"


def _tmp_tree(tmp_path: pathlib.Path, relative: str, text: str) -> pathlib.Path:
    """A throwaway tree holding one document at ``relative``; returns its root."""
    root = tmp_path / "tree"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return root


def _mutated_script(tmp_path: pathlib.Path, live: Mapping[str, str]) -> tuple[pathlib.Path, Quote, str]:
    """Copy the real narration script into ``tmp_path`` with its live id replaced by `RETIRED`."""
    relative = "docs/video-script.md"
    source = (ROOT / relative).read_text(encoding="utf-8")
    live_quotes = [quote for quote in find_quotes(relative, source) if quote.value in live.values()]
    assert live_quotes, (
        f"{relative} no longer quotes a live provenance id, so there is nothing to mutate. Point "
        "this test at a document that does, or the proof that the guard can fail is stale."
    )
    quote = live_quotes[0]
    mutated = source.replace(quote.value, RETIRED, 1)
    assert mutated.count(RETIRED) == 1 and quote.value not in mutated
    root = _tmp_tree(tmp_path, relative, mutated)
    return root, quote, mutated


def test_a_retired_id_in_a_copy_of_the_narration_script_is_reported(tmp_path: pathlib.Path) -> None:
    """The incident, reproduced: one retired id in the script's own bytes must fail the guard.

    This is the shape that shipped: a document that is right in every other respect, quoting an id
    the artefacts no longer carry, with nothing in the sentence to say it is history.
    """
    live = authoritative_live_ids()
    root, quote, _mutated = _mutated_script(tmp_path, live)
    quotes, _scanned = scan(root)

    problems = quote_problems(quotes, live)
    assert problems, "a retired provenance id was accepted; the guard would be vacuous"
    message = problems[0]
    live_values = sorted(set(live.values()))
    assert message.startswith(
        f"docs/video-script.md:{quote.line} quotes provenance_id {RETIRED!r} which no committed "
        "artefact carries; live ids are"
    ), message
    assert f"live ids are {live_values}" in message, message
    assert ACTION in message and EXAMPLE_ACTION in message, message
    print(message)


def test_the_same_id_passes_once_the_marker_is_declared(tmp_path: pathlib.Path) -> None:
    """The other half: identical bytes plus one declared marker are accepted, as history."""
    live = authoritative_live_ids()
    unmarked_root, _quote, mutated = _mutated_script(tmp_path, live)
    unmarked_quotes, _scanned = scan(unmarked_root)
    assert quote_problems(unmarked_quotes, live), "the unmarked copy must fail before it can pass"

    lines = mutated.splitlines()
    index = next(position for position, line in enumerate(lines) if RETIRED in line)
    lines[index] = (
        lines[index]
        + f" <!-- {HISTORICAL}: retired pre-window digest, kept to show what the window changed -->"
    )
    marked_root = _tmp_tree(tmp_path / "marked", "docs/video-script.md", "\n".join(lines) + "\n")

    quotes, _scanned = scan(marked_root)
    assert quote_problems(quotes, live) == [], "a declared historical quote was refused"
    verdicts = [quote.verdict(live) for quote in quotes if quote.value == RETIRED]
    assert verdicts == ["historical"], verdicts


def test_a_marker_without_a_reason_is_refused(tmp_path: pathlib.Path) -> None:
    """`<!-- fingerprint-historical: -->` declares nothing; the marker needs a reason."""
    live = authoritative_live_ids()
    _root, _quote, mutated = _mutated_script(tmp_path, live)
    lines = mutated.splitlines()
    index = next(position for position, line in enumerate(lines) if RETIRED in line)
    lines[index] = lines[index] + f" <!-- {HISTORICAL}:   -->"
    blank = _tmp_tree(tmp_path / "blank", "docs/video-script.md", "\n".join(lines) + "\n")

    quotes, _scanned = scan(blank)
    problems = quote_problems(quotes, live)
    assert problems and RETIRED in problems[0], (
        "a marker with a blank reason excused a retired id; the reason is the reviewable part"
    )


def test_an_unknown_marker_name_is_refused(tmp_path: pathlib.Path) -> None:
    """A near-miss marker (`retired-id`, `historical`) must not excuse: the names are the contract."""
    live = authoritative_live_ids()
    _root, _quote, mutated = _mutated_script(tmp_path, live)
    lines = mutated.splitlines()
    index = next(position for position, line in enumerate(lines) if RETIRED in line)
    lines[index] = lines[index] + " <!-- retired-id: the previous digest, honest -->"
    typo = _tmp_tree(tmp_path / "typo", "docs/video-script.md", "\n".join(lines) + "\n")

    quotes, _scanned = scan(typo)
    assert quote_problems(quotes, live), "an undeclared marker name excused a retired id"


def test_a_marker_on_a_live_id_is_reported(tmp_path: pathlib.Path) -> None:
    """Marking today's correct quote would hide tomorrow's drift — so it is a failure today."""
    live = authoritative_live_ids()
    relative = "docs/video-script.md"
    source = (ROOT / relative).read_text(encoding="utf-8")
    live_quote = next(
        quote for quote in find_quotes(relative, source) if quote.value in live.values()
    )
    lines = source.splitlines()
    lines[live_quote.line - 1] = (
        lines[live_quote.line - 1] + f" <!-- {HISTORICAL}: nothing has retired yet -->"
    )
    marked = _tmp_tree(tmp_path, relative, "\n".join(lines) + "\n")

    quotes, _scanned = scan(marked)
    problems = quote_problems(quotes, live)
    assert problems and "carries a 'fingerprint-historical' marker" in problems[0], (
        "a marker on a live id was accepted; that is how a guard goes quiet after a regeneration"
    )
    print(problems[0])


def test_an_example_marker_excuses_a_shape_illustration(tmp_path: pathlib.Path) -> None:
    """The placeholder in the contract's schema examples is declared, not silently allowed."""
    live = authoritative_live_ids()
    sample = "mexico-city+nisar-gunw+20261114+abc12345"  # the row `docs/data-contract-v1.md` shows
    assert sample not in live.values()
    body = f"Ejemplo de fila:\n\n```json\n{{ \"provenance_id\": \"{sample}\" }}\n```\n"
    unmarked = _tmp_tree(tmp_path / "unmarked", "docs/example.md", body)
    quotes, _scanned = scan(unmarked)
    assert quote_problems(quotes, live), "an unmarked placeholder was accepted"

    marked = _tmp_tree(
        tmp_path / "marked",
        "docs/example.md",
        body.replace(
            "Ejemplo de fila:",
            f"Ejemplo de fila: <!-- {EXAMPLE}: illustrative row, the digest is a placeholder -->",
        ),
    )
    quotes, _scanned = scan(marked)
    assert quote_problems(quotes, live) == [], "a declared shape illustration was refused"
    assert [quote.verdict(live) for quote in quotes] == ["example"]


def test_a_table_row_marker_does_not_excuse_the_rest_of_the_table(tmp_path: pathlib.Path) -> None:
    """Scope proof: marking one narration row must not license a retired id two rows below."""
    live = authoritative_live_ids()
    body = (
        "| time | number |\n|---|---|\n"
        f"| 1:40 | `{RETIRED}` <!-- {HISTORICAL}: this row records the retired digest --> |\n"
        f"| 1:50 | `{RETIRED}` |\n"
    )
    root = _tmp_tree(tmp_path, "docs/rows.md", body)

    quotes, _scanned = scan(root)
    verdicts = [quote.verdict(live) for quote in quotes]
    assert verdicts == ["historical", "unmarked"], verdicts
    problems = quote_problems(quotes, live)
    assert len(problems) == 1 and "docs/rows.md:4" in problems[0], problems


# ---------------------------------------------------------------------------------------------
# The id pattern is the contract's
# ---------------------------------------------------------------------------------------------
def test_the_id_pattern_agrees_with_the_contract() -> None:
    """The scan must not invent its own idea of an id: it mirrors `PROVENANCE_ID_RE`."""
    sample = C.provenance_id("mexico-city", "mock", "2026-11-14", "0123456789abcdef")
    assert C.PROVENANCE_ID_RE.match(sample)

    found = find_quotes("sample.md", f"the card shows `provenance_id={sample}`\n")
    assert [quote.value for quote in found] == [sample]

    # A longer tail, a shorter date and a missing product are not ids, and must not be truncated
    # into one: a silent substring match would compare the wrong string against the artefacts.
    for not_an_id in (f"{sample}0", "mexico-city+mock+2026111+01234567", "mexico-city+01234567"):
        assert find_quotes("sample.md", f"id: {not_an_id}\n") == [], not_an_id
