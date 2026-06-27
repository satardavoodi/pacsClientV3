"""Agent-control permission & side-effect policy (P0 safety layer, 2026-06-23).

Pure, stdlib-only. Classifies every CommandBus action by **side-effect** and
decides whether a given session **mode** may run it (and whether it needs
confirmation). It is consulted at the single dispatch choke point
(``registry.AdapterRegistry.dispatch``) so EVERY caller — the voice assistant,
the MCP / Test Control Server, and GUI tests — is covered by one gate.

Why this exists
---------------
Before this module, ``CommandPlan.needs_confirmation`` was carried but never
read on the execution path, and ``registry.dispatch`` performed no permission,
side-effect, or confirmation check at all (see
``docs/reports/AGENT_CONTROL_ARCHITECTURE_REVIEW_2026-06-23.md`` §3/§7,
Appendix B). An external agent could therefore invoke server-write /
destructive actions with no in-app gate. This module is the policy half of the
fix; ``registry.py`` is the enforcement half.

Hard design contract (DO NOT BREAK — these are what make the gate safe to ship
default-on without changing any current behaviour):

1. **Inert for the legacy / unscoped caller.** When no explicit ``agent_mode``
   is supplied (mode :data:`UNRESTRICTED`), every action is allowed with no
   confirmation — byte-identical to the pre-gate behaviour, and
   ``plan.needs_confirmation`` is ignored exactly as it was before. Enforcement
   activates ONLY when a caller opts in by setting a restrictive mode. The
   voice executor, the test server, and direct callers pass no mode today, so
   they are unaffected.
2. **Fail closed on an unknown *explicit* mode.** A non-empty mode string that
   isn't recognised resolves to the most restrictive mode
   (:data:`READ_ONLY_MODE`), never to ``UNRESTRICTED``. An empty / ``None`` mode
   is the legacy/unscoped case and resolves to ``UNRESTRICTED`` (rule 1).
3. **Dangerous actions are classified explicitly.** A *known-but-unmapped*
   action defaults to :data:`UI_NAV` (low risk); every server-write and
   destructive action is listed explicitly below. Keep new SERVER_WRITE /
   DESTRUCTIVE actions in the map.

The kill switch is the ``AIPACS_AGENT_PERMISSIONS`` env var, read in
``registry.py`` (``=0`` restores byte-identical legacy dispatch).
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Side-effect classes ───────────────────────────────────────────────────────
READ_ONLY = "read_only"
UI_NAV = "ui_navigation"
LOCAL_WRITE = "local_write"
SERVER_WRITE = "server_write"
DESTRUCTIVE = "destructive"

_ALL_SIDE_EFFECTS = (READ_ONLY, UI_NAV, LOCAL_WRITE, SERVER_WRITE, DESTRUCTIVE)

# ── Session modes ─────────────────────────────────────────────────────────────
UNRESTRICTED = "unrestricted"     # legacy / unscoped caller — gate is INERT
READ_ONLY_MODE = "read_only"      # resources + read-only tools only
ASSISTANT = "assistant"           # end-user assistant (EchoMind voice/chat)
QA = "qa"                         # automated developer / QA harness
SERVER_WRITE_MODE = "server_write"
DESTRUCTIVE_MODE = "destructive"

#: Mode used when a caller supplies none. MUST stay ``UNRESTRICTED`` so the gate
#: is inert for every current caller (see contract rule 1).
DEFAULT_MODE = UNRESTRICTED

#: Friendly aliases a caller may pass instead of the canonical mode strings.
_MODE_ALIASES = {
    "rw": UNRESTRICTED,
    "full": UNRESTRICTED,
    "none": UNRESTRICTED,
    "dev": QA,
    "developer": QA,
    "test": QA,
    "qa_harness": QA,
    "end_user": ASSISTANT,
    "user": ASSISTANT,
    "secretary": ASSISTANT,
    "readonly": READ_ONLY_MODE,
    "read-only": READ_ONLY_MODE,
    "ro": READ_ONLY_MODE,
}

# ── Action → side-effect classification ───────────────────────────────────────
# Seeded from the 2026-06-23 architecture review inventory (§6.1). Keep the
# SERVER_WRITE / DESTRUCTIVE entries explicit; a known-but-unmapped action
# defaults to ``_DEFAULT_SIDE_EFFECT`` (UI_NAV).
ACTION_SIDE_EFFECTS: dict[str, str] = {
    # ── system probes (read-only) ──
    "snapshot_resources": READ_ONLY,
    "count_aipacs_processes": READ_ONLY,
    "count_native_faults_since": READ_ONLY,
    "probe_idle_cpu": READ_ONLY,
    # ── viewer reads (strictly read-only adapter) ──
    "get_active_tab": READ_ONLY,
    "list_open_tabs": READ_ONLY,
    "get_thumbnails_data": READ_ONLY,
    "get_active_series": READ_ONLY,
    "get_multistudy_info": READ_ONLY,
    # ── viewer_write reads ──
    "query_viewport_state": READ_ONLY,
    "get_series_info": READ_ONLY,
    # ── download reads ──
    "check_download_status": READ_ONLY,
    "list_downloads": READ_ONLY,
    "download_statistics": READ_ONLY,
    # ── module / agent reads ──
    "list_modules": READ_ONLY,
    "agent_task_status": READ_ONLY,
    # ── home (a patient *search* returns data; treat as read) ──
    "list_patients": READ_ONLY,
    # ── UI navigation (no data change) ──
    "select_patient": UI_NAV,
    "open_browser": UI_NAV,
    "browser_back": UI_NAV,
    "browser_forward": UI_NAV,
    "refresh_page": UI_NAV,
    "open_consultation": UI_NAV,
    "show_consultant_profiles": UI_NAV,
    "open_courses": UI_NAV,
    "open_case_of_day": UI_NAV,
    "search_education": UI_NAV,
    "open_module": UI_NAV,
    "toggle_eagle": UI_NAV,
    "open_mpr": UI_NAV,
    "open_printing": UI_NAV,
    "open_education": UI_NAV,
    "switch_tab": UI_NAV,
    # ── local write (app/UI state; may trigger background work) ──
    "open_patient": LOCAL_WRITE,
    "change_series": LOCAL_WRITE,
    "scroll_slices": LOCAL_WRITE,
    "change_layout": LOCAL_WRITE,
    "start_report": LOCAL_WRITE,
    "transcribe_voice": LOCAL_WRITE,
    "generate_report": LOCAL_WRITE,
    "pause_download": LOCAL_WRITE,
    # ── server write / network egress ──
    "download_patient": SERVER_WRITE,
    "resume_download": SERVER_WRITE,
    "web_search": SERVER_WRITE,
    "open_url": SERVER_WRITE,
    "login_website": SERVER_WRITE,
    "search_education_content": SERVER_WRITE,
    "send_report_to_pacs": SERVER_WRITE,
    # ── destructive (teardown / cancel) ──
    "cancel_download": DESTRUCTIVE,
    "cancel_agent_task": DESTRUCTIVE,
    "close_patient_tab": DESTRUCTIVE,
    # ── browser structured page tools (2026-06-27) ──
    # Reads return page data with no state change; fill/click are local page
    # writes; navigate/submit cause network egress (match open_url's gating so
    # the alias can't bypass the confirmation open_url requires).
    "browser_get_url": READ_ONLY,
    "browser_get_text": READ_ONLY,
    "browser_get_html": READ_ONLY,
    "browser_dom_summary": READ_ONLY,
    "browser_selected_text": READ_ONLY,
    "browser_get_links": READ_ONLY,
    "browser_extract_table": READ_ONLY,
    "browser_find_element": READ_ONLY,
    "browser_screenshot": READ_ONLY,
    "browser_go_back": UI_NAV,
    "browser_go_forward": UI_NAV,
    "browser_reload": UI_NAV,
    "browser_fill_field": LOCAL_WRITE,
    "browser_click": LOCAL_WRITE,
    "browser_navigate": SERVER_WRITE,
    "browser_submit_form": SERVER_WRITE,
}

#: Side-effect assigned to a known-but-unmapped action (conservative low-risk).
_DEFAULT_SIDE_EFFECT = UI_NAV

# ── Mode policy ───────────────────────────────────────────────────────────────
#: Side-effects each mode is allowed to run.
_ALLOW: dict[str, set] = {
    UNRESTRICTED: set(_ALL_SIDE_EFFECTS),
    QA: set(_ALL_SIDE_EFFECTS),
    DESTRUCTIVE_MODE: set(_ALL_SIDE_EFFECTS),
    SERVER_WRITE_MODE: {READ_ONLY, UI_NAV, LOCAL_WRITE, SERVER_WRITE},
    ASSISTANT: {READ_ONLY, UI_NAV, LOCAL_WRITE, SERVER_WRITE},
    READ_ONLY_MODE: {READ_ONLY},
}

#: Side-effects that require an explicit confirmation in a given mode.
_CONFIRM: dict[str, set] = {
    UNRESTRICTED: set(),          # legacy: never gate (preserves behaviour)
    QA: set(),                    # automated harness: no human in the loop
    DESTRUCTIVE_MODE: {DESTRUCTIVE},
    SERVER_WRITE_MODE: {SERVER_WRITE, DESTRUCTIVE},
    ASSISTANT: {SERVER_WRITE, DESTRUCTIVE},
    READ_ONLY_MODE: set(),
}

#: Modes in which a plan's ``needs_confirmation`` flag is honored. Automated
#: (``qa``) and ``read_only`` / ``unrestricted`` sessions never pause for
#: confirmation, so a stray ``needs_confirmation`` can't wedge the QA harness.
_CONFIRMING_MODES = {ASSISTANT, SERVER_WRITE_MODE, DESTRUCTIVE_MODE}


@dataclass(frozen=True)
class Decision:
    """Outcome of a permission check.

    ``allowed`` False  → caller must NOT run the action (``error_code``
    ``PERMISSION_DENIED``). ``allowed`` True + ``requires_confirmation`` True →
    hold the action and ask the user first (``error_code`` ``CONFIRM_REQUIRED``).
    ``allowed`` True + ``requires_confirmation`` False → run it.
    """

    allowed: bool
    requires_confirmation: bool
    side_effect: str
    mode: str
    reason: str = ""
    error_code: str | None = None


def normalize_mode(mode) -> str:
    """Resolve a caller-supplied mode to a canonical mode string.

    Empty / ``None`` → :data:`UNRESTRICTED` (legacy/unscoped, gate inert).
    Unknown *explicit* mode → :data:`READ_ONLY_MODE` (fail closed).
    """
    if mode is None or (isinstance(mode, str) and not mode.strip()):
        return DEFAULT_MODE
    m = str(mode).strip().lower()
    m = _MODE_ALIASES.get(m, m)
    if m in _ALLOW:
        return m
    return READ_ONLY_MODE  # fail closed: an explicit but unrecognised mode


def classify(action: str) -> str:
    """Return the side-effect class for ``action`` (UI_NAV if unmapped)."""
    return ACTION_SIDE_EFFECTS.get(action, _DEFAULT_SIDE_EFFECT)


def is_destructive(action: str) -> bool:
    return classify(action) == DESTRUCTIVE


def decide(
    action: str,
    *,
    mode=None,
    confirmed: bool = False,
    plan_needs_confirmation: bool = False,
) -> Decision:
    """Decide whether ``action`` may run under ``mode``.

    ``UNRESTRICTED`` (the default / unscoped caller) is fully permissive and
    ignores ``plan_needs_confirmation`` — this is the legacy-preserving path.
    Any other mode enforces :data:`_ALLOW` and :data:`_CONFIRM`, and also honours
    ``plan_needs_confirmation`` (which the legacy execution path ignored).
    """
    m = normalize_mode(mode)
    se = classify(action)

    if m == UNRESTRICTED:
        return Decision(True, False, se, m, "unrestricted (legacy/unscoped)")

    if se not in _ALLOW.get(m, set()):
        return Decision(
            False, False, se, m,
            f"side-effect '{se}' is not permitted in mode '{m}'",
            "PERMISSION_DENIED",
        )

    needs = se in _CONFIRM.get(m, set())
    if plan_needs_confirmation and m in _CONFIRMING_MODES:
        needs = True
    if needs and not confirmed:
        return Decision(
            True, True, se, m,
            f"side-effect '{se}' requires confirmation in mode '{m}'",
            "CONFIRM_REQUIRED",
        )

    return Decision(True, False, se, m, "allowed")


__all__ = [
    "READ_ONLY", "UI_NAV", "LOCAL_WRITE", "SERVER_WRITE", "DESTRUCTIVE",
    "UNRESTRICTED", "READ_ONLY_MODE", "ASSISTANT", "QA",
    "SERVER_WRITE_MODE", "DESTRUCTIVE_MODE", "DEFAULT_MODE",
    "ACTION_SIDE_EFFECTS", "Decision",
    "normalize_mode", "classify", "is_destructive", "decide",
]
