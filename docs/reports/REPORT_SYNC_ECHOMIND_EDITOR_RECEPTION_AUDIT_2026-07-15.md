# Report Synchronization Audit — EchoMind ↔ Report Editor ↔ INO Reception

**Date:** 2026-07-15
**Patient used for live verification:** reception **50304** (KOHI SEDIGHEH), workflow id
`6a54dc8418a091772b77d753`, reception server `192.168.2.222`.
**Method:** code trace + **live round-trip write test on the running source build**, verified
against the INO web page (`/singleReportPatient`) and the raw REST API
(`GET /api/pacs/report/50304`). The patient's original report was **backed up and restored
byte-for-byte** at the end (`content_equals_backup: true`, status `completed`, flags true/true).

> **Status = AUDIT ONLY.** No product code was changed. §7 lists the proposed fixes for approval.

---

## 1. Executive summary

| # | Question | Verdict |
|---|----------|---------|
| 1 | Do both paths send HTML + status to the server? | ✅ Yes — identical endpoint & payload |
| 2 | Does the **Report Editor** preserve RTL/LTR, alignment, colors? | ✅ Yes — verified live end-to-end |
| 3 | Does **EchoMind** preserve colors? | ⚠️ **Partial** — inline colors survive; **`<style>`-class colors are dropped** |
| 4 | Is the **status** updated correctly on INO? | ✅ Yes — `report.status` **and** `approvalFlags` both sync |
| 5 | Does the server return a valid confirmation? | ✅ Yes — `200 { success:true }` |
| 6 | Does re-fetch (View/Edit Report) match the server? | ✅ Data matches; ⚠️ editor **display** flattens per-block alignment on load |
| 7 | Does a 2nd EchoMind report **append** below the first? | ❌ **No — it REPLACES.** This is a real defect |

**The two problems the user reported are both real and now root-caused:**

- **"Some EchoMind text colors do not transfer"** → EchoMind's *Assistant* and *Search* cards
  put their colors in a `<style>` block using **CSS classes**. The server-export normalizer
  **strips `<style>` blocks** and the INO server keeps **inline styles only**, so those colors
  vanish. EchoMind's *Report* renderer uses **inline** colors, which is why some colors survive
  and others don't. (§4)
- **"A second report should append, not replace"** → EchoMind's *Send to Reception* builds the
  payload from the **current bubble only** and never reads the existing server report, so every
  send **overwrites**. Verified live: sending the lumbar report erased the knee report. (§5)

---

## 2. The shared pipeline (both paths are the same on the wire)

Both entry points converge on one contract:

```
POST {reception_base:8080}/api/pacs/update-report
Authorization: Bearer <JWT from socket_token_manager>
{ receptionId, content, findings, status, approvalFlags }
        │
        ├─ content/findings = prepare_report_html_for_server(<editor|bubble HTML>)
        ├─ status            = user-selected status
        └─ approvalFlags     = approval_flags_for_status(status)      (flag AIPACS_UPDATE_REPORT_APPROVAL_FLAGS)

then, on 200:  sync_report_approval_for_status_async(receptionId, status)
               → resolve workflow id → PATCH /api/imagingWorkflow/{wid}/workflow/report/approval-flags
```

| Concern | Report Editor | EchoMind |
|---|---|---|
| Handler | `reception_data_tab._save_report_to_api` (~:1630) | `ai_chat_pages._send_to_reception._send_with_patient_id` (~:4038) |
| HTML source | `ReportEditorDialog.text_edit.toHtml()` | `MessageBubble.get_html()` (the rendered card HTML) |
| Normalizer | `prepare_report_html_for_server()` | `prepare_report_html_for_server()` |
| Status → flags | `approval_flags_for_status()` + `sync_report_approval_for_status_async` | same |
| Existing report read first? | n/a (editor already holds it) | **No — never fetched** ← root of the append bug |

`prepare_report_html_for_server()` (`PacsClient/utils/report_server_html.py`) is the shared
server-export normalizer: it produces one inline-styled `<div data-aipacs-report-root>` wrapper,
sets a content-detected `dir`+`text-align`+`unicode-bidi:isolate` on every block, applies the
neutral-symbol LRM fix, **preserves existing inline colors/fonts**, and **strips `<style>`,
`<script>`, and document chrome** (`_STYLE_BLOCK_RE.sub("")`). That last step is exactly what
loses EchoMind's class-based colors (§4).

---

## 3. Report Editor path — VERIFIED WORKING (colors + RTL/LTR + status)

Live test: opened patient 50304 → View/Edit Report → appended four probe lines, saved.
Server (`GET /api/pacs/report/50304`) and the INO web page both showed:

| Probe line | Sent as | Server HTML | INO rendered (computed style) |
|---|---|---|---|
| `SYNC-TEST-A1 English…` | LTR | `dir="ltr"`, `text-align:left`, `unicode-bidi:isolate` | dir **ltr**, align **left** ✅ |
| `تست همگام سازی … راست چین شود.` | Persian | `dir="rtl"`, `text-align:right` | dir **rtl**, align **right** ✅ |
| `SYNC-TEST-A3 … RED.` | red text | `color:#d32f2f` preserved | color **rgb(211,47,47)** ✅ |
| `SYNC-TEST-A4 centered.` | centered | `align="center"` + `text-align` kept | align **center** ✅ |
| (original section headers) | inline colors | `#1f3b77 / #b00020 / #00695c` preserved | colored ✅ |

Root wrapper: `dir="rtl" … unicode-bidi:plaintext`. **Editor → server → INO fidelity for colors,
per-block RTL/LTR, and explicit center/justify is correct.** Status set to `completed` produced
`approvalFlags {physicianApproved:true, secretaryApproved:true}` on the server — confirming the
status+flags sync.

**One display-side caveat (not a data bug).** On *load*, `ReportEditorDialog._normalize_document_blocks()`
(`report_editor_dialog.py:888`) force-applies a **single** alignment/layout-direction to **every**
block (`AlignRight` if `is_rtl` else `AlignLeft`). So when you re-open a report that mixes RTL and
LTR paragraphs, the on-screen editor can flatten them to the document's dominant side. The **saved**
copy is fine (the save re-detects per block via `prepare_report_html_for_server`), but the editor is
not a perfect *visual* mirror of mixed-direction content. This matches the user's note that editor
alignment "appears to work more correctly" — it mostly does; the imperfect case is mixed direction.

---

## 4. EchoMind color loss — ROOT CAUSE

EchoMind renders three kinds of card, and they color text two different ways:

| Renderer | Used for | How colors are set | Survives server? |
|---|---|---|---|
| `_render_kv_report_html` (~:6071) | **Report** mode (structured findings) | **inline** `style='… color:#1f3b77'` on each header | ✅ Yes |
| `_render_assistant_html` (~:6489) | **Assistant** mode | `<style>` block, **CSS classes** (`.step1/.step2/.step3{color:#86b7ff}`, `.title`, `.subttl`…) | ❌ **No** |
| `_render_search_html` (~:6663) | **Search** mode | `<style>` block, **CSS classes** (`.title`, `.subttl`, `.para`…) | ❌ **No** |

`prepare_report_html_for_server()` deletes `<style>` blocks and the INO server keeps inline styles
only. So the **step-color-coding of Assistant answers and the Search-card colors are dropped**,
while Report-mode findings keep their colors. That is precisely "**some** EchoMind colors don't
transfer."

Live confirmation: the two reports I sent (Report-mode) kept `#1f3b77 / #b00020 / #00695c` on the
server. The `<style>`-class colors never reach the server because the block is stripped before send.

---

## 5. Append vs replace — CONFIRMED DEFECT (highest-impact)

**`_send_to_reception` overwrites; it never appends.** It builds
`server_html = prepare_report_html_for_server(bubble.get_html())` from the **current bubble only**
and POSTs it as the whole `content`/`findings`. There is **no** `GET /api/pacs/report/{id}` before
the send (confirmed: the only report reads in the file are `ai_fetch_reports_for_session`, the local
DB, not the server).

**Live proof on 50304:**

1. Editor report on server (knee).
2. EchoMind send #1 (knee card, status *pending*) → server `content` = knee, `has_knee:true`,
   status `pending`, flags `false/false`.
3. EchoMind send #2 (**lumbar** card, status *completed*) → server `content` = lumbar,
   **`has_knee:false`** (knee report **gone**), `has_lumbar:true`, status `completed`, flags
   `true/true`, `appended_below:false`.

So a shoulder-then-wrist workflow loses the shoulder report — exactly the user's scenario.

**Note — an append path exists, but only in the editor, not in EchoMind.** When you *open*
View/Edit Report, `reception_data_tab._show_report_editor` (~:1319) merges a locally-saved AI report
**above** the existing server report using `"<hr><h3>Previous Report:</h3>"` (guarded by the
`<!-- AI_REPORT_MERGED -->` marker). That is a display-time merge in the editor; EchoMind's own
*Send to Reception* has no equivalent.

---

## 6. Status synchronization — VERIFIED WORKING

`update-report` writes `report.status`; INO *renders* status from `approvalFlags`, so the client
also PATCHes the workflow approval-flags (`ino_report_workflow.sync_report_approval_for_status_async`,
mapping in `socket_report_status_service.approval_flags_for_status`). Live results on 50304:

| Sent status | server `report.status` | server `approvalFlags` |
|---|---|---|
| `pending` | `pending` | phys **false**, sec **false** ✅ |
| `completed` | `completed` | phys **true**, sec **true** ✅ |

Both the editor and the EchoMind paths do this. Status sync is healthy. (Background: the
2026-07-09 approvalFlags root-cause work — this audit re-confirms it live.)

---

## 7. Proposed fixes (for approval — nothing changed yet)

Ordered by clinical impact. All should be **flag-gated default-safe** and guard-tested, per project
rules. None touch the viewer / DICOM / download paths.

### Fix A — EchoMind append instead of replace *(highest priority)*
In `_send_to_reception`, before building the payload: `GET /api/pacs/report/{receptionId}`, and if
the server already has non-empty `content`, **append** the new card below it with a separator
(reuse the editor's `"<hr>"` style) rather than overwriting. Preserve the existing report's HTML
verbatim (do not re-normalize the old section destructively). Because clinicians sometimes *correct*
rather than *add*, surface an **Append / Replace** choice in the existing `_ReceptionIdDialog`
(default **Append**). Flag e.g. `AIPACS_ECHOMIND_APPEND_REPORT`.
*Files:* `modules/EchoMind/viewer_chat/ai_chat_pages.py` (+ echomind plugin mirror — sync after edit).

### Fix B — stop dropping `<style>`-class colors
Make the server export self-contained. Preferred, one-place fix: in `prepare_report_html_for_server`,
**inline simple class rules before stripping `<style>`** — parse `.class{color/font-weight/font-size…}`
and fold them onto matching elements' inline `style`, then remove the block as today. This fixes
Assistant + Search + any future class-styled HTML without touching each renderer. Narrower
alternative: change `_render_assistant_html` / `_render_search_html` to emit **inline** colors like
`_render_kv_report_html` already does. Flag e.g. `AIPACS_REPORT_INLINE_CLASS_STYLES`.
*Files:* `PacsClient/utils/report_server_html.py` (preferred) or the two EchoMind renderers.

### Fix C — editor display mirror for mixed-direction reports *(low priority)*
`_normalize_document_blocks` should detect **per-block** direction/alignment (as the server
normalizer does) instead of forcing one document-wide alignment on load, so re-opened mixed RTL/LTR
reports display exactly as stored. Server data is already correct; this only improves the on-screen
mirror. Flag e.g. `AIPACS_EDITOR_PER_BLOCK_ALIGN`.
*Files:* `modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py`.

---

## 8. Bidirectional-sync scorecard

```
EchoMind / Editor ──▶ prepare_report_html_for_server ──▶ update-report ──▶ INO stores content+status
                                                                    └────▶ approval-flags PATCH (status)
INO ──▶ GET /api/pacs/report ──▶ Editor display
```

| Leg | Colors | RTL/LTR align | Status | Verdict |
|---|---|---|---|---|
| Editor → server → INO | ✅ | ✅ | ✅ | Correct |
| EchoMind (Report) → server → INO | ✅ inline | ✅ | ✅ | Correct |
| EchoMind (Assistant/Search) → server | ❌ class colors dropped | ✅ | ✅ | **Fix B** |
| 2nd EchoMind report | — | — | ✅ | **Fix A (replaces, must append)** |
| server → Editor (re-open) | ✅ | ⚠️ mixed-dir flattened on display | ✅ | **Fix C (display only)** |

---

## 9. Verification evidence & safety

- Live writes were confined to reception **50304** (the user-authorized target). Every write went
  through the **real application code path** (Report Editor Save, EchoMind Send to Reception) or the
  server's own `update-report` endpoint using the workstation's session token.
- The original report was captured at session start and **restored byte-identically** at the end:
  `GET /api/pacs/report/50304` → `content_equals_backup: true`, `findings_equals_backup: true`,
  `len 5970`, `status: completed`, `approvalFlags {phys:true, sec:true}`; the INO web page re-renders
  the original report with **no** `SYNC-TEST` remnants.
- Local disk snapshots of every intermediate state are under
  `user_data/reports/reception/patient_50304/` (the app writes these automatically on open/edit).
```
