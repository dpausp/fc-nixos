"""Scaffold and sunset component pages in ``doc/``.

Two modes over the SAME two artifacts -- the markdown page under
``src/components/`` and the hand-maintained explicit navigation in
``zensical.toml``:

* GENERATE (:func:`scaffold`): create ``src/components/<name>.md`` as
  a house-convention stub (H1 with the ``{ #nixos-<name> }`` anchor,
  TODO intro, ``nix`` fence with the role option, ``sudo fc-manage
  switch`` hint) and insert the nav entry alphabetically into the
  chosen ``Components`` group.

* SUNSET (:func:`sunset`): replace a component page with a generic
  tombstone (H1 + anchor stay verbatim, warning admonition, generic
  switcher hint) and mark the nav label ``<Label> (removed)`` in
  place -- position and sorting untouched. The page file STAYS (no
  frontmatter, no ``search: exclude``): the payload scan of
  :mod:`tools.gen_platform_versions` is file-existence based, so the
  version switcher keeps offering the snapshots' real documentation
  for the tombstoned page.

The nav edit is TEXTUAL TOML SURGERY on line level -- never a tomllib
roundtrip, which would destroy the file's formatting and comments.
The parser below understands exactly the two line shapes the
Components section uses: plain entry lines and the compressed group
ending ``{ "Last" = "..." } ] },``; anything else inside the section
fails loudly instead of guessing. Every rewritten file is verified by
parsing it with tomllib before it is written back.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import structlog
import tomllib

from tools.gen_platform_versions import DOC_ROOT

log = structlog.get_logger()

# The two files every mode touches, relative to the doc root.
NAV_NAME = "zensical.toml"
COMPONENTS_SUBTREE = Path("src") / "components"
GERMAN_SUBTREE = Path("src") / "de" / "components"

# The nav section component pages live in, and the slug they must
# match (file name, anchor tail, and role option all derive from it).
NAV_SECTION = "Components"
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


# Line shapes of the Components nav section (house layout: section at
# indent 2, groups at 6, entries at 10 -- indents are captured, never
# assumed). A group's LAST entry line is compressed: it carries the
# group's closing ``] },`` on the same line.
SECTION_LINE_RE = re.compile(rf'^\s*\{{ "{NAV_SECTION}" = \[$')
GROUP_LINE_RE = re.compile(r'^\s*\{ "(?P<name>[^"]+)" = \[$')
CLOSE_LINE_RE = re.compile(r"^(?P<indent>\s*)\] \},?$")
ENTRY_LINE_RE = re.compile(
    r'^(?P<indent>\s*)\{ "(?P<label>[^"]+)" = "(?P<page>[^"]+)" \},?$'
)
COMPRESSED_ENTRY_RE = re.compile(
    r'^(?P<indent>\s*)\{ "(?P<label>[^"]+)" = '
    r'"(?P<page>[^"]+)" \} \] \},?$'
)

# Double-sunset marker: the admonition title only a tombstone carries.
TOMBSTONE_MARKER = '!!! warning "Component removed"'

STUB_TEMPLATE = """\
# {title} {{ #nixos-{name} }}

TODO: Describe what this component provides and how it is used.

## Configuration

TODO: Describe the role options and local configuration files.

Enable the role in the NixOS configuration:

```nix
flyingcircus.roles.{name}.enable = true;
```

To activate config changes, run `sudo fc-manage switch`.
"""

TOMBSTONE_TEMPLATE = """\
{h1}

{marker}

    This component is no longer part of the current platform version.

    Use the version switcher in the sidebar to open this page in an
    older platform version, which may still include the component.
"""


class ScaffoldError(Exception):
    """Any generate/sunset input problem (unknown group, existing page,
    missing nav entry, ...). :func:`main` maps it to exit code 1."""


@dataclass(frozen=True, slots=True)
class NavEntry:
    """One ``{ "Label" = "components/x.md" }`` line of the nav."""

    label: str
    page: str
    lineno: int  # index into the split lines of zensical.toml
    indent: str
    compressed: bool  # line carries the group's closing ``] },``


def parse_nav_groups(lines: list[str]) -> dict[str, list[NavEntry]]:
    """Ordered ``group name -> entries`` of the Components section.

    Raises :class:`ScaffoldError` when the section is missing or a
    line inside it matches no known shape -- the textual surgery only
    ever runs on layouts it fully understands.
    """
    section_start = next(
        (i for i, line in enumerate(lines) if SECTION_LINE_RE.match(line)),
        None,
    )
    if section_start is None:
        msg = (
            f'no {{ "{NAV_SECTION}" = [ section found in {NAV_NAME} -- '
            "component pages are navigated through it"
        )
        raise ScaffoldError(msg)
    section_indent = len(lines[section_start]) - len(
        lines[section_start].lstrip()
    )

    groups: dict[str, list[NavEntry]] = {}
    current: list[NavEntry] | None = None
    for i in range(section_start + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        close = CLOSE_LINE_RE.match(line)
        if close and len(close.group("indent")) <= section_indent:
            break  # the Components section ended
        group = GROUP_LINE_RE.match(line)
        if group:
            current = groups.setdefault(group["name"], [])
            continue
        if close:  # standalone group close (uncompressed layout)
            current = None
            continue
        entry = COMPRESSED_ENTRY_RE.match(line) or ENTRY_LINE_RE.match(line)
        if entry and current is not None:
            current.append(
                NavEntry(
                    label=entry["label"],
                    page=entry["page"],
                    lineno=i,
                    indent=entry["indent"],
                    compressed=COMPRESSED_ENTRY_RE.match(line) is not None,
                )
            )
            if COMPRESSED_ENTRY_RE.match(line):
                current = None  # the compressed line closed the group
            continue
        if current is None:
            continue  # between groups (e.g. a plain string entry)
        msg = (
            f"unsupported line {i + 1} inside the {NAV_SECTION} nav "
            f"section: {line.strip()!r} -- the scaffold tool only "
            "edits layouts it fully understands"
        )
        raise ScaffoldError(msg)
    return groups


def read_nav(doc_root: Path) -> list[str]:
    """``zensical.toml`` as lines; missing/unreadable fails loudly."""
    path = doc_root / NAV_NAME
    try:
        text = path.read_text()
    except OSError as exc:
        msg = f"cannot read {path}: {exc}"
        raise ScaffoldError(msg) from exc
    return text.splitlines()


def write_nav(doc_root: Path, lines: list[str]) -> None:
    """Write lines back, verifying the result still parses as TOML."""
    text = "\n".join(lines) + "\n"
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        msg = f"refusing to write a {NAV_NAME} that no longer parses: {exc}"
        raise ScaffoldError(msg) from exc
    (doc_root / NAV_NAME).write_text(text)


def insert_nav_entry(
    lines: list[str], name: str, title: str, group: str
) -> None:
    """Insert ``{ "Title" = "components/<name>.md" }`` alphabetically.

    Sorting is case-insensitive over the nav labels. The new line
    copies the sibling entries' indentation; an append past the last
    entry splits the compressed ``} ] },`` group ending (or lands
    before a standalone close line in uncompressed layouts).
    """
    groups = parse_nav_groups(lines)
    if group not in groups:
        known = ", ".join(groups)
        msg = (
            f"unknown {NAV_SECTION} nav group {group!r} -- available "
            f"groups: {known}"
        )
        raise ScaffoldError(msg)
    page_rel = f"components/{name}.md"
    for entries in groups.values():
        clash = next((e for e in entries if e.page == page_rel), None)
        if clash is not None:
            msg = (
                f"nav entry for {page_rel} exists already "
                f"(label {clash.label!r}) -- remove it or pick another "
                "name"
            )
            raise ScaffoldError(msg)

    entries = groups[group]
    if not entries:
        msg = (
            f"group {group!r} has no entries -- its indentation is "
            "unknown; add the first entry by hand"
        )
        raise ScaffoldError(msg)
    indent = entries[0].indent

    position = next(
        (
            j
            for j, entry in enumerate(entries)
            if title.casefold() < entry.label.casefold()
        ),
        len(entries),
    )
    new_line = f'{indent}{{ "{title}" = "{page_rel}" }},'
    if position < len(entries):
        lines.insert(entries[position].lineno, new_line)
    else:
        last = entries[-1]
        if last.compressed:
            old = lines[last.lineno]
            closing = old[old.index("} ] ") + 2 :]  # `` ] },`` tail
            lines[last.lineno] = (
                f'{last.indent}{{ "{last.label}" = "{last.page}" }},'
            )
            lines.insert(
                last.lineno + 1,
                f'{last.indent}{{ "{title}" = "{page_rel}" }} {closing}',
            )
        else:
            close = next(
                (
                    i
                    for i in range(last.lineno + 1, len(lines))
                    if CLOSE_LINE_RE.match(lines[i])
                ),
                None,
            )
            if close is None:
                msg = (
                    f"group {group!r} neither ends compressed nor with "
                    "a close line -- unsupported layout"
                )
                raise ScaffoldError(msg)
            lines.insert(close, new_line)


def mark_nav_removed(lines: list[str], name: str) -> str:
    """Suffix the label of ``components/<name>.md``'s nav entry.

    Position, sorting, and the page path stay untouched -- only the
    label text gains `` (removed)``. Returns the old label.
    """
    page_rel = f"components/{name}.md"
    entry = next(
        (
            e
            for entries in parse_nav_groups(lines).values()
            for e in entries
            if e.page == page_rel
        ),
        None,
    )
    if entry is None:
        msg = (
            f"no nav entry for {page_rel} in the {NAV_SECTION} section "
            f"of {NAV_NAME} -- sunset keeps the page navigated; add "
            "the entry first"
        )
        raise ScaffoldError(msg)
    if entry.label.endswith(" (removed)"):
        msg = f"nav label {entry.label!r} carries the marker already"
        raise ScaffoldError(msg)
    old_pair = f'{{ "{entry.label}" = "{page_rel}" }}'
    new_pair = f'{{ "{entry.label} (removed)" = "{page_rel}" }}'
    lines[entry.lineno] = lines[entry.lineno].replace(old_pair, new_pair, 1)
    return entry.label


def h1_of(page: Path) -> str:
    """The page's first ``# `` heading line (kept verbatim by sunset)."""
    for line in page.read_text().splitlines():
        if line.startswith("# "):
            return line
    msg = f"no H1 heading found in {page}"
    raise ScaffoldError(msg)


def scaffold(
    name: str,
    title: str | None,
    group: str,
    doc_root: Path = DOC_ROOT,
) -> Path:
    """Generate the component page stub and its nav entry (see module
    docstring). Returns the created page path."""
    if not SLUG_RE.fullmatch(name):
        msg = f"invalid component slug {name!r}: must match {SLUG_RE.pattern}"
        raise ScaffoldError(msg)
    resolved_title = title or name.capitalize()

    page_rel = COMPONENTS_SUBTREE / f"{name}.md"
    page = doc_root / page_rel
    if page.exists():
        msg = (
            f"page exists already: {page_rel.as_posix()} -- sunset or "
            "edit it instead"
        )
        raise ScaffoldError(msg)

    lines = read_nav(doc_root)
    insert_nav_entry(lines, name, resolved_title, group)

    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(STUB_TEMPLATE.format(name=name, title=resolved_title))
    write_nav(doc_root, lines)
    log.info(
        "page-scaffolded",
        name=name,
        title=resolved_title,
        page=page_rel.as_posix(),
        group=group,
    )
    log.info(
        "nav-entry-inserted",
        group=group,
        label=resolved_title,
        page=page_rel.as_posix(),
    )
    return page


def sunset(name: str, doc_root: Path = DOC_ROOT) -> Path:
    """Replace the component page with a tombstone and mark the nav
    label ``... (removed)`` in place (see module docstring). Returns
    the tombstoned page path."""
    page_rel = COMPONENTS_SUBTREE / f"{name}.md"
    page = doc_root / page_rel
    twin_rel = GERMAN_SUBTREE / f"{name}.md"
    if (doc_root / twin_rel).is_file():
        msg = (
            f"German twin exists: {twin_rel.as_posix()} -- decide its "
            "fate (tombstone or remove it) by hand first; sunset "
            "refuses to leave a stale translation behind"
        )
        raise ScaffoldError(msg)
    if not page.is_file():
        msg = f"no such component page: {page_rel.as_posix()}"
        raise ScaffoldError(msg)

    text = page.read_text()
    if TOMBSTONE_MARKER in text:
        msg = f"{page_rel.as_posix()} is a tombstone already"
        raise ScaffoldError(msg)
    h1 = h1_of(page)

    lines = read_nav(doc_root)
    old_label = mark_nav_removed(lines, name)

    page.write_text(TOMBSTONE_TEMPLATE.format(h1=h1, marker=TOMBSTONE_MARKER))
    write_nav(doc_root, lines)
    log.info("page-sunset", name=name, page=page_rel.as_posix(), h1=h1)
    log.info(
        "nav-marked-removed",
        label=f"{old_label} (removed)",
        page=page_rel.as_posix(),
    )
    return page


# Minimum log level for the CLI (matches logging.INFO; the int literal keeps
# the tool free of an ``import logging`` per the project's structlog-only rule).
_INFO_LEVEL = 20


def _configure_logging() -> None:
    """Render human-readable diagnostics to stderr (see gen_platform_versions)."""
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
    """CLI entry: ``python -m tools.scaffold_page <name> [--sunset]``.

    Exit codes: ``0`` (page generated or sunsets), ``1`` (input
    problem, with the reason on stderr), ``2`` (usage error, via
    argparse).
    """
    _configure_logging()
    parser = argparse.ArgumentParser(
        prog="scaffold_page",
        description=(
            "Generate a component page stub (src/components/<name>.md + "
            "nav entry) or, with --sunset, replace a page with a "
            "tombstone and mark its nav label (removed)."
        ),
    )
    parser.add_argument(
        "name", help="component slug (file name under src/components/)"
    )
    parser.add_argument(
        "--sunset",
        action="store_true",
        help="tombstone NAME's page instead of generating one",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="nav label and H1 title (default: the capitalized slug)",
    )
    parser.add_argument(
        "--group",
        default=None,
        help="Components nav group the new entry is sorted into",
    )
    parser.add_argument(
        "--doc-root", type=Path, default=DOC_ROOT, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)

    if args.sunset:
        if args.group or args.title:
            parser.error("--sunset takes no --group/--title")
    elif not args.group:
        parser.error(
            f"--group is required for generate mode (a {NAV_SECTION} nav group)"
        )

    try:
        if args.sunset:
            sunset(args.name, doc_root=args.doc_root)
        else:
            scaffold(
                args.name,
                title=args.title,
                group=args.group,
                doc_root=args.doc_root,
            )
    except ScaffoldError as exc:
        log.error("scaffold-page-failed", name=args.name, error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
