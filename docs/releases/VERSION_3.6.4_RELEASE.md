# AI-PACS v3.6.4 — Release Record

**Version:** 3.6.4
**Release date:** 2026-08-29
**Previous stable:** v3.6.3 (2026-08-23)
**Branch:** `beta-version` (published to `main` + `beta-version` on all three remotes)
**Type:** Minor — Eagle Eye lumbar-spine AI, Legion Consult, two native-crash fixes, strict-offline Local mode

---

## 1. Headline

Two new AI reading workflows and two crash fixes.

**Eagle Eye — Lumbar Spine MRI** graduates from a capture prototype to a full
two-stage reading pipeline (4.2.0) with a parallel clinical-context branch, a
frozen grading catalogue, and evidence sheets. **Legion Consult** adds an
attention-directed MRI consultation: the reader draws one ROI and asks a
question about it.

On the stability side, a **native access violation** in the loading overlay
(series-switch re-entrancy) and a **Shiboken ownership crash** when opening
Local Server are both closed, each with a pre-fix-failing guard suite. Local
mode is now **strict-offline by default** and Advanced Patient Search actually
applies every filter it offers.

---

## 2. Eagle Eye — Lumbar Spine MRI

**Stage 1 — capture.** One click resolves study → protocol → series *before*
the Eagle Eye tab exists (automatic when confident, interactive when not),
builds a synchronised 3×1 layout, and runs screenshot sweeps into a versioned
session on disk. Nothing opens on a partial mapping. Design:
`docs/plans/EAGLE_EYE_LUMBAR_STAGE1_2026-08-26.md`.

**Stage 2 — reading (pipeline 4.2.0).** The captured session becomes an ordered
image package that goes out over the existing EchoMind → GapGPT transport:

- **Parallel branches** — Gemini MRI screening runs beside a Gemini
  clinical-context branch; GPT verification is the sole diagnostic verifier.
- **Clinical context (4.0.0 → 4.1.0)** — study attachments, allowlisted
  reception facts, prior reports, DICOMized history series (`100000`), a
  UID-free full PACS series catalogue snapshot, and four bounded MRI overview
  frames. Context is treated as *untrusted prior data*: it can never establish
  a current MRI finding, and missing-sequence / post-contrast claims are
  suppressed unless the inventory scope is the full catalogue.
- **Frozen grading catalogue** — Lee central canal, Lee neural foramen and
  Bartynski-style lateral recess, rendered identically into both prompts, with
  `grade_system` + ordinal `grade` required for assessable stenosis. This
  closes the severe → mild → moderate → mild instability seen across four runs
  of the same study.
- **Per-stage sampling** — temperature is now a per-role value (1.0 Gemini
  screening, 0.2 GPT verification) recorded in request provenance.
- **Evidence sheets (`focused-v1`)** — capture manifest 1.2.0 records each real
  VTK viewport rectangle; opt-in worker-side sheets give most of one bounded
  canvas to the evaluated panes while retaining every localizer pane and
  reference line. The default `layout` arm is a zero-I/O no-op for rollback.
- **Negative-evidence rule (4.2.0)** — preserved central nucleus-pulposus T2
  hyperintensity on adjacent mid-sagittal slices is explicit evidence *against*
  desiccation; a dark annulus or axial T2 alone cannot establish it.
- **Provider identity** — the result panel shows only `AI-PACS AI Lumbar
  Analysis`; raw stage-model provenance stays on disk for audit.

**Architecture.** The workflow was extracted out of the oversized
`ImagingToolsTab` into a feature-owned `EagleEyeWorkflowCoordinator` with its
own result panel; the tab keeps only construction, wiring, status and close
delegation. Patient identity and the complete series catalogue now cross the
existing TTL-bound one-shot handoff (sanitized of UIDs and paths), so the
reduced Eagle Eye widget no longer loses context.

Files: `modules/ai_imaging/eagle_eye_lumbar/*`, `eagle_eye_modes.py`,
`eagle_eye_function_catalog.py`, `eagle_eye_function_dialog.py`.
Design: `docs/plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md`,
`docs/plans/EAGLE_EYE_LLM_PROMPT_DRAFT_2026-08-26.md`.

---

## 3. Legion Consult

A new Eagle Eye function (MRI only). The reader selects the diagnostically
relevant series and draws **one rectangular ROI** around the suspicious
finding — attention direction, not manual 3D segmentation. The Eagle Eye
toolbar button now opens a function picker; each modality keeps its native
function as the first choice.

The four ROI corners are projected in LPS into every selected stack; full-stack
overview pages plus clipped ROI ±5 context/zoom images are rendered **off the
GUI thread**; the reader's own sensitivity prompt runs on Gemini and its
complete answer is carried with the same evidence into GPT verification. Both
responses are preserved in a non-modal result panel, and Retry reuses the
persisted derived evidence rather than re-rendering.

Burned-in annotation **fails closed**, outbound identity is anonymous, and no
new network or credential path was introduced — the existing EchoMind/GapGPT
boundary is still the only one.

Files: `modules/ai_imaging/legion_consult/{workflow,evidence,prompts,runner,result_panel}.py`.
Design: `docs/plans/LEGION_CONSULT_FOUNDATION_2026-08-28.md`.

---

## 4. Crash fixes

### 4.1 Overlay / series-switch re-entrancy (native access violation)

A hard process death — `Windows fatal exception: access violation`, no
`[SHUTDOWN-INITIATOR]` record, no OS-level event — while stack-scrolling during
a series switch. `AiPacsLoadingOverlay.show_overlay` called
`QApplication.processEvents()` twice "to paint the overlay immediately";
`processEvents` re-enters the Qt event loop and dispatches queued work, so a
second series switch started on top of the first and the nested overlay was
built against a viewport the outer switch was already tearing down.

The same race crashed the app on 2026-06-05 and that fix treated only the
symptom (a liveness check inside the fade), so the race simply moved from the
fade to construction. Three fixes:

- **the cause** — `show_overlay` now paints with a synchronous
  `overlay.repaint()`; the double `processEvents()` survives only behind the
  kill switch;
- **defence in depth** — `switch_series` refuses a re-entrant call on the same
  container and clears its flag in a `finally` that also covers the early
  `return False` (a stuck flag would turn a crash into a permanently dead pane);
- **anchor guard** — `AiPacsLoadingOverlay.__init__` refuses a destroyed anchor
  *before* anything dereferences it; the liveness probe falls back to "alive"
  when `shiboken6` is unimportable.

The 2026-06-05 fade guard is untouched and pinned by a new test. Kill switches:
`AIPACS_OVERLAY_SYNC_PAINT`, `AIPACS_SWITCH_REENTRANCY_GUARD`,
`AIPACS_OVERLAY_ANCHOR_GUARD`. Report:
`docs/reports/OVERLAY_REENTRANCY_CRASH_2026-08-26.md`.

### 4.2 Local Server `clear_table` Shiboken crash

Frozen v3.6.3 crashed in
`shiboken6.abi3.dll!Shiboken::BindingManager::releaseWrapper` while opening
Local Server: `add_patient_data` replaced the same owned `SortableItem` twice,
and `clear_table` bulk-invalidated the remaining item wrappers from inside
`setRowCount(0)`. The row builder now writes each cell once, safe
clear/removal transfers items with `takeItem` before model mutation, and local
search no longer pumps a nested Qt event loop between clear and its coroutine
yield.

---

## 5. Local mode — strict offline + Advanced Patient Search

- **Strict offline by default.** Local selection and open were leaking into
  PACS sockets through click reconciliation, grouped preview, cache-miss
  thumbnail fetch, existing-tab refresh and previous-exam initialisation — with
  the network disconnected this produced missing thumbnails and
  timeout-dependent behaviour. `LocalDatabase` now builds series cards from
  SQLite/disk on a cache miss; explicit manual / opt-in server refresh is
  preserved.
- **Multi-study Local open** now aggregates every resolved study through the
  existing SQLite/disk payload builder and pushes the complete map to the
  viewer, so grouped patient tabs get their thumbnails.
- **Advanced Patient Search** no longer silently drops multiple Patient IDs,
  body part, DICOM age range or physician; the local repository combines all of
  them and persists valid reporting-physician metadata for offline reuse.
- **Imported Date** — a reversed custom range (`From > To`) returned nothing;
  both the dialog and the repository now order the bounds defensively and the
  repository uses a half-open next-day upper bound so the final day stays
  complete.

Files: `PacsClient/pacs/workstation_ui/home_ui/*`, `database/*`,
`modules/storage/sync_mode_policy.py`.
Architecture: `docs/architecture/SYNC_MODE_SEPARATION.md`.

---

## 6. Build and packaging

Eagle Eye's runtime is default-enabled but reached through lazy UI imports.
PyInstaller already force-collects non-optional `modules` submodules; **neither
Nuitka path did**, so static import optimisation could produce a build that
passed every source test and lacked Eagle Eye at runtime. Both the monolithic
Nuitka specification and the staged `full_core` profile now force-include the
4.16 MiB internal AI Imaging package, with EchoMind and other optional packages
still external and the Viewer payload synchronised byte-for-byte.

Files: `builder nuitka/{AIPacs_nuitka.spec.py,build_nuitka_release.py}`,
`builder/docs/NUITKA_BUILD_PLAN.md`.

### EchoMind client credential protection

The installed EchoMind payload no longer ships plaintext center access codes or plaintext
GapGPT provider credentials in Python source. A center access code is reduced to a lookup digest,
derives a per-code key with scrypt, and opens only that center's AES-GCM authenticated credential
envelope. Company Server 3 uses the credential opened by the validated EchoMind center and no
longer carries an independent fallback bearer key.

This implements the release owner's requested client-only extraction resistance without adding an
AI-PACS server dependency. It raises the cost of casual source/binary inspection but cannot prevent
a determined runtime debugger from observing a credential in process memory. Dashboard quotas and
center controls remain the operational enforcement boundary. Previously published Git history is
also outside this client-side protection and requires separate rotation or explicit risk acceptance.

---

## 7. Supporting work

- **EchoMind** — reporter and parallel-backend additions plus settings-store
  keys backing the Eagle Eye / Legion Consult stages; the shared transport is
  used, never forked.
- **Viewer / patient tab** — `ai_chat_interactorstyle` entry into the function
  picker, toolbar and panel wiring, thumbnail source service and fast-container
  refinements.
- **Documentation** — `tests/INDEX_BY_GUARD.md` (+274 lines),
  `docs/INDEX_BY_SUBSYSTEM.md`, the regression catalogue (11 new entries),
  a pre-development system map, `AGENTS.md`, `RECOVERY.md`, and a repository
  readiness evaluation.

---

## 8. Verification status

Offscreen (test lane), all with guards that **failed before the fix**:

| Area | Guard suite |
|---|---|
| Overlay re-entrancy | `tests/code/system/test_overlay_reentrancy_crash.py` (13; 11 fail pre-fix) |
| Local Server crash | `tests/code/ui_services/test_clear_table_crash_guard.py` (16) |
| Eagle Eye LLM | `tests/code/ai_imaging/test_eagle_eye_llm_analysis.py` (77) |
| Eagle Eye pipeline / UI / evidence / capability / protocol | `test_eagle_eye_{lumbar_pipeline,ui_boundary,evidence_bundle,gapgpt_capability,protocol_resolution}.py` |
| Legion Consult | `test_legion_consult_{analysis,foundation,ui_contract}.py` |
| Local offline / search | `test_local_offline_contract.py`, `test_advanced_search_routing.py`, `tests/code/database/test_local_advanced_search.py`, `test_local_incremental_and_import_date.py` |
| Build inclusion | `tests/code/builder/test_eagle_eye_default_build_inclusion.py` |
| EchoMind credential protection | `tests/code/echomind/test_credential_obfuscation.py` (6; 3 fail pre-fix) |

Domain gates at the time of the last slice: AI Imaging **559 passed, 8
pre-existing xfailed**; viewer/system/ui_services/fast_viewer **3,862 passed, 6
failed** (all pre-existing and measured as *caused by this work: 0*); plugin
mirrors **456/456**.

After the credential hardening slice, the complete non-live EchoMind suite is **2,315 passed,
12 skipped, 15 live tests deselected, 4 pre-existing xfailed**; plugin mirrors are **458/458**.
The current source and installer payload scan reports **zero** plaintext provider credentials and
**zero** plaintext center access codes.

**Still required — live verification:**

1. **Eagle Eye 4.2.0** radiologist validation on real lumbar studies.
2. **Legion Consult** end-to-end on a live MRI study.
3. **Overlay fix** — stack-scroll during a series switch, repeatedly, with no
   native fault and no dead pane.
4. **Local Server** — open with the network disconnected: thumbnails render,
   advanced search filters apply, no crash.
5. **A clean source build** from this tagged commit that actually contains
   `modules.ai_imaging`.

---

## 9. Known open items (not closed by this release)

These are carried forward from
`docs/reports/CODEX_REPOSITORY_READINESS_2026-08-27.md` and
`deploy-record-workstation-2026-08-28.md`, and remain **blockers for shipping
an installer** even though the source is now tagged:

- **Residual credential risk** — current source and installer payloads are clean and protected by
  a regression scan, but a determined runtime debugger can observe credentials in memory and
  previously published Git history may contain earlier plaintext values. Dashboard quotas are the
  accepted operational control; provider-key rotation/history remediation remains a separate
  release-owner decision.
- **`run_test.ps1 -Fast` masks failures** — `$Fast` and `$fast` collide in
  case-insensitive PowerShell, so the wrapper can return success after pytest
  fails. Use direct pytest until this is fixed.
- **No clean release artifact** — no clean PyInstaller/Nuitka release build has
  been produced from a clean committed SHA; the v3.6.3 stage/installer must not
  be reused.
- **No CI enforcement** — no GitHub Actions workflow enforces secret scanning,
  tests, lint or package parity before merge.

---

## 10. Publication

Published to `main` + `beta-version` with an annotated `v3.6.4` tag
(release commit `7f96b392`):

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3

Client credential hardening was published afterward as fast-forward commit `a2919adb` to both
branches on all three remotes. The original annotated tag was not force-moved. The later
2026-08-31 source follow-up below also changes runtime code. Any new installer must record its
exact reviewed source SHA; the original tag alone does not include these follow-ups.

Excluded from the release commit by design (local/generated state):
`builder nuitka/output/**`, `generated-files/runtime_profile.json`,
`generated-files/gapgpt/**`, `config/patient_table_sort.json`.

## 11. Source follow-up — 2026-08-31

The application version remains **3.6.4**. The latest source batch adds DICOM import/displayability
and duplicate-series identity fixes, Fast Viewer color/cine handling, Eagle Eye pipeline **4.6.1**
with opt-in focused evidence modes, benchmark tooling, and Slicer control/research documentation.
Experimental evidence modes and research proposals are not claims of clinical validation.

Publication preflight: **675 AI Imaging tests passed, 8 existing xfailed**; **174 related
viewer/import/security/build checks passed, 3 existing local-fixture tests skipped**; **458 plugin
mirror pairs matched**. This is source publication, not a newly built or approved installer.

See [the complete follow-up scope and exclusions](VERSION_3.6.4_FOLLOWUP_2026-08-31.md) and
[the source-publication safety record](../../deploy-record-workstation-2026-08-31.md).
