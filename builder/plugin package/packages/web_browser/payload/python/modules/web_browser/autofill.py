"""Secure credential autofill helpers for the Web Browser (2026-06-27).

Restores the "remember my login and offer to fill it" feature on top of the
existing encrypted credential vault (``credential_vault.py`` → OS keychain /
Windows DPAPI; NEVER plaintext).

Two halves:

* **FILL** — on page load, if a saved credential matches the page's **EXACT
  host** AND the page has a login form, the browser *offers* to fill it. The
  user confirms; nothing is filled silently and never across domains.
* **SAVE** — when the user submits a login form, the browser *offers* to save
  the entered username/password (user confirmation) into the vault.

This module holds the **pure, Qt-free** parts (host matching + the injected
JavaScript) so they are headless-unit-testable. The Qt wiring (the QWebChannel
bridge and the offer/save UI) lives in ``widget.py``.

Security contract (module-3 spec):
* domain-EXACT host match only — never autofill into an unrelated domain;
* the password is JSON-encoded into JS (never string-concatenated) and is
  NEVER written to a log;
* user confirmation is required before a NEW credential is saved;
* the connector script runs in an **isolated** JS world so page scripts can
  neither read it nor clobber it.

Kill switch (read in widget.py): ``AIPACS_BROWSER_AUTOFILL=0``.
"""
from __future__ import annotations

from urllib.parse import urlparse


def host_of(url: str) -> str:
    """Lower-cased hostname of *url* ('' when not a real web URL)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        return (urlparse(raw).hostname or "").lower()
    except Exception:
        return ""


def same_host(a: str, b: str) -> bool:
    """True only when *a* and *b* resolve to the same exact hostname."""
    ha, hb = host_of(a), host_of(b)
    return bool(ha) and ha == hb


def should_offer_fill(saved_host: str, current_url: str) -> bool:
    """Offer to fill ONLY when the saved credential's host exactly equals the
    current page's host (no subdomain/substring cross-matching)."""
    sh = (saved_host or "").strip().lower()
    if not sh:
        return False
    return sh == host_of(current_url)


# Quick check: does the page have a password field (i.e. a login form)?
JS_HAS_LOGIN_FORM = (
    "(function(){try{return !!document.querySelector("
    "'input[type=password]');}catch(e){return false;}})()"
)


# Injected connector (runs in an ISOLATED world). Adds a capturing 'submit'
# listener to the document; when a submitted form contains a non-empty
# password field it forwards {host, username, password} to the Python bridge
# over QWebChannel. Idempotent (guards window.__aipacsAutofillWired) and fully
# wrapped in try/catch so it can never disturb the page.
AUTOFILL_CONNECTOR_JS = r"""
(function(){
  try{
    if (window.__aipacsAutofillWired) { return; }
    function wire(bridge){
      if (!bridge) { return; }
      document.addEventListener('submit', function(ev){
        try{
          var form = ev.target;
          if (!form || !form.querySelector) { return; }
          var pw = form.querySelector('input[type=password]');
          if (!pw || !pw.value) { return; }
          var user = '';
          var cand = form.querySelectorAll(
            'input[type=text],input[type=email],input[name],input:not([type])');
          for (var i=0;i<cand.length;i++){
            var c = cand[i];
            if (c.type==='password' || c.type==='hidden') { continue; }
            if (c.value){ user = c.value; break; }
          }
          bridge.credentialSubmitted(String(location.host||''),
                                     String(user||''), String(pw.value||''));
        }catch(e){}
      }, true);
      window.__aipacsAutofillWired = true;
    }
    if (typeof QWebChannel === 'undefined' || !window.qt || !qt.webChannelTransport){
      return;
    }
    new QWebChannel(qt.webChannelTransport, function(channel){
      try{ wire(channel.objects.aipacsAutofill); }catch(e){}
    });
  }catch(e){}
})();
"""


__all__ = ["host_of", "same_host", "should_offer_fill",
           "JS_HAS_LOGIN_FORM", "AUTOFILL_CONNECTOR_JS"]
