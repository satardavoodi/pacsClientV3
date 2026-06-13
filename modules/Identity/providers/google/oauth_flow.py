"""Google OAuth 2.0 Authorization-Code + PKCE flow for a Desktop (installed) app.

Uses ``google-auth-oauthlib``'s ``InstalledAppFlow`` which implements the
Google-recommended desktop flow: opens the system browser and runs a one-shot
loopback HTTP server on an ephemeral port to receive the authorization code, with
PKCE applied by the library. **Blocking** — callers must run :func:`run_installed_app_flow`
off the Qt UI thread.

All heavy imports are local so importing this module is cheap and does not require
the google libraries to be installed.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ── OAuth surface policy (owner directive 2026-06-12, see pipeline doc §11.6) ────
# The owner wants the Google sign-in / consent to open inside OUR embedded Web
# Browser module (the docked QtWebEngine tab), NOT the external system browser.
# An earlier crash fix over-corrected by flipping the default to the system
# browser; this restores embedded-by-default.
#
# The earlier crash was a hard process kill — Windows fatal exception 0x8001010d
# (RPC_E_CANTCALLOUT_ININPUTSYNCCALL): a COM call made by QtWebEngine while the
# Qt event loop was dispatching an input-synchronous message. That is NOT a
# Python exception and cannot be try/excepted, so the embedded path is
# crash-HARDENED instead of disabled:
#   * the consent URL is opened EXACTLY ONCE per flow (no run_local_server
#     open_browser, no double-open);
#   * the open is QUEUED onto the GUI thread (``_call_on_gui_thread`` / postEvent)
#     — never run synchronously inside an input-sync click dispatch;
#   * the actual QtWebEngine navigate runs on a CLEAN event-loop turn
#     (``QTimer.singleShot(0, …)``) so it is not performed inside the postEvent
#     handler that may itself be mid-input-dispatch (the standard 0x8001010d
#     mitigation);
#   * a ``_DOCKED_FLOW_GEN`` generation guard makes a prior attempt's deferred
#     reset/re-assert no-op against a newer attempt's browser.
#
# Policy:
#   * DEFAULT = embedded docked Web Browser module WHEN usable
#     (``_embedded_browser_usable()``: web_browser module enabled + live
#     QApplication).
#   * SYSTEM browser is the automatic FALLBACK (a) when the embedded surface is
#     not usable (headless / CLI / module off), and (b) on ANY Python-level
#     failure of the embedded path.
#   * KILL-SWITCH (force system browser): env ``AIPACS_OAUTH_EMBEDDED=0`` (or
#     ``off``/``false``/``no``) OR ``oauth_embedded: false`` in
#     ``config/cloud_consultation/cloud_consultation.json``. Env wins over config.
#   * An explicit caller-supplied ``open_url_cb`` is always honoured verbatim.
# ``open_verification_url`` (non-OAuth, plain navigation) is unchanged.
_OAUTH_EMBEDDED_ENV = "AIPACS_OAUTH_EMBEDDED"
_FORCE_SYSTEM_VALUES = ("0", "false", "off", "no", "disabled")
_FORCE_EMBEDDED_VALUES = ("1", "true", "on", "yes", "enabled")


def _oauth_embedded_kill_switch() -> bool:
    """True when the operator has FORCED the system browser (kill-switch),
    disabling the embedded surface for OAuth.

    Resolution (env wins over config):
      * env ``AIPACS_OAUTH_EMBEDDED`` in {0, off, false, no, disabled} → forced;
        in {1, on, true, yes, enabled} → NOT forced (embedded re-asserted).
      * else config ``oauth_embedded: false`` in
        ``config/cloud_consultation/cloud_consultation.json`` → forced.
      * default (neither set) → False (embedded is the default surface).

    Kept dependency-free + guarded so importing this module stays cheap and a
    bad config can never break the flow. Never raises."""
    raw = (os.environ.get(_OAUTH_EMBEDDED_ENV) or "").strip().lower()
    if raw in _FORCE_SYSTEM_VALUES:
        return True
    if raw in _FORCE_EMBEDDED_VALUES:
        return False
    # No env directive → honour the config kill-switch if present.
    try:
        val = _config_oauth_embedded()
        if val is False:
            return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("oauth_embedded config read failed: %s", exc)
    return False


def _config_oauth_embedded():
    """Return the ``oauth_embedded`` value from the cloud-consultation flag file
    (True/False) or ``None`` when absent/unreadable. Lazy import + guarded so
    this module stays import-cheap and never raises. Env is resolved separately
    (and wins) by the caller."""
    try:
        from modules.cloud_consultation.feature_flags import _flag_payload

        data = _flag_payload()
        if isinstance(data, dict) and "oauth_embedded" in data:
            return bool(data["oauth_embedded"])
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("oauth_embedded config lookup failed: %s", exc)
    return None


def _resolve_oauth_surface():
    """Decide whether OAuth uses the embedded docked browser or the system
    browser, and WHY (for the ``[OAUTH_SURFACE]`` log).

    Returns ``(use_embedded: bool, reason: str)``. Reasons:
      * ``"kill-switch"``   — operator forced the system browser.
      * ``"not-usable"``    — embedded surface unavailable (headless/CLI/off).
      * ``"default-embedded"`` — embedded-when-usable (the new default).
    The post-failure ``"fallback-after-failure"`` reason is logged by the
    caller when an embedded attempt raises and we fall through to system."""
    if _oauth_embedded_kill_switch():
        return False, "kill-switch"
    if not _embedded_browser_usable():
        return False, "not-usable"
    return True, "default-embedded"

# OpenID Connect + Drive (per-file) scopes. ``drive.file`` is non-sensitive and only
# grants access to files this app creates/opens — minimal verification burden.
DEFAULT_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",
]

USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


_SUCCESS_MESSAGE = (
    "AI-PACS: Google sign-in complete. You can close this tab and return "
    "to AI-PACS."
)


class EmbeddedAuthUnavailable(RuntimeError):
    """Raised when a caller requires the internal Web Browser surface
    (``require_embedded=True``) but it cannot be used. Callers surface this as a
    retryable in-workstation error — it is NEVER silently downgraded to an
    external system browser (ADR-0009 D5)."""


def run_installed_app_flow(
    client_config: dict,
    scopes: list[str] | None = None,
    *,
    auth_url_kwargs: dict | None = None,
    open_url_cb=None,
    require_embedded: bool = False,
):
    """Run the loopback PKCE flow. Returns google ``Credentials``. BLOCKING.

    SURFACE POLICY (owner directive 2026-06-12, pipeline doc §11.6): the
    embedded docked Web Browser module is the DEFAULT surface when it is usable
    (web_browser module + live QApplication). The SYSTEM browser is the
    automatic FALLBACK when the embedded surface is not usable (headless/CLI/
    module off) OR on ANY Python-level failure of the embedded path. A
    KILL-SWITCH forces the system browser: env ``AIPACS_OAUTH_EMBEDDED=0``
    (or off/false/no) OR config ``oauth_embedded: false`` (env wins). The
    embedded path is crash-hardened (queued open + clean-turn navigate +
    generation guard) so it cannot reintroduce the 0x8001010d GUI-thread COM
    crash.

    Additive (ADR-0008, 2026-06-11): ``auth_url_kwargs`` is forwarded to
    ``flow.authorization_url`` (e.g. ``{"prompt": "select_account"}`` for the
    transient Gmail attestation); ``open_url_cb`` lets a caller EXPLICITLY
    override how the consent URL is opened (an explicit caller-supplied opener
    is always honoured — it is the caller's own choice, not the embedded
    auto-selection). Defaults keep the original behaviour byte-identical.
    """
    if open_url_cb is not None:
        # Explicit caller-supplied opener: honour it verbatim (the caller owns
        # the surface choice — e.g. a CLI/test harness or a deliberate embed).
        logger.info("[OAUTH_SURFACE] surface=docked reason=explicit-open-url-cb")
        return _run_flow_embedded(
            client_config, scopes,
            auth_url_kwargs=auth_url_kwargs, open_url=open_url_cb,
        )
    if require_embedded:
        # ADR-0009 D5: the consultation/hub connect path must stay inside the
        # internal Web Browser module — NEVER the external system browser. Force
        # the embedded surface; on unavailability or failure raise (the caller
        # shows a retryable in-app error). The env/config kill-switch does not
        # downgrade THIS path to the system browser.
        if not _embedded_browser_usable():
            raise EmbeddedAuthUnavailable(
                "The AI-PACS Web Browser module is unavailable, so Google "
                "sign-in cannot open. Please try again."
            )
        logger.info("[OAUTH_SURFACE] surface=docked reason=require-embedded")
        try:
            return _run_flow_embedded(
                client_config, scopes,
                auth_url_kwargs=auth_url_kwargs, require_embedded=True,
            )
        except EmbeddedAuthUnavailable:
            raise
        except Exception as exc:
            logger.warning("[OAUTH_SURFACE] require-embedded path failed: %s", exc)
            raise EmbeddedAuthUnavailable(
                "Google sign-in couldn't open in the AI-PACS browser. "
                "Please try again."
            ) from exc

    # Default = embedded docked browser WHEN usable; system browser is the
    # fallback (not-usable / kill-switch / after an embedded failure).
    use_embedded, reason = _resolve_oauth_surface()
    if use_embedded:
        logger.info("[OAUTH_SURFACE] surface=docked reason=%s", reason)
        try:
            return _run_flow_embedded(
                client_config, scopes, auth_url_kwargs=auth_url_kwargs
            )
        except Exception as exc:
            # ANY Python-level failure of the embedded path falls back to the
            # system browser so sign-in can still complete. (A 0x8001010d COM
            # crash is NOT a Python exception — that is prevented up-front by
            # the queued open + clean-turn navigate + generation guard, not
            # caught here.)
            logger.warning(
                "[OAUTH_SURFACE] surface=system reason=fallback-after-failure (%s)",
                exc,
            )
    else:
        logger.info("[OAUTH_SURFACE] surface=system reason=%s", reason)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        client_config, scopes=scopes or DEFAULT_SCOPES
    )
    # port=0 -> ephemeral loopback port; opens the system browser. Extra
    # kwargs are forwarded by the library to flow.authorization_url().
    creds = flow.run_local_server(
        port=0,
        open_browser=True,
        authorization_prompt_message="",
        success_message=_SUCCESS_MESSAGE,
        **(auth_url_kwargs or {}),
    )
    return creds


# ── embedded-browser variant ───────────────────────────────────────────────────
# POLICY (owner directive 2026-06-12, supersedes the 2026-06-12 system-default
# over-correction; restores the 2026-06-11 embedded default):
#   * OAuth / attestation (the loopback InstalledAppFlow — Gmail attestation,
#     Drive connect) DEFAULTS to the embedded docked Web Browser module when it
#     is usable. The system browser is the FALLBACK (not-usable / kill-switch /
#     embedded failure).
#   * Non-OAuth plain navigation (open_verification_url) also uses the embedded
#     Web Browser module — no loopback/COM-in-input-sync hazard for a plain open.
# Either way, new flows must route through run_installed_app_flow() or
# open_verification_url() — never call webbrowser.open() directly.
#
# CRASH-HARDENING CONTRACT (0x8001010d / RPC_E_CANTCALLOUT_ININPUTSYNCCALL):
# Any call that can trigger COM work — QtWebEngine view creation/navigation,
# clipboard access, native file dialogs, modal event loops — MUST NEVER run
# synchronously inside an input-synchronous click/keypress dispatch on the GUI
# thread. They must be QUEUED onto the GUI thread (_call_on_gui_thread /
# postEvent) and, for the QtWebEngine navigate specifically, deferred one more
# clean event-loop turn (QTimer.singleShot(0, …)) so they do not run inside the
# postEvent handler that may itself be mid-input-dispatch.
def open_verification_url(url: str) -> bool:
    """Open a verification/consent URL in the internal Web Browser module.

    Returns True when the embedded browser was used; False when the caller
    must fall back to the system browser (module unavailable / headless).
    Safe to call from worker threads (GUI work is marshalled). Never raises.
    """
    try:
        if not _embedded_browser_usable():
            return False
        _open_url_on_gui_thread(url)
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("open_verification_url fell back: %s", exc)
        return False


def _embedded_browser_usable() -> bool:
    """True only when the web_browser module is enabled, importable, and a Qt
    GUI application exists. Never raises."""
    try:
        from aipacs_runtime import is_module_enabled

        if not is_module_enabled("web_browser"):
            return False
        import modules.web_browser  # noqa: F401 - import check only

        from PySide6.QtWidgets import QApplication

        return QApplication.instance() is not None
    except Exception as exc:
        logger.debug("embedded browser not usable: %s", exc)
        return False


def _call_on_gui_thread(fn) -> None:
    """Run ``fn`` on the Qt GUI thread (queued, fire-and-forget). Never blocks.

    Extracted from the original ``_open_url_on_gui_thread`` so the post-auth
    docked-browser reset can reuse the same marshalling pattern.
    """
    from PySide6.QtCore import QCoreApplication, QEvent, QObject
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("No QApplication for embedded browser")

    class _CallEvent(QEvent):
        TYPE = QEvent.Type(QEvent.registerEventType())

        def __init__(self, fn):
            super().__init__(self.TYPE)
            self.fn = fn

    class _Invoker(QObject):
        def event(self, e):
            if isinstance(e, _CallEvent):
                try:
                    e.fn()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("GUI-thread call failed: %s", exc)
                return True
            return super().event(e)

    invoker = _Invoker()
    invoker.moveToThread(app.thread())
    # Parent assignment must happen on the owning thread; keep a module ref instead.
    _INVOKER_KEEPALIVE.append(invoker)
    del _INVOKER_KEEPALIVE[:-8]  # bound the keepalive list
    QCoreApplication.postEvent(invoker, _CallEvent(fn))


def _find_home_panel():
    """Locate the live HomePanelWidget that owns ``open_web_browser``.

    Mirrors ``modules/education/online_consultation/launcher.py::_find_home_panel``
    (no PacsClient import — pure widget-tree lookup). Never raises.
    """
    try:
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return None
        # Fast path: any top-level exposing ui.home_widget (ControlPanelInterface).
        for w in QApplication.topLevelWidgets():
            ui = getattr(w, "ui", None)
            hw = getattr(ui, "home_widget", None) or getattr(w, "home_widget", None)
            if hw is not None and hasattr(hw, "open_web_browser"):
                return hw
        # Fallback: scan all widgets once (user-initiated flow; acceptable).
        for w in QApplication.allWidgets():
            if w.__class__.__name__ == "HomePanelWidget" and hasattr(
                w, "open_web_browser"
            ):
                return w
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("home panel lookup failed: %s", exc)
    return None


def _open_docked_browser(url: str) -> None:
    """Open the web_browser module in its NORMAL docked home-page tab and
    navigate it to ``url``. GUI thread only. Raises on ANY failure so the
    caller falls back to the floating window (the pre-2026-06-11 behaviour).

    CRASH-HARDENING (0x8001010d): the QtWebEngine ``setUrl`` navigate is the COM
    trigger. This function is already reached on the GUI thread via a QUEUED
    postEvent (``_call_on_gui_thread``), but the postEvent handler itself can run
    while Windows is dispatching an input-synchronous message. So the navigate is
    deferred ONE MORE clean event-loop turn with ``QTimer.singleShot(0, …)`` —
    the standard RPC_E_CANTCALLOUT_ININPUTSYNCCALL mitigation. Tab creation
    (``open_web_browser``) does not navigate, so it stays inline. The deferred
    navigate is guarded + generation-checked so it never raises and a stale
    callback can never touch a newer flow's browser.
    """
    import weakref

    from PySide6.QtCore import QTimer, QUrl

    home = _find_home_panel()
    if home is None:
        raise RuntimeError("home panel not found")
    widget = home.open_web_browser(show_unavailable_dialog=False)
    if widget is None:
        raise RuntimeError("open_web_browser returned no widget")
    view = getattr(widget, "web_view", None)
    if view is None:
        raise RuntimeError("web browser widget has no web_view")

    # Generation guard (crash-hardening 2026-06-12): a second flow opening the
    # docked browser invalidates a still-pending re-assert/reset from a prior
    # flow, so a stale deferred callback can never navigate the browser the new
    # flow is using (the open-reset-open race observed in the 0x8001010d log).
    global _DOCKED_BROWSER_REF, _DOCKED_FLOW_GEN
    _DOCKED_FLOW_GEN += 1
    gen = _DOCKED_FLOW_GEN
    _DOCKED_BROWSER_REF = weakref.ref(widget)

    def _navigate_clean_turn():
        # Runs on a fresh event-loop turn (NOT inside the postEvent handler that
        # may be mid-input-dispatch). This is where the QtWebEngine COM work
        # happens; doing it here is what keeps 0x8001010d from firing.
        try:
            if gen != _DOCKED_FLOW_GEN:
                return  # a newer flow took over the docked browser; do not fight it
            ref = _DOCKED_BROWSER_REF
            w = ref() if ref is not None else None
            v = getattr(w, "web_view", None) if w is not None else None
            if v is not None:
                v.setUrl(QUrl(url))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("docked clean-turn navigate skipped: %s", exc)

    # 0-delay: next clean event-loop turn (the COM-safe navigate).
    QTimer.singleShot(0, _navigate_clean_turn)

    def _reassert():
        # The tab may have been created this very call; a deferred home/session
        # load could overwrite the consent URL — re-assert once after settling.
        try:
            if gen != _DOCKED_FLOW_GEN:
                return  # a newer flow took over; do not fight it
            ref = _DOCKED_BROWSER_REF
            w = ref() if ref is not None else None
            if w is not None and getattr(w, "web_view", None) is not None:
                if w.web_view.url().toString() != url:
                    w.web_view.setUrl(QUrl(url))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("docked URL re-assert skipped: %s", exc)

    QTimer.singleShot(250, _reassert)


def _open_floating_browser(url: str) -> None:
    """The original floating WebBrowserWidget window (fallback #2)."""
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtWidgets import QApplication

    from modules.web_browser import WebBrowserWidget

    app = QApplication.instance()
    browser = WebBrowserWidget()
    browser.setAttribute(Qt.WA_DeleteOnClose, True)
    browser.setWindowTitle("Google sign-in — AI-PACS")
    browser.resize(980, 720)
    browser.web_view.setUrl(QUrl(url))
    browser.show()
    browser.raise_()
    # Keep a reference alive on the application object.
    if app is not None:
        holders = getattr(app, "_aipacs_oauth_browsers", [])
        holders.append(browser)
        app._aipacs_oauth_browsers = holders


def _open_url_on_gui_thread(url: str, *, require_embedded: bool = False) -> None:
    """Open ``url`` for the user, marshalled to the GUI thread.

    Called from the OAuth worker thread. Surface chain (owner directive
    2026-06-12): DOCKED web_browser module tab (its normal home-page
    container) → floating WebBrowserWidget window → system browser. Each
    fallback engages on ANY failure of the previous step, so the URL is always
    opened one way or another and the loopback wait can complete. The chosen
    surface is logged as ``[OAUTH_SURFACE]`` for live QA.

    CRASH-HARDENING: the open is QUEUED via ``_call_on_gui_thread`` (postEvent)
    — never run synchronously inside an input-sync click dispatch — and the
    docked QtWebEngine navigate is itself deferred one more clean event-loop
    turn inside ``_open_docked_browser`` (the 0x8001010d mitigation).
    """

    def _open():
        surface = "docked"
        reason = "default-embedded"
        try:
            _open_docked_browser(url)
        except Exception as exc:
            logger.debug("[OAUTH_SURFACE] docked open failed (%s); trying floating", exc)
            surface = "floating"
            reason = "fallback-after-failure"
            try:
                _open_floating_browser(url)
            except Exception as exc2:
                if require_embedded:
                    # ADR-0009 D5: both embedded surfaces failed for a path that
                    # must stay inside the workstation. Do NOT open Chrome/Edge/
                    # the default browser; log so the loopback aborts/cancels.
                    surface = "none"
                    reason = "embedded-required-no-external"
                    logger.warning(
                        "[OAUTH_SURFACE] embedded surfaces failed, require_embedded"
                        "=True; NOT launching external browser (%s)", exc2,
                    )
                else:
                    logger.warning(
                        "Embedded browser open failed; using system browser: %s", exc2
                    )
                    surface = "system"
                    reason = "fallback-after-failure"
                    import webbrowser

                    webbrowser.open(url, new=1, autoraise=True)
        logger.info(
            "[OAUTH_SURFACE] consent URL opened via surface=%s reason=%s",
            surface, reason,
        )

    _call_on_gui_thread(_open)


def _reset_docked_browser_after_auth() -> None:
    """BEST-EFFORT: send the docked browser back to a neutral page after the
    loopback redirect arrived, so the consent page does not linger. Never
    required for the flow, never raises. No-op when the docked surface was not
    used (floating/system fallbacks keep their existing behaviour)."""
    global _DOCKED_BROWSER_REF
    ref, _DOCKED_BROWSER_REF = _DOCKED_BROWSER_REF, None
    if ref is None:
        return
    gen = _DOCKED_FLOW_GEN  # the flow we are resetting for

    def _reset():
        try:
            if gen != _DOCKED_FLOW_GEN:
                return  # a newer flow took over the docked browser — leave it
            w = ref()
            if w is None:
                return
            if hasattr(w, "navigate_home"):
                w.navigate_home()
            else:  # pragma: no cover - older widget API
                from PySide6.QtCore import QUrl

                w.web_view.setUrl(QUrl("about:blank"))
            logger.info("[OAUTH_SURFACE] docked browser reset to home after auth")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("docked post-auth reset skipped: %s", exc)

    try:
        _call_on_gui_thread(_reset)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("post-auth reset marshal skipped: %s", exc)


_INVOKER_KEEPALIVE: list = []
_DOCKED_BROWSER_REF = None
# Monotonic counter: bumped each time the docked browser is opened for a flow so
# a stale deferred re-assert/reset from an earlier flow never navigates the
# browser a newer flow is using (crash-hardening 2026-06-12).
_DOCKED_FLOW_GEN = 0


def _run_flow_embedded(
    client_config: dict,
    scopes: list[str] | None,
    *,
    auth_url_kwargs: dict | None = None,
    open_url=None,
    require_embedded: bool = False,
):
    """The run_local_server pattern, split so WE control how the URL is opened.

    Identical loopback redirect server + PKCE handling (uses
    google_auth_oauthlib's own WSGI helpers); only the browser launch differs.
    Raises on any setup mismatch — the caller falls back to run_local_server.
    """
    import wsgiref.simple_server

    from google_auth_oauthlib.flow import InstalledAppFlow

    # Internal helpers of google_auth_oauthlib — verified present for the pinned
    # version; ImportError here simply triggers the system-browser fallback.
    from google_auth_oauthlib.flow import _RedirectWSGIApp, _WSGIRequestHandler

    flow = InstalledAppFlow.from_client_config(
        client_config, scopes=scopes or DEFAULT_SCOPES
    )

    wsgi_app = _RedirectWSGIApp(_SUCCESS_MESSAGE)
    wsgiref.simple_server.WSGIServer.allow_reuse_address = False
    local_server = wsgiref.simple_server.make_server(
        "localhost", 0, wsgi_app, handler_class=_WSGIRequestHandler
    )
    try:
        flow.redirect_uri = f"http://localhost:{local_server.server_port}/"
        auth_url, _ = flow.authorization_url(**(auth_url_kwargs or {}))

        if open_url is not None:
            open_url(auth_url)
        else:
            _open_url_on_gui_thread(auth_url, require_embedded=require_embedded)

        # Blocks this (worker) thread until the redirect arrives — same
        # behaviour as flow.run_local_server.
        local_server.handle_request()

        if not wsgi_app.last_request_uri:
            raise RuntimeError("OAuth redirect was not received.")
        authorization_response = wsgi_app.last_request_uri.replace("http", "https", 1)
        flow.fetch_token(authorization_response=authorization_response)
        # Loopback hit + token exchanged: don't leave the consent page lingering
        # in the docked browser (best-effort, guarded, never required).
        _reset_docked_browser_after_auth()
        return flow.credentials
    finally:
        local_server.server_close()


def fetch_userinfo(creds) -> dict:
    """Fetch the OIDC userinfo (sub, email, name, picture, email_verified)."""
    import requests

    resp = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def revoke_token(refresh_or_access_token: str) -> bool:
    """Best-effort revoke at Google. Returns True on HTTP 200."""
    import requests

    try:
        resp = requests.post(
            REVOKE_URL,
            params={"token": refresh_or_access_token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("Google token revoke failed: %s", exc)
        return False


def credentials_to_payload(creds) -> dict:
    """Serialize google ``Credentials`` to a JSON-safe payload for secure storage."""
    expiry = getattr(creds, "expiry", None)
    return {
        "token": getattr(creds, "token", None),
        "refresh_token": getattr(creds, "refresh_token", None),
        "token_uri": getattr(creds, "token_uri", None),
        "client_id": getattr(creds, "client_id", None),
        "client_secret": getattr(creds, "client_secret", None),
        "scopes": list(getattr(creds, "scopes", None) or []),
        "expiry": expiry.isoformat() if expiry else None,
    }


def payload_to_credentials(payload: dict):
    """Rebuild google ``Credentials`` from a stored payload (for later API calls)."""
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=payload.get("token"),
        refresh_token=payload.get("refresh_token"),
        token_uri=payload.get("token_uri"),
        client_id=payload.get("client_id"),
        client_secret=payload.get("client_secret"),
        scopes=payload.get("scopes"),
    )
