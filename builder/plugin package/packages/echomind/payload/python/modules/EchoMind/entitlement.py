"""The ONE place that answers: is this installation licensed for company AI?

WHY THIS EXISTS (2026-08-09, owner decision)
--------------------------------------------
Turbo used to be a subfunction of the AI-PACS backend, so one company authorisation
covered both. Turbo is now technically separate — it holds its own hardcoded GapGPT
configuration and talks to the model directly. Technical separation must NOT become
licensing separation:

    Valid AI-PACS authorisation
        ├── AI-PACS backend : enabled
        └── Turbo           : enabled

    No valid authorisation
        ├── AI-PACS backend : disabled
        └── Turbo           : disabled

The user's OWN OpenAI key is deliberately outside this. EchoMind being installed is
the only requirement there; it spends the user's quota, not the company's.

WHAT THIS REPLACES
------------------
The entitlement decision was expressed in four places with four slightly different
shapes — the Turbo click handler, `_resolve_active_ai_identity`,
`llm_client._resolve_company_backend`, and `Manage.get_irannobat_key`. They agreed on
2026-08-09, which is luck rather than design: eleven call sites reach a company
function through `_ai_module(backend).<fn>()`, and the next one added would have had
to remember to re-implement the check. One authority, called from all of them.

FAIL CLOSED
-----------
Every failure path here returns False. An import error, a corrupt settings file, a
raising validator — none of them may produce an entitled answer. The cost of a wrong
False is that a licensed user re-enters their key; the cost of a wrong True is an
unlicensed installation spending company API budget.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Shown wherever a company feature is refused. One string so the UI cannot drift.
ENTITLEMENT_DENIED = (
    "❌ This feature requires an authorized AI-PACS company key. Please enter it in "
    "Settings → EchoMind (Company Authentication)."
)


class EntitlementError(RuntimeError):
    """Raised by `require_company_entitlement` when the installation is not licensed."""


def company_entitled() -> bool:
    """True only when a company licence key has been validated.

    Checks the in-memory manager first, and falls back to re-validating the key saved
    in settings — the same self-heal `_resolve_company_backend` has always done, so a
    licensed user who has not opened Settings this session is not locked out.

    This is the ONLY function that should decide whether company AI is available.
    Callers must not re-implement it, and must not accept a hardcoded credential as a
    substitute for it: the GapGPT key being present in the binary is not entitlement.
    """
    try:
        from modules.EchoMind.api_manager import APIKeyManager

        manager = APIKeyManager.instance()
        if manager.is_validated():
            return True

        from modules.EchoMind.settings_store import get_echomind_api_key

        saved = str(get_echomind_api_key() or "").strip()
        if not saved:
            return False
        ok, _center, _err = manager.validate_key(saved)
        return bool(ok)
    except Exception as exc:                       # pragma: no cover - defensive
        logger.warning("[entitlement] check failed, denying: %s", exc)
        return False


def require_company_entitlement(feature: str = "This feature") -> None:
    """Raise unless the installation is licensed. For non-UI call paths."""
    if not company_entitled():
        raise EntitlementError(f"{feature} requires a valid AI-PACS company key.")


def entitled_center_code() -> str:
    """The licensed centre code, or "" when not entitled. Never raises."""
    try:
        from modules.EchoMind.api_manager import APIKeyManager

        if not company_entitled():
            return ""
        return str(APIKeyManager.instance().get_current_center() or "")
    except Exception:                              # pragma: no cover - defensive
        return ""
