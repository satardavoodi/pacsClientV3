"""Drift detector for the Download Manager widget V/P/C migration plan.

The migration plan lives in
``modules/download_manager/ui/widget/_dm_contracts.py``:

* :data:`MIXIN_RESPONSIBILITY_MAP` — which mixin moves to which layer.
* :data:`MIXIN_PUBLIC_METHODS` — baseline list of public methods per mixin.

This test ensures the plan and the source code stay in sync. If somebody
adds a new method to ``_dm_workers.py`` without updating
``MIXIN_PUBLIC_METHODS["_dm_workers"]``, this test fails. If somebody
deletes a mixin without updating ``MIXIN_RESPONSIBILITY_MAP``, this test
fails. The intent is **not** to freeze the code; it is to make every
structural change explicit in the migration plan.

Companion to:

* ``test_structured_logging_lint.py`` (R23 — silent-drop hygiene)
* ``test_dm_combo_signal_hygiene.py`` (R22 — combo-signal hygiene)

Same philosophy: codify the architectural contract as a pytest assertion.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Set

import pytest

from modules.download_manager.ui.widget._dm_contracts import (
    ALL_LAYERS,
    DownloadManagerCommandsProtocol,
    DownloadManagerPresenterProtocol,
    DownloadManagerViewProtocol,
    MIXIN_PUBLIC_METHODS,
    MIXIN_RESPONSIBILITY_MAP,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WIDGET_DIR = (
    REPO_ROOT / "modules" / "download_manager" / "ui" / "widget"
)


# ---------------------------------------------------------------------------
# Helpers — extract method names from a mixin source file.
# ---------------------------------------------------------------------------


_DEF_RE = re.compile(r"^    def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)


def _extract_methods(path: Path) -> Set[str]:
    text = path.read_text(encoding="utf-8")
    return set(_DEF_RE.findall(text))


# ---------------------------------------------------------------------------
# Plan integrity tests.
# ---------------------------------------------------------------------------


def test_responsibility_map_uses_known_layers():
    for mixin, (primary, secondary) in MIXIN_RESPONSIBILITY_MAP.items():
        assert primary in ALL_LAYERS, (
            f"{mixin}: primary layer {primary!r} not in {ALL_LAYERS}"
        )
        if secondary is not None:
            assert secondary in ALL_LAYERS, (
                f"{mixin}: secondary layer {secondary!r} not in {ALL_LAYERS}"
            )
            assert secondary != primary, (
                f"{mixin}: secondary layer must differ from primary"
            )


def test_responsibility_map_covers_every_mixin_file_on_disk():
    """Every ``_dm_*.py`` file (except contracts itself) MUST be classified."""
    on_disk = {
        p.stem
        for p in WIDGET_DIR.glob("_dm_*.py")
        if p.stem != "_dm_contracts"
    }
    classified = set(MIXIN_RESPONSIBILITY_MAP.keys())

    missing = on_disk - classified
    extra = classified - on_disk
    if missing or extra:
        msg = ["DM widget V/P/C plan drift:"]
        if missing:
            msg.append(
                "  Mixin files on disk but NOT in MIXIN_RESPONSIBILITY_MAP: "
                + ", ".join(sorted(missing))
            )
        if extra:
            msg.append(
                "  Mixins in MIXIN_RESPONSIBILITY_MAP but NOT on disk: "
                + ", ".join(sorted(extra))
            )
        msg.append(
            "\nFix: update modules/download_manager/ui/widget/_dm_contracts.py "
            "to match the file system before merging."
        )
        pytest.fail("\n".join(msg))


def test_public_methods_baseline_matches_source():
    """Drift detector: declared public methods must match what is on disk."""
    diffs = []
    for mixin, declared in MIXIN_PUBLIC_METHODS.items():
        path = WIDGET_DIR / f"{mixin}.py"
        if not path.exists():
            diffs.append(f"  {mixin}: file missing on disk")
            continue
        live = _extract_methods(path)
        declared_set = set(declared)

        missing_in_source = declared_set - live
        new_in_source = live - declared_set

        if missing_in_source:
            diffs.append(
                f"  {mixin}: methods removed from source but still in plan: "
                + ", ".join(sorted(missing_in_source))
            )
        if new_in_source:
            diffs.append(
                f"  {mixin}: methods added to source but not in plan: "
                + ", ".join(sorted(new_in_source))
            )

    if diffs:
        msg = ["DM widget public-method baseline drift:"]
        msg.extend(diffs)
        msg.append(
            "\nFix: update MIXIN_PUBLIC_METHODS in _dm_contracts.py. "
            "Adding a method = explicit plan update; this is by design."
        )
        pytest.fail("\n".join(msg))


def test_every_classified_mixin_has_methods_baseline():
    """Each classified mixin must also have a public-method baseline."""
    classified = set(MIXIN_RESPONSIBILITY_MAP.keys())
    documented = set(MIXIN_PUBLIC_METHODS.keys())
    missing = classified - documented
    if missing:
        pytest.fail(
            "Classified mixins lacking MIXIN_PUBLIC_METHODS entries: "
            + ", ".join(sorted(missing))
        )


# ---------------------------------------------------------------------------
# Protocol shape tests.
# ---------------------------------------------------------------------------


def test_view_protocol_has_no_state_or_coordinator_words():
    """View Protocol must be widget-only — no state/coordinator vocabulary."""
    forbidden = ("state_store", "coordinator", "intent_coordinator")
    annotations = list(DownloadManagerViewProtocol.__annotations__.keys())
    for name in dir(DownloadManagerViewProtocol):
        if name.startswith("_"):
            continue
        for word in forbidden:
            assert word not in name, (
                f"View Protocol member {name!r} contains forbidden word "
                f"{word!r}; that belongs in Presenter or Commands."
            )
    # Annotation names get the same scrub.
    for name in annotations:
        for word in forbidden:
            assert word not in name


def test_commands_protocol_does_not_expose_observers():
    """Commands Protocol must NOT have ``on_*`` observer-style methods."""
    for name in dir(DownloadManagerCommandsProtocol):
        if name.startswith("_") or name.startswith("__"):
            continue
        assert not name.startswith("on_"), (
            f"Commands Protocol member {name!r} looks like an observer "
            "callback; observers belong in Presenter."
        )


def test_presenter_protocol_has_attach_and_detach():
    """Presenter Protocol must own its lifecycle (attach/detach)."""
    members = set(dir(DownloadManagerPresenterProtocol))
    for required in ("attach", "detach"):
        assert required in members, (
            f"Presenter Protocol missing required lifecycle method {required!r}"
        )


def test_protocols_are_runtime_checkable():
    """Runtime-checkable Protocols allow ``isinstance`` smoke tests later."""
    for proto in (
        DownloadManagerViewProtocol,
        DownloadManagerPresenterProtocol,
        DownloadManagerCommandsProtocol,
    ):
        assert hasattr(proto, "_is_runtime_protocol") or getattr(
            proto, "_is_protocol", False
        ), f"{proto.__name__} must be @runtime_checkable"
