"""Regression guard for the repository's ignore policy — in BOTH directions.

Why this exists (a real near-miss): `.gitignore` opens with a blanket ``.*`` rule, which silently
ignored ``.github/`` — so the CI workflow that ``docs/submission-checklist.md`` claims runs the
contract tests would never have been committed — and did the same to ``.gitattributes`` and a safe
``.env.example``. Targeted negations (``!.github/``, ``!.github/**``, ``!.gitattributes``,
``!.env.example``) were added afterwards. Nothing stopped that from regressing, and the opposite
failure is just as expensive: a ~2.3 GB NISAR GUNW granule or an Earthdata cookie jar must never
be one ``git add -A`` away from history.

The rules are evaluated with ``git check-ignore``, which answers for paths that do **not** exist,
so this module creates nothing on disk and stays hermetic (no network, no writes, <3 s).

``--no-index`` matters for :func:`test_no_tracked_file_is_ignored`: plain ``git check-ignore``
deliberately omits paths already in the index, so piping ``git ls-files`` into it would print
nothing even when the ignore rules match every tracked file — a vacuous check. ``--no-index``
inspects the rules alone, which is what "is this file invisible to ``git add -A``" actually asks.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GIT_DIR = ROOT / ".git"
GITIGNORE = ROOT / ".gitignore"

# A ZIP/tarball download is not a clone, so there is no repository and no ignore rules to test.
# Skip (do not fail) so the rest of the suite stays green for that judge.
if not GIT_DIR.exists():
    pytest.skip(
        f"no git repository at {ROOT} (downloaded archive rather than a clone); "
        "the .gitignore policy is only meaningful inside a work tree",
        allow_module_level=True,
    )
if shutil.which("git") is None:
    pytest.skip("git executable not found on PATH", allow_module_level=True)


#: Secrets, local state, and anything heavy: committable by accident is unacceptable.
NEVER_COMMITTABLE = (
    # local credentials / editor + venv state — all covered by the blanket `.*` rule
    ".env",
    ".venv/lib/python3.14/site-packages/x.py",
    # Streamlit's documented secrets location. `config.toml` is NOT listed here on purpose: it
    # carries theme only, and it is committed so the app boots with the theme the demo was designed
    # against (2026-11-14). The secret risk is policed by CONTENT instead — see
    # test_streamlit_config_carries_no_secrets.
    ".streamlit/secrets.toml",
    # raw downloads: one NISAR GUNW is ~2.3 GB and cannot be removed from history
    "data/raw/mexico-city/nisar_gunw/granule.h5",
    # pipeline sidecars (enrich_context.py output) are regenerated, not shipped
    "data/staging/land_use.csv",
    # a granule moved or resumed outside data/raw/ still must not be committed
    "somewhere/stray.h5",
    # Earthdata session cookies
    "cookies.txt",
    # partial downloads, archives, and GeoTIFFs are all re-derivable and heavy
    "somewhere/file.part",
    "somewhere/product.zip",
    "somewhere/tile.tif",
)

#: What a public repository must be able to carry; losing any of these breaks a documented
#: promise (CI, licences/attributes, contribution context) without failing anything else.
TRACKABLE = (
    ".github/workflows/ci.yml",
    ".gitattributes",
    ".env.example",
    # The ignore file itself matches the blanket `.*` rule, so without `!.gitignore` it is
    # untracked-but-ignored: `git add -A` skips it and the published repo ships with no ignore
    # rules at all. Caught on 2026-11-14 by a cross-branch scan, not by this guard.
    ".gitignore",
    # The app boots with this theme; it must stay trackable, which is what `!.streamlit/` plus
    # `!.streamlit/config.toml` in .gitignore exist for.
    ".streamlit/config.toml",
    "LICENSE",
    "config/aoi/mexico-city.geojson",
    "data/processed/mexico-city/nisar_grid.parquet",
)


def _git(
    *args: str, stdin: str | None = None, ok: tuple[int, ...] = (0, 1)
) -> subprocess.CompletedProcess[str]:
    """Run git in the repo root; ``check-ignore`` legitimately exits 1 when nothing matches."""
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in ok:
        raise AssertionError(
            f"git {' '.join(args)} failed with {proc.returncode}: {proc.stderr.strip()}"
        )
    return proc


def _ignored(paths: tuple[str, ...] | list[str], *, no_index: bool = False) -> set[str]:
    """Return the subset of ``paths`` matched by an ignore rule (paths need not exist)."""
    if not paths:
        return set()
    args = ["check-ignore", "--stdin", "-z"]
    if no_index:
        args.append("--no-index")
    # 128 is tolerated here only so the symlinked-directory case below can fall back cleanly.
    proc = _git(*args, stdin="\0".join(paths) + "\0", ok=(0, 1, 128))
    if proc.returncode == 128:
        # One bad pathspec aborts the whole batch (e.g. a `.venv` that is itself a symlink:
        # "fatal: pathspec ... is beyond a symbolic link"). Retry singly so one odd entry cannot
        # turn a clean policy verdict into a crash.
        return _ignored_one_by_one(paths, no_index=no_index)
    return {p for p in proc.stdout.split("\0") if p}


def _ignored_one_by_one(
    paths: tuple[str, ...] | list[str], *, no_index: bool
) -> set[str]:
    """Per-path fallback for :func:`_ignored`; git cannot walk through a symlinked directory."""
    matched: set[str] = set()
    for path in paths:
        args = ["check-ignore"]
        if no_index:
            args.append("--no-index")
        proc = _git(*args, "--", path, ok=(0, 1, 128))
        if proc.returncode == 0:
            matched.add(path)
        elif proc.returncode == 128 and "beyond a symbolic link" in proc.stderr:
            # git refuses to even resolve this path, so no `git add` can stage it: protected.
            matched.add(path)
        elif proc.returncode == 128:
            raise AssertionError(f"git check-ignore failed on {path!r}: {proc.stderr.strip()}")
    return matched


def test_secrets_and_heavy_data_are_never_committable() -> None:
    """Every path in NEVER_COMMITTABLE matches an ignore rule, so `git add -A` cannot stage it."""
    ignored = _ignored(NEVER_COMMITTABLE)
    committable = [p for p in NEVER_COMMITTABLE if p not in ignored]

    assert not committable, (
        "these paths are NOT ignored and `git add -A` would commit them:\n  "
        + "\n  ".join(committable)
        + "\nFix .gitignore (do not weaken the data/raw/ or *.h5/*.zip/*.tif backstops)."
        + (
            ""
            if GITIGNORE.exists()
            else f"\nThere is no .gitignore in this work tree at all ({GITIGNORE} is missing), so "
            "nothing protects these paths; the policy file itself must be committed."
        )
    )


def test_public_repo_files_are_trackable() -> None:
    """No ignore rule may hide CI, licensing, or documented public files."""
    ignored = _ignored(TRACKABLE)
    hidden = [p for p in TRACKABLE if p in ignored]

    assert not hidden, (
        "these files are ignored and would silently never be committed:\n  "
        + "\n  ".join(hidden)
        + "\nA blanket `.*` rule needs a targeted negation (see `!.github/`, `!.gitattributes`)."
    )


def test_no_tracked_file_is_ignored() -> None:
    """`git ls-files` must survive its own ignore rules, or a tracked file is already invisible."""
    tracked = [p for p in _git("ls-files", "-z").stdout.split("\0") if p]
    assert tracked, "git ls-files reported no tracked files; this check would be vacuous"

    # --no-index: plain check-ignore skips indexed paths, which would hide a real regression.
    ignored = _ignored(tracked, no_index=True)
    assert not ignored, (
        "tracked files are also matched by an ignore rule (invisible to `git add -A` after a "
        "re-add, e.g. following a reset):\n  " + "\n  ".join(sorted(ignored))
    )


#: A `config.toml` is trackable because it carries the app's theme, so the secret risk moves from
#: the filename to the content: these key names and value shapes must never appear in it.
#: Deliberately narrow -- `primaryColor = "#06B6D4"` is configuration, not a credential.
SECRET_KEY_RE = re.compile(
    r"(?i)\b(pass(word|wd)?|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"credential|auth[_-]?key|session[_-]?key|cookie)\b"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(EARTHDATA|ASF_[A-Z_]*|Bearer\s|Basic\s|-----BEGIN)"  # known credential shapes
    r"|\b[A-Za-z0-9+/_-]{32,}={0,2}\b"  # opaque blob: a token, not a colour, font or path
)


def test_streamlit_config_carries_no_secrets() -> None:
    """A committed `.streamlit/config.toml` may theme the app; it may not hold a credential."""
    config = ROOT / ".streamlit" / "config.toml"
    tracked = config.relative_to(ROOT).as_posix() in _git("ls-files").stdout.split("\n")
    if not tracked:
        pytest.skip(
            "no tracked .streamlit/config.toml (the theme is optional; secrets.toml is what "
            "must never be tracked, and NEVER_COMMITTABLE checks that path)"
        )

    findings: list[str] = []
    for lineno, line in enumerate(config.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.split("#", 1)[0].strip()
        if not stripped or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if SECRET_KEY_RE.search(key):
            findings.append(f"  line {lineno}: secret-shaped key: {stripped}")
        elif SECRET_VALUE_RE.search(value):
            findings.append(f"  line {lineno}: credential-shaped value under {key.strip()!r}")

    assert not findings, (
        ".streamlit/config.toml is tracked (it themes the app) but looks like it holds a "
        "credential. Streamlit reads secrets from .streamlit/secrets.toml, which is gitignored:"
        "\n" + "\n".join(findings)
    )
