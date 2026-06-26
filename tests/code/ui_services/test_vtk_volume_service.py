"""Guard: S4b-1 — VtkVolumeService (shared VTK Volume Cache owner) + the SHADOW observation.

Design: docs/plans/architecture/S4B_VTK_CACHE_ARCHITECTURE_2026-06-26.md. S4b-1 introduces the
service over the S4a VolumeCache + a default-OFF shadow that detects, at each legacy VTK-volume build
site, when a shared cache would have AVOIDED the rebuild (same (study_uid, series_uid) built again)
or when geometry diverges across builders. No production consumer reads a cached volume yet.

Pure stdlib + threading (no VTK / numpy / Qt) → runs headless in the sandbox.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from PacsClient.utils import vtk_volume_service as svc


@pytest.fixture(autouse=True)
def _clean_singleton():
    svc.reset_vtk_volume_service()
    yield
    svc.reset_vtk_volume_service()


# --------------------------------------------------------------------------- #
# Pure geometry signature
# --------------------------------------------------------------------------- #
def test_signature_stable_and_fp_tolerant():
    a = svc.vtk_geometry_signature((512, 512, 30), (0.5, 0.5, 1.0), (0.0, 0.0, 0.0))
    b = svc.vtk_geometry_signature((512, 512, 30), (0.5000001, 0.5, 1.0), (0.0, 0.0, 0.0))
    assert a == b  # fp noise below 4 digits absorbed → same series compares equal


def test_signature_sensitive_to_real_changes():
    base = svc.vtk_geometry_signature((512, 512, 30), (0.5, 0.5, 1.0), (0, 0, 0))
    assert base != svc.vtk_geometry_signature((512, 512, 31), (0.5, 0.5, 1.0), (0, 0, 0))  # slices
    assert base != svc.vtk_geometry_signature((512, 512, 30), (0.6, 0.5, 1.0), (0, 0, 0))  # spacing
    assert base != svc.vtk_geometry_signature((512, 512, 30), (0.5, 0.5, 1.0), (1, 0, 0))  # origin
    assert base != svc.vtk_geometry_signature((512, 512, 30), (0.5, 0.5, 1.0), (0, 0, 0),
                                              direction=(-1, 0, 0, 0, 1, 0, 0, 0, 1))         # dir


# --------------------------------------------------------------------------- #
# Shadow observe — the core S4b-1 evidence
# --------------------------------------------------------------------------- #
def test_first_build_is_not_a_rebuild():
    s = svc.VtkVolumeService()
    o = s.observe_build("ST1", "SE1", slice_count=30, geometry_signature="g", source="fast")
    assert o.is_rebuild is False and o.geometry_changed is False and o.would_save_rebuild is False


def test_second_build_same_key_is_a_rebuild_cache_would_avoid():
    s = svc.VtkVolumeService()
    s.observe_build("ST1", "SE1", slice_count=30, geometry_signature="g", source="fast")
    o2 = s.observe_build("ST1", "SE1", slice_count=30, geometry_signature="g", source="mpr")
    assert o2.is_rebuild is True
    assert o2.geometry_changed is False
    assert o2.would_save_rebuild is True          # the headline double-build the cache removes
    assert o2.prior_source == "fast"


def test_geometry_divergence_flagged():
    s = svc.VtkVolumeService()
    s.observe_build("ST1", "SE1", slice_count=30, geometry_signature="gA", source="fast")
    o2 = s.observe_build("ST1", "SE1", slice_count=30, geometry_signature="gB", source="orthogonal")
    assert o2.is_rebuild is True
    assert o2.geometry_changed is True
    assert o2.would_save_rebuild is False         # divergent geometry → NOT a safe reuse


def test_distinct_series_do_not_collide():
    s = svc.VtkVolumeService()
    s.observe_build("ST1", "SE1", slice_count=30, geometry_signature="g", source="fast")
    o = s.observe_build("ST1", "SE2", slice_count=40, geometry_signature="g", source="fast")
    assert o.is_rebuild is False                  # different series_uid = different key


# --------------------------------------------------------------------------- #
# The one-call build-site helper — flag gating + logging
# --------------------------------------------------------------------------- #
class _FakeLogger:
    def __init__(self):
        self.infos = []

    def info(self, msg, *args):
        try:
            self.infos.append(msg % args if args else msg)
        except Exception:
            self.infos.append(msg)


def test_observe_helper_is_noop_when_flag_off(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", False)
    lg = _FakeLogger()
    out = svc.observe_vtk_build("ST1", "SE1", slice_count=30, dims=(512, 512, 30),
                                spacing=(0.5, 0.5, 1.0), origin=(0, 0, 0), source="fast", logger=lg)
    assert out is None and lg.infos == []         # default-off → zero work, no log


def test_observe_helper_logs_rebuild_when_flag_on(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", True)
    svc.reset_vtk_volume_service()
    lg = _FakeLogger()
    geom = dict(dims=(512, 512, 30), spacing=(0.5, 0.5, 1.0), origin=(0, 0, 0))
    first = svc.observe_vtk_build("ST1", "SE1", slice_count=30, source="fast", logger=lg, **geom)
    second = svc.observe_vtk_build("ST1", "SE1", slice_count=30, source="mpr", logger=lg, **geom)
    assert first is not None and first.is_rebuild is False
    assert second.is_rebuild is True and second.would_save_rebuild is True
    assert any("[VTK-VOLUME-SHADOW]" in m and "REBUILD" in m for m in lg.infos)
    assert not any("GEOMETRY DIVERGES" in m for m in lg.infos)   # same geometry → no divergence log


def test_observe_helper_logs_geometry_divergence(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", True)
    svc.reset_vtk_volume_service()
    lg = _FakeLogger()
    svc.observe_vtk_build("ST1", "SE1", slice_count=30, dims=(512, 512, 30), spacing=(0.5, 0.5, 1.0),
                          origin=(0, 0, 0), source="fast", logger=lg)
    svc.observe_vtk_build("ST1", "SE1", slice_count=30, dims=(512, 512, 30), spacing=(0.5, 0.5, 1.0),
                          origin=(0, 0, 0), direction=(-1, 0, 0, 0, 1, 0, 0, 0, 1),
                          source="orthogonal", logger=lg)
    assert any("[VTK-VOLUME-SHADOW]" in m and "GEOMETRY DIVERGES" in m for m in lg.infos)


# --------------------------------------------------------------------------- #
# Production surface delegates to the coalescing cache (used by S4b-2/3, not yet wired)
# --------------------------------------------------------------------------- #
def test_get_or_build_coalesces_concurrent_decodes():
    s = svc.VtkVolumeService()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        time.sleep(0.05)            # hold the decode so the others coalesce
        return "VOLUME"

    results, threads = [], []

    def worker():
        results.append(s.get_or_build("mpr", "ST1", "SE1", factory, pin=True))

    for _ in range(6):
        threads.append(threading.Thread(target=worker))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["VOLUME"] * 6
    assert calls["n"] == 1          # built ONCE despite 6 concurrent callers (acceptance 4)


def test_pin_unpin_and_invalidate_delegate(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_CROSS_DOMAIN", False)
    s = svc.VtkVolumeService()
    s.get_or_build("mpr", "ST1", "SE1", lambda: "V", pin=False)
    assert s.peek("mpr", "ST1", "SE1") == "V"
    assert s.pin("mpr", "ST1", "SE1") is True
    assert s.unpin("mpr", "ST1", "SE1") is True
    assert s.invalidate("ST1", "SE1") == 1       # bus: dropped from the 1 domain that held it
    assert s.peek("mpr", "ST1", "SE1") is None


def test_per_domain_caches_isolated_by_default(monkeypatch):
    """SEPARATION RULE: with cross-domain OFF (default), a volume built by one VTK domain is NEVER
    handed to another — the same series builds once PER DOMAIN."""
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", True)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_SHADOW", False)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_CROSS_DOMAIN", False)
    svc.reset_vtk_volume_service()
    calls = {"n": 0}
    b = _counting_builder(calls)
    svc.build_or_get_volume("mpr", "ST1", "SE1", b)        # mpr cache miss → build
    svc.build_or_get_volume("advanced", "ST1", "SE1", b)  # advanced cache miss → SEPARATE build
    assert calls["n"] == 2                                 # isolated: each domain built its own
    # and within a domain it still reuses (no third build)
    svc.build_or_get_volume("mpr", "ST1", "SE1", b)
    assert calls["n"] == 2


def test_invalidation_bus_clears_all_domains(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", True)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_SHADOW", False)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_CROSS_DOMAIN", False)
    svc.reset_vtk_volume_service()
    s = svc.get_vtk_volume_service()
    s.get_or_build("mpr", "ST1", "SE1", lambda: "Vm")
    s.get_or_build("advanced", "ST1", "SE1", lambda: "Va")
    assert s.invalidate("ST1", "SE1") == 2                 # bus dropped BOTH domains' entries
    assert s.peek("mpr", "ST1", "SE1") is None and s.peek("advanced", "ST1", "SE1") is None


def test_cross_domain_shares_when_enabled(monkeypatch):
    """OPT-IN: with cross-domain ON, the VTK domains share ONE cache → built ONCE across them."""
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", True)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_SHADOW", False)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_CROSS_DOMAIN", True)
    svc.reset_vtk_volume_service()
    calls = {"n": 0}
    b = _counting_builder(calls)
    v1 = svc.build_or_get_volume("mpr", "ST1", "SE1", b)
    v2 = svc.build_or_get_volume("advanced", "ST1", "SE1", b)
    assert v1 is v2 and calls["n"] == 1                    # one shared volume across domains


def test_singleton_identity_and_reset():
    a = svc.get_vtk_volume_service()
    assert a is svc.get_vtk_volume_service()
    svc.reset_vtk_volume_service()
    assert svc.get_vtk_volume_service() is not a


# --------------------------------------------------------------------------- #
# S4b-2 routing — build_or_get_mpr_volume (cache reuse / shadow / legacy)
# --------------------------------------------------------------------------- #
class _FakeVol:
    def GetDimensions(self): return (512, 512, 30)
    def GetSpacing(self): return (0.5, 0.5, 1.0)
    def GetOrigin(self): return (0.0, 0.0, 0.0)


def _counting_builder(calls):
    def _b():
        calls["n"] += 1
        return _FakeVol()
    return _b


def test_route_both_flags_off_is_legacy_no_cache(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", False)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_SHADOW", False)
    svc.reset_vtk_volume_service()
    calls = {"n": 0}
    b = _counting_builder(calls)
    v1 = svc.build_or_get_mpr_volume("ST1", "SE1", b)
    v2 = svc.build_or_get_mpr_volume("ST1", "SE1", b)
    assert isinstance(v1, _FakeVol) and isinstance(v2, _FakeVol)
    assert calls["n"] == 2          # no caching → builder runs every time (byte-identical legacy)


def test_route_cache_on_builds_once_and_reuses(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", True)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_SHADOW", False)
    svc.reset_vtk_volume_service()
    calls = {"n": 0}
    b = _counting_builder(calls)
    v1 = svc.build_or_get_mpr_volume("ST1", "SE1", b)
    v2 = svc.build_or_get_mpr_volume("ST1", "SE1", b)
    assert v1 is v2                 # SAME cached volume reused
    assert calls["n"] == 1          # built ONCE — the double-build removed (acceptance 4)


def test_route_shadow_on_builds_every_time_but_observes(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", False)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_SHADOW", True)
    svc.reset_vtk_volume_service()
    calls = {"n": 0}
    b = _counting_builder(calls)
    lg = _FakeLogger()
    svc.build_or_get_mpr_volume("ST1", "SE1", b, logger=lg)
    svc.build_or_get_mpr_volume("ST1", "SE1", b, logger=lg)
    assert calls["n"] == 2          # shadow measures; it does NOT cache (every open still builds)
    assert any("[VTK-VOLUME-SHADOW]" in m and "REBUILD" in m for m in lg.infos)  # 2nd build measured


def test_route_none_build_not_cached(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", True)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_SHADOW", False)
    svc.reset_vtk_volume_service()
    state = {"first": True}

    def flaky():
        if state["first"]:
            state["first"] = False
            return None             # first build fails
        return _FakeVol()           # later build succeeds

    v1 = svc.build_or_get_mpr_volume("ST1", "SE1", flaky)
    v2 = svc.build_or_get_mpr_volume("ST1", "SE1", flaky)
    assert v1 is None               # failed build returns None (legacy 'blocked')
    assert isinstance(v2, _FakeVol)  # NOT cached as None → retried + succeeded


def test_route_missing_series_uid_is_passthrough(monkeypatch):
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_ENABLED", True)
    monkeypatch.setattr(svc, "_VTK_VOLUME_CACHE_SHADOW", False)
    svc.reset_vtk_volume_service()
    calls = {"n": 0}
    b = _counting_builder(calls)
    svc.build_or_get_mpr_volume("ST1", "", b)
    svc.build_or_get_mpr_volume("ST1", "", b)
    assert calls["n"] == 2          # no stable key → never cached, always builds


# --------------------------------------------------------------------------- #
# Identity normalization — one key across builders (MPR 'series_uid' vs
# image_io 'series_instance_uid'), truncation rejected
# --------------------------------------------------------------------------- #
_FULL_UID = "1.2.840.113619.2.55.3.1234567890.123.456"   # a realistic long SeriesInstanceUID


def test_normalize_rejects_truncated_uid():
    assert svc.normalize_series_uid("ABCD1234") == ""           # 8-char log truncation rejected
    assert svc.normalize_series_uid("") == ""
    assert svc.normalize_series_uid(None) == ""
    assert svc.normalize_series_uid(_FULL_UID) == _FULL_UID      # full UID accepted


def test_normalize_picks_first_full_candidate():
    assert svc.normalize_series_uid("short", _FULL_UID) == _FULL_UID   # skip the short, take the full


def test_series_uid_from_meta_tolerates_key_names():
    # image_io stores 'series_instance_uid'; MPR stores 'series_uid' — both resolve to the full UID
    assert svc.series_uid_from_meta({"series_instance_uid": _FULL_UID}) == _FULL_UID
    assert svc.series_uid_from_meta({"series_uid": _FULL_UID}) == _FULL_UID
    assert svc.series_uid_from_meta({"SeriesInstanceUID": _FULL_UID}) == _FULL_UID
    # a truncated 'series_uid' is rejected even if present (safe: no cache key)
    assert svc.series_uid_from_meta({"series_uid": "ABCD1234"}) == ""
    assert svc.series_uid_from_meta(None) == ""


def test_cross_builder_keys_match_when_uid_full():
    """The MPR site (series_uid) and the Advanced site (series_instance_uid) must produce the SAME
    key for the same series so the shadow can compare them and the cache can share."""
    mpr_meta = {"series_uid": _FULL_UID, "study_uid": "ST"}
    adv_meta = {"series_instance_uid": _FULL_UID, "study_instance_uid": "ST"}
    assert svc.series_uid_from_meta(mpr_meta) == svc.series_uid_from_meta(adv_meta) == _FULL_UID


def test_study_uid_from_meta():
    assert svc.study_uid_from_meta({"study_instance_uid": "ST1"}) == "ST1"
    assert svc.study_uid_from_meta({"study_uid": "ST2"}) == "ST2"
    assert svc.study_uid_from_meta({}) == ""                     # empty acceptable (series_uid keys)


# --------------------------------------------------------------------------- #
# Source-pins — default-off + the shadow contract
# --------------------------------------------------------------------------- #
def _src() -> str:
    p = Path(__file__).resolve().parents[3] / "PacsClient" / "utils" / "vtk_volume_service.py"
    return p.read_text(encoding="utf-8")


def test_flag_defaults_off():
    s = _src()
    assert '"AIPACS_VTK_VOLUME_CACHE", "0"' in s, "S4b-1 master flag must DEFAULT OFF (shadow-first)"


def test_observe_helper_gated_and_safe():
    s = _src()
    # the one-call helper must return early when BOTH flags are off, and never raise into the caller
    body = s[s.index("def observe_vtk_build("):]
    assert "if not (_VTK_VOLUME_CACHE_SHADOW or _VTK_VOLUME_CACHE_ENABLED):" in body
    assert "return None" in body
    assert "except Exception:" in body
    assert "[VTK-VOLUME-SHADOW]" in s


def test_keyed_by_stable_identity():
    s = _src()
    assert "make_key(study_uid, series_uid)" in s   # (study_uid, series_uid), not bare series_number


def test_shadow_flag_also_defaults_off():
    s = _src()
    assert '"AIPACS_VTK_VOLUME_CACHE_SHADOW", "0"' in s   # measure-only flag default OFF too


def test_cross_domain_flag_defaults_off_and_per_domain():
    s = _src()
    assert '"AIPACS_VTK_VOLUME_CACHE_CROSS_DOMAIN", "0"' in s   # separation rule: per-domain by default
    assert "def _cache_for(self, domain" in s                  # ONE cache per domain
    # the shared "_shared" bucket is used ONLY when cross-domain reuse is explicitly enabled
    cf = s[s.index("def _cache_for(self, domain"):]
    assert 'if cross_domain_enabled()' in cf[:400] and '"_shared"' in cf[:400]


def test_routing_helper_present_and_pin_deferred():
    s = _src()
    assert "def build_or_get_mpr_volume(" in s
    # S4b-2 does NOT pin (lifetime governed by the caller's ref; pin deferred to S4b-4)
    body = s[s.index("def build_or_get_mpr_volume("):]
    assert "pin=False" in body
