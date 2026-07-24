"""Guard: a PREVIOUS-EXAM (secondary-study) OFFSET-KEY series grows to its full on-disk
count after a mid-download drop — WITHOUT a layout switch (patients 51234 / 51249, 2026-07-20).

Field report (other-PC logs, both patients): a cross-PatientID previous exam (a 3-image series,
offset display key like ``2000001`` / ``1000001``) was dragged onto a viewport while its download
was still in flight. The viewport painted ``slices=1``; the download then completed to disk=3, but
the series stayed stuck at 1 until the user changed LAYOUT, which re-loaded it fresh from the
now-complete disk and showed all 3. Root cause: the displayed-to-disk grow backstop
(``_maybe_grow_displayed_to_disk``, "Stage A1") is the ONLY thing that grows a secondary /
previous-exam series whose remaining images arrive with no bridged progress event — but it runs
only inside ``_dl_watchdog``, which was armed ONLY from the awaiting/spinner path and self-stops
when nothing is awaiting AND nothing is behind. A drop that awaited, showed its first image, then
cleared its awaiting flag can hit a stop-check tick where disk == displayed and no ``.part`` is
momentarily present -> the watchdog stops and the later images never trigger A1.

Two things are pinned here:
  1. BEHAVIORAL — ``_maybe_grow_displayed_to_disk`` resolves an OFFSET display key to the previous
     exam's OWN folder (not the primary study's non-existent ``<primary>/2000001``), counts its
     disk files, and grows via the smooth ``bridge.grow`` append once the folder has SETTLED. This
     is the coverage the older shipped build lacked, and the existing ``test_grow_displayed_to_disk``
     only source-pins it.
  2. WIRING — both progressive-activation paths now (re)arm the watchdog when a series enters
     progressive mode incomplete (``total > avail``), gated by ``AIPACS_PROGRESSIVE_ARMS_WATCHDOG``
     (default-on), so A1 is guaranteed to sweep a progressively-loaded-but-behind viewport.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _prog_src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_progressive.py"
    ).read_text(encoding="utf-8")


# ── 1. WIRING (source-pins; no Qt import needed) ──────────────────────────────

def test_progressive_arms_watchdog_flag_default_on():
    src = _prog_src()
    # default-on with a kill switch, following the house pattern
    assert (
        'os.getenv("AIPACS_PROGRESSIVE_ARMS_WATCHDOG", "1") or "1"' in src
        or "getenv(\"AIPACS_PROGRESSIVE_ARMS_WATCHDOG\", \"1\") or \"1\"" in src
    )
    assert "_PROGRESSIVE_ARMS_WATCHDOG = (" in src


def test_both_progressive_paths_arm_the_watchdog_when_incomplete():
    """The two controller-level progressive activations must (re)arm the self-stopping
    watchdog so A1 can grow a behind-displayed viewport regardless of await timing."""
    src = _prog_src()
    for meth in ("_apply_progressive_to_target_viewer", "_activate_progressive_mode_on_viewers"):
        i = src.find("def " + meth)
        assert i != -1, f"{meth} not found"
        body = src[i:i + 6000]
        assert "_PROGRESSIVE_ARMS_WATCHDOG" in body, f"{meth} does not gate on the flag"
        assert "self._ensure_dl_watchdog()" in body, f"{meth} does not arm the watchdog"
        # only when the series is known-incomplete (never spin the watchdog for a complete load)
        assert (
            "> int(avail" in body or "> int(avail or 0)" in body
        ), f"{meth} arms unconditionally (must require total > avail)"


# ── 2. BEHAVIORAL (drives the real _maybe_grow_displayed_to_disk) ─────────────

def _load_progressive_module():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as MX
        from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_load as LOAD
    except Exception as exc:  # pragma: no cover - offscreen-only import
        pytest.skip(f"viewer modules unavailable offscreen: {exc}")
    return MX, LOAD


def _make_controller(MX, LOAD, *, prev_study, primary_study, server_info, nodes):
    """A minimal ViewerController stub that binds the REAL A1 grow, the REAL displayed-series
    reader, and the REAL canonical-identity resolver — nothing about identity is faked."""
    class _Ctl(MX._VCProgressiveMixin, LOAD._VCLoadMixin):
        pass

    ctl = object.__new__(_Ctl)  # bypass heavy __init__
    import logging
    ctl.logger = logging.getLogger("test.a1grow")
    ctl._tab_active = True
    ctl.lst_nodes_viewer = nodes
    ctl.parent_widget = SimpleNamespace(
        _server_series_info=server_info,
        study_uid=primary_study,
    )
    ctl._update_calls = []
    ctl._change_series_calls = []
    ctl._update_vtk_slice_range = lambda *a, **k: ctl._update_calls.append((a, k))
    ctl.change_series_on_viewer = lambda *a, **k: ctl._change_series_calls.append((a, k))
    return ctl


def _make_vtk_w(*, display_key, displayed, grow_returns):
    grow_calls = []

    def _grow(**kw):
        grow_calls.append(kw)
        return grow_returns

    vtk_w = SimpleNamespace(
        _qt_bridge=SimpleNamespace(metadata={"series": {"series_number": str(display_key)}}),
        _qt_bridge_active=True,
        image_viewer=SimpleNamespace(grow=_grow),
        slider=None,
    )
    vtk_w.get_count_of_slices = lambda: displayed
    vtk_w._grow_calls = grow_calls
    return vtk_w


def _write_dcms(folder: Path, n: int, *, part: bool = False):
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (folder / f"Instance_{i:04d}.dcm").write_bytes(b"\x00" * 8)
    if part:
        (folder / "Instance_partial.part").write_bytes(b"\x00" * 8)


def test_a1_grows_previous_exam_offset_key_from_its_own_folder(tmp_path, monkeypatch):
    """The heart of it: displayed offset key 2000001 shows 1 slice; the previous exam's OWN
    folder <prev_study>/1 holds 3 complete files; A1 must resolve the offset key to THAT folder
    (never <primary>/2000001, which does not exist) and grow to 3 via the smooth append — after
    the folder has SETTLED (2 ticks), never before."""
    MX, LOAD = _load_progressive_module()

    PRIMARY = "1.3.12.2.1107.5.2.46.174759.30000026071904352507100000085"
    PREV = "1.2.156.112536.1.2126.114102085041190255.15594304880.14"
    DISPLAY_KEY = "2000001"  # slot-2 offset key for the previous exam, orig series 1

    # _server_series_info is STRING-keyed for offset keys (str(orig_int + offset)); the entry
    # carries the real study_uid + _orig_series_number — exactly as _rebuild_multistudy_series_index
    # builds it.
    server_info = {
        DISPLAY_KEY: {
            "study_uid": PREV,
            "_orig_series_number": "1",
            "series_uid": "1.2.156.previx.series1",
            "image_count": 3,
        },
    }

    # The previous exam's OWN on-disk folder = SOURCE_PATH/<prev_study>/<orig_series 1>, complete.
    _write_dcms(tmp_path / PREV / "1", 3)
    # Deliberately do NOT create <primary>/2000001 — if A1 grew, it can only have resolved the
    # offset key to the previous exam's folder.
    assert not (tmp_path / PRIMARY / DISPLAY_KEY).exists()

    monkeypatch.setattr("PacsClient.utils.config.SOURCE_PATH", str(tmp_path), raising=False)

    vtk_w = _make_vtk_w(display_key=DISPLAY_KEY, displayed=1, grow_returns=3)
    node = SimpleNamespace(vtk_widget=vtk_w, slider=None)
    ctl = _make_controller(
        MX, LOAD, prev_study=PREV, primary_study=PRIMARY,
        server_info=server_info, nodes=[node],
    )

    # Sanity: the displayed-series reader returns the OFFSET key, and the resolver maps it to the
    # previous exam's own study + orig series (this is the real end-to-end identity path).
    assert ctl._viewport_displayed_series_number(vtk_w) == DISPLAY_KEY
    assert ctl._resolve_canonical_series_identity(DISPLAY_KEY)[:2] == (PREV, "1")

    # Tick 1: folder is complete but its count has not yet been seen twice -> NOT settled -> keep
    # watching, do NOT grow (this is what stops mid-download flicker from churning).
    r1 = ctl._maybe_grow_displayed_to_disk(vtk_w)
    assert r1 is True
    assert vtk_w._grow_calls == [], "A1 grew before the folder settled (first sighting)"

    # Tick 2: count stable across two ticks, no .part -> SETTLED -> grow to the full on-disk set
    # via the smooth append (bridge.grow), NOT a destructive change_series rebuild.
    ctl._maybe_grow_displayed_to_disk(vtk_w)
    assert vtk_w._grow_calls == [{"force_flush": True}], "A1 did not smooth-grow the offset key"
    assert ctl._change_series_calls == [], "smooth append should not fall back to change_series"
    # the slider/slice-range was updated to the grown count (3)
    assert ctl._update_calls, "slice range was not updated after grow"
    assert ctl._update_calls[-1][0][2] == 3


def test_a1_does_not_grow_while_download_in_flight(tmp_path, monkeypatch):
    """A ``.part`` in the folder means the DM is still writing it — A1 must NOT rebuild/grow
    (never settle a mid-download folder), even across repeated ticks."""
    MX, LOAD = _load_progressive_module()

    PRIMARY = "1.3.12.2.1107.5.2.46.174759.PRIMARY"
    PREV = "1.2.156.PREVEXAM"
    DISPLAY_KEY = "1000001"

    server_info = {
        DISPLAY_KEY: {"study_uid": PREV, "_orig_series_number": "1", "series_uid": "u"},
    }
    # 3 files present but a .part is still being written -> in-flight, not settled.
    _write_dcms(tmp_path / PREV / "1", 3, part=True)
    monkeypatch.setattr("PacsClient.utils.config.SOURCE_PATH", str(tmp_path), raising=False)

    vtk_w = _make_vtk_w(display_key=DISPLAY_KEY, displayed=1, grow_returns=3)
    node = SimpleNamespace(vtk_widget=vtk_w, slider=None)
    ctl = _make_controller(
        MX, LOAD, prev_study=PREV, primary_study=PRIMARY,
        server_info=server_info, nodes=[node],
    )

    for _ in range(4):  # several ticks — must never grow while a .part is present
        ctl._maybe_grow_displayed_to_disk(vtk_w)
    assert vtk_w._grow_calls == [], "A1 grew a folder that was still downloading (.part present)"
