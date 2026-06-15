"""Mode-aware synchronization policy — the single source of truth for
"is this a live-server workflow or a local/offline one?".

Background + full contract: ``docs/architecture/SYNC_MODE_SEPARATION.md``.

The client must clearly separate workflows that depend on **live-server**
synchronization (server is source of truth, version-aware sync mandatory) from
workflows that rely only on **local/offline** data (local is source of truth, the
live server must never be required). Before this module, "is this local?" was
re-derived ad-hoc with *different* source-sets at each call site
(``source == DB``, ``source != DB``, ``(DB, OFFLINE_CLOUD)``,
``(DB, OFFLINE_CLOUD, IMPORT)`` …) — an open invitation to cross-mode bugs. Every
such decision now asks this policy instead, so the same question always gets the
same, logged answer.

Pure logic, no Qt / no heavy imports — safe to call from any thread or subprocess.
The ``SourceOfPatientLoad`` string values are duplicated here intentionally (kept
in lock-step with ``home_panel/widget.py``) to avoid importing the heavy home
widget into a low-level policy module.
"""

from __future__ import annotations

import os
from typing import Optional

# ── Raw patient-load source values (mirror SourceOfPatientLoad in widget.py) ──
SRC_SERVER = "server"
SRC_DB = "db"
SRC_IMPORT = "import"
SRC_OFFLINE_CLOUD = "offline_cloud"


# ── Workflow modes (explicit, what code reasons about) ────────────────────────
class WorkflowMode:
    LIVE_SERVER = "LiveServer"        # server is source of truth; strict version sync
    LOCAL_DATABASE = "LocalDatabase"  # local DB/disk is source of truth
    IMPORT = "Import"                 # in-flight import of local files
    OFFLINE_SERVER = "OfflineServer"  # offline-cloud package; offline rules, not live
    CD_BURN = "CDBurn"                # local selected data; never live-server
    UNKNOWN = "Unknown"               # source not yet established → treat conservatively


_SOURCE_TO_MODE = {
    SRC_SERVER: WorkflowMode.LIVE_SERVER,
    SRC_DB: WorkflowMode.LOCAL_DATABASE,
    SRC_IMPORT: WorkflowMode.IMPORT,
    SRC_OFFLINE_CLOUD: WorkflowMode.OFFLINE_SERVER,
}


def resolve_workflow_mode(source: Optional[str]) -> str:
    """Map a ``source_of_patient_load`` value (or a WorkflowMode) to a WorkflowMode.

    ``None`` / unrecognised → ``UNKNOWN`` (treated conservatively: no auto live-sync).
    Accepts a WorkflowMode value too, so callers can pass either.
    """
    if not source:
        return WorkflowMode.UNKNOWN
    s = str(source).strip()
    if s in _SOURCE_TO_MODE:
        return _SOURCE_TO_MODE[s]
    # already a WorkflowMode?
    if s in vars(WorkflowMode).values():
        return s
    return WorkflowMode.UNKNOWN


def _localdb_auto_server_sync_enabled() -> bool:
    """Whether a LocalDatabase (DB-source) patient runs the AUTO background
    server contentVersion check on reselect.

    DEFAULT **ON**. A DB/Local patient is a *locally-cached server study*, so the
    server's ``contentVersion`` must be consulted to detect server-side growth —
    new instances AND attachments / voice / captures / documents all bump it
    (STUDY_STORAGE_AND_VERSIONING §4.3), and the client rule is
    ``server_version > local_version -> re-sync`` (§7). This is the core
    synchronization contract and must NOT be silently disabled. It does not violate
    the mode-separation directive: the check is fire-and-forget (never blocks the
    open), throttled, contentVersion-cheap, and a no-op when the server is
    unavailable (so a local patient is never blocked or marked stale).

    Set ``AIPACS_LOCALDB_AUTO_SERVER_SYNC=0`` for strict local-only behaviour (no
    auto server check for DB patients). IMPORT / CD are always skipped regardless
    (those studies do not exist on the server). A manual "Refresh / Sync from
    server" always runs for any source.
    """
    return str(
        os.environ.get("AIPACS_LOCALDB_AUTO_SERVER_SYNC", "1")
    ).strip().lower() not in ("0", "false", "no", "off")


# ── Predicates (ask the policy, don't re-derive) ──────────────────────────────

def requires_live_server_sync(source_or_mode: Optional[str]) -> bool:
    """Should the AUTO (non-user-initiated) path verify against the live ai-pacs
    server (version check + delta sync)?

    LiveServer → always. LocalDatabase → only when the opt-in flag is on. Import /
    OfflineServer / CDBurn / Unknown → never (local/offline-first). A manual refresh
    bypasses this — it is a user-initiated action, not the auto path.
    """
    mode = resolve_workflow_mode(source_or_mode)
    if mode == WorkflowMode.LIVE_SERVER:
        return True
    if mode == WorkflowMode.LOCAL_DATABASE:
        return _localdb_auto_server_sync_enabled()
    return False


def requires_remote_resync(source_or_mode: Optional[str]) -> bool:
    """Should the AUTO reselect/reopen path run a remote resync at all?

    This is broader than ``requires_live_server_sync`` because the resync method
    serves two remotes: the **live ai-pacs server** (LiveServer → contentVersion
    delta sync) and the **offline-cloud** (OfflineServer → cloud preview sync, an
    offline rule). Both keep running. **LocalDatabase** only when the opt-in flag is
    set; **Import / CDBurn / Unknown** never (purely local — no remote to consult).
    A manual refresh bypasses this entirely.
    """
    mode = resolve_workflow_mode(source_or_mode)
    # Only the EXPLICITLY-local sources are skipped — those studies do not exist on
    # any remote, so a resync is a guaranteed no-op.
    if mode in (WorkflowMode.IMPORT, WorkflowMode.CD_BURN):
        return False
    if mode == WorkflowMode.LOCAL_DATABASE:
        return _localdb_auto_server_sync_enabled()
    # LiveServer + OfflineServer run; UNKNOWN runs too (no-regression default — a
    # not-yet-classified patient resyncs exactly as before and degrades gracefully
    # if the server lacks the study). This keeps the resync mode-agnostic except for
    # the two sources we KNOW are purely local.
    return True


def requires_server_version_check(source_or_mode: Optional[str]) -> bool:
    """Should the server's per-study ``contentVersion`` be consulted on open/refresh?
    Same set as ``requires_live_server_sync`` (the version check IS the live sync's
    cheap first gate)."""
    return requires_live_server_sync(source_or_mode)


def local_is_source_of_truth(source_or_mode: Optional[str]) -> bool:
    """Is the local DB/disk the authority (vs the live server)? True for every mode
    except an active LiveServer workflow."""
    return resolve_workflow_mode(source_or_mode) != WorkflowMode.LIVE_SERVER


def can_trust_local_cache_as_authoritative(source_or_mode: Optional[str]) -> bool:
    """May the local cache be treated as the authoritative current state (not just a
    display accelerator)? False only for LiveServer, where the server is truth and the
    cache is display-only."""
    return resolve_workflow_mode(source_or_mode) != WorkflowMode.LIVE_SERVER


def missing_files_trigger_server_download(source_or_mode: Optional[str]) -> bool:
    """If clinical files are missing on disk, may the client fetch them from the live
    ai-pacs server automatically?

    True wherever a live-server sync runs — LiveServer always, and LocalDatabase
    (a server-origin cached study) when auto-sync is on (the resync's disk-aware
    manifest pulls the missing/partial series). For OfflineServer the cloud rules
    govern (not the live server); for Import / CD / Unknown a missing file is a
    LOCAL missing-file condition, never a live-server fetch."""
    return requires_live_server_sync(source_or_mode)


def log_mode_decision(
    logger,
    *,
    mode: Optional[str] = None,
    source: Optional[str] = None,
    source_of_truth: Optional[str] = None,
    local_version=None,
    server_version=None,
    sync_skipped: Optional[bool] = None,
    reason: str = "",
    changed: Optional[str] = None,
    study_uid: str = "",
) -> None:
    """Emit one mode-aware decision line (best-effort; never raises).

    Shows the mode, the chosen source of truth, the local/server versions (when
    applicable), and whether sync was skipped and why / what changed. NEVER logs
    tokens, passwords, or credentials — callers must not pass any.
    """
    try:
        m = mode or resolve_workflow_mode(source)
        sot = source_of_truth or ("server" if m == WorkflowMode.LIVE_SERVER else "local")
        logger.info(
            "[SYNC_MODE] mode=%s source_of_truth=%s study=%s local_version=%s "
            "server_version=%s sync_skipped=%s reason=%s changed=%s",
            m, sot, (study_uid or "-"),
            ("-" if local_version is None else local_version),
            ("-" if server_version is None else server_version),
            ("-" if sync_skipped is None else int(bool(sync_skipped))),
            (reason or "-"), (changed or "-"),
        )
    except Exception:
        pass
