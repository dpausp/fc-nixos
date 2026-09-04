"""Source-level contract for the silent "General" nav section.

Pins the three cooperating artifacts:
- ``zensical.toml``: General is the first nav group (Changelog latest
  link, Security, Support)
- ``theme/partials/nav-item.html``: the hunk adds
  ``md-nav__item--silent`` for the level-1 group titled "General" (and
  the inert navigation.indexes-era exemption is gone)
- ``_static/flyingcircus.css``: the rule hides the silent section's
  title labels on desktop only
"""

import re
from pathlib import Path

import tomllib
from pytest_readable import readable

DOC = Path(__file__).resolve().parents[1]

SECURITY_PAGES = [
    "security/data-protection.md",
    "security/disaster-recovery.md",
    "security/network.md",
    "security/policy.md",
    "security/software-vulnerabilities.md",
]


@readable(
    intention="General ist erste Nav-Gruppe mit Changelog-Latest-Link, Security, Support",
    steps=[
        "zensical.toml parsen",
        "Struktur der ersten zwei Top-Level-Entries pruefen",
        "Changelog-Target existiert als Datei",
    ],
    criteria=[
        "nav[0] = General mit Kindern Changelog/Security/Support",
        "Changelog ist Single-Pair auf changes/<jahr>/rNNN.md",
        "nav[1] = Infrastructure",
    ],
)
def test_nav_general_shape() -> None:
    data = tomllib.loads((DOC / "zensical.toml").read_text())
    nav = data["project"]["nav"]
    general = nav[0]
    assert list(general) == ["General"]
    children = general["General"]
    labels = [list(child) for child in children]
    assert labels == [["Changelog"], ["Security"], ["Support"]]
    target = children[0]["Changelog"]
    assert re.fullmatch(r"changes/\d{4}/r\d{3}\.md", target)
    assert (DOC / "src" / target).is_file()
    assert children[1] == {"Security": SECURITY_PAGES}
    assert children[2] == {"Support": "support/overview.md"}
    assert list(nav[1]) == ["Infrastructure"]


@readable(
    intention="nav-item.html traegt den Silent-Hunk und nicht mehr die inerte Altausnahme",
    steps=["Partial lesen", "Hunk-Strings und entfernte Altausnahme pruefen"],
    criteria=[
        "md-nav__item--silent und title == 'General' vorhanden",
        "index.url[:8]-Exemption entfernt",
    ],
)
def test_nav_item_hunk_present() -> None:
    text = (DOC / "theme" / "partials" / "nav-item.html").read_text()
    assert "md-nav__item--silent" in text
    assert 'nav_item.title == "General"' in text
    assert "index.url[:8]" not in text


@readable(
    intention="flyingcircus.css versteckt die Titel-Labels der Silent-Sektion nur auf Desktop",
    steps=["CSS lesen", "Selektor und Media-Query pruefen"],
    criteria=[
        "Regel fuer .md-nav__item--silent vorhanden",
        "auf min-width 76.25em beschraenkt (Mobile-Drawer intakt)",
    ],
)
def test_css_rule_present() -> None:
    css = (DOC / "src" / "_static" / "flyingcircus.css").read_text()
    assert ".md-nav__item--silent > label.md-nav__link" in css
    assert (
        '.md-nav__item--silent > nav[data-md-level="1"] > label.md-nav__title'
        in css
    )
    assert "min-width: 76.25em" in css
