"""Secure credential autofill helpers for the Web Browser (2026-06-27).

Restores the "remember my login and offer to fill it" feature on top of the
existing encrypted credential vault (``credential_vault.py`` → OS keychain /
Windows DPAPI; NEVER plaintext).

Two halves:

* **FILL** — when the user focuses/clicks a login field, if a saved credential
  matches the page's **EXACT host** the browser shows a small **floating
  suggestion popup anchored to the field** (a native Qt window, NOT injected
  DOM, so the page never shifts or resizes). The user picks an account and the
  username/password are filled. Nothing is filled silently, never cross-domain.
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


# Injected connector (runs in an ISOLATED world). It:
#   * on a login-form SUBMIT, forwards {host, username, password} so the
#     browser can offer to SAVE the credential;
#   * on FOCUS/CLICK of a login field (a password field, or a text/email field
#     whose form has a password — or with a username/email hint), forwards
#     {host, fieldType, boundingClientRect} so the browser can show a FLOATING
#     suggestion popup anchored to the field;
#   * on SCROLL/RESIZE, asks the browser to dismiss the popup (the field moved).
# Idempotent (guards window.__aipacsAutofillWired) and fully wrapped in
# try/catch so it can never disturb the page. The rect is in CSS pixels,
# viewport-relative (getBoundingClientRect) — the Python side maps it to global
# screen coordinates. The popup is a native Qt window, NOT injected DOM, so the
# page is never reflowed.
AUTOFILL_CONNECTOR_JS = r"""
(function(){
  try{
    if (window.__aipacsAutofillWired) { return; }
    function isLoginField(el){
      if(!el || !el.tagName || el.tagName.toLowerCase()!=='input') return false;
      var type=(el.type||'text').toLowerCase();
      if(type==='password') return true;
      if(type==='text' || type==='email'){
        var form=el.form||(el.closest?el.closest('form'):null);
        if(form && form.querySelector('input[type=password]')) return true;
        var ac=(el.getAttribute('autocomplete')||'').toLowerCase();
        var nm=(el.name||'').toLowerCase();
        if(ac.indexOf('username')>=0 || ac.indexOf('email')>=0) return true;
        if(nm.indexOf('user')>=0 || nm.indexOf('email')>=0 || nm.indexOf('login')>=0) return true;
      }
      return false;
    }
    function rectOf(el){
      try{
        var r=el.getBoundingClientRect();
        return JSON.stringify({left:r.left, top:r.top, width:r.width, height:r.height});
      }catch(e){ return ''; }
    }
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
      function onFocus(ev){
        try{
          var el = ev.target;
          if(!isLoginField(el)) { return; }
          if(bridge.loginFieldFocused){
            bridge.loginFieldFocused(String(location.host||''),
              String((el.type||'').toLowerCase()), rectOf(el));
          }
        }catch(e){}
      }
      document.addEventListener('focusin', onFocus, true);
      document.addEventListener('click', onFocus, true);
      function onDismiss(){
        try{ if(bridge.dismissSuggestions){ bridge.dismissSuggestions(); } }catch(e){}
      }
      window.addEventListener('scroll', onDismiss, true);
      window.addEventListener('resize', onDismiss, true);
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


def compute_anchor(field_left, field_top, field_height,
                   view_global_x, view_global_y, zoom,
                   popup_w, popup_h,
                   screen_left, screen_top, screen_right, screen_bottom,
                   gap=4):
    """Global top-left (x, y) for a suggestion popup anchored to a login field.

    Pure / unit-testable. The field rect is in CSS pixels (viewport-relative);
    multiplying by the view's *zoom* maps it to device-independent widget
    pixels, then the view's global origin maps it to screen coordinates.

    The popup is placed just BELOW the field; if it would overflow the screen
    bottom it FLIPS ABOVE the field; horizontally it is clamped to the screen.
    Returns ``(x, y, placed_above)``.
    """
    z = zoom or 1.0
    x = view_global_x + field_left * z
    field_bottom_y = view_global_y + (field_top + field_height) * z
    field_top_y = view_global_y + field_top * z

    placed_above = False
    y = field_bottom_y + gap
    if y + popup_h > screen_bottom:
        above_y = field_top_y - gap - popup_h
        if above_y >= screen_top:
            y = above_y
            placed_above = True
        else:
            y = max(screen_top, screen_bottom - popup_h)

    if x + popup_w > screen_right:
        x = screen_right - popup_w
    if x < screen_left:
        x = screen_left
    return int(round(x)), int(round(y)), placed_above


__all__ = ["host_of", "same_host", "should_offer_fill",
           "JS_HAS_LOGIN_FORM", "AUTOFILL_CONNECTOR_JS", "compute_anchor"]
