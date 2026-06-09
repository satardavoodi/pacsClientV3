"""Guards for two 2026-06-09 fixes.

1. F12 global Secretary popup — confirmation dialog must parent to the REAL
   main window (not the always-on-top Qt.Tool popup) and sit above it, so a
   confirmed action (e.g. download) actually executes instead of silently
   cancelling ("asks for confirmation, then nothing happens"). Plus, when
   hosted in the popup, a successful home-data command brings the Home page
   forward so the result is visible.

2. Patient-Tab status/sync comment — must ride the SAME comment pipeline as
   the Main-Page Report popup: the shared local cache (_save/_load_local_
   comment_entry) AND the REST comment endpoint (_sync_comment_to_server),
   with the socket status call gated on an ACTUAL status change. No duplicate
   / disconnected storage.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_PW_PANELS = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
              / "patient_widget_core" / "_pw_panels.py")
_TOOLBAR = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
            / "patient_toolbar" / "toolbar_manager.py")
_SEC_WIDGET = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
               / "secretary_button_widget.py")
_SEC_POPUP = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
              / "secretary_popup.py")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _no_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


# ───────────────────── 1. F12 confirm-dialog parenting ────────────────────

def test_confirm_dialog_parents_to_main_window_not_popup():
    src = _read(_SEC_WIDGET)
    start = src.index("def _show_secretary_confirm_dialog")
    end = src.index("def append_log", start)
    body = _no_comments(src[start:end])
    # Resolve the real main window via the home widget, not self.window().
    assert "get_home_widget" in body, "confirm dialog must resolve the real main window"
    assert "hw.window()" in body
    # And the dialog must be lifted above the always-on-top F12 popup.
    assert "WindowStaysOnTopHint" in body


def test_popup_marks_inner_as_global_hosted():
    body = _no_comments(_read(_SEC_POPUP))
    assert "_in_global_popup = True" in body


def test_secretary_surfaces_home_result_when_hosted_in_popup():
    src = _read(_SEC_WIDGET)
    body = _no_comments(src)
    assert "_HOME_RESULT_ACTIONS" in body
    assert "def _maybe_surface_home_result" in body
    # Wired into the result handler.
    assert "self._maybe_surface_home_result(result or {})" in body
    # Only acts when hosted in the popup + only on success.
    fn_start = body.index("def _maybe_surface_home_result")
    fn = body[fn_start:fn_start + 1400]
    assert "_in_global_popup" in fn
    assert '.get("ok")' in fn
    assert "_show_home_page" in fn


# ───────────────── 2. Patient-Tab comment shared pipeline ─────────────────

def test_pw_change_report_status_uses_shared_comment_store():
    src = _read(_PW_PANELS)
    body = _no_comments(src)
    assert "def _get_shared_comment_store" in body
    # Reuses the Main-Page patient table's store (one storage, no fork).
    assert "patient_table_widget" in body
    start = body.index("def _change_report_status")
    end = body.index("def _handle_status_update_result", start)
    method = body[start:end]
    # Local save + REST comment sync (the Main-Page mechanism), not socket-only.
    assert "_save_local_comment_entry" in method
    assert "_sync_comment_to_server" in method
    # Socket status update is gated on an actual status change.
    assert "status_changed" in method
    assert "if status_changed and report_status_service" in method


def test_toolbar_dropdown_prefills_comment_from_shared_cache():
    body = _no_comments(_read(_TOOLBAR))
    assert "_get_shared_comment_store" in body
    assert "_load_local_comment_entry" in body


def test_change_report_status_comment_only_skips_socket_uses_rest():
    """Behavioral: a comment-only update (status unchanged) must NOT call the
    socket status service, but MUST save locally and POST via the REST comment
    endpoint — the gap that made the Patient-Tab comment vanish."""
    src = _read(_PW_PANELS)
    start = src.index("    def _change_report_status")
    end = src.index("    def _handle_status_update_result", start)
    method_src = src[start:end]

    # Run the method body synchronously by faking threading.Thread.
    class _FakeThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    class _FakeThreading:
        Thread = _FakeThread

    class _Store:
        def __init__(self):
            self.saved = []
            self.synced = []

        def _save_local_comment_entry(self, pid, suid, comment, sync_state, sync_error=""):
            self.saved.append((pid, suid, comment, sync_state))
            return True

        def _sync_comment_to_server(self, pid, comment):
            self.synced.append((pid, comment))
            return {"success": True}

    class _Service:
        def __init__(self):
            self.calls = []

        def update_report_status(self, study_uid, new_status, user_id=None, comment=None):
            self.calls.append((study_uid, new_status, comment))
            return {"ok": True}

    store = _Store()
    service = _Service()

    class _Holder:
        report_comment = ""

        def _resolve_patient_id_for_comment(self):
            return "P1"

        def _get_shared_comment_store(self):
            return store

        def _get_report_status_service(self):
            return service

        def _handle_status_update_result(self, *a, **k):
            raise AssertionError("status UI must not run for a comment-only update")

    # _change_report_status now emits structured logger output (so the viewer
    # comment-sync is visible in app.log) — provide a logger for the isolated exec.
    ns = {"threading": _FakeThreading, "logger": __import__("logging").getLogger("test")}
    exec("class _Bind:\n" + method_src, ns)  # noqa: S102 — test-local exec of repo source
    bound = ns["_Bind"]._change_report_status
    holder = _Holder()

    # comment-only: old == new
    ok = bound(holder, "1.2.3", "pending", "pending", comment="follow up with CT")
    assert ok is True
    # socket status service NOT called (status unchanged)
    assert service.calls == []
    # comment saved locally AND synced to server via REST
    assert any(c == "follow up with CT" for (_p, c) in store.synced)
    assert any(s[3] == "local_only" for s in store.saved)
    assert any(s[3] == "synced" for s in store.saved)
