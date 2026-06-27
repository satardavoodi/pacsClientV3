"""Guard: slow-link progressive grow — Mehr "viewport doesn't grow until complete" (2026-06-27).

Live evidence — Mehr server (5.57.36.202, poor-connection, batch=1 ≈ one image per several
seconds). The FAST viewport bound the first image then did NOT grow as images 2..N downloaded;
it filled only at completion. The per-image progress signal WAS delivered to the viewer — the
``app.log`` showed 17 ``[SIGNAL_FANOUT] source=series_images_progress`` lines, one per image,
with correct ``downloaded/total`` (e.g. study A 1..4/5, study B 1..8/8). The break was the
GROW gate, not the signal.

Root cause: in ``_on_series_images_progress_impl`` the steady-state grow gate only grows when
``delta`` (new images since the last applied grow) reaches ``_progressive_grow_batch_size``
(default ``max(5, env or 10)`` = 10) OR ``downloaded >= total``. Tuned for a FAST link where
images arrive in big bursts; on a slow link ``delta`` rises by 1 per image, so a series with
fewer than ``_progressive_grow_batch_size`` images NEVER reaches the batch boundary and grows
only at completion (and larger series jump in coarse 10-image steps).

Fix (flag ``AIPACS_PROGRESSIVE_SLOW_LINK_GROW`` default-on; ``=0`` → byte-identical legacy
batch-only): a time-based escape grows with whatever HAS arrived once ``idle_ms`` has elapsed
since the last grow AND ``delta >= 1``. On a FAST link the batch fills before ``idle_ms``
elapses, so the batch path fires first and behaviour is unchanged. The grow still flows through
``_progressive_grow_timer`` → ``_flush_progressive_grow_impl`` (interaction-hot defer + the
HOT_FORCE starvation guard), so it never storms the UI during a drag. The pure decision lives in
``_should_slow_link_grow`` so it is unit-testable.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_CANON = (
    Path(__file__).resolve().parents[3]
    / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_progressive.py"
)


def _src() -> str:
    return _CANON.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Functional — the pure decision helper
# --------------------------------------------------------------------------- #

@pytest.fixture()
def _mod():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as mod
    except Exception as exc:  # pragma: no cover - heavy import unavailable
        pytest.skip(f"_vc_progressive import unavailable: {exc}")
    return mod


def test_grows_after_idle_with_new_image(_mod, monkeypatch):
    """The Mehr case: one new image, clock armed, idle window elapsed → grow now."""
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_ENABLED", True)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_IDLE_MS", 1200.0)
    # delta=1 (one new image), last grow at t=1000, now=1000+5000 → 5s idle ≥ 1.2s
    assert _mod._should_slow_link_grow(1, 1000.0, 6000.0) is True
    assert _mod._should_slow_link_grow(3, 1000.0, 2300.0) is True   # exactly at the window


def test_no_grow_before_idle_elapses(_mod, monkeypatch):
    """Within the idle window the batch path still governs — escape stays quiet (no UI churn)."""
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_ENABLED", True)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_IDLE_MS", 1200.0)
    assert _mod._should_slow_link_grow(1, 1000.0, 1100.0) is False   # 100ms < 1.2s
    assert _mod._should_slow_link_grow(5, 1000.0, 2199.0) is False   # 1199ms < 1.2s


def test_no_grow_without_new_image(_mod, monkeypatch):
    """delta < 1 → nothing new to show → never escape (avoids redundant grows)."""
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_ENABLED", True)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_IDLE_MS", 1200.0)
    assert _mod._should_slow_link_grow(0, 1000.0, 9000.0) is False


def test_unarmed_clock_does_not_grow(_mod, monkeypatch):
    """last_grow_ms <= 0 means the clock is not armed yet → no escape."""
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_ENABLED", True)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_IDLE_MS", 1200.0)
    assert _mod._should_slow_link_grow(3, 0.0, 9000.0) is False
    assert _mod._should_slow_link_grow(3, -1.0, 9000.0) is False


def test_kill_switch_disables_escape(_mod, monkeypatch):
    """AIPACS_PROGRESSIVE_SLOW_LINK_GROW=0 → never escapes → byte-identical legacy batch-only."""
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_ENABLED", False)
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_IDLE_MS", 1200.0)
    assert _mod._should_slow_link_grow(3, 1000.0, 99999.0) is False


def test_bad_input_is_safe(_mod, monkeypatch):
    monkeypatch.setattr(_mod, "_PROGRESSIVE_SLOW_LINK_GROW_ENABLED", True)
    assert _mod._should_slow_link_grow(None, 1000.0, 9000.0) is False
    assert _mod._should_slow_link_grow(1, "nan", 9000.0) is False


def test_defaults_are_sane(_mod):
    assert _mod._PROGRESSIVE_SLOW_LINK_GROW_ENABLED is True          # default-on
    assert isinstance(_mod._PROGRESSIVE_SLOW_LINK_GROW_IDLE_MS, float)
    assert 200.0 <= _mod._PROGRESSIVE_SLOW_LINK_GROW_IDLE_MS <= 5000.0


# --------------------------------------------------------------------------- #
# Source-pins — the hot-path wiring (no heavy import needed)
# --------------------------------------------------------------------------- #

def test_flag_and_helper_defined():
    s = _src()
    assert "AIPACS_PROGRESSIVE_SLOW_LINK_GROW" in s
    assert "AIPACS_PROGRESSIVE_SLOW_LINK_GROW_MS" in s
    assert "def _should_slow_link_grow(" in s


def test_flag_defined_after_os_import():
    """Uses _os.getenv → must be defined after `import os as _os` (NameError at load otherwise,
    which py_compile would NOT catch)."""
    s = _src()
    assert s.index("import os as _os") < s.index("_PROGRESSIVE_SLOW_LINK_GROW_ENABLED ="), (
        "_PROGRESSIVE_SLOW_LINK_GROW_ENABLED defined before `import os as _os` → NameError."
    )


def test_grow_gate_consults_escape():
    """The steady-state progressive grow condition must OR-in the slow-link escape alongside
    the batch-size and terminal conditions."""
    s = s_full = _src()
    # locate the steady-state grow gate (the `if viewers_showing:` branch)
    anchor = s.index('reason="progressive_viewer_present"')
    region = s_full[anchor:anchor + 1500]
    assert "_slow_link_escape = _should_slow_link_grow(" in region
    assert "delta >= self._progressive_grow_batch_size" in region
    assert "or _slow_link_escape" in region
    # the legacy conditions must remain (batch boundary + terminal)
    assert "downloaded >= total" in region


def test_clock_armed_at_retroactive_activate():
    """The slow-link clock must be seeded at the first shown image (retroactive activation),
    otherwise the first trickled image waits an extra cycle to grow."""
    s = _src()
    anchor = s.index('"progressive: retroactive activate series=%s avail=%d total=%d"')
    region = s[anchor - 400:anchor]
    assert 'info["last_grow_ms"] = time.monotonic() * 1000.0' in region


def test_progressive_series_dict_inits_last_grow_ms():
    s = _src()
    assert '"last_grow_ms": 0' in s
