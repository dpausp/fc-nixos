"""Tests for the fix_platform_releases docs tool.

Focus: the sunsetting banner guard — lines carrying the banner are never
mangled, and self-links never collapse into an empty href.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import structlog

TOOL_PATH = Path(__file__).resolve().parent / "fix_platform_releases.py"

BANNER_LINE = (
    "    This is a sunsetting version of the platform documentation. "
    "Go to [the current version]"
    "(../../platform-releases/fc-26.05-production/web.md) "
    "for optimized support.\n"
)

PLAIN_LINK_LINE = (
    "See [webgateway](../../platform-releases/fc-26.05-production/web.md).\n"
)


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "fix_platform_releases", TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


fpr = load_tool()


def make_tree(tmp_path: Path, link_line: str) -> tuple[Path, Path]:
    """Create root/web.md and root/page.md, page containing link_line."""
    web = tmp_path / "web.md"
    web.write_text("# Web { #web }\n", encoding="utf-8")
    page = tmp_path / "page.md"
    page.write_text(link_line + "\n# Page\n", encoding="utf-8")
    return page, web


def run_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL_PATH), *args],
        capture_output=True,
        text=True,
    )


class TestComputeNewUrl:
    def test_self_link_without_anchor_keeps_old_url(self, tmp_path):
        page = tmp_path / "page.md"
        page.write_text("# Page\n", encoding="utf-8")
        old_url = "../../platform-releases/fc-26.05-production/page.md"
        assert fpr.compute_new_url(page, page, None, old_url) == old_url

    def test_self_link_with_anchor_returns_anchor_ref(self, tmp_path):
        page = tmp_path / "page.md"
        page.write_text("# Page { #top }\n", encoding="utf-8")
        assert fpr.compute_new_url(page, page, "top", "old.md#top") == "#top"

    def test_cross_file_relative_path(self, tmp_path):
        src_dir = tmp_path / "a"
        src_dir.mkdir()
        source = src_dir / "source.md"
        source.write_text("# S\n", encoding="utf-8")
        target = tmp_path / "b" / "target.md"
        target.parent.mkdir()
        target.write_text("# T { #sec }\n", encoding="utf-8")
        assert (
            fpr.compute_new_url(source, target, None, "old.md")
            == "../b/target.md"
        )
        assert (
            fpr.compute_new_url(source, target, "sec", "old.md#sec")
            == "../b/target.md#sec"
        )


class TestBannerGuard:
    def test_banner_link_untouched_and_logged(self, tmp_path):
        page, _ = make_tree(tmp_path, BANNER_LINE)
        original = page.read_text(encoding="utf-8")
        with structlog.testing.capture_logs() as logs:
            count, changes, errors, new_text = fpr.process_file(
                page, tmp_path, *fpr.build_indexes(tmp_path)
            )
        assert (count, changes, errors) == (0, [], [])
        assert new_text == original
        skips = [e for e in logs if e.get("event") == "banner-skipped"]
        assert len(skips) == 1
        assert skips[0]["url"].endswith("web.md")

    def test_plain_platform_releases_link_still_fixed(self, tmp_path):
        page, _ = make_tree(tmp_path, PLAIN_LINK_LINE)
        count, changes, errors, new_text = fpr.process_file(
            page, tmp_path, *fpr.build_indexes(tmp_path)
        )
        assert count == 1
        assert errors == []
        assert changes[0][0].endswith("fc-26.05-production/web.md")
        assert changes[0][1] == "web.md"
        assert "[webgateway](web.md)" in new_text

    def test_self_link_without_anchor_not_rewritten_to_empty(self, tmp_path):
        page = tmp_path / "page.md"
        old = "[self](../../platform-releases/fc-26.05-production/page.md)"
        page.write_text(old + "\n# Page\n", encoding="utf-8")
        count, changes, errors, new_text = fpr.process_file(
            page, tmp_path, *fpr.build_indexes(tmp_path)
        )
        assert (count, changes, errors) == (0, [], [])
        assert new_text.splitlines()[0] == old


class TestCheckEndToEnd:
    def test_check_passes_and_apply_keeps_banner(self, tmp_path):
        page, _ = make_tree(tmp_path, BANNER_LINE)
        before = page.read_text(encoding="utf-8")
        checked = run_tool("--root", str(tmp_path), "--check", "-v")
        assert checked.returncode == 0, checked.stdout
        assert "banner-skipped" in checked.stdout
        assert "check-passed" in checked.stdout
        assert page.read_text(encoding="utf-8") == before
        applied = run_tool("--root", str(tmp_path), "--apply", "-v")
        assert applied.returncode == 0, applied.stdout
        assert "banner-skipped" in applied.stdout
        assert page.read_text(encoding="utf-8") == before

    def test_check_fails_on_broken_non_banner_link(self, tmp_path):
        page = tmp_path / "page.md"
        page.write_text(
            "[x](../../platform-releases/fc-26.05-production/missing.md)\n",
            encoding="utf-8",
        )
        result = run_tool("--root", str(tmp_path), "--check")
        assert result.returncode == 1
        assert "unresolved-target" in result.stdout
