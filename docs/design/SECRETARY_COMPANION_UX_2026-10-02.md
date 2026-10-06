# Secretary EchoMind companion UI concept

Status: researched design and interactive HTML prototype. No production UI changes in this slice. The prototype uses synthetic studies and simulated states; it does not call MCP, Eagle Eye, microphones or TTS. HTML parsing, JavaScript syntax and the existing image path were checked. Production acceptance and browser-rendered visual acceptance are not claimed.

## Evidence and adaptation

- [Meta: How We Designed Muse](https://introducing.muse.ai/) describes a continuing conversation, distinct chat bubbles, avatar-adjacent activity snippets, an expanded activity view and structured approval controls. These inform a single Secretary conversation surface with progressive detail disclosure.
- [Meta: Bringing Your Muse to Life](https://research.meta.ai/blog/bringing-your-muse-to-life) describes synchronized streaming voice and generated avatars. This is a separate media infrastructure capability, not something established by our existing Windows SAPI speech or orb animation. Keep our existing identity and inexpensive local animation first.
- [Microsoft: Acrylic material](https://learn.microsoft.com/en-us/windows/apps/design/style/acrylic) recommends deliberate material use and solid fallback when transparency is unavailable. The prototype illustrates a translucent surround with readable content surfaces. CSS backdrop blur is not a claim that PySide6 currently implements native Acrylic.

## Proposed interaction

Keep the existing left-corner entry point and EchoMind identity. Expand into a compact modeless companion panel. Use an approximately 80–96 px avatar, a prominent activity sentence, readable conversation bubbles, a task card and a fixed text/voice composer. Keep support and memory behind Activity & conversation rather than beside the primary request. A minimized indicator retains current status and restores the same conversation.

Use real transitions: Ready, Listening, Transcribing, Preparing request, Executing a named step, Waiting for user input, Completed, Failed and Speaking. Planning remains indeterminate until the server returns a valid proposal; never invent percentages or steps. Show named steps and verified completion from the local workflow callbacks. A failed verification must stop the task card and identify the last confirmed action. Reopening a panel must not resend the request. Hiding the panel must not cancel work or stop recording silently.

Responses appear in the same conversation instead of opening a second central response window. Keep technical trace behind Details. Use readable proportional type at 14–16 px and semantic labels rather than raw phase/JSON messages. The current separate response panel already has local English Read aloud, Stop and opt-in speech; consolidate those controls without claiming Persian speech or realtime streaming support. Text is always available. Only actual speech state drives Speaking animation. Never read patient details automatically unless the user has opted into the relevant behavior.

The orb microphone action remains explicit. Add a visible microphone control with keyboard access and recording indication. Voice-transcription integration must continue using VoiceTranscriptionService. Preserve the current busy/concurrency guard: Muse-style concurrent tasks or interruptible speech are not yet supported here and must not be suggested by the UI. Draft editing can be available while busy; execution submission remains disabled until supported.

No global dimming overlay for routine conversation, progress or replies. Existing clinical/native dialogs such as Write CD retain their own controls and confirmation requirements; the companion is not a substitute for them. A collapse or playback-stop control must not masquerade as workflow cancellation. Only expose task cancellation once the executor supports a reliable cancellation boundary.

Dark appearance suits reading work; light appearance is optional. Transparency applies to the surround, not text readability. Use color plus text/icon, reduced motion, keyboard focus and solid high-contrast fallback. Respect workstation theme settings rather than introducing an independent permanent theme.

## Implementation boundaries

Current touchpoints: SecretaryButtonWidget/SecretaryOrbButton, SecretaryResponsePanel, the F12 popup host, and shared workflow callbacks. Prefer a separate companion presentation widget and state model rather than adding planning logic to the oversized Secretary controller. Keep server planning, typed local proposal validation, identity binding, permission checks and execution unchanged. Never map cosmetic animation completion to medical action success.

Before implementing, verify the modeless host and retained conversation lifecycle, step events, compact sidebar layout at 1024 px and high DPI, local speech teardown, busy submission, focus return, confirmation stacking, minimized recording visibility and hidden-panel completion. Use synthetic code guards and an affected-workflow live source GUI pass. No new server inference route or avatar video dependency is needed for this first design.

Prototype: [secretary-companion-concept.html](secretary-companion-concept.html). Demo controls intentionally simulate state transitions. The result count is illustrative, not a patient dataset.


## Entry-point source review

Home `_hp_layout.py` creates a SecretaryButtonWidget when EchoMind is enabled. `shortcut_manager.py` registers F12 with Qt.ApplicationShortcut. `secretary_popup.py` lazily creates a modeless Qt.Tool singleton hosting a separate SecretaryButtonWidget, with its own orchestrator session. It reuses that popup across toggles, but does not share the Home widget session. Close/F12-hide currently calls cancel_recording and cleanup; it is not a pure minimize operation. Actual cross-module keyboard coverage was not live-tested in this design slice.

Target: Home orb and global shortcut should open the same conversation/controller. Viewer, Education, Browser, Advanced Analysis and Settings use the global entry point without duplicating agents. Current page and authorized patient/viewer identity must be resolved when accepting a request, with stale identity validation preserved. Do not infer a patient from the last Home command. A compact status indicator restores the panel without submitting a request. F12 availability remains subject to module installation and active application focus.

The prototype now includes Home/Viewer/Settings context switches and an F12 visibility toggle; these simulate placement only. The smaller circular surround retains the EchoMind identity, while the unchanged user-tie silhouette is larger within it and gains subtle shadow depth. Browser/developer tools may intercept F12, so the visible minimize/restore controls provide the same preview interaction.


## Persistent access correction

The Home sidebar must use two layout regions: a stretchable independently scrolling server/search area and a compact Secretary area outside that scroll viewport. The prototype now uses viewport-bounded grid rows, preserving Secretary visibility while search scrolls. The compact avatar is 52 px on desktop; detailed conversation expands separately. Narrow layouts use a pinned bottom composer. Native implementation should use a QScrollArea for search only and a fixed-height companion sibling, respecting small-window/high-DPI minimums. This correction is prototype-only; native GUI acceptance remains pending.


## Owner correction: preserve visible search controls

Supersedes the search-scroll proposal above. Move Adaptive to Screen Size into the study toolbar beside font-size controls. Remove unnecessary Server Selection vertical slack, keep its source tabs/server selector/status visible, reduce search spacing and reduce Secretary size. Fit the complete sidebar rather than introducing routine search scrolling. The prototype now follows this arrangement with a shorter-height compact variant; runtime layout and measured native fit have not yet been changed or verified. Very short windows must use an explicit compact layout rather than clipping controls.


## First native layout slice

Only the approved preliminary layout has changed: existing Adaptive callback is preserved while its button moves into a compact group with A-/A+ in the study toolbar (30 x 32 px controls, 2 px internal spacing). The separate 54 px adaptive sidebar wrapper is no longer inserted. Server-group margins/spacing are reduced and vertical size policy prevents unnecessary expansion; the data panel no longer forces 180 px minimum. Local/Server/Import widgets remain present and their layout hints determine content height. Secretary visuals and sessions are unchanged. Syntax compilation and one synthetic Qt control/signal test pass. No applicable packaged mirrors were found for these base Home files. Live acceptance awaits the user source launch: check all three source tabs, Adaptive action, font +/- behavior, theme and visible search/Secretary at the actual monitor resolution.


## Voice-first compact companion correction

Owner direction: remove the unusable narrow text field and duplicate microphone button from the compact surface. The smaller circular avatar is the recording entry point, with a visible recording label and click-again-to-finish instruction. Open conversation exposes the full-size typed composer and replies. Sound on/off governs reply playback only and never controls capture. Finish recording sends the captured request; discard/cancel must remain a distinct supported operation. Prototype state transitions are simulated only; no microphone or TTS runs. Native recording guards, STT service and permission semantics must be preserved during eventual integration.
