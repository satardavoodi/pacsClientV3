"""Feature flag for the AiPacs Chat manager console (default OFF).

Resolution: env ``AIPACS_CHAT`` → ``config/aipacs_chat/aipacs_chat.json`` →
default OFF, which is the same order and the same default every other module
flag uses. Path resolution never creates directories: a disabled module must
have no startup side effects at all, not even an empty folder.

THE GATE IS THREE THINGS, NOT ONE. ``aipacs_chat_available()`` is the single
call every entry point should make. It answers yes only when

  * the Identity module is on — this module has no auth of its own and no
    reason to exist without a paired AI-PACS web account,
  * this flag is on,
  * and the commercial module registry has ``aipacs_chat`` enabled for this
    workstation.

Checking one of the three and not the others is how a module ends up visible
on a workstation that never licensed it, or throwing an import error on one
that did.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_VAR = "AIPACS_CHAT"
_TRUE = {"1", "true", "on", "yes", "enabled"}
_FALSE = {"0", "false", "off", "no", "disabled"}
_FLAG_FILE = "aipacs_chat.json"

_MODULE_ID = "aipacs_chat"


def _config_root() -> Path:
    try:
        if getattr(sys, "frozen", False):
            from aipacs_runtime import roaming_config_root, seed_user_config_defaults

            seed_user_config_defaults()
            return Path(roaming_config_root())
        from _project_root import PROJECT_ROOT

        return Path(PROJECT_ROOT) / "config"
    except Exception:  # pragma: no cover
        return Path.home() / ".aipacs" / "config"


def _flag_file_path() -> Path:
    return _config_root() / "aipacs_chat" / _FLAG_FILE


def _flag_payload() -> dict:
    try:
        path = _flag_file_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("aipacs_chat flag read failed: %s", exc)
    return {}


def aipacs_chat_enabled() -> bool:
    """This module's own flag. Env wins, then the config file, then OFF."""
    raw = os.environ.get(_ENV_VAR)
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUE:
            return True
        if val in _FALSE:
            return False
    data = _flag_payload()
    if "enabled" in data:
        return bool(data["enabled"])
    return False


def save_aipacs_chat_enabled(enabled: bool) -> bool:
    """Persist this module's flag file (Settings-tab writer). Never raises.

    Merges into the existing payload so unknown keys survive. The env override
    (``AIPACS_CHAT``) still wins at read time — the Settings UI warns when it
    is set (see :func:`aipacs_chat_env_override`). Note the shipped-build
    sanitizer forces this file back to OFF (builder/config_sanitizer.py), so
    the shipped default stays OFF regardless of the dev tree.
    """
    try:
        payload = _flag_payload()
        payload["enabled"] = bool(enabled)
        path = _flag_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return True
    except Exception as exc:  # pragma: no cover - disk/permission problems
        logger.warning("aipacs_chat flag write failed: %s", exc)
        return False


def aipacs_chat_env_override() -> str:
    """The env var name forcing this flag, or "" (Settings-tab warning)."""
    raw = os.environ.get(_ENV_VAR)
    return _ENV_VAR if raw is not None and raw.strip() else ""


def _module_registry_enabled() -> bool:
    """The commercial registry's answer.

    FAILS OPEN, matching ``modules/education/online_consultation``: if the
    registry cannot be consulted at all (source checkout, a runtime that did
    not import) the answer is yes, because the alternative is a licensed
    module that silently refuses to open and no way to tell why.
    """
    try:
        from aipacs_runtime import is_module_enabled

        return bool(is_module_enabled(_MODULE_ID))
    except Exception as exc:  # pragma: no cover - must never break callers
        logger.debug("aipacs_chat module registry lookup failed: %s", exc)
        return True


def _identity_enabled() -> bool:
    try:
        from modules.Identity.feature_flags import identity_module_enabled

        return bool(identity_module_enabled())
    except Exception as exc:  # pragma: no cover
        logger.debug("aipacs_chat identity flag lookup failed: %s", exc)
        return False


def aipacs_chat_available() -> bool:
    """THE gate. One call, three conditions — do not bypass it.

    Every entry point (the left-menu button, the tab factory, the poller
    autostart) asks this and nothing else. A caller that checks
    ``aipacs_chat_enabled()`` alone is a caller that will open a console with
    no way to authenticate.
    """
    return bool(_identity_enabled() and aipacs_chat_enabled() and _module_registry_enabled())


def aipacs_chat_unavailable_reason() -> str:
    """Why the gate is closed, in words a user can act on ("" when open).

    One paragraph per failing condition, each NAMING the condition and where
    to fix it. The generic "module is not installed or not enabled" dialog is
    banned (2026-08-22): it covered three different causes — the module
    package missing from the workstation, the module disabled in the
    commercial registry, and this module's own settings toggle — and told the
    user nothing about which one applied. Never raises.
    """
    reasons: list[str] = []

    # 1) Commercial module registry — the install-state condition.
    try:
        if not _module_registry_enabled():
            detail: dict = {}
            try:
                from aipacs_runtime import module_availability_detail

                detail = module_availability_detail(_MODULE_ID)
            except Exception:
                detail = {}
            status = str(detail.get("status") or "")
            warning = str(detail.get("warning") or "")
            if status in {"install_failed", "install_incomplete"}:
                reasons.append(
                    "The AiPacs Chat module package did not install completely"
                    + (f": {warning}" if warning else ".")
                    + "\nReinstall it from Settings → Installation & Updates, "
                    "or re-run the AI-PACS installer with 'AiPacs Chat' ticked."
                )
            elif not detail.get("installed", False):
                reasons.append(
                    "The AiPacs Chat module package is not installed on this "
                    "workstation.\nInstall it from Settings → Installation & "
                    "Updates (Install Package / From Folder / From URL, or "
                    "Apply Selected Update), or re-run the AI-PACS installer "
                    "with 'AiPacs Chat' ticked."
                )
            else:
                reasons.append(
                    "The AiPacs Chat module is installed but disabled for this "
                    "workstation.\nEnable it in Settings → Installation & "
                    "Updates, then restart AI-PACS."
                )
    except Exception as exc:  # pragma: no cover - must never break callers
        logger.debug("aipacs_chat registry reason lookup failed: %s", exc)

    # 2) This module's own settings toggle.
    try:
        if not aipacs_chat_enabled():
            env = aipacs_chat_env_override()
            if env:
                reasons.append(
                    f"AiPacs Chat is forced off by the environment variable {env}. "
                    "Unset it to use the settings toggle."
                )
            else:
                reasons.append(
                    "AiPacs Chat is switched off in this workstation's settings."
                    "\nTurn it on in Settings → Consultation & Education → "
                    "AiPacs Chat."
                )
    except Exception as exc:  # pragma: no cover
        logger.debug("aipacs_chat flag reason lookup failed: %s", exc)

    # 3) The Identity dependency.
    try:
        if not _identity_enabled():
            reasons.append(
                "The Identity module is switched off on this workstation, and "
                "AiPacs Chat signs in with your AI-PACS web account through it."
                "\nEnable Identity in Settings → Consultation & Education."
            )
    except Exception as exc:  # pragma: no cover
        logger.debug("aipacs_chat identity reason lookup failed: %s", exc)

    if not reasons:
        try:
            if aipacs_chat_available():
                return ""
        except Exception:
            pass
        reasons.append("AiPacs Chat is not available on this workstation.")
    return "\n\n".join(reasons)


# ── where the backend lives ──────────────────────────────────────────────────
# Deliberately NOT a setting of this module's own. The base URL is the Identity
# module's (``AIPACS_WEB_BASE_URL`` / config/identity/aipacs_web.json) because
# the token is the Identity module's, and a second copy of the address is a
# second thing to get wrong the day the site moves. This helper exists only so
# callers do not have to import the provider to ask "is it configured yet".


def backend_configured() -> bool:
    try:
        from modules.Identity.providers.aipacs_web import aipacs_web_configured

        return bool(aipacs_web_configured())
    except Exception as exc:  # pragma: no cover
        logger.debug("aipacs_chat backend config lookup failed: %s", exc)
        return False
