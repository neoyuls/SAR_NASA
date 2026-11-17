"""Link and path integrity for every Markdown file the team reads.

Documentation drifts faster than code: files are renamed (``pipeline/01_generate_mock.py`` became
``pipeline/generate_mock.py``), planned directories are described as if they already exist
(``serve/``), and source documents are deleted while the pages that cite them keep the old link.
The README is already checked in other suites; this module widens the net to every Markdown file a
judge or a teammate is likely to open.

Three things are checked per document:

1. **Relative links** ``[text](target)`` -- resolved against the *linking file's own directory*,
   never against the repository root (that is the classic false-positive/false-negative bug). An
   anchor is checked only when it points into a local Markdown file: the heading must exist under
   GitHub's slug rules.
2. **Backticked repository paths** (inline code only, e.g. ``docs/x.md``) -- the path must exist
   *and* be tracked. Tokens that are not real repository paths are skipped, and every such
   rule/entry carries its reason in this file, next to the code.
3. **Same-file anchors** ``](#section)`` -- the heading must exist in that file.

Existence on this disk is not existence in the repository. An untracked file (work in progress by
another writer) exists in the working tree, so the filesystem check passes locally -- but a clone
and CI get only the ``git ls-files`` set, so a document that cites it is broken everywhere else.
That happened twice (``docs/context-sources.md`` and ``pipeline/context.py``: present here, cited
by a committed page, absent from every clone). So a citation in a document that ships must name a
path the index knows. The citation is read from the *index blob* of the document, not the working
tree, because the index is what ``git commit`` records: an unstaged edit cannot reach a clone, and
staging the document makes the guard fire one step before the bad commit lands.

A failure names the linking file, the line, the target and the exact path the link was resolved to.
This module *reports*; it never edits a document. A missing *scope* document is skipped (a doc can
legitimately be absent), but a link pointing at it from an existing document still fails.

Everything here is read-only and offline: no network, no writes. The tracked-ness rule is the one
exception to "no subprocess": it shells out to the read-only ``git ls-files``/``git show``, and when
git cannot answer it *skips* with a message instead of passing, so a bare tree never looks green.
"""

from __future__ import annotations

import functools
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Documents in scope. ``docs/*.md`` is expanded at collection time; the rest are named because
#: they are the entry points people actually read. ``flujo...`` is optional (the task calls it
#: "if present"); a missing file is skipped, never failed.
DOC_PATTERNS: tuple[str, ...] = (
    "README.md",
    "CONTEXT.md",
    "docs/*.md",
    "pipeline/README.md",
    "pipeline/ingest/README.md",
    "flujo_trabajo_y_responsabilidades.md",
)

#: Top-level names that make ``a/b`` a repository path rather than an HDF5 path, a branch name or
#: prose. Deliberately hard-coded: if ``serve/`` disappears tomorrow its references must still be
#: checked (a dynamic listing would silently stop treating them as paths).
#: ``.venv`` is excluded on purpose: it is a local environment created by setup, not repository
#: content, so ``.venv/bin/python`` in README is not a documentation link.
REPO_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "app",
        "config",
        "data",
        "deploy",
        "docs",
        "examples",
        "pipeline",
        "scripts",
        "serve",
        "src",
        "tests",
        ".github",
        ".streamlit",
    }
)

#: Placeholder syntax used throughout the docs. A path containing one cannot be resolved: it
#: describes a family of files (``data/processed/{case}/meta.json``), an example name
#: (``NISAR_L2_...``) or an HDF5 internal path (``/science/LSAR/...``).
PLACEHOLDER_MARKERS: tuple[str, ...] = ("<", ">", "{", "}", "…", "...")

#: Globs intentionally describe sets, not one file (``data/processed/_availability/*.json``).
GLOB_MARKERS: tuple[str, ...] = ("*", "?")

#: Paths under this prefix are gitignored downloads (see .gitignore and flujo §3.2), so their
#: absence says nothing about the docs.
ALLOWLIST_PREFIXES: dict[str, str] = {
    "data/raw/": "gitignored download tree (flujo §3.2); contents are never committed",
    "data/staging/": "gitignored enrichment staging (land_use sidecar); never committed",
}

#: Singular paths that look checkable but are legitimately absent. Each reason is one line.
ALLOWLIST: dict[str, str] = {
    # README §7 "Produces" and §8 "(planned)" mark these as Rol 2 deliverables, not present files.
    ".streamlit/config.toml": "planned Rol 2 Streamlit config (README §7); app not built yet",
    "src/ui/map_view.py": "planned Rol 2 module (flujo §3.1 'Estructura propuesta'); not built yet",
    "data/raw": "gitignored download directory (submission-checklist §2); absent on clean clone",
    # Post-MVP Option B target paths (route-contract & submission-checklist explicitly mark post-MVP).
    "app/src/": "route-contract §0 post-MVP Option B static frontend directory; not built in MVP",
    "serve/": "submission-checklist §1 post-MVP Option B static server directory; not built in MVP",
    "serve/build.py": "route-contract §7 'Target layout only'; marked (target), post-MVP",
    "serve/dev.py": "route-contract §7 'Target layout only'; marked (target), post-MVP",
    "serve/check_contract.py": "route-contract §7 'Target layout only'; marked (target), post-MVP",
}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+[\"'][^)]*[\"'])?\s*\)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
#: ``path.py:SYMBOL`` (and ``path.py::SYMBOL``) is a path plus a symbol under it; only the path
#: is checkable. The separator is greedy on purpose: with ``::SYMBOL`` the lazy form would take the
#: first colon into the path and leave a trailing ``:``, which then "does not exist".
PATH_SYMBOL_RE = re.compile(r"^(.+?):{1,2}[A-Za-z_][A-Za-z0-9_.]*$")
FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


@dataclass(frozen=True)
class LinkFinding:
    doc: Path
    line: int
    target: str
    resolution: str
    problem: str


@dataclass(frozen=True)
class PathRef:
    doc: Path
    line: int
    token: str
    normalized: str
    skip_reason: str | None
    resolution: str


@dataclass(frozen=True)
class UntrackedFinding:
    """A cited repository path the index does not contain (so a clone cannot resolve it)."""

    doc: Path
    line: int
    token: str
    on_disk: bool


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _where(directory: Path) -> str:
    """Human-readable base for a resolution, e.g. ``docs/`` or ``repository root``."""
    return "repository root" if directory == ROOT else f"{_rel(directory)}/"


def _documents() -> list[Path]:
    docs: list[Path] = []
    for pattern in DOC_PATTERNS:
        if "*" in pattern:
            docs.extend(sorted(ROOT.glob(pattern)))
        else:
            docs.append(ROOT / pattern)
    # Stable order, no duplicates (docs/*.md never overlaps the explicit names, but be safe).
    return sorted(dict.fromkeys(docs))


def _lines_outside_fences(text: str):
    """Yield ``(lineno, line)`` for editable Markdown, skipping fenced code blocks.

    Links and inline code inside fences are examples, not live references.
    """
    fence: str | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        match = FENCE_RE.match(line.lstrip())
        if match:
            marker = match.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is None:
            yield lineno, line


def _slugify(heading: str) -> str:
    """GitHub heading slug: lower-case, punctuation stripped, spaces to hyphens.

    ``\\w`` is Unicode-aware, so Spanish accents survive exactly as GitHub keeps them
    (``Málaga`` -> ``málaga``). No accent-stripping fallback is needed; if GitHub ever changes
    that, only this function moves.
    """
    text = heading.strip()
    text = re.sub(r"\s+#+\s*$", "", text)  # optional closing hashes
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return text


def _anchors(text: str) -> set[str]:
    """Slugs for every heading in ``text``, including GitHub's ``-1``/``-2`` duplicates."""
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for _lineno, line in _lines_outside_fences(text):
        match = HEADING_RE.match(line)
        if not match:
            continue
        slug = _slugify(match.group(2))
        if slug in seen:
            seen[slug] += 1
            anchors.add(f"{slug}-{seen[slug]}")
        else:
            seen[slug] = 0
            anchors.add(slug)
    return anchors


def _iter_links(doc: Path):
    """Yield ``(lineno, raw_target)`` for every Markdown link/image, fences excluded."""
    for lineno, line in _lines_outside_fences(doc.read_text(encoding="utf-8")):
        for match in LINK_RE.finditer(line):
            target = match.group(1).strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1].strip()
            yield lineno, target


def _check_anchor(doc: Path, resolved: Path, fragment: str, lineno: int, target: str) -> LinkFinding | None:
    fragment = unquote(fragment)
    if not fragment:
        return None
    if resolved.is_dir():
        # A directory anchor is not a Markdown heading reference; nothing cheap to verify.
        return None
    if resolved.suffix.lower() != ".md":
        # Anchors into non-Markdown files are opaque to us (e.g. a line in a script).
        return None
    available = _anchors(resolved.read_text(encoding="utf-8"))
    if fragment in available:
        return None
    return LinkFinding(
        doc=doc,
        line=lineno,
        target=target,
        resolution=f"{_rel(resolved)} (heading anchors: {', '.join(sorted(available))[:300]})",
        problem=f"fragment '#{fragment}' has no matching heading in {_rel(resolved)}",
    )


def check_links(doc: Path) -> list[LinkFinding]:
    """Every broken *relative* link in ``doc`` (same-file anchors have their own check)."""
    findings: list[LinkFinding] = []
    for lineno, target in _iter_links(doc):
        if not target or target.startswith("#"):
            continue
        if URI_SCHEME_RE.match(target):
            # http(s):// and friends are external; the test is hermetic and never fetches them.
            continue

        path_part, _, fragment = target.partition("#")
        if not path_part:
            continue
        path_part = unquote(path_part)
        # Relative to the linking file's directory -- not the repo root.
        resolved = (doc.parent / path_part).resolve()
        if not resolved.exists():
            findings.append(
                LinkFinding(
                    doc=doc,
                    line=lineno,
                    target=target,
                    resolution=f"{_rel(resolved)} (relative to {_where(doc.parent)})",
                    problem="target file does not exist",
                )
            )
            continue
        if fragment:
            finding = _check_anchor(doc, resolved, fragment, lineno, target)
            if finding:
                findings.append(finding)
    return findings


def check_same_file_anchors(doc: Path) -> list[LinkFinding]:
    """Broken ``](#section)`` anchors, checked against ``doc``'s own headings."""
    findings: list[LinkFinding] = []
    for lineno, target in _iter_links(doc):
        if not target.startswith("#") or len(target) == 1:
            continue
        finding = _check_anchor(doc, doc, target[1:], lineno, target)
        if finding:
            findings.append(finding)
    return findings


def _normalize_path_token(token: str) -> str | None:
    """Return the repository-relative path in ``token``, or ``None`` if it is not one."""
    text = token.strip()
    if not text or any(char.isspace() for char in text):
        return None  # a command line, a table cell of prose, ...
    if text.startswith(("~", "/")):
        return None  # home directory or absolute OS path, outside the repository
    if "://" in text:
        return None
    if text.startswith("./"):
        text = text[2:]
    symbol = PATH_SYMBOL_RE.match(text)
    if symbol:
        text = symbol.group(1)  # drop ``:SYMBOL``
    if "/" not in text:
        return None  # bare filename or symbol, not a repository path
    first = text.split("/", 1)[0]
    if first not in REPO_TOP_LEVEL:
        return None  # e.g. ``origin/HEAD``, ``release/mvp``, ``asf.alaska.edu/...``
    return text


def _skip_reason(token: str) -> str | None:
    if any(marker in token for marker in PLACEHOLDER_MARKERS):
        return "placeholder/example path (contains <...>, {...}, … or ...)"
    if any(marker in token for marker in GLOB_MARKERS):
        return "glob, describes a set of files rather than one path"
    for prefix, reason in ALLOWLIST_PREFIXES.items():
        # A doc may name the directory itself (`data/raw`) or something inside it (`data/raw/x`).
        # Both are the same gitignored tree, and the directory legitimately does NOT exist in a
        # fresh clone — so compare with the trailing slash normalised, or the bare form escapes
        # the allowlist and a clean clone fails this guard.
        if token.startswith(prefix) or token.rstrip("/") == prefix.rstrip("/"):
            return reason
    return ALLOWLIST.get(token)


def _iter_backticked_paths_in(text: str, doc: Path):
    """Yield a :class:`PathRef` for every inline-code token in ``text`` that looks like a repo path.

    Separated from :func:`iter_backticked_paths` so the same extraction can run over a document's
    index blob, which is not a file on disk.
    """
    for lineno, line in _lines_outside_fences(text):
        for raw in INLINE_CODE_RE.findall(line):
            normalized = _normalize_path_token(raw)
            if normalized is None:
                continue
            resolved = (ROOT / normalized).resolve()
            yield PathRef(
                doc=doc,
                line=lineno,
                token=raw.strip(),
                normalized=normalized,
                skip_reason=_skip_reason(normalized),
                resolution=f"{_rel(resolved)} (repository root)",
            )


def iter_backticked_paths(doc: Path):
    """Yield a :class:`PathRef` for every inline-code token that looks like a repo path."""
    yield from _iter_backticked_paths_in(doc.read_text(encoding="utf-8"), doc)


def check_backticked_paths(doc: Path) -> list[PathRef]:
    """Backticked repo paths in ``doc`` that neither exist nor carry an allowlist reason."""
    return [
        ref
        for ref in iter_backticked_paths(doc)
        if ref.skip_reason is None and not (ROOT / ref.normalized).exists()
    ]


# --------------------------------------------------------------------------------------------------
# Tracked-ness: "it is on this disk" is not "it is in the repository".
#
# The existence check above answers the wrong question for a citation that ships. Untracked work in
# progress (``docs/context-sources.md``, ``pipeline/context.py`` on the day this was written) is
# present under the working tree, so ``Path.exists()`` is satisfied and the guard passes locally,
# while a clone -- which has only ``git ls-files`` content -- resolves nothing and CI fails. The
# rule below asks git instead of the filesystem, so the answer is the one a clone gets.
#
# The document side is read from the *index blob* (``git show :<doc>``), never from the working
# tree, because the invariant is about what ``git commit`` records: an unstaged prose edit cannot
# reach a clone, so it is not a shipped citation yet -- and the moment ``git add`` stages it, the
# guard fires, one step before the commit that would have broken CI lands. This is also why an
# untracked document is skipped: a clone never reads it, so no citation of it ships.
#
# No allowlist is added for this rule. A path deliberately cited before it lands is precisely the
# failure this prevents; the fix is to add the file in the same commit (or stop citing it), never
# to exempt the citation here. The pre-existing allowlists above are untouched and still apply.
# --------------------------------------------------------------------------------------------------

#: What to print when git cannot answer. A skip is visible in the pytest summary; a silent pass
#: would make a tree without git (or without a checkout) look like a verified tree.
GIT_UNAVAILABLE: str = (
    f"git cannot report the index at {ROOT} (no `git` binary, not a git repository, or that path "
    "is not the work-tree root), so 'is this cited path tracked?' cannot be proved; skipping this "
    "check rather than passing it silently"
)


def _git(*args: str) -> bytes | None:
    """Run a read-only ``git <args>`` at :data:`ROOT`; ``None`` when git is missing or says no."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


@functools.lru_cache(maxsize=1)
def _tracked_paths() -> frozenset[str] | None:
    """Index entries, root-relative -- exactly the paths a commit would record -- or ``None``.

    ``git ls-files`` (not ``HEAD`` alone) is the definition of "a clone gets this": it covers a
    fully staged tree and an unmodified one alike. Caching matters because every document asks.
    """
    prefix = _git("rev-parse", "--show-prefix")
    if prefix is None:
        return None
    if prefix.strip():
        # ``ROOT`` sits inside a larger work tree: ls-files output would carry a prefix that never
        # matches a doc citation. Refuse to guess instead of failing every path in the repository.
        return None
    raw = _git("ls-files", "-z", "--full-name")
    if raw is None:
        return None
    entries = raw.decode("utf-8", "replace").split("\0")
    return frozenset(Path(entry).as_posix() for entry in entries if entry)


@functools.lru_cache(maxsize=None)
def _index_text(rel: str) -> str | None:
    """The blob the index holds for ``rel`` (``git show :rel``), or ``None`` if it is untracked."""
    raw = _git("show", f":{rel}")
    return None if raw is None else raw.decode("utf-8", "replace")


def _is_tracked(normalized: str, tracked: frozenset[str]) -> bool:
    """True when ``normalized`` is an index entry, or a directory that holds one.

    A directory is never an index entry, but ``src/ui/`` and ``docs/`` are perfectly good
    citations, so they count as tracked when anything beneath them is.
    """
    candidate = normalized.rstrip("/")
    if candidate in tracked:
        return True
    prefix = f"{candidate}/"
    return any(path.startswith(prefix) for path in tracked)


def check_untracked_backticked_paths(doc: Path) -> list[UntrackedFinding] | None:
    """Repository paths ``doc`` cites in its index blob that the index does not contain.

    ``None`` means git could not answer; the caller must skip rather than treat that as "clean".
    Documents that are themselves untracked yield ``[]``: they are not in a clone, so nothing they
    cite ships, and the rule starts applying the moment the document is added to the index.
    """
    tracked = _tracked_paths()
    if tracked is None:
        return None
    text = _index_text(_rel(doc))
    if text is None:
        return []
    findings: list[UntrackedFinding] = []
    for ref in _iter_backticked_paths_in(text, doc):
        if ref.skip_reason is not None:
            continue  # placeholder, glob or allowlisted path: same reasons as the existence check
        if _is_tracked(ref.normalized, tracked):
            continue
        findings.append(
            UntrackedFinding(
                doc=doc,
                line=ref.line,
                token=ref.token,
                on_disk=(ROOT / ref.normalized).exists(),
            )
        )
    return findings


def _format_untracked_finding(finding: UntrackedFinding) -> str:
    condition = (
        "exists in the working tree but is not tracked"
        if finding.on_disk
        else "is not in the working tree and is not tracked"
    )
    return (
        f"{_rel(finding.doc)}:{finding.line} references {finding.token!r}, which {condition} "
        "— a clone and CI cannot resolve it; add the file in the same commit or stop citing it"
    )


@pytest.mark.parametrize("token", ["data/raw", "data/raw/granule.h5", "data/staging"])
def test_gitignored_trees_are_allowlisted_with_or_without_a_trailing_slash(token: str) -> None:
    """A clone legitimately has no ``data/raw/`` or ``data/staging/``, so the guard must not ask.

    Regression: ``docs/submission-checklist.md`` backticks ``data/raw`` (no trailing slash) while
    the allowlist key was ``data/raw/``, so a naive ``startswith`` let the bare form through and
    ``test_backticked_repo_paths_exist`` failed for anyone who cloned without a download tree.
    Proved by a clean-copy rehearsal on 2026-11-14. This test pins the slash-insensitive match.
    """
    assert _skip_reason(token), f"{token} would fail a guard in a fresh checkout"


def _format_link_finding(finding: LinkFinding) -> str:
    return (
        f"{_rel(finding.doc)}:{finding.line}: {finding.target!r} -> {finding.resolution}\n"
        f"    {finding.problem}"
    )


def _format_path_finding(ref: PathRef) -> str:
    return (
        f"{_rel(ref.doc)}:{ref.line}: `{ref.token}` -> {ref.resolution}\n"
        f"    path does not exist (and is not allowlisted)"
    )


DOCUMENTS = _documents()


@pytest.mark.parametrize("doc", DOCUMENTS, ids=[_rel(doc) for doc in DOCUMENTS])
def test_relative_links_resolve(doc: Path) -> None:
    """Relative links resolve against the linking file's directory; local anchors exist."""
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} is not present; no links to check")
    if _tracked_paths() is not None and _index_text(_rel(doc)) is None:
        pytest.skip(
            f"{_rel(doc)} is a local note, not part of the repository: a clone never reads it, so "
            "its links are not a shipped instruction"
        )
    problems = check_links(doc)
    assert not problems, (
        f"{len(problems)} broken relative link(s) in {_rel(doc)} "
        "(resolved against the linking file's directory):\n"
        + "\n".join(_format_link_finding(problem) for problem in problems)
    )


@pytest.mark.parametrize("doc", DOCUMENTS, ids=[_rel(doc) for doc in DOCUMENTS])
def test_backticked_repo_paths_exist(doc: Path) -> None:
    """Every backticked repository path exists, unless an allowlist above says why it cannot."""
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} is not present; no paths to check")
    if _tracked_paths() is not None and _index_text(_rel(doc)) is None:
        pytest.skip(
            f"{_rel(doc)} is a local note, not part of the repository: a clone never reads it, so "
            "its citations are not a shipped instruction"
        )
    checked = [ref for ref in iter_backticked_paths(doc) if ref.skip_reason is None]
    problems = check_backticked_paths(doc)
    assert not problems, (
        f"{len(problems)} broken backticked path(s) in {_rel(doc)} "
        f"({len(checked)} checked, allowlist reasons live in tests/test_docs_links.py):\n"
        + "\n".join(_format_path_finding(problem) for problem in problems)
    )


@pytest.mark.parametrize("doc", DOCUMENTS, ids=[_rel(doc) for doc in DOCUMENTS])
def test_backticked_repo_paths_are_tracked(doc: Path) -> None:
    """A path cited by a document that ships must be in the index, not merely on this disk.

    The existence test above cannot see the difference between a committed file and another
    writer's untracked work in progress, and that difference is exactly what a clone and CI see.
    """
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} is not present; no paths to check")
    if _tracked_paths() is None:
        pytest.skip(GIT_UNAVAILABLE)
    text = _index_text(_rel(doc))
    if text is None:
        pytest.skip(
            f"{_rel(doc)} is untracked work in progress (not in the index): a clone never reads "
            "it, so nothing it cites ships; the rule applies once it is added to the index"
        )
    problems = check_untracked_backticked_paths(doc) or []
    checked = [ref for ref in _iter_backticked_paths_in(text, doc) if ref.skip_reason is None]
    assert not problems, (
        f"{len(problems)} cited path(s) in {_rel(doc)} exist in the working tree but not in the "
        f"repository ({len(checked)} checked; a clone resolves only what `git ls-files` lists):\n"
        + "\n".join(_format_untracked_finding(problem) for problem in problems)
    )


#: Tokens that appear backticked all over the docs but are not repository paths. Each one is a
#: rule in ``_normalize_path_token``/``_skip_reason``; pinning them here proves the tracked-ness
#: rule above stays non-vacuous without firing on prose, commands, flags or templates.
NON_PATHS: tuple[str, ...] = (
    "meta.stats",  # dotted identifier: no slash
    "./scripts/python.sh -m pytest tests -q",  # command line: whitespace
    "--fast",  # flag
    "data/processed/<case>/meta.json",  # template: placeholder marker
    "data/processed/{case_id}/nisar_grid.parquet",  # template: placeholder marker
    "data/processed/_availability/*.json",  # glob
    "origin/HEAD",  # git ref, not a top-level repository directory
    "/science/LSAR/GUNW/grids/frequencyA",  # absolute HDF5 path inside a product
    "data/raw/granule.h5",  # gitignored download tree
    "serve/build.py",  # post-MVP target, allowlisted with its reason
)


@pytest.mark.parametrize("token", NON_PATHS)
def test_non_paths_are_not_checked_for_trackedness(token: str) -> None:
    """Only genuine repository paths reach the tracked-ness rule; everything else is skipped."""
    refs = [
        ref
        for ref in _iter_backticked_paths_in(f"see `{token}` in prose", ROOT / "docs/example.md")
    ]
    assert all(ref.skip_reason is not None for ref in refs) or not refs, (
        f"{token!r} would be demanded from git; extend the skip rules above instead of the allowlist"
    )


@pytest.mark.parametrize("doc", DOCUMENTS, ids=[_rel(doc) for doc in DOCUMENTS])
def test_same_file_anchors_resolve(doc: Path) -> None:
    """``](#section)`` must name a heading that exists in the same document."""
    if not doc.exists():
        pytest.skip(f"{_rel(doc)} is not present; no anchors to check")
    findings = check_same_file_anchors(doc)
    assert not findings, (
        f"{len(findings)} broken same-file anchor(s) in {_rel(doc)}:\n"
        + "\n".join(_format_link_finding(finding) for finding in findings)
    )
