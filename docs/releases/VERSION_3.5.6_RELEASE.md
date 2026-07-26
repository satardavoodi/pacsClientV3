# AI-PACS v3.5.6 — Release Record

**Version:** 3.5.6
**Release date:** 2026-07-26
**Previous stable:** v3.5.5 (2026-07-25)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Minor — OS theme immunity for dialogs, local-list incremental loading + import-date filter, EchoMind reporting/voice

---

## 1. Headline

Three independent threads.

The most broadly-felt is a **theming** fix: popups and dialogs were inheriting the
operating system's light/dark palette and could come out unreadable. They now render
against the app's own fixed theme regardless of what Windows is set to.

Alongside it: the **local patient list** now loads incrementally instead of stalling
on a large store, with a new Advanced-Search **import-date filter**; and **EchoMind
reporting** gets three improvements — it stops discarding the user's prompt, gains a
new assist endpoint, and adds a voice-transcription provider.

---

## 2. OS light/dark theme immunity for popups and dialogs (OPT-44)

**The problem.** Custom popups and dialogs could fall back to the operating system's
palette when Windows was in (or switched to) a different light/dark mode than the
app's theme — producing unreadable combinations such as dark text on a dark surface.

**Root cause.** Three things combined: the app used the **native Qt style**, set **no
fixed `QPalette`**, and its stylesheet only covered Qt's **built-in dialog classes**.
So any *custom* widget that wasn't explicitly styled inherited the OS palette
directly, and flipped with the OS theme.

**The fix — central, not per-dialog.** Apply the **Fusion** style with a **fixed dark
palette at the application level** (`apply_global_app_theme`), so every widget —
including custom ones — starts from the app's own palette instead of the OS one. The
existing QSS overrides are kept for the widgets that are already styled, so only the
previously-broken widgets change appearance; the already-correct ones are untouched.
The remaining per-widget mechanism is theme tokens / `apply_dialog_theme`.

`PacsClient/utils/theme_manager.py` (+116), `main.py` (application-level apply). New
`docs/design/THEMING_DIALOGS.md`. Default-on.

**Status:** needs live verification — dialogs render correctly under both Windows
light and dark modes.

---

## 3. Local patient list — incremental loading + import-date filter (OPT-43)

**Incremental loading.** The local (on-disk) patient list used to build in one pass,
which stalled the list on a large local store. It now paints a small first batch
immediately and **streams the remaining rows in the background** — driven by an idle
timer, not only by scrolling — so the list is responsive straight away and fills in
without blocking.

**Import-date filter.** Advanced Search gains a filter over `studies.imported_at`
(the "when did this study first enter the local DB on this computer" value added in
v3.5.4): Today / Yesterday / Two days ago / a custom day / a date range. It is routed
to the **local** search path (not the server), so it filters the local list.

`advanced_search_dialog.py` (+71), `_hp_search.py`, `home_search_service.py`,
`patient_table_widget.py`, `database/dicom_db.py`. Default-on.

**Status:** needs live verification — the list streams smoothly and the import-date
filter returns the right studies.

---

## 4. EchoMind — reporting and voice

- **Report-prompt preservation.** The reporting path used to discard the user's
  prompt on the way to the model; it now preserves it. Regression guard:
  `tests/code/echomind/test_report_prompt_preservation.py`.
- **New assist endpoint** for EchoMind reporting (`openai_reporter.py` +126,
  `ai_chat_pages.py` +75, `ai_chat_config.py`), with a server-side test
  (`test_assist_endpoint_server.py`).
- **Voice transcription** gains an added provider (`aipacs_3`) and its routing
  (`voice_transcription.py` +86), going through the ONE shared
  `VoiceTranscriptionService` — never a fork — with the endpoint still resolved per
  call from Settings so a settings change takes effect without a restart. Guard:
  `test_voice_transcription_service.py`. New docs:
  `docs/pipelines/echomind-reporting-prompts.md`.

`modules/EchoMind/*` is plugin-mirrored — both the canonical and
`builder/plugin package/.../EchoMind/*` copies are updated in sync.

The one config change (`config/echomind_settings.json`) selects the new `aipacs_3`
voice provider; no secret is involved.

---

## 5. Verification status

Offscreen (test lane): new guard suites for the app-theme enforcement, the local
incremental / import-date path, EchoMind report-prompt preservation, voice
transcription, and the assist endpoint all live under `tests/code/`.

**Still required — live source-build verification** (cannot be done from the test
lane):

1. **Theming:** open popups and dialogs with Windows set to light mode and to dark
   mode — text stays readable in both.
2. **Local list:** open a large local store — the list appears immediately and fills
   in; the Advanced-Search import-date filter returns the correct studies.
3. **EchoMind:** generate a report and confirm the prompt is preserved; exercise the
   new assist endpoint and the `aipacs_3` voice provider against the live server.

---

## 6. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.5.6` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
