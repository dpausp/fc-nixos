"""Invariants of the sunsetting banner migration in doc/src/25.11.

Every sunsetting banner must link to the stable version via the
``{{ stable_url }}`` placeholder instead of a per-version URL, and the
migrated content must stay intact (e.g. the Permissions section).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "doc/src/25.11"
PLACEHOLDER = "[the stable version]({{ stable_url }})"
BANNER_MARKER = "sunsetting version of the platform documentation"
EXPECTED_BANNER_LINE = (
    "    This is a sunsetting version of the platform documentation. "
    f"Go to {PLACEHOLDER} for optimized support."
)


def md_files():
    return sorted(ROOT.rglob("*.md"))


def banner_lines(path: Path):
    """Yield every banner line in path."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if BANNER_MARKER in line:
            yield line


def test_exactly_49_banner_lines_all_with_placeholder():
    hits = [(p, l) for p in md_files() for l in banner_lines(p)]
    assert len(hits) == 49
    for path, line in hits:
        assert line == EXPECTED_BANNER_LINE, (path, line)
    placeholder_files = {
        p for p in md_files() if PLACEHOLDER in p.read_text(encoding="utf-8")
    }
    assert len(placeholder_files) == 49


def test_no_current_version_links_remain():
    for path in md_files():
        text = path.read_text(encoding="utf-8")
        assert "[the current version]" not in text, path


def test_no_platform_releases_urls_remain():
    for path in md_files():
        text = path.read_text(encoding="utf-8")
        assert "platform-releases" not in text, path


def test_users_index_permissions_section_intact():
    text = (ROOT / "platform/users/index.md").read_text(encoding="utf-8")
    assert "## Permissions { #permissions }" in text
    assert re.search(r"^Permissions control user access", text, re.MULTILINE)
