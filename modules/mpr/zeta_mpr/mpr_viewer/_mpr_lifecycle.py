"""MPR lifecycle helpers: guaranteed teardown + memory accounting.

2026-08-19. Found by auditing a real reading session (patient 54921, pid
340640): the MPR teardown itself is excellent — ``_MprLayoutMixin.cleanup()``
releases GPU resources, finalizes the render windows, drops the flipped host
volume and breaks the interactor-style reference cycles — but it was reachable
from **exactly one place**, the toolbar's MPR toggle
(``toolbar_manager._restore_selected_viewer``).

Every other way an MPR viewer can die skipped it:

===========================  ==================================================
path                         what happened before this module
===========================  ==================================================
toolbar toggle OFF           cleanup() ran. Correct.
patient tab closed           ``_pw_lifecycle`` cleans the HOST vtk_widget and
                             nulls ``node.vtk_widget``; the MPR child was
                             never reached.
layout / viewport change     ``delete_widgets_in_layout`` does only
                             ``setParent(None)`` — the MPR is orphaned with
                             its volume and render windows live.
app exit                     nothing calls cleanup().
===========================  ==================================================

Evidence from the log ledger (open vs "cleanup() completed"):

    pid 340640 : 4 opened, 2 freed     12:57 MPR open -> 15:35 close_patient
                                       -> 17:45 toggle scan finds no widget,
                                       and no cleanup() in between.
    all pids   : 14 opened, 6 freed

Qt does NOT call ``closeEvent`` when a parent is destroyed or when a widget is
merely re-parented away, which is why a ``closeEvent`` hook alone would not
have fixed any of the three leaking rows above. The fix therefore has two
parts: a ``closeEvent`` for the explicit-close case, and
:func:`release_mpr_children`, called by the owners *before* they drop the
widget — while the VTK objects are still valid, which is the only moment
``ReleaseGraphicsResources()`` and ``Finalize()`` can do anything.

Kill switch: ``AIPACS_MPR_RELEASE_ON_DESTROY=0`` restores the pre-fix
behaviour (toolbar-toggle-only teardown).
"""
from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# Attributes a host widget uses to hold an MPR viewer. Kept in one place so the
# owners and the toolbar cannot drift apart on the name.
MPR_CHILD_ATTRS = (
    "_zeta_mpr_widget",
    "_new_mpr_zeta_widget",
    "_curved_mpr_widget",
    "_mpr_widget",
)


def release_enabled() -> bool:
    """Whether owners release MPR children before dropping them."""
    return (os.getenv("AIPACS_MPR_RELEASE_ON_DESTROY", "1") or "1").strip() != "0"


def memory_probe_enabled() -> bool:
    return (os.getenv("AIPACS_MPR_MEM_PROBE", "1") or "1").strip() != "0"


def _rss_mb() -> Optional[float]:
    """Resident set size of THIS process in MB, or None if psutil is absent.

    Deliberately unthrottled, unlike ``_emit_viewer_resource_probe`` — an MPR
    open/close happens a handful of times per session, and throttling is what
    would make the open/close pair unusable as a before/after measurement.
    """
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except Exception:
        return None


def mpr_memory_probe(phase: str, **fields: Any) -> Optional[float]:
    """Log ``[MPR-MEM]`` for *phase* and return the RSS in MB.

    Emitted at MPR open and at both ends of teardown so "was the memory
    actually released?" is answerable straight from the log. Answering that
    question on 2026-08-19 took a four-log reconstruction because the MPR
    timings live in ``viewer_diagnostics.log`` while the close path logs to
    ``app.log`` — and neither recorded a single byte of memory.
    """
    if not memory_probe_enabled():
        return None
    rss = _rss_mb()
    try:
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        logger.info(
            "[MPR-MEM] phase=%s rss_mb=%s %s",
            phase,
            f"{rss:.1f}" if rss is not None else "unavailable",
            extra,
        )
    except Exception:
        pass
    return rss


def find_mpr_viewers(widget: Any) -> List[Any]:
    """MPR viewers reachable from *widget* — itself and its known child slots.

    Duck-typed on the teardown contract (``cleanup`` + ``_mpr_closed``) rather
    than on the class, so this module stays importable from
    ``PacsClient.pacs.patient_tab.utils`` without an import cycle, and so a
    future MPR flavour is picked up automatically.

    Deliberately NOT a ``findChildren`` sweep: the hosts always publish the
    viewer through one of :data:`MPR_CHILD_ATTRS`, and walking every descendant
    of an arbitrary widget on a layout teardown would be both slower and
    happy to pick up things that merely look similar.
    """
    found: List[Any] = []
    if widget is None:
        return found

    def _is_mpr(obj: Any) -> bool:
        return (
            obj is not None
            and hasattr(obj, "cleanup")
            and hasattr(obj, "_mpr_closed")
        )

    try:
        if _is_mpr(widget):
            found.append(widget)
    except Exception:
        pass

    for attr in MPR_CHILD_ATTRS:
        try:
            child = getattr(widget, attr, None)
        except Exception:
            continue          # a deleted C++ object raises on attribute access
        try:
            if _is_mpr(child) and child not in found:
                found.append(child)
        except Exception:
            continue
    return found


def release_mpr_children(widget: Any, reason: str = "unspecified") -> int:
    """Run MPR teardown on every viewer reachable from *widget*.

    Call this BEFORE ``setParent(None)`` / ``deleteLater()`` / nulling the
    host reference. Afterwards the render windows may already be finalized and
    ``ReleaseGraphicsResources()`` can no longer reach a live GL context, so
    the VRAM would stay allocated until the driver reclaims it at process
    exit.

    Returns how many viewers were torn down (0 is the normal case — most
    widgets host no MPR). Never raises: this runs on close paths where an
    exception would strand the caller mid-teardown, and ``cleanup()`` is
    itself idempotent and individually guarded at every step.
    """
    if not release_enabled():
        return 0

    released = 0
    for viewer in find_mpr_viewers(widget):
        try:
            if getattr(viewer, "_mpr_closed", False):
                continue      # already torn down; cleanup() is idempotent but
                              # skipping keeps the log honest about the count
        except Exception:
            pass
        try:
            before = mpr_memory_probe("release_begin", reason=reason)
            viewer.cleanup()
            after = mpr_memory_probe("release_end", reason=reason)
            if before is not None and after is not None:
                logger.info(
                    "[MPR-MEM] phase=released reason=%s freed_mb=%.1f "
                    "rss_before_mb=%.1f rss_after_mb=%.1f",
                    reason, before - after, before, after,
                )
            released += 1
            logger.info(
                "[MPR-LIFECYCLE] released an MPR viewer on '%s' (%s)",
                reason, type(viewer).__name__,
            )
        except Exception:
            logger.warning(
                "[MPR-LIFECYCLE] MPR teardown failed on '%s'", reason,
                exc_info=True,
            )
    return released
