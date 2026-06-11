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

logger = logging.getLogger(__name__)

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


def run_installed_app_flow(
    client_config: dict,
    scopes: list[str] | None = None,
    *,
    auth_url_kwargs: dict | None = None,
    open_url_cb=None,
):
    """Run the loopback PKCE flow. Returns google ``Credentials``. BLOCKING.

    Best-effort enhancement (2026-06-10): when the internal Web Browser module
    is enabled, the consent URL is rendered in the embedded browser window
    instead of the system browser — the loopback redirect server is unchanged.
    ANY failure of the embedded path silently falls back to the original
    system-browser behaviour (zero regression risk).

    Additive (ADR-0008, 2026-06-11): ``auth_url_kwargs`` is forwarded to
    ``flow.authorization_url`` (e.g. ``{"prompt": "select_account"}`` for the
    transient Gmail attestation); ``open_url_cb`` lets a caller override how
    the consent URL is opened (skips the embedded/system auto-selection).
    Defaults keep the original behaviour byte-identical.
    """
    if open_url_cb is not None:
        return _run_flow_embedded(
            client_config, scopes,
            auth_url_kwargs=auth_url_kwargs, open_url=open_url_cb,
        )
    if _embedded_browser_usable():
        try:
            return _run_flow_embedded(
                client_config, scopes, auth_url_kwargs=auth_url_kwargs
            )
        except Exception as exc:
            logger.warning(
                "Embedded-browser OAuth failed; falling back to system browser: %s",
                exc,
            )

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
# POLICY (owner directive 2026-06-11): the internal Web Browser module is the
# DEFAULT surface for ALL identity verification/connection flows (Drive
# connect, Gmail attestation, future providers). The system browser is ONLY a
# fallback for when the web_browser module is not installed/enabled or no Qt
# application exists (e.g. CLI tools). New verification flows must route
# through run_installed_app_flow() or open_verification_url() — never call
# webbrowser.open() directly.
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


def _open_url_on_gui_thread(url: str) -> None:
    """Open ``url`` in the embedded WebBrowserWidget, marshalled to the GUI thread.

    Called from the OAuth worker thread. If the embedded open fails on the GUI
    side, it falls back to the system browser THERE, so the URL is always
    opened one way or another and the loopback wait below can complete.
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

    def _open():
        try:
            from PySide6.QtCore import Qt, QUrl

            from modules.web_browser import WebBrowserWidget

            browser = WebBrowserWidget()
            browser.setAttribute(Qt.WA_DeleteOnClose, True)
            browser.setWindowTitle("Google sign-in — AI-PACS")
            browser.resize(980, 720)
            browser.web_view.setUrl(QUrl(url))
            browser.show()
            browser.raise_()
            # Keep a reference alive on the application object.
            holders = getattr(app, "_aipacs_oauth_browsers", [])
            holders.append(browser)
            app._aipacs_oauth_browsers = holders
        except Exception as exc:
            logger.warning(
                "Embedded browser open failed; using system browser: %s", exc
            )
            import webbrowser

            webbrowser.open(url, new=1, autoraise=True)

    invoker = _Invoker()
    invoker.moveToThread(app.thread())
    # Parent assignment must happen on the owning thread; keep a module ref instead.
    global _INVOKER_KEEPALIVE
    _INVOKER_KEEPALIVE = invoker
    QCoreApplication.postEvent(invoker, _CallEvent(_open))


_INVOKER_KEEPALIVE = None


def _run_flow_embedded(
    client_config: dict,
    scopes: list[str] | None,
    *,
    auth_url_kwargs: dict | None = None,
    open_url=None,
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

        (open_url or _open_url_on_gui_thread)(auth_url)

        # Blocks this (worker) thread until the redirect arrives — same
        # behaviour as flow.run_local_server.
        local_server.handle_request()

        if not wsgi_app.last_request_uri:
            raise RuntimeError("OAuth redirect was not received.")
        authorization_response = wsgi_app.last_request_uri.replace("http", "https", 1)
        flow.fetch_token(authorization_response=authorization_response)
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
