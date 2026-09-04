"""Generate the changelog archive ``src/changes/index.md``.

Input is the release tree ``src/changes/<year>/rNNN.md``. Three
facts are parsed per page:

* the ``Publish Date: 'YYYY-MM-DD'`` frontmatter line -- the
  release date;
* the ``## NixOS NN.NN platform`` section headings -- the platform
  versions carried, deduplicated, newest first;
* markers: ``(cancelled)`` in the H1 or the body phrase ``never
  rolled out`` -- special releases that legitimately lack date
  and/or versions.

Output is twofold:

* ``changes/index.md`` -- one table (``Release | Date | Versions``)
  per year, years descending, releases descending within a year.
  Marker rows render the marker as an italic annotation instead of
  versions (a cancelled release has no date either and shows an
  em dash). The file is COMMITTED (generated, never hand-edited);
  regenerate via ``python -m tools.gen_changes_index`` after adding
  release pages.

* the archive link ``*All releases: [changelog archive](../index.md).*``
  directly under the H1 of the CURRENT latest release page (maximum
  year and number), idempotently. A former latest page keeps
  whatever it carries -- nothing is ever removed or moved.

A non-marker page lacking a date or platform versions is a broken
release page: the run fails LOUDLY (exit 1) naming every broken
page instead of silently rendering gaps.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger()

# doc/ root -- defaults resolve relative to the module, not the cwd,
# so the tool works from any directory (sister tools do the same).
DOC_ROOT = Path(__file__).resolve().parents[1]

# Pinned line shapes of a release page.
DATE_RE = re.compile(r"^Publish Date: '(\d{4}-\d{2}-\d{2})'$", re.MULTILINE)
SECTION_RE = re.compile(r"^## NixOS (\d{2}\.\d{2}) platform$", re.MULTILINE)
H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)

# changes/<year>/rNNN.md: the stem names the release number, the
# parent directory the year.
STEM_RE = re.compile(r"r(\d+)")
YEAR_RE = re.compile(r"\d{4}")

CANCELLED = "cancelled"
NEVER_ROLLED_OUT = "never rolled out"

ARCHIVE_LINE = "*All releases: [changelog archive](../index.md).*"

INTRO = (
    "All user-visible changes made to our infrastructure in reverse "
    "chronological order: the newest release comes first within each "
    "year, the newest year at the top. The current release is also "
    "linked directly in the sidebar navigation."
)

TABLE_HEADER = "| Release | Date | Versions |"
TABLE_SEPARATOR = "| ------- | ---- | -------- |"


@dataclass(frozen=True, slots=True)
class Release:
    """One release page below ``changes/``.

    ``year`` is the parent directory name and ``num`` the release
    number from the ``rNNN`` stem. ``date`` is the ``Publish Date``
    frontmatter value, ``versions`` the unique ``## NixOS NN.NN
    platform`` headings (descending). ``marker`` names a special
    release (``cancelled`` / ``never rolled out``) or ``None``;
    marker pages legitimately lack date and/or versions.
    """

    year: str
    num: int
    date: str | None
    versions: list[str]
    marker: str | None

    @property
    def label(self) -> str:
        return f"{self.year}_{self.num:03d}"


def parse_release_page(path: Path) -> Release:
    """Parse one release page into a :class:`Release`."""
    text = path.read_text()
    stem = STEM_RE.fullmatch(path.stem)
    if stem is None:
        msg = f"not a release page stem: {path.stem!r}"
        raise ValueError(msg)
    h1 = H1_RE.search(text)
    marker = None
    if h1 is not None and "(cancelled)" in h1.group(1):
        marker = CANCELLED
    elif NEVER_ROLLED_OUT in text:
        marker = NEVER_ROLLED_OUT
    date = DATE_RE.search(text)
    return Release(
        year=path.parent.name,
        num=int(stem.group(1)),
        date=date.group(1) if date else None,
        versions=sorted(set(SECTION_RE.findall(text)), reverse=True),
        marker=marker,
    )


def scan_releases(changes: Path) -> list[tuple[Path, Release]]:
    """All release pages below *changes*, latest first.

    Sorted by year and release number, both descending -- position
    ``0`` IS the current latest release. ``index.md`` pages (the
    archive itself and per-year nav stubs) are skipped silently;
    files that are neither ``rNNN`` stems inside a year directory
    nor index pages are warned about and skipped -- the archive
    only ever lists release pages.
    """
    releases: list[tuple[Path, Release]] = []
    for page in sorted(changes.rglob("*.md")):
        if page.name == "index.md":
            continue
        rel = page.relative_to(changes)
        if STEM_RE.fullmatch(page.stem) is None or not YEAR_RE.fullmatch(
            page.parent.name
        ):
            log.warning(
                "page-skipped",
                page=rel.as_posix(),
                reason="not a release page (<year>/rNNN.md)",
            )
            continue
        releases.append((page, parse_release_page(page)))
    releases.sort(key=lambda pair: (pair[1].year, pair[1].num), reverse=True)
    return releases


def invalid_pages(
    changes: Path, releases: Sequence[tuple[Path, Release]]
) -> list[str]:
    """Changes/-relative paths of non-marker pages lacking date or versions.

    Marker pages are exempt by design; everything else must carry a
    ``Publish Date`` frontmatter line and at least one ``## NixOS
    NN.NN platform`` section.
    """
    return [
        page.relative_to(changes).as_posix()
        for page, rel in releases
        if rel.marker is None and (rel.date is None or not rel.versions)
    ]


def _row(page: Path, rel: Release) -> str:
    """One table row: link, date (em dash when absent), versions."""
    target = page.relative_to(page.parents[1]).as_posix()
    if rel.marker is not None:
        versions = f"*({rel.marker})*"
    else:
        versions = ", ".join(rel.versions)
    return f"| [{rel.label}]({target}) | {rel.date or '—'} | {versions} |"


def _render_tables(releases: Sequence[tuple[Path, Release]]) -> str:
    """The complete ``index.md`` for an already-scanned release list."""
    lines = ["# Changelog { #changelog }", "", INTRO]
    years = sorted({rel.year for _, rel in releases}, reverse=True)
    for year in years:
        lines += ["", f"## {year}", "", TABLE_HEADER, TABLE_SEPARATOR]
        lines += [_row(page, rel) for page, rel in releases if rel.year == year]
    return "\n".join(lines) + "\n"


def render_index(src: Path) -> str:
    """Render the complete ``changes/index.md`` of the *src* tree."""
    return _render_tables(scan_releases(src / "changes"))


def place_archive_link(page: Path) -> bool:
    """Idempotently place :data:`ARCHIVE_LINE` under the H1 of *page*.

    Returns ``True`` when the page was rewritten, ``False`` when the
    line was already in place. Never removes or moves anything --
    former latest pages keep their lines untouched.
    """
    lines = page.read_text().splitlines()
    h1 = next(
        (i for i, line in enumerate(lines) if line.startswith("# ")), None
    )
    if h1 is None:
        msg = f"no H1 heading in {page}"
        raise ValueError(msg)
    if (
        h1 + 2 < len(lines)
        and lines[h1 + 1] == ""
        and lines[h1 + 2] == ARCHIVE_LINE
    ):
        return False
    lines[h1 + 1 : h1 + 1] = ["", ARCHIVE_LINE]
    page.write_text("\n".join(lines) + "\n")
    return True


# Minimum log level for the CLI (matches logging.INFO; the int
# literal keeps the tool free of an ``import logging`` per the
# project's structlog-only rule).
_INFO_LEVEL = 20


def _configure_logging() -> None:
    """Render human-readable diagnostics to stderr.

    stderr, resolved at call time: ``make`` surfaces a failing
    prerequisite's stderr verbatim while stdout stays clean, and
    pytest's capsys captures it (capture_logs around ``main()``
    does NOT work: this reconfiguration clobbers it).
    """
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_INFO_LEVEL),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: ``python -m tools.gen_changes_index``.

    Exit codes: ``0`` (index and archive link up to date), ``1``
    (missing ``changes/`` tree, no release pages at all, or
    non-marker release pages lacking date or versions).
    """
    _configure_logging()
    parser = argparse.ArgumentParser(
        prog="gen_changes_index",
        description=(
            "Generate src/changes/index.md (per-year release tables) and "
            "place the archive link under the H1 of the latest release "
            "page."
        ),
    )
    parser.add_argument("--src", type=Path, default=DOC_ROOT / "src")
    args = parser.parse_args(argv)

    changes = args.src / "changes"
    if not changes.is_dir():
        log.error("changes-missing", changes=str(changes))
        return 1

    releases = scan_releases(changes)
    if not releases:
        log.error(
            "releases-missing",
            changes=str(changes),
            hint="no <year>/rNNN.md release pages found",
        )
        return 1

    broken = invalid_pages(changes, releases)
    if broken:
        log.error(
            "release-pages-invalid",
            pages=broken,
            count=len(broken),
            hint=(
                "non-marker release pages need a Publish Date frontmatter "
                "line and a '## NixOS NN.NN platform' section"
            ),
        )
        return 1

    index = changes / "index.md"
    rendered = _render_tables(releases)
    if index.exists() and index.read_text() == rendered:
        log.info("index-unchanged", index=str(index), releases=len(releases))
    else:
        index.write_text(rendered)
        log.info("index-written", index=str(index), releases=len(releases))

    latest_page, latest = releases[0]
    linked = place_archive_link(latest_page)
    log.info(
        "archive-link-placed" if linked else "archive-link-present",
        page=latest_page.relative_to(changes).as_posix(),
        release=latest.label,
    )

    log.info(
        "gen-changes-index-done",
        years=len({rel.year for _, rel in releases}),
        releases=len(releases),
        latest=latest.label,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
