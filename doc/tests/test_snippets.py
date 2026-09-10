"""Executable spec for the shared snippet library (``doc/snippets/``).

``pymdownx.snippets`` includes (``--8<-- "file.md"`` with
``base_path = "snippets"``, ``check_paths = true`` -- see
``zensical.toml``) splice shared fragments into pages at build time.
This suite pins three properties:

- every scissors include in ANY rendered page under ``src/`` --
  including the generated snapshot trees, which the same build renders
  -- resolves to an existing file under ``snippets/``. ``check_paths``
  fails COLD builds on missing targets, but warm builds serve
  snippet-including pages from the render cache (warm-cache caveat in
  ``zensical.toml``), so a typo'd include never surfaces locally;
  this test catches it in every cache state;
- scissors lines are well-formed per the project convention: quoted
  targets only (unquoted bare filenames are valid pymdownx.snippets
  syntax but fragile -- a missing closing quote would silently include
  the wrong file);
- no orphaned fragments: every file under ``snippets/`` is referenced
  by at least one include. Unreferenced fragments are dead content and
  rot invisibly -- nothing renders them, nothing tests them.

Includes inside fenced code blocks are documentation examples, not
includes: the extension itself skips fenced regions, and so does this
suite.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.helpers import DOC_ROOT as DOC

SRC = DOC / "src"
SNIPPETS = DOC / "snippets"

# --8<-- "file.md" -- possibly several quoted targets per line.
SCISSORS_RE = re.compile(r"^\s*--8<--\s+(.+?)\s*$")
TARGET_RE = re.compile(r'"([^"]+)"')

# Fence tracking mirrors pymdownx.snippets: lines inside ``` / ~~~ fences
# are never treated as includes.
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def includes() -> Iterator[tuple[Path, int, str | None]]:
    """Yield ``(page, line_no, target)`` for every scissors include.

    ``target`` is ``None`` for malformed lines (no quoted target);
    the snippet extension's own nesting/escaping rules are not modelled
    beyond that.
    """
    for page in sorted(SRC.rglob("*.md")):
        fenced = False
        for line_no, line in enumerate(page.read_text().splitlines(), 1):
            if FENCE_RE.match(line):
                fenced = not fenced
                continue
            if fenced:
                continue
            m = SCISSORS_RE.match(line)
            if not m:
                continue
            targets = TARGET_RE.findall(m.group(1))
            if not targets:
                yield page, line_no, None
            for target in targets:
                yield page, line_no, target


def test_every_scissors_line_is_well_formed() -> None:
    malformed = [
        f"{page.relative_to(DOC)}:{line_no}"
        for page, line_no, target in includes()
        if target is None
    ]
    assert not malformed, (
        "scissors lines without a quoted target (convention: "
        '--8<-- "file.md"):\n' + "\n".join(malformed)
    )


def test_every_include_target_exists() -> None:
    missing = [
        f"{page.relative_to(DOC)}:{line_no} -> {target}"
        for page, line_no, target in includes()
        if target is not None and not (SNIPPETS / target).is_file()
    ]
    assert not missing, (
        "scissors includes pointing at missing snippet files "
        "(warm builds would NOT catch this -- see zensical.toml):\n"
        + "\n".join(missing)
    )


def test_no_orphaned_snippets() -> None:
    if not SNIPPETS.is_dir():
        pytest.skip("snippet library does not exist (no snippets in use)")
    referenced = {target for _, _, target in includes() if target is not None}
    orphans = sorted(
        str(path.relative_to(SNIPPETS))
        for path in SNIPPETS.rglob("*")
        if path.is_file() and str(path.relative_to(SNIPPETS)) not in referenced
    )
    assert not orphans, (
        "snippet files no page includes (dead content):\n" + "\n".join(orphans)
    )
