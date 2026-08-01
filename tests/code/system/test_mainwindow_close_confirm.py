"""Exit confirmation dialog on main window close."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = (REPO / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py").read_text(
    encoding="utf-8"
)


def test_close_event_requires_confirmation():
    assert "def _confirm_application_exit(self)" in SRC
    assert "Are you sure you want to close the application?" in SRC
    assert "_exit_confirmed" in SRC
    assert "event.ignore()" in SRC


def test_user_account_menu_wiring():
    src = (REPO / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py").read_text(
        encoding="utf-8"
    )
    assert "attach_user_account_menu" in src
    menu_src = (
        REPO / "PacsClient" / "pacs" / "workstation_ui" / "user_account_menu.py"
    ).read_text(encoding="utf-8")
    assert "ACCOUNT" in menu_src
    assert "Settings" in menu_src
    assert "Internal Assignments" in menu_src
