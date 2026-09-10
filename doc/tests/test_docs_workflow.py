"""Pin-format invariants for ``.github/workflows/docs.yml``.

setup-uv publishes immutable exact-version tags only: since v8.0.0 the
action has NO major or minor moving tags (supply-chain policy after the
tj-actions incident), so ``@v10`` would not resolve at all and a ref
without the ``v`` prefix never existed -- the CI died on
``setup-uv@8.0.0`` for exactly that reason. These tests keep the
failure class "unresolvable action ref" out of the workflow file:
setup-uv must be pinned to a full ``vX.Y.Z`` tag, GitHub-owned actions
to a ``v``-prefixed ref (major tag or exact version).
"""

from __future__ import annotations

import re

from tests.helpers import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs.yml"


def refs(action: str, text: str) -> list[str]:
    return re.findall(rf"{re.escape(action)}@(\S+)", text)


def test_workflow_file_exists() -> None:
    assert WORKFLOW.is_file(), f"missing workflow file: {WORKFLOW}"


def test_setup_uv_is_pinned_to_exact_version_tag() -> None:
    """Major tags do not exist for setup-uv -- only full vX.Y.Z resolves."""
    found = refs("astral-sh/setup-uv", WORKFLOW.read_text())
    assert len(found) == 1, f"expected exactly one setup-uv ref, got {found}"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", found[0]), (
        f"setup-uv ref {found[0]!r} is not an exact version tag -- "
        "major/minor tags do not exist since v8.0.0"
    )


def test_github_owned_actions_use_v_prefixed_refs() -> None:
    """actions/* resolve via major tags (or exact versions) -- never bare."""
    text = WORKFLOW.read_text()
    for action in (
        "actions/checkout",
        "actions/setup-python",
        "actions/upload-artifact",
    ):
        found = refs(action, text)
        assert len(found) == 1, (
            f"expected exactly one {action} ref, got {found}"
        )
        assert re.fullmatch(r"v\d+(\.\d+)*", found[0]), (
            f"{action} ref {found[0]!r} is not v-prefixed"
        )
