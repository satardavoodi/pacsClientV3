"""Startup Feature Activation audit.

Emits one ``[FEATURE_ACTIVATION]`` log line per recently-added capability stating
whether it is ACTIVE on this machine and WHY — so a single ``app.log`` from any
client tells you exactly which features are live, without attaching a debugger or
reading the source. This exists because "works in dev, dead on the installed
build" has several distinct causes that are otherwise invisible:

  * a feature flag whose default lives in code (e.g. MPR canonical geometry),
  * a purchasable module gated by the installed module profile (e.g. consultation),
  * a UI variant resolved from build default vs. user config,
  * stale user config preserved across upgrades (the seeder never overwrites).

Design rules: every probe is wrapped so the audit can NEVER break startup, calls
only cheap/network-free gates, and runs exactly once per process.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_AUDITED = False


def _safe(fn):
    try:
        return fn(), None
    except Exception as exc:  # never raise out of the audit
        return None, repr(exc)


def log_feature_activation() -> None:
    """Log the activation state of recent features once. Best-effort; never raises."""
    global _AUDITED
    if _AUDITED:
        return
    _AUDITED = True

    # Build/runtime context first.
    try:
        import sys

        frozen = bool(getattr(sys, "frozen", False))
        version = "unknown"
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None and app.applicationVersion():
                version = str(app.applicationVersion())
        except Exception:
            pass
        logger.info("[FEATURE_ACTIVATION] context frozen=%s version=%s", frozen, version)
    except Exception as exc:
        logger.debug("[FEATURE_ACTIVATION] context probe failed: %r", exc)

    # --- MPR corrected geometry (canonicalize) ---------------------------------
    def _mpr():
        import os

        from modules.mpr.zeta_mpr._mpr_canonicalize import (
            canonicalize_enabled,
            _BUILD_DEFAULT_CANONICALIZE,
        )

        active = canonicalize_enabled()
        env = os.environ.get("AIPACS_ZETA_MPR_CANONICALIZE", "").strip()
        source = "env" if env else "config_or_build_default"
        return f"active={active} build_default={_BUILD_DEFAULT_CANONICALIZE} source={source}"

    val, err = _safe(_mpr)
    logger.info("[FEATURE_ACTIVATION] feature=mpr_canonical_geometry %s",
                val if err is None else f"active=UNKNOWN error={err}")

    # --- Online consultation (purchasable, triple-gated) -----------------------
    def _consult():
        from modules.education.online_consultation import online_consultation_available

        avail = online_consultation_available()
        reason = ""
        if not avail:
            try:
                from aipacs_runtime import is_module_enabled

                reason = " reason=module_disabled" if not is_module_enabled("consultation") \
                    else " reason=feature_flags_off"
            except Exception:
                reason = " reason=gate_off"
        return f"active={avail}{reason}"

    val, err = _safe(_consult)
    logger.info("[FEATURE_ACTIVATION] feature=online_consultation %s",
                val if err is None else f"active=UNKNOWN error={err}")

    # --- UI variant (V1 legacy vs V2 default) ----------------------------------
    def _ui():
        from PacsClient.utils.ui_variant import get_ui_variant

        return f"home={get_ui_variant('home')} viewer={get_ui_variant('viewer')}"

    val, err = _safe(_ui)
    logger.info("[FEATURE_ACTIVATION] feature=ui_variant %s",
                val if err is None else f"home=UNKNOWN error={err}")

    # --- Installed module profile (frozen-build gating) ------------------------
    def _modules():
        from aipacs_runtime import is_module_enabled

        ids = ("consultation", "identity", "printing", "cd_burner", "web_browser", "EchoMind")
        return " ".join(f"{m}={is_module_enabled(m)}" for m in ids)

    val, err = _safe(_modules)
    logger.info("[FEATURE_ACTIVATION] feature=module_profile %s",
                val if err is None else f"UNKNOWN error={err}")
