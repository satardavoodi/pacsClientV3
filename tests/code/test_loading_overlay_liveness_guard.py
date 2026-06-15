"""Guard the home loading-overlay fade liveness fix (pc2 native_fault.log, 2026-06-15).

native_fault.log on a second workstation captured access violations in the
patient-open path:

    _hp_layout.py  _hide_loading_overlay  ←  hide_loading  ←  _on_patient_double_clicked_async

Root cause: `_hide_loading_overlay` / `_show_loading_overlay` built a
QPropertyAnimation on the overlay's graphics effect WITHOUT checking the overlay's
C++ object is still alive. During an async-open teardown race (made frequent by the
network failures on that PC) the overlay was already gone, so the opacity access /
animation dereferenced a deleted QObject -> access violation, which the main.py
notify() override then escalates into a hard process crash.

Fix: match the already-hardened pattern in components/loading_overlay.py — verify
liveness (`shiboken6.isValid`) and wrap the fade in try/except so a dying overlay is
just hidden, never raised into the open path. Static source guard (constructing the
home panel pulls heavy deps).
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_HP_LAYOUT = _REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "_hp_layout.py"
_LOADING_OVERLAY = _REPO / "PacsClient" / "components" / "loading_overlay.py"


def _method_src(tree: ast.Module, name: str, source: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    return ""


def test_hide_loading_overlay_is_liveness_guarded():
    src = _HP_LAYOUT.read_text(encoding="utf-8")
    body = _method_src(ast.parse(src), "_hide_loading_overlay", src)
    assert body, "_hp_layout must define _hide_loading_overlay"
    assert "shiboken6.isValid" in body, (
        "_hide_loading_overlay must verify the overlay is alive before animating it"
    )
    assert "QPropertyAnimation" in body and "except Exception" in body, (
        "the fade must be wrapped so a dead overlay/effect can't raise into the open path"
    )
    # The safety net is to still hide the overlay rather than crash.
    assert body.count("overlay.hide()") >= 2, (
        "a failed/guarded fade must fall back to hiding the overlay"
    )


def test_show_loading_overlay_fade_is_guarded():
    src = _HP_LAYOUT.read_text(encoding="utf-8")
    body = _method_src(ast.parse(src), "_show_loading_overlay", src)
    assert body, "_hp_layout must define _show_loading_overlay"
    # The cosmetic fade-in must not be able to raise (overlay is already shown).
    assert "QPropertyAnimation" in body and "except Exception" in body, (
        "the show fade-in must be wrapped in try/except"
    )


def test_components_loading_overlay_still_hardened():
    """Regression anchor: the original hardened site must keep its liveness guard."""
    src = _LOADING_OVERLAY.read_text(encoding="utf-8")
    assert "shiboken6.isValid" in src, (
        "components/loading_overlay.py must keep its overlay liveness guard"
    )
