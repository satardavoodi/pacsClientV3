# Password-only ordinary Eagle authentication

Owner-authorized source implementation, 2026-10-12. The canonical [connection boundaries](../../../architecture/EAGLE_EYE_CONNECTION_BOUNDARIES_2026-10-12.md) governs this change.

`UserAuthority.login` now rejects caller provider/upstream_token bodies before provider I/O and session allocation. Existing username/password remains mandatory. The historical provider field accompanying a password is an ignored compatibility hint: it cannot select an authority or bypass PACS-first resolution. Only a definitive 401 allows Reception fallback. Outages fail closed. Local enabled and feature/module grants remain independent, and denial never tries another person. Passwords remain memory-only; the server-issued opaque session, bounded refresh and revocation semantics remain.

Compatibility: older Eagle callers using PACS/provider token exchange must migrate to existing captured username/password before this source is activated. No automatic token fallback is retained. The separate mobile-to-Windows remote Agent PACS QR/HTTPS protections and main PACS socket authentication are unchanged. Synthetic integration fixtures now authenticate through password adapters rather than injecting sessions or bypassing admission.

This is local prepared source, not an activation claim. The current immutable Razi candidate02 still has the historical token route. No executing source is overwritten, no service restarted and no build qualified by this slice. An immutable combined candidate requires reviewed Client/Android/iOS migration, scoped source parity, full automated checks and separate live acceptance.
