"""Shutdown-initiator diagnostic logging (2026-08-01).

A repeated "the app just closed by itself" with NO crash recorded (verified in
both the app fault log and the Windows Event Viewer) is only debuggable if the
app records WHAT initiated each quit. Three logging-only, flag-gated hooks:
  1. `_AIPacsApplication.quit()` override — the synchronous call site of every quit.
  2. `app.aboutToQuit` — the single universal quit signal + reason + visible windows.
  3. the workstation `closeEvent` — `spontaneous()` (user/OS close vs code close).

main.py / mainwindow_ui.py import Qt at module scope, so these are source-pinned.
All are gated by AIPACS_LOG_SHUTDOWN_INITIATOR (default on) and wrapped so they
can never affect startup or shutdown.
"""
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _main_src() -> str:
    return (_repo_root() / "main.py").read_text(encoding="utf-8", errors="replace")


def _mainwin_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "workstation_ui"
            / "mainwindow_ui.py").read_text(encoding="utf-8", errors="replace")


_FLAG = 'AIPACS_LOG_SHUTDOWN_INITIATOR'


def test_flag_is_default_on_kill_switch():
    # default on: the gate resolves truthy unless explicitly "0"
    for src in (_main_src(), _mainwin_src()):
        assert _FLAG in src
        assert f'os.environ.get("{_FLAG}", "1") != "0"' in src or \
               f'_os.environ.get("{_FLAG}", "1") != "0"' in src


def test_quit_override_logs_call_site_and_still_quits():
    src = _main_src()
    q = src[src.find("class _AIPacsApplication(QApplication):"):]
    q = q[:q.find("def notify(")]
    assert "def quit(self):" in q
    assert "[SHUTDOWN-INITIATOR] QApplication.quit() called" in q
    assert "format_stack()" in q
    # must ALWAYS fall through to the real quit (never block shutdown)
    assert "super().quit()" in q
    # logging must never raise into the quit path
    assert "except Exception:" in q


def test_about_to_quit_logger_is_connected():
    src = _main_src()
    assert "def _log_shutdown_initiator():" in src
    assert "app.aboutToQuit.connect(_log_shutdown_initiator)" in src
    # keeps the original loop.stop connection intact
    assert "app.aboutToQuit.connect(loop.stop)" in src
    # records the reason set by the more specific hooks + visible windows
    assert '_reason = getattr(app, "_shutdown_reason", "unknown")' in src
    assert "topLevelWidgets()" in src


def test_closeevent_records_spontaneous():
    src = _mainwin_src()
    ce = src[src.find("def closeEvent(self, event):"):]
    ce = ce[:ce.find("\n    def ", 10)]
    assert "[SHUTDOWN-INITIATOR] mainwindow.closeEvent spontaneous=" in ce
    assert "event.spontaneous()" in ce
    # sets a labeled reason the aboutToQuit hook will surface
    assert "_shutdown_reason" in ce
    assert "mainwindow_close_spontaneous" in ce
    assert "mainwindow_close_programmatic" in ce
    # the diagnostic must run BEFORE the real teardown and never block it
    i_diag = ce.find("[SHUTDOWN-INITIATOR]")
    i_teardown = ce.find("lifecycle_manager")
    assert -1 < i_diag < i_teardown


def test_hooks_are_logging_only_no_new_exit_calls():
    """The diagnostic must not introduce any new process-exit / quit side effect."""
    src = _main_src()
    q = src[src.find("class _AIPacsApplication(QApplication):"):]
    q = q[:q.find("def notify(")]
    # the override adds logging + one super().quit(); no os._exit / sys.exit here
    assert "os._exit" not in q
    assert "sys.exit" not in q
