# Home patient-list source identity normalization

The captured Android request terminal diagnostic reported action list_patients, VERIFY_FAILED and no terminal ready receipt. This proves verification failed after dispatch; it does not retain which verification branch failed. No original request was replayed or queried against a replacement native binding.

A deterministic defect fits that evidence: DataAccessPanelWidget stores visible tab labels Server/Local; HomeWidgetAdapter resolves them to canonical server/local. HomeCommandAdapter binds search handles to the canonical source, but HomeSelectionAdapter previously returned the display label unchanged for read/list identity. Thus a source comparison rejected Server versus server, and even a synchronous ready list could not satisfy the verifier's canonical source contract.

HomeSelectionAdapter now maps exactly Server, Local, server and local to the two canonical source IDs. Other values remain unknown; it does not guess a source or default to server. The canonical value is shared by list identity and ordinal/source checks. Existing title-case list handles become stale rather than receiving a cross-source compatibility fallback.

Eight synthetic guards failed before the change and pass afterward. Focused source/list/date/ordinal/receipt verification: 64 passed, exit 0. One owned EchoMind payload mirror synchronized; all 531 mirror pairs match. Tests preserve one initiating search, exact list/search identity, normalized date provenance and replaced-task rejection. This establishes the source defect and fix; it does not independently prove the exact historical failing branch or a live mobile acceptance pass.

No authentication, patient-data extraction, request replay, service transition or live source overwrite occurred. Frozen source/test/doc and mirror pins are under generated-files/eagle-eye/home-source-normalization-20261012. Immutable Razi synchronization and new-binding native/mobile acceptance remain pending.
