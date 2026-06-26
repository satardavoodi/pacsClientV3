"""VtkVolumeService — the single owner/front for the shared **VTK Volume Cache** (Layer 3 of S4B).

Design: ``docs/plans/architecture/S4B_VTK_CACHE_ARCHITECTURE_2026-06-26.md``. This service wraps the
S4a :class:`PacsClient.utils.volume_cache.VolumeCache` as ONE process-wide owner, so every in-process
VTK consumer (the Advanced viewer, Standard/Dental Curve MPR, Dental Imaging, Orthogonal MPR, in-proc
AI/segmentation) shares **one volume built once per ``(study_uid, series_uid)``**, with pin/unpin and
a single invalidation bus — replacing the FAST-stub + ``_load_full_vtk_for_mpr`` + Advanced
``convert_itk2vtk`` + Orthogonal SimpleITK rebuilds.

**S4b-1 (this commit) is SHADOW + scaffolding only.** It is gated default-OFF by
``AIPACS_VTK_VOLUME_CACHE`` and **no production consumer reads a cached volume yet** (introduced
UNUSED, like S3a/S4a/S5a). In shadow, each legacy VTK-volume build calls :func:`observe_vtk_build`,
which records the build signature for its stable key and reports when:

* the SAME ``(study_uid, series_uid)`` was already built — a **rebuild the cache would have avoided**
  (the headline double-build the design targets), or
* the geometry **signature diverges** from the first build of that key — a correctness flag for the
  one-geometry-contract goal.

That is the live evidence that gates S4b-2 (route MPR/Dental) and S4b-3 (route the Advanced switch).
The module is **pure stdlib + threading — NO VTK / numpy / Qt at import** — so it is headless
unit-testable; callers extract plain ``(dims, spacing, origin, direction)`` tuples from their
``vtkImageData`` and hand them in.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from PacsClient.utils.volume_cache import VolumeCache, VolumeCacheError, make_key, Key


# --------------------------------------------------------------------------- #
# Flags (read once at import; all default-OFF / safe)
# --------------------------------------------------------------------------- #
def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or default).strip() == "1"


# Master gate. OFF (default) → the shadow observation is inert and NO cache is created → zero cost,
# byte-identical legacy. ``=1`` turns on the S4b-1 shadow (observe + log only; still no consumer
# reads a cached volume). Kept as the same flag the later wiring stages flip.
_VTK_VOLUME_CACHE_ENABLED = _flag("AIPACS_VTK_VOLUME_CACHE", "0")

# Pure-SHADOW gate (S4b-1): observe + log only, NEVER caches/reuses. Lets a validation run QUANTIFY
# the rebuilds + confirm geometry consistency BEFORE the cache is allowed to ACT. Independent of the
# caching flag (either may be on); when only this is on, every build still happens — it is just
# measured. Default OFF.
_VTK_VOLUME_CACHE_SHADOW = _flag("AIPACS_VTK_VOLUME_CACHE_SHADOW", "0")


def service_enabled() -> bool:
    """True when ``AIPACS_VTK_VOLUME_CACHE=1`` — the cache ACTS (build-once + reuse)."""
    return _VTK_VOLUME_CACHE_ENABLED


def shadow_enabled() -> bool:
    """True when ``AIPACS_VTK_VOLUME_CACHE_SHADOW=1`` — observe/log only, no caching/reuse."""
    return _VTK_VOLUME_CACHE_SHADOW


# CROSS-DOMAIN reuse gate (separation HARD RULE, 2026-06-27 — boundary doc §0.1/§7.1). DEFAULT OFF →
# each VTK domain (advanced / mpr / dental / orthogonal / ai) gets its OWN per-domain VTK volume cache,
# so a volume built by one domain is NEVER handed to another (no cross-domain coupling). Within a
# domain, reuse still removes that domain's own repeat-builds. When ON (OPT-IN, must pass the §7.1
# strict test on a live clinical pass) all VTK domains share ONE cache keyed by identity, so a series
# is built once across them — the cross-domain optimization. The Fast viewer NEVER uses this service.
_VTK_VOLUME_CACHE_CROSS_DOMAIN = _flag("AIPACS_VTK_VOLUME_CACHE_CROSS_DOMAIN", "0")


def cross_domain_enabled() -> bool:
    """True when ``AIPACS_VTK_VOLUME_CACHE_CROSS_DOMAIN=1`` — VTK domains share ONE volume cache.
    Default OFF → per-domain caches (no cross-domain coupling; the separation rule's safe default)."""
    return _VTK_VOLUME_CACHE_CROSS_DOMAIN


def _cache_max_entries() -> int:
    try:
        return max(1, int(os.getenv("AIPACS_VTK_VOLUME_CACHE_ENTRIES", "8")))
    except ValueError:
        return 8


def _cache_max_bytes() -> int:
    """Byte budget for the VTK volume cache (the real memory control — VTK volumes are large). MB."""
    try:
        mb = max(0, int(os.getenv("AIPACS_VTK_VOLUME_CACHE_MB", "1536")))
    except ValueError:
        mb = 1536
    return mb * 1024 * 1024


# --------------------------------------------------------------------------- #
# Pure geometry signature (the one-contract comparison key)
# --------------------------------------------------------------------------- #
def _round_seq(seq: Any, ndigits: int = 4) -> Tuple:
    if seq is None:
        return ()
    out = []
    for v in seq:
        try:
            out.append(round(float(v), ndigits))
        except (TypeError, ValueError):
            out.append(v)
    return tuple(out)


def vtk_geometry_signature(dims: Any, spacing: Any, origin: Any,
                           direction: Any = None) -> str:
    """Pure, stable signature of a VTK volume's geometry — dimensions + spacing + origin (+ optional
    direction matrix). Floats are rounded to absorb fp noise, so two builds of the SAME series from
    the SAME files compare equal, while a different spacing / origin / orientation / slice-count
    diverges. Used by the shadow to detect a geometry mismatch across builders (the
    one-geometry-contract guard). No VTK dependency — caller passes plain tuples."""
    d = tuple(int(x) for x in dims) if dims is not None else ()
    return "dims=%s|spc=%s|org=%s|dir=%s" % (
        d, _round_seq(spacing), _round_seq(origin), _round_seq(direction),
    )


# --------------------------------------------------------------------------- #
# Identity normalization (one key across builders — MPR uses 'series_uid',
# image_io/Advanced uses 'series_instance_uid', and some builders truncate)
# --------------------------------------------------------------------------- #
_MIN_UID_LEN = 16   # real DICOM SeriesInstanceUIDs are long; reject 8-char log truncations


def normalize_series_uid(*candidates: Any) -> str:
    """Return the first candidate that looks like a FULL DICOM SeriesInstanceUID (length ≥ 16 — long
    enough to be a safe, collision-free cache key). Different metadata dicts store the UID under
    different keys and some are truncated for logging; a short/empty value is rejected (returns "")
    so a truncated or ambiguous id NEVER becomes a cache key — no cache entry is safer than a wrong
    shared one. This is what lets the MPR and Advanced builders key the SAME series identically."""
    for c in candidates:
        s = str(c or "").strip()
        if len(s) >= _MIN_UID_LEN:
            return s
    return ""


def series_uid_from_meta(series_meta: Any) -> str:
    """Resolve the full SeriesInstanceUID from a series-metadata dict, tolerant of the differing key
    names across builders (`series_instance_uid` | `series_uid` | `SeriesInstanceUID`)."""
    if not isinstance(series_meta, dict):
        return ""
    return normalize_series_uid(series_meta.get("series_instance_uid"),
                                series_meta.get("series_uid"),
                                series_meta.get("SeriesInstanceUID"))


def study_uid_from_meta(series_meta: Any) -> str:
    """Resolve the StudyInstanceUID from a series-metadata dict (best-effort; empty is acceptable —
    a full series_uid alone keys uniquely)."""
    if not isinstance(series_meta, dict):
        return ""
    for k in ("study_instance_uid", "study_uid", "StudyInstanceUID"):
        v = str(series_meta.get(k) or "").strip()
        if v:
            return v
    return ""


# --------------------------------------------------------------------------- #
# Shadow observation result
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ShadowObservation:
    """What the shadow learned from one legacy VTK-volume build."""
    key: Key
    source: str
    slice_count: int
    signature: str
    is_rebuild: bool          # this (study_uid, series_uid) was already built → cache would reuse
    geometry_changed: bool    # signature differs from the FIRST recorded build of this key
    prior_source: Optional[str] = None

    @property
    def would_save_rebuild(self) -> bool:
        """True when a shared cache would have returned the existing volume instead of this build."""
        return self.is_rebuild and not self.geometry_changed


# --------------------------------------------------------------------------- #
# The service
# --------------------------------------------------------------------------- #
class VtkVolumeService:
    """Process-wide owner of the shared VTK volume cache. Thread-safe. In S4b-1 only the shadow
    (:meth:`observe_build`) is exercised; :meth:`get_or_build` / :meth:`pin` / :meth:`invalidate`
    are the wiring surface S4b-2/3 will call."""

    def __init__(self) -> None:
        self._caches_lock = threading.RLock()
        # ONE VolumeCache PER DOMAIN (advanced / mpr / dental / orthogonal / ai). Per the separation
        # HARD RULE the default is per-domain: a volume built by one domain is never reachable from
        # another. When AIPACS_VTK_VOLUME_CACHE_CROSS_DOMAIN is on, every domain maps to one "_shared"
        # cache (the opt-in cross-domain optimization). Caches are created lazily.
        self._caches: Dict[str, VolumeCache] = {}
        self._shadow_lock = threading.RLock()
        # key -> (first_signature, first_source, build_count)  — domain-agnostic cross-domain detector
        self._shadow_seen: Dict[Key, Tuple[str, str, int]] = {}

    def _cache_for(self, domain: Any) -> VolumeCache:
        """The VolumeCache for ``domain`` — per-domain by default, or the one "_shared" cache when
        cross-domain reuse is enabled."""
        bucket = "_shared" if cross_domain_enabled() else (str(domain or "default").strip() or "default")
        with self._caches_lock:
            c = self._caches.get(bucket)
            if c is None:
                c = VolumeCache(max_entries=_cache_max_entries(), max_bytes=_cache_max_bytes())
                self._caches[bucket] = c
            return c

    # -- production surface — PER-DOMAIN, delegates to that domain's coalescing cache ------- #
    def get_or_build(self, domain: Any, study_uid: Any, series_uid: Any,
                     factory: Callable[[], Any], *, pin: bool = False, size: int = 0) -> Any:
        """Return ``domain``'s cached volume for ``(study_uid, series_uid)``; build it via ``factory``
        exactly once even under concurrent callers (decode-coalescing). By default each VTK domain has
        its OWN cache (no cross-domain sharing); the cross-domain flag collapses them to one. ``factory``
        runs OFF the GUI thread. **Never reachable from the Fast viewer.**"""
        return self._cache_for(domain).get_or_create(make_key(study_uid, series_uid), factory,
                                                      size=size, pin=pin)

    def peek(self, domain: Any, study_uid: Any, series_uid: Any) -> Optional[Any]:
        return self._cache_for(domain).peek(make_key(study_uid, series_uid))

    def pin(self, domain: Any, study_uid: Any, series_uid: Any) -> bool:
        return self._cache_for(domain).pin(make_key(study_uid, series_uid))

    def unpin(self, domain: Any, study_uid: Any, series_uid: Any) -> bool:
        return self._cache_for(domain).unpin(make_key(study_uid, series_uid))

    def invalidate(self, study_uid: Any, series_uid: Any) -> int:
        """Invalidation BUS (trunk): drop ``(study_uid, series_uid)`` from EVERY domain's cache — a
        server-grew / series-changed event invalidates whatever each domain cached. Returns the count
        of domains that held it. Drops the cache ref only; the backing frees when the last live
        ``vtkImageData`` releases it (never an eager unmap)."""
        key = make_key(study_uid, series_uid)
        with self._caches_lock:
            caches = list(self._caches.values())
        return sum(1 for c in caches if c.invalidate(key))

    def invalidate_study(self, study_uid: Any) -> int:
        with self._caches_lock:
            caches = list(self._caches.values())
        return sum(c.invalidate_study(study_uid) for c in caches)

    def stats(self) -> Dict[str, int]:
        with self._caches_lock:
            caches = list(self._caches.values())
        agg = {"domains": len(caches), "entries": 0, "hits": 0, "misses": 0, "coalesced": 0, "pinned": 0}
        for c in caches:
            s = c.stats()
            for k in ("entries", "hits", "misses", "coalesced", "pinned"):
                agg[k] += int(s.get(k, 0))
        return agg

    # -- the S4b-1 shadow ------------------------------------------------------------------ #
    def observe_build(self, study_uid: Any, series_uid: Any, *, slice_count: int,
                      geometry_signature: str, source: str) -> ShadowObservation:
        """Record one legacy VTK-volume build under its stable key and report whether the shared
        cache would have AVOIDED it (same key already built) and whether the geometry signature
        diverges from that key's first build. Pure bookkeeping — never builds or caches a volume."""
        key = make_key(study_uid, series_uid)
        with self._shadow_lock:
            prior = self._shadow_seen.get(key)
            if prior is None:
                self._shadow_seen[key] = (geometry_signature, str(source), 1)
                return ShadowObservation(key, str(source), int(slice_count),
                                         geometry_signature, is_rebuild=False,
                                         geometry_changed=False, prior_source=None)
            first_sig, first_source, count = prior
            self._shadow_seen[key] = (first_sig, first_source, count + 1)
            return ShadowObservation(
                key, str(source), int(slice_count), geometry_signature,
                is_rebuild=True,
                geometry_changed=(geometry_signature != first_sig),
                prior_source=first_source,
            )

    def shadow_stats(self) -> Dict[str, int]:
        with self._shadow_lock:
            return {"keys_seen": len(self._shadow_seen),
                    "total_builds": sum(c for _, _, c in self._shadow_seen.values())}


# --------------------------------------------------------------------------- #
# Process-wide singleton + the one-call shadow helper for build sites
# --------------------------------------------------------------------------- #
_service_singleton: Optional[VtkVolumeService] = None
_singleton_lock = threading.Lock()


def get_vtk_volume_service() -> VtkVolumeService:
    """The process-wide :class:`VtkVolumeService`. Created lazily (only once a caller asks), so when
    the flag is off and no caller runs, no cache is ever allocated."""
    global _service_singleton
    if _service_singleton is None:
        with _singleton_lock:
            if _service_singleton is None:
                _service_singleton = VtkVolumeService()
    return _service_singleton


def reset_vtk_volume_service() -> None:
    """Test helper — drop the singleton so a test starts from a clean service."""
    global _service_singleton
    with _singleton_lock:
        _service_singleton = None


def observe_vtk_build(study_uid: Any, series_uid: Any, *, slice_count: int,
                      dims: Any, spacing: Any, origin: Any, direction: Any = None,
                      source: str, logger: Any = None) -> Optional[ShadowObservation]:
    """ONE cheap call for a legacy VTK-volume build site (S4b-1 shadow). No-ops (returns ``None``)
    when ``AIPACS_VTK_VOLUME_CACHE`` is off — so the default path adds nothing. When on, it records
    the build and logs ``[VTK-VOLUME-SHADOW]`` when the shared cache would have AVOIDED the rebuild,
    or when the geometry diverges across builders. Never raises into the caller. Runs when EITHER the
    shadow (measure) or the cache (act) flag is on; no-ops otherwise."""
    if not (_VTK_VOLUME_CACHE_SHADOW or _VTK_VOLUME_CACHE_ENABLED):
        return None
    try:
        sig = vtk_geometry_signature(dims, spacing, origin, direction)
        obs = get_vtk_volume_service().observe_build(
            study_uid, series_uid, slice_count=int(slice_count),
            geometry_signature=sig, source=str(source))
        if logger is not None and (obs.is_rebuild or obs.geometry_changed):
            if obs.geometry_changed:
                logger.info(
                    "[VTK-VOLUME-SHADOW] series_uid=%s GEOMETRY DIVERGES from first build "
                    "(this=%s prior_source=%s) — one-geometry-contract flag", series_uid,
                    source, obs.prior_source)
            else:
                logger.info(
                    "[VTK-VOLUME-SHADOW] series_uid=%s REBUILD by source=%s (first built by %s) — "
                    "the shared VTK volume cache would have reused the existing volume "
                    "(slice_count=%d)", series_uid, source, obs.prior_source, int(slice_count))
        return obs
    except Exception:
        return None


def build_or_get_volume(domain: Any, study_uid: Any, series_uid: Any, builder: Callable[[], Any], *,
                        source: str = "vtk", logger: Any = None) -> Any:
    """S4b routing for a FULL VTK volume (Layer 3), scoped to ONE VTK ``domain`` (advanced / mpr /
    dental / orthogonal / ai). Per the separation HARD RULE the cache is **per-domain by default** —
    a volume built by one domain is NEVER handed to another; ``AIPACS_VTK_VOLUME_CACHE_CROSS_DOMAIN``
    collapses the domains to one shared cache (opt-in). Behaviour by flag:

    * ``AIPACS_VTK_VOLUME_CACHE`` ON → return ``domain``'s cached volume for ``(study_uid, series_uid)``,
      building it ONCE via ``builder()`` on a miss (decode-coalesced) and REUSING it on a hit within
      that domain — the repeat double-build removed. A None/failed build is NEVER cached.
    * else ``AIPACS_VTK_VOLUME_CACHE_SHADOW`` ON → call ``builder()`` every time (no caching) but
      OBSERVE each build (measure rebuilds + cross-domain geometry) — the S4b-1 evidence path.
    * both OFF → ``builder()`` directly: **byte-identical legacy, zero work**.

    Never raises into the caller — a failed build returns ``None`` (= the legacy 'blocked' result).
    ``builder`` returns the ``vtkImageData`` or ``None``. Lifetime is governed by the CALLER's own
    reference exactly as today; the cache holds an ADDITIONAL ref (pin is deferred to S4b-4), so a
    consumer that keeps its volume is never affected by cache eviction."""
    cache_on = service_enabled()
    shadow_on = shadow_enabled()
    if not cache_on and not shadow_on:
        return builder()                                   # legacy path, no observe, no cache
    if not str(series_uid or "").strip():
        return builder()                                   # no stable key → cannot cache safely

    def _observe(volume: Any) -> None:
        try:
            d = tuple(volume.GetDimensions())
            sp = tuple(volume.GetSpacing())
            og = tuple(volume.GetOrigin())
        except Exception:
            d = sp = og = ()
        # the shadow is domain-agnostic (keyed by identity + source) so it still detects when MPR and
        # Advanced build the SAME series with DIFFERENT geometry — the cross-domain reuse gate.
        observe_vtk_build(study_uid, series_uid,
                          slice_count=(int(d[2]) if len(d) == 3 else 0),
                          dims=d, spacing=sp, origin=og, source=source, logger=logger)

    if not cache_on:
        # SHADOW-only: build every time, observe, never cache.
        v = builder()
        if v is not None:
            _observe(v)
        return v

    # CACHE mode: build once per (domain, key) (coalesced); observe fires only on a real build.
    def _factory():
        v = builder()
        if v is None:
            raise VolumeCacheError("vtk volume build returned None")
        _observe(v)
        return v

    try:
        return get_vtk_volume_service().get_or_build(domain, study_uid, series_uid, _factory, pin=False)
    except Exception:
        return None


def build_or_get_mpr_volume(study_uid: Any, series_uid: Any, builder: Callable[[], Any], *,
                            source: str = "mpr_full_rebuild", logger: Any = None) -> Any:
    """Back-compat thin wrapper — the **MPR** domain. See :func:`build_or_get_volume`. The MPR cache is
    isolated from every other VTK domain by default (separation rule)."""
    return build_or_get_volume("mpr", study_uid, series_uid, builder, source=source, logger=logger)
