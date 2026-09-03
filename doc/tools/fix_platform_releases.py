#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "typer>=0.12",
#   "rich>=13",
#   "structlog>=24",
# ]
# ///
"""
Fix broken platform-releases links in versioned docs.

Replaces links like ``../../platform-releases/fc-26.05-production/webgateway.md#anchor``
with correct relative paths computed from the current doc tree (``doc/src/<version>``).

Features:
- Auto-discovers target files by basename or anchor lookup — no manual table.
- Handles renames (``upgrade.md`` → ``upgrades-whats-new.md``, ``user_profile.md`` → ``user-profile.md``).
- Computes correct relative paths per source file.
- Verifies target file and anchor existence.
- Modes: ``--dry-run`` (list changes), ``--check`` (exit 1 if broken links), ``--apply`` (write files).

Usage:
    uv run doc/tools/fix_platform_releases.py --dry-run
    uv run doc/tools/fix_platform_releases.py --check
    uv run doc/tools/fix_platform_releases.py --apply
    uv run doc/tools/fix_platform_releases.py --root doc/src/26.05 --apply

Reusable on any branch: scans the given ``--root`` directory for ``*.md`` files and
fixes any link containing ``platform-releases``.
"""

from __future__ import annotations

import os
import re
import sys
from logging import DEBUG, INFO, WARNING
from pathlib import Path
from typing import Annotated

import structlog
import typer
from rich.console import Console
from rich.table import Table

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]*platform-releases[^)]*)\)")
ANCHOR_RE = re.compile(r"\{\s*#([A-Za-z0-9_-]+)")

# Sunsetting banner lines link to the stable docs via a template placeholder.
# They are not version-relative links — never rewrite them.
BANNER_MARKER = "sunsetting version of the platform documentation"


def on_banner_line(match: re.Match[str]) -> bool:
    """Return True if the regex match sits on a sunsetting banner line."""
    text = match.string
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    if line_end == -1:
        line_end = len(text)
    return BANNER_MARKER in text[line_start:line_end]


KNOWN_RENAMES: dict[str, str] = {
    "upgrade.md": "upgrades-whats-new.md",
    "user_profile.md": "user-profile.md",
}

app = typer.Typer(no_args_is_help=False)
console = Console()

log = structlog.get_logger()


def configure_logging(verbose: int) -> None:
    level = WARNING
    if verbose >= 2:
        level = DEBUG
    elif verbose >= 1:
        level = INFO

    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if sys.stderr.isatty():
        processors = shared + [structlog.dev.ConsoleRenderer()]
    else:
        processors = shared + [structlog.processors.JSONRenderer()]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def collect_anchors(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        log.warning(
            "collect-anchors-failed",
            _replace_msg="Failed to read {path} for anchor collection",
            path=str(path),
        )
        return set()
    return set(ANCHOR_RE.findall(text))


def build_indexes(
    root: Path,
) -> tuple[dict[str, list[Path]], dict[str, Path], dict[Path, set[str]]]:
    file_index: dict[str, list[Path]] = {}
    anchor_index: dict[str, Path] = {}
    file_anchors: dict[Path, set[str]] = {}
    for md in root.rglob("*.md"):
        file_index.setdefault(md.name, []).append(md)
        anchors = collect_anchors(md)
        file_anchors[md] = anchors
        for a in anchors:
            if a not in anchor_index:
                anchor_index[a] = md
            else:
                log.debug(
                    "duplicate-anchor",
                    _replace_msg="Duplicate anchor {anchor} in {path}, keeping first {first}",
                    anchor=a,
                    path=str(md),
                    first=str(anchor_index[a]),
                )
    return file_index, anchor_index, file_anchors


def resolve_target(
    filename: str,
    anchor: str | None,
    file_index: dict[str, list[Path]],
    anchor_index: dict[str, Path],
) -> Path | None:
    candidates = file_index.get(filename, [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        if anchor and anchor in anchor_index:
            return anchor_index[anchor]
        log.warning(
            "ambiguous-target",
            _replace_msg="Ambiguous target {filename} with {count} candidates, picking first",
            filename=filename,
            count=len(candidates),
            candidates=[str(p) for p in candidates],
        )
        return candidates[0]
    # zero candidates -> try normalized names
    for alt in (filename.replace("_", "-"), filename.replace("-", "_")):
        if alt != filename and alt in file_index:
            cands = file_index[alt]
            if len(cands) == 1:
                return cands[0]
            if (
                anchor
                and anchor in anchor_index
                and anchor_index[anchor] in cands
            ):
                return anchor_index[anchor]
            return cands[0]
    if filename in KNOWN_RENAMES:
        target_name = KNOWN_RENAMES[filename]
        if target_name in file_index:
            cands = file_index[target_name]
            if len(cands) == 1:
                return cands[0]
            if anchor and anchor in anchor_index:
                return anchor_index[anchor]
            return cands[0]
    if anchor and anchor in anchor_index:
        return anchor_index[anchor]
    return None


def compute_new_url(
    source: Path, target: Path, anchor: str | None, old_url: str
) -> str:
    if source.resolve() == target.resolve():
        if anchor:
            return f"#{anchor}"
        # self-link without anchor: an empty href would be invalid — keep
        # the original URL so the link stays untouched
        log.debug(
            "self-link-kept",
            _replace_msg="Self-link without anchor kept as-is in {source}",
            source=str(source),
            old_url=old_url,
        )
        return old_url
    rel = os.path.relpath(target, start=source.parent)
    rel = rel.replace(os.sep, "/")
    if anchor:
        return f"{rel}#{anchor}"
    return rel


def process_file(
    source: Path,
    root: Path,
    file_index: dict[str, list[Path]],
    anchor_index: dict[str, Path],
    file_anchors: dict[Path, set[str]],
) -> tuple[int, list[tuple[str, str, str]], list[str], str]:
    """Return (fix_count, changes, errors, new_text).

    changes is a list of (old_url, new_url, target_name).
    Sunsetting banner lines are skipped entirely.
    """
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        log.exception("file-read-failed", path=str(source))
        raise

    changes: list[tuple[str, str, str]] = []
    errors: list[str] = []
    new_text = text

    for m in LINK_RE.finditer(text):
        if on_banner_line(m):
            log.info(
                "banner-skipped",
                _replace_msg="Skipping sunsetting banner link in {source}: {url}",
                source=str(source),
                url=m.group(2),
            )
            continue
        url = m.group(2)
        # split anchor
        if "#" in url:
            path_part, anchor = url.split("#", 1)
            anchor = anchor.strip()
            # anchor may contain spaces? unlikely
            # need to handle quotes? strip
            anchor = anchor.split()[0] if anchor else None
        else:
            path_part = url
            anchor = None
        # filename is basename of path_part
        # path_part may be like ../../platform-releases/fc-26.05-production/webgateway.md
        # extract after last slash
        filename = Path(path_part).name
        if not filename:
            errors.append(f"empty filename in {url}")
            continue
        # Some links may have query? ignore
        filename = filename.split("?")[0]

        target = resolve_target(filename, anchor, file_index, anchor_index)
        if target is None:
            msg = f"unresolved target {filename} anchor={anchor} in {source}"
            log.warning(
                "unresolved-target",
                _replace_msg="Unresolved {filename} anchor {anchor} in {source}",
                filename=filename,
                anchor=anchor,
                source=str(source),
                url=url,
            )
            errors.append(msg)
            continue
        # verify anchor exists
        if anchor:
            anchors = file_anchors.get(target, set())
            if anchor not in anchors:
                msg = f"missing anchor #{anchor} in {target} (source {source} url {url})"
                log.warning(
                    "missing-anchor",
                    _replace_msg="Missing anchor {anchor} in {target} from {source}",
                    anchor=anchor,
                    target=str(target),
                    source=str(source),
                    url=url,
                )
                errors.append(msg)
                # still fix path, anchor verification is separate
        new_url = compute_new_url(source, target, anchor, url)
        old_url = url
        if new_url == old_url:
            continue
        # we will replace later via string substitution; but need to ensure correct relative path already?
        # For now collect change
        changes.append((old_url, new_url, target.name))

    # Apply replacements
    if changes:
        # Build new_text by replacing each old_url occurrence that was matched
        # Use re.sub with function to avoid double-replace issues
        def repl(m: re.Match[str]) -> str:
            if on_banner_line(m):
                return m.group(0)
            label = m.group(1)
            url = m.group(2)
            # find corresponding change for this url instance
            # need to recompute per occurrence because same old_url may appear multiple times with different targets? but unlikely
            # We'll recompute target per occurrence
            if "#" in url:
                path_part, anchor2 = url.split("#", 1)
                anchor2 = anchor2.split()[0] if anchor2 else None
            else:
                path_part = url
                anchor2 = None
            filename2 = Path(path_part).name.split("?")[0]
            target2 = resolve_target(
                filename2, anchor2, file_index, anchor_index
            )
            if target2 is None:
                return m.group(0)
            new_url2 = compute_new_url(source, target2, anchor2, url)
            if new_url2 == url:
                return m.group(0)
            return f"[{label}]({new_url2})"

        new_text = LINK_RE.sub(repl, text)

    return len(changes), changes, errors, new_text


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    root: Annotated[
        Path,
        typer.Option(
            "--root", "-r", help="Root of versioned docs (e.g. doc/src/26.05)"
        ),
    ] = Path("doc/src/26.05"),
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="List changes without writing (default if no --apply)",
        ),
    ] = False,
    check: Annotated[
        bool,
        typer.Option(
            "--check", help="Exit non-zero if broken links or changes needed"
        ),
    ] = False,
    apply: Annotated[
        bool, typer.Option("--apply", help="Write fixes to files")
    ] = False,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose", "-v", count=True, help="Increase verbosity (-v, -vv)"
        ),
    ] = 0,
) -> None:
    """
    Fix broken platform-releases links in versioned docs.

    Scans markdown files under --root, replaces any link containing
    'platform-releases' with a correct relative path to the current doc tree,
    verifying target file and anchor existence.
    """
    if ctx.invoked_subcommand is not None:
        return

    configure_logging(verbose)

    # Resolve root
    original_root = root
    if not root.exists():
        for cand in [
            Path("doc/src/26.05"),
            Path("doc/src"),
            Path("doc"),
            Path.cwd(),
        ]:
            if (
                cand.exists()
                and any(cand.rglob("*.md"))
                and root == Path("doc/src/26.05")
                and cand != root
            ):
                log.warning(
                    "root-fallback",
                    _replace_msg="Root {original} not found, falling back to {fallback}",
                    original=str(original_root),
                    fallback=str(cand),
                )
                root = cand
                break
        if not root.exists():
            log.error(
                "root-not-found",
                _replace_msg="Root {root} not found",
                root=str(root),
            )
            raise typer.Exit(2)

    root = root.resolve()
    log.info(
        "scan-started",
        _replace_msg="Scanning {root} for markdown files",
        root=str(root),
    )

    file_index, anchor_index, file_anchors = build_indexes(root)
    log.info(
        "index-built",
        _replace_msg="Indexed {file_count} markdown files with {anchor_count} anchors",
        file_count=sum(len(v) for v in file_index.values()),
        anchor_count=len(anchor_index),
    )
    log.debug(
        "index-detail",
        file_index={k: [str(p) for p in v] for k, v in file_index.items()},
    )

    md_files = list(root.rglob("*.md"))
    # Also include files outside root? We scan only root, but for checking broken links in root only.
    # The spec says fix links on any branch, root is versioned dir.

    total_changes = 0
    total_errors = 0
    total_files_changed = 0
    changes_by_file: list[tuple[Path, list[tuple[str, str, str]]]] = []
    errors_all: list[str] = []

    for md in sorted(md_files):
        count, changes, errors, new_text = process_file(
            md, root, file_index, anchor_index, file_anchors
        )
        if errors:
            total_errors += len(errors)
            errors_all.extend(errors)
            for e in errors:
                log.warning(
                    "link-error",
                    _replace_msg="Link error: {error}",
                    error=e,
                    file=str(md),
                )
        if count:
            changes_by_file.append((md, changes))
            total_changes += count
            total_files_changed += 1
            for old, new, target_name in changes:
                log.info(
                    "link-fix",
                    _replace_msg="Fix {file}: {old} -> {new}",
                    file=str(md.relative_to(root)),
                    old=old,
                    new=new,
                    target=target_name,
                )
            if apply:
                try:
                    md.write_text(new_text, encoding="utf-8")
                except OSError:
                    log.exception("file-write-failed", path=str(md))
                    raise
                log.info(
                    "file-written",
                    _replace_msg="Wrote {file} with {count} fixes",
                    file=str(md),
                    count=count,
                )
            else:
                log.debug("dry-run-skip-write", path=str(md), count=count)

    # Summary table
    if changes_by_file:
        table = Table(title="Platform-releases link fixes")
        table.add_column("File", style="cyan")
        table.add_column("Old URL", style="red")
        table.add_column("New URL", style="green")
        for f, chs in changes_by_file:
            for old, new, _ in chs:
                table.add_row(str(f.relative_to(root)), old, new)
        console.print(table)
    else:
        log.info(
            "no-changes",
            _replace_msg="No platform-releases links needing fixes in {root}",
            root=str(root),
        )

    if errors_all:
        log.warning(
            "anchor-warnings",
            _replace_msg="Found {count} anchor/target warnings",
            count=len(errors_all),
            warnings=errors_all,
        )

    log.info(
        "summary",
        _replace_msg="Files changed: {changed}, total links fixed: {links}, warnings: {warnings}",
        changed=total_files_changed,
        links=total_changes,
        warnings=total_errors,
    )

    log.info(
        "scan-completed",
        _replace_msg="Completed {file_count} files: {changed} files changed, {links} links fixed, {warnings} warnings",
        file_count=len(md_files),
        changed=total_files_changed,
        links=total_changes,
        warnings=total_errors,
    )

    # Exit codes
    if check:
        if total_changes > 0 or total_errors > 0:
            log.warning(
                "check-failed",
                _replace_msg="Check failed: {changed} files need fixes, {warnings} warnings",
                changed=total_files_changed,
                warnings=total_errors,
            )
            raise typer.Exit(1)
        else:
            log.info(
                "check-passed",
                _replace_msg="Check passed: no broken links",
                root=str(root),
            )
            raise typer.Exit(0)

    if not apply and total_changes > 0 and not dry_run and not check:
        # default to dry-run behavior: indicate changes would be made, but don't fail
        pass

    raise typer.Exit(0)


if __name__ == "__main__":
    app()
