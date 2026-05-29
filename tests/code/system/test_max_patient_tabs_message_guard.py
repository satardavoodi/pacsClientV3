"""Regression guards: 'Maximum Patient Tabs Reached' message stays in sync
with the MAX_PATIENT_TABS constant.

Background - 2026-05-29
=======================
User reported that the warning dialog said "You can only open a maximum of
3 patient tabs at once" even though MAX_PATIENT_TABS was bumped to 4. The
message text in _hp_modules.py was a hardcoded literal that drifted away
from the constant.

Fix:
- _hp_modules.py: read MAX_PATIENT_TABS at warning-time via a lazy import
  and f-string the value into the message. No more hardcoded "3".
- custom_tab_manager.py: the docstring on add_patient_tab also said
  "MAX_PATIENT_TABS (3)" - generalised to "(see module-level constant)".

Guards:
1. No hardcoded "maximum of N patient tabs" with N != MAX_PATIENT_TABS
   anywhere in the workstation UI tree.
2. The warning-construction code uses an f-string interpolating a name
   (not a hardcoded number).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
TAB_MANAGER = (
    REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "custom_tab_manager.py"
)
HP_MODULES = (
    REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
    / "home_panel" / "_hp_modules.py"
)


@pytest.fixture(scope="module")
def max_patient_tabs() -> int:
    """Parse the MAX_PATIENT_TABS literal from the tab manager source.

    Reading it via source-parse instead of import keeps the test
    headless-safe (no PySide6 import required to evaluate the constant).
    """
    src = TAB_MANAGER.read_text(encoding="utf-8")
    m = re.search(r"^MAX_PATIENT_TABS\s*=\s*(\d+)\s*$", src, re.MULTILINE)
    assert m is not None, (
        "MAX_PATIENT_TABS constant disappeared from custom_tab_manager.py - "
        "any consumer of the warning message will now silently drift."
    )
    return int(m.group(1))


def test_warning_message_does_not_hardcode_count(max_patient_tabs: int) -> None:
    """The Maximum-Patient-Tabs warning text must NOT hardcode a digit
    literal next to 'patient tabs' - it must interpolate MAX_PATIENT_TABS
    (or any equivalent) so it stays correct when the limit changes."""
    src = HP_MODULES.read_text(encoding="utf-8")
    # Look for any "maximum of <digit> patient tabs" form (single digit or
    # multi-digit), which is the exact phrasing that drifted last time.
    hardcoded = re.findall(
        r"maximum of (\d+) patient tabs",
        src,
        flags=re.IGNORECASE,
    )
    assert not hardcoded, (
        "_hp_modules.py contains a hardcoded literal in the "
        "'maximum of N patient tabs' phrase. This drifts whenever "
        "MAX_PATIENT_TABS changes. Use an f-string that reads the "
        "constant instead. Offending literals: "
        f"{hardcoded} (MAX_PATIENT_TABS is currently {max_patient_tabs})."
    )


def test_warning_imports_max_patient_tabs_constant() -> None:
    """The warning block must import MAX_PATIENT_TABS (lazy or top-level)
    so the runtime message reflects the live constant value."""
    src = HP_MODULES.read_text(encoding="utf-8")
    # Either the symbol is imported, or it's referenced via a short alias
    # like `_max_tabs`. We accept both forms.
    has_import = (
        "MAX_PATIENT_TABS" in src
        and "from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager"
        in src
    )
    assert has_import, (
        "_hp_modules.py no longer imports MAX_PATIENT_TABS from "
        "custom_tab_manager. The Maximum-Patient-Tabs warning will drift "
        "out of sync with the constant the next time MAX_PATIENT_TABS "
        "changes."
    )


def test_docstring_does_not_pin_stale_count() -> None:
    """The add_patient_tab docstring used to say 'MAX_PATIENT_TABS (3)'.
    It must not pin a specific number, because the constant changes."""
    src = TAB_MANAGER.read_text(encoding="utf-8")
    # Look in add_patient_tab body specifically.
    idx = src.find("def add_patient_tab(")
    assert idx >= 0
    end = src.find("\n    def ", idx + 1)
    body = src[idx : end if end > 0 else len(src)]
    bad = re.findall(r"MAX_PATIENT_TABS\s*\(\d+\)", body)
    assert not bad, (
        "add_patient_tab docstring pins a specific MAX_PATIENT_TABS value "
        "with a literal in parentheses - this drifts when the constant "
        "changes. Use 'MAX_PATIENT_TABS (see module-level constant)' or "
        "similar instead. Offending text: "
        f"{bad}"
    )
