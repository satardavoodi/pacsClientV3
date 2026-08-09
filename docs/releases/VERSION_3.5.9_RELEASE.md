# AI-PACS v3.5.9 — Release Record

**Version:** 3.5.9
**Release date:** 2026-08-10
**Previous stable:** v3.5.8 (2026-08-04)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Minor — EchoMind Turbo reporting overhaul, per-chat case metadata, cold-load warm-up, download cancel/retry

---

## 1. Headline

This release is dominated by a deep **EchoMind reporting overhaul**. Turbo report
generation is rebuilt around a **study-aware, region-gated prompt system**, a
**per-chat case-metadata panel** is added, and reporting is made materially safer and
more correct. Around that: series header-scan cold-load warm-up, MPR deferred-3D
layout stability, and download-manager cancel/retry hardening.

---

## 2. EchoMind — study-aware, region-gated Turbo prompts

Previously Turbo sent one large prompt carrying the reporting rules for every region
and modality. Turbo now assembles the prompt from a shared template plus **only the
modules relevant to the study**:

- `turbo_template.py` — the shared skeleton;
- `turbo_modules.py` + `turbo_region_modules.py` — the module registry / router;
- per-modality libraries: `turbo_regions.py` / `turbo_regions_extra.py` (CT),
  `turbo_mri_modules.py`, `turbo_us_modules.py`, `turbo_xr_modules.py`,
  `turbo_mammo_modules.py`;
- `turbo_prompt.py` — the Turbo entry point.

So a CT chest study no longer receives the reporting rules for brain, spine, or
mammography — the model gets the region's own structures, its standardized-system
guidance, and its dictation lexicon. Turbo remains **pinned to the company GapGPT
pipeline** as a locked configuration (the end user can't repoint it), and the two AI
backends share the same report/correction prompt authorities.

Some of the region content is compiled from the literature and is flagged in-module as
**needing radiologist review**; that review is a live-build task, not a test-lane one.

---

## 3. EchoMind — per-chat case-metadata panel

Each report chat now opens with a structured **case card** showing the detected
patient/study fields — sex, age, service, modality, body part, study description,
region — each with **provenance** (detected vs. physician-set):

- `session_metadata.py` — a three-layer record (auto / user / effective) with a
  never-guess rule for sex and body-part region;
- `metadata_panel.py` — the in-conversation card (the first structured chat card, not
  a sidebar);
- `reception_prefetch.py` — fetches the reception record **while the physician
  dictates** (the one idle network window), so the card is populated by report time,
  off the GUI thread and fully swallowed so it can never affect the voice path.

Because the local DB is sparse for demographics (measured: patient sex ~3% populated),
the detector reads the displayed study's **own DICOM header** to fill gaps, and caches
the reception **services** locally.

---

## 4. EchoMind — reporting correctness & safety

- **Source-fidelity contract** — the model may not invent a finding, change stated
  anatomy or laterality, or firm up a hedge ("may represent" must not become
  "represents"). Stated once, shared across every modality and both backends.
- **Normal-findings register** — normal findings are a generation task with per-organ
  depth, contrast-aware phrasing (no enhancement statement on a non-contrast study),
  and completeness scaled to the anatomy the study covers (never padded).
- **Report organization** — findings are grouped by region/organ inside the existing
  flat JSON keys (never a nested schema, which would break the parser / renderer /
  reception send).
- **A completely normal study is reportable** — an empty `Pathological Findings` field
  is coerced to "No pathological findings are identified." instead of the validator
  rejecting the whole report (which previously made a normal study unreportable).
- **Report-persistence chain** — `ai_reports` rows are finally written (the table had
  been empty for months due to a `getattr`-guarded call that never resolved), with
  physician / model / modality attribution and correction linkage.

---

## 5. Viewer, MPR, download manager

- **Series header-scan cold-load warm-up** (`series_file_warm.py`) — opening a cold,
  large study re-read DICOM headers on the hot path; they are now pre-warmed so
  patient open and the first interactions are faster on a cold cache.
- **MPR deferred-3D layout stability** — the MPR host viewport stays visible until its
  replacement exists, so starting MPR with two viewports open no longer lets the other
  viewport expand and snap back while the reconstruction loads.
- **Download-manager cancel + retry hardening** — more robust cancel escalation, and a
  retry no longer discards already-finished files (`_dm_retry`,
  `download_process_worker`).

---

## 6. Housekeeping

- Docs reorganized: handoff prompts → `docs/handoff/`, deploy records + crash reports →
  `docs/reports/` and `crash-diagnostics/`; a new `docs/echomind/` architecture set.
- Reception services cached locally (`database/ai_reception_db.py`).
- **Machine-local preferences intentionally not shipped.** The developer's local
  `config/echomind_settings.json` had flipped `llm_backend`→`openai` and the STT
  provider→`v2t` for testing; these were reverted before commit so the shipped config
  keeps its sensible defaults (a fresh center has no OpenAI key / local v2t).

---

## 7. Verification status

Offscreen (test lane): a large set of new EchoMind guard suites (Turbo prompt seam +
CT/MRI/US/X-ray/mammo modules, region/subtype routing, source-fidelity, normal-findings
register, report organization, metadata detection/card, session seeding + persistence
chain, transcribe retry, Turbo-is-locked), plus download-manager cancel/retry, reception
services cache, and MPR layout-stability suites live under `tests/code/`.

**Still required — live source-build verification** (cannot be done from the test lane;
the reporting wording in particular needs a radiologist):

1. **Turbo reporting:** generate reports across CT / MRI / US / X-ray / mammography and
   confirm each gets the right region rules; a completely normal study reports; a
   correction preserves the report.
2. **Case-metadata panel:** open a report chat → the card shows correct detected fields
   with provenance, populated by report time.
3. **Cold-load warm-up:** open a cold, large study → faster first open.
4. **MPR:** start MPR with two viewports open → the other viewport doesn't jump.
5. **Download manager:** cancel and retry during an active download → clean cancel,
   finished files kept.

---

## 8. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.5.9` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
