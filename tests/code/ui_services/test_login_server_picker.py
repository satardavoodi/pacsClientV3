"""Guard: the login-page gear and Settings ▸ Server Settings share ONE server store.

Before (2026-07-13): the login gear (`modules/network/server_settings_dialog.py`)
wrote `socket_host` / `socket_port` / `connection_timeout` straight into
`socket_config.json` and knew nothing about the configured server list. Meanwhile
`socket_config._seed_from_active_profile()` seeds the live socket from the ACTIVE
server profile with `save_to_file=False` — so whatever the user typed into the gear
was overridden and ignored. The two screens were never connected.

Now the gear picks a server BY NAME from `PacsClient.utils.server_profiles` (the same
store Server Settings writes), activates that profile, and writes a port change back
to it — so both directions stay in sync.

Source-pin + API contract; no Qt needed.
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_DIALOG = os.path.join(_ROOT, "modules", "network", "server_settings_dialog.py")


def _read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def test_gear_reads_the_shared_server_profile_store():
    src = _read(_DIALOG)
    assert "server_profiles" in src, "login gear must use the shared server store"
    assert "list_profiles" in src, "it must list the CONFIGURED servers"


def test_gear_selects_server_by_name_not_ip():
    """User picks 'Razi Imaging Center', not 192.168.x.x.

    2026-08-02: the raw ``QComboBox`` was replaced by ``LoginComboField``, a
    styled composite that wraps one. What matters is that a DROPDOWN of server
    NAMES exists — not which class renders it — so the pin is widened to either.
    """
    src = _read(_DIALOG)
    assert "QComboBox" in src or "LoginComboField" in src
    assert "display_name" in src, "the dropdown must show the server NAME"
    # the legacy free-text host field must remain as a fallback, not the default
    assert "host_input" in src


def test_saving_writes_through_to_the_shared_store_both_directions():
    src = _read(_DIALOG)
    # choosing a server makes it the ACTIVE profile (Server Settings reads this)
    assert "set_active_profile_id" in src
    # a port edit is written back to THAT server's profile
    assert "upsert_profile" in src
    # and socket_config.json is mirrored so the legacy fallback cannot disagree
    assert 'self.config.set("socket_host"' in src
    assert 'self.config.set("socket_port"' in src


def test_all_four_fields_are_editable_inputs():
    """Host / Port / AE Title / Connection Timeout must be real editable inputs on
    the Welcome page (they used to be a read-only hint label)."""
    src = _read(_DIALOG)
    assert "self.host_input = QLineEdit()" in src, "Host must be editable"
    assert "self.port_input = LoginNumberField(" in src, "Port must be editable"
    assert "self.ae_input = QLineEdit()" in src, "AE Title must be editable"
    assert "self.timeout_input = LoginNumberField(" in src, "Timeout must be editable"
    # the old read-only echo label is gone
    assert "host_hint" not in src


def test_the_numeric_fields_accept_TYPED_input():
    """2026-08-02: ``QSpinBox`` was replaced by ``LoginNumberField``. The first
    cut of that widget rendered its value in a QLabel with +/-1 chevrons and no
    keyboard path at all — changing the socket port from 50052 to 104 would have
    taken ~49,948 clicks. This pins the ACTUAL requirement (a real text input),
    which the class name alone does not."""
    styles = _read(os.path.join(_ROOT, "PacsClient", "utils", "login_form_styles.py"))
    body = styles.split("class LoginNumberField(", 1)[1].split("\nclass ", 1)[0]
    assert "QLineEdit(self)" in body, "the value must be a real text input"
    assert "QIntValidator(" in body, "typed input must be range-validated"
    assert "editingFinished" in body, "a typed value must be committed"
    assert "def keyPressEvent" in body, "Up/Down must step, like QSpinBox"
    assert "setAutoRepeat" in styles, "the steppers must repeat when held"


def test_a_stray_scroll_cannot_silently_change_the_port():
    styles = _read(os.path.join(_ROOT, "PacsClient", "utils", "login_form_styles.py"))
    body = styles.split("class LoginNumberField(", 1)[1].split("\nclass ", 1)[0]
    wheel = body.split("def wheelEvent", 1)[1]
    assert "hasFocus()" in wheel, "wheel must only step a FOCUSED field"
    assert "event.ignore()" in wheel, "otherwise the scroll must reach the parent"


def test_edits_are_written_back_to_the_selected_profile():
    src = _read(_DIALOG)
    for field in ("prof.host = host",
                  "prof.socket_port = port",
                  "prof.ae_title = ae_title"):
        assert field in src, f"edit must sync to the profile: {field}"


def test_kill_switch_present():
    src = _read(_DIALOG)
    assert "AIPACS_LOGIN_SERVER_PICKER" in src
    assert "def _server_picker_enabled" in src


def test_server_profiles_api_contract():
    """The dialog depends on these; pin them so a refactor can't silently break it."""
    from PacsClient.utils import server_profiles as sp

    for fn in ("list_profiles", "get_active_profile_id", "set_active_profile_id",
               "upsert_profile", "server_profiles_enabled"):
        assert callable(getattr(sp, fn, None)), f"server_profiles.{fn} is missing"

    # the fields the login dropdown renders / writes
    for fieldname in ("display_name", "host", "socket_port", "ae_title", "id"):
        assert fieldname in sp.ServerProfile.__dataclass_fields__, fieldname
