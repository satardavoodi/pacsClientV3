# Internal Assignment — "false assigned" regression (Assign + Report columns)

**Date:** 2026-07-15
**Reported by:** user (screenshot: MG/BREAST list, patients 50258 / 50016 / 50107).
**Symptom:** patients appear **assigned** in the Assign column (and the assignee name paints
in the Report column) when **no valid internal assignment exists**.
**Verified live** against the reception/PACS server `192.168.2.222` (`GET :8000/api/patients/{id}/assign`).

> **Status = FIX IMPLEMENTED (flag-gated default-on) 2026-07-15.** See §8. Audit is §1–§6.
> Needs a source-build restart + live re-verify (§9).

---

## 1. Answer to the two structural questions

**Do both entry points use the same server-side source, model, and status mapping?**
**Yes — they already do.** As of commit `c4809f16` (v3.5.1) both the **Assign** column and the
**Report** column, *and* both click-through popups (Report→referral-management, Assign→Internal
Assign), read one shared accessor:

```
_assign_icon_state()  ─┐
_apply_report_status_display() ─┼─▶ assignment_display_for(rid)
get_assignment_details(rid) ───┘        ├─ ino_assignment_server_state.get_state(rid)   (SERVER snapshot)
   (Assign menu + both popups)          └─ ino_assignment_history.current_assignment_details(rid) (local: completed only)
                                        ▼
                              merge_assignment_status()  →  effective_assign_status()  →  assign_icon_for_status()
```

They cannot disagree **with each other** — that part is correct. **The problem is that the one
shared source is wrong.**

**Do they infer assignment from local/incomplete data, or only from a valid server assignment?**
The server snapshot is filled by `ino_assignment_refresh.parse_assignment()`, which **treats the
server's `assignment.radiologist` as an internal assignment whenever `radiologist.id` is non-empty.**
On this server that field is **the RIS reporting radiologist**, auto-populated for essentially every
reception that has a reporting physician. So the app displays "assigned" for patients that were never
internally assigned.

---

## 2. Live evidence — `GET :8000/api/patients/{id}/assign`

I scanned 15 receptions. The discriminator is unambiguous:

| Reception | radiologist.name | source | **last_assigned_by** | Report done? | Assign column shows | Correct? |
|---|---|---|:---:|:---:|---|:---:|
| **50258** | دكتر بهاره مباشری | ris_personnel | **(empty)** | yes | 🟢 completed (green ✓) | ❌ false |
| **50016** | دكتر بهاره مباشری | ris_personnel | **(empty)** | no | 🔴 active (red) | ❌ false |
| **50107** | دكتر بهاره مباشری | ris_personnel | **(empty)** | no | 🔴 active (red) | ❌ false |
| 49628 | دكتر رضا علیزاده | ris_personnel | (empty) | — | assigned | ❌ false |
| 49836 | دكتر وحید علیزاده | ris_personnel | (empty) | — | assigned | ❌ false |
| 49868 | دكتر رضا علیزاده | ris_personnel | (empty) | — | assigned | ❌ false |
| 49900 | دكتر بهاره مباشری | ris_personnel | (empty) | — | assigned | ❌ false |
| 50304 | دكتر رضا علیزاده | ris_personnel | (empty) | — | assigned | ❌ false |
| **50210** | دكتر وحید علیزاده | ris_personnel | **SET** | — | assigned | ✅ **real** |
| 50179 / 50100 / 50050 / 50000 / 49800 / 49700 | *(none)* | — | (empty) | — | not assigned | ✅ correct |

**Only 50210 has `last_assigned_by` set** — and 50210 is the documented genuine internal assign
(it is the patient `ino_assignment_refresh.py`'s own docstring cites, assigned to the logged-in
user "vahid"). Every false-positive is a RIS reporting radiologist with **empty `last_assigned_by`**.
The three from the screenshot were batch-set to the same radiologist at `16:07–16:09` on 2026-07-14 —
a reception-side reporting assignment, not three AI-PACS actions.

---

## 3. Root cause (single point)

`modules/network/ino_assignment_refresh.py :: parse_assignment()`:

```python
rad_id = str(rad.get("id") or "").strip()
primary_id = rad_id or typ_id
return {"assigned": bool(primary_id), ...}   # ← any radiologist id ⇒ "assigned"
```

`fetch_assignment()` → `set_state(assigned=bool(primary_id), …)` persists that into
`ino_assignment_server_state`, and every consumer paints from it. Because the PACS
`/api/patients/{id}/assign` endpoint returns the **RIS reporting radiologist** (not only explicit
hand-assignments), `assigned` is `True` for almost every reported patient.

`effective_assign_status()` then splits them by report status — report **done** → `completed`
(green ✓, e.g. 50258), report **in progress** → `active` (red, e.g. 50016/50107) — which is exactly
the green/red pattern in the screenshot.

**The code already knows about this conflation** (`ino_assignment_server_state.set_state` docstring:
*"the PACS `/assign` radiologist field is set by the RIS report workflow for most receptions — it is
the reporting radiologist, not only an explicit hand-assignment"*). The mitigation added was `mine`
(an ID match to the logged-in user) — but `mine` was only ever applied to the Report column's red
**text**, never to the `assigned` boolean that drives the whole Assign column, and it was
subsequently **removed** as a gate too (see §5). So nothing actually stops a RIS reporting
radiologist from being shown as an internal assignment.

---

## 4. Where the regression entered

Commit **`c4809f16` — "feat(v3.5.1): … INO assignment refresh …"** (2026-07-14). It:

- added `modules/network/ino_assignment_refresh.py` (new server read-path, +193),
- rewired `patient_table_widget.py` (+554) so the Assign **and** Report columns paint from the
  server snapshot via `assignment_display_for` / `merge_assignment_status` / `effective_assign_status`,
- added those pure helpers to `ino_assignment_models.py` (+49).

The **intent** was right and is an improvement (patient 50210: a cross-PC assignment was invisible
because nothing ever read the server). The **defect** is that the new read path does not distinguish
a deliberate internal assignment from the RIS-populated reporting radiologist, so turning the server
read on made *every reported patient* look assigned. Before this commit the columns were painted from
the local action log only, so a patient never internally-assigned on any workstation stayed neutral —
hence this is a regression introduced by the "assignment refresh" change, exactly as suspected.

---

## 5. Related: the two removed Report-column gates

The same commit **deliberately removed** the `mine` and `same_person_name` gates from
`_apply_report_status_display` (documented in-code at ~line 5446), on the theory "show the assigned
person, whoever it is." Combined with §3, that is why the Report column now also paints the RIS
reporting radiologist's name in red for non-completed reports. The §6 fix cures this too (a RIS
reporting radiologist stops being classified as an assignment, so there is nothing to paint red).
Whether the Report red should *additionally* be restricted to `mine` is a product choice, separate
from this regression.

---

## 6. Proposed fix (minimal, single point, flag-gated)

**Require positive server evidence of a deliberate assignment before `assigned=True`.** The only
field that distinguishes a real assign from the RIS reporting radiologist is **`last_assigned_by`**
(the assigner's user id). A genuine AI-PACS assign always sets it — the assign `PUT` sends
`X-User-Id: _current_user_id()` (`ino_assignment.py:469`), which the server stores as
`last_assigned_by` (confirmed on 50210). The RIS reporting radiologist has it empty.

In `parse_assignment()` (the **one** ingestion boundary — fixes both columns, both popups, and the
persisted snapshot at once):

```python
assigner = str(a.get("last_assigned_by") or "").strip()
has_assigner = bool(assigner)
# A radiologist/typist id with NO assigner is the RIS reporting radiologist,
# not an internal assignment — do not treat it as assigned.
assigned = bool(primary_id) and has_assigner
```

- Gate it behind a default-on flag (e.g. `AIPACS_INO_ASSIGN_REQUIRE_ASSIGNER`); `=0` restores the
  current behaviour. Keep `radiologist_name`/`radiologist_id` in the parsed dict (useful for the
  tooltip) but do not let them set `assigned`.
- **Do not** infer assignment from the local history either: `merge_assignment_status` already only
  lets the local log contribute `completed` *on top of* a server assignment — with `assigned=False`
  the local-only `completed` path must also be re-checked so a stale local record can't resurrect a
  green icon (verify `resolve_assignment_status` / the `server_assigned=False & local==completed`
  branch after the change).
- Guard tests: extend `tests/code/network/test_server_config_and_assignment_refresh.py` — a
  radiologist with empty `last_assigned_by` parses to `assigned=False`; with a `last_assigned_by`
  parses to `assigned=True` (the 50210 case); no-radiologist stays `assigned=False`.

*Files:* `modules/network/ino_assignment_refresh.py` (not plugin-mirrored). Re-verify the icon
mapping in `patient_table_widget._assign_icon_state` / `_apply_report_status_display` needs no change
once the source is corrected.

**Open question for the reception team (one line):** should a radiologist assigned through the INO
**reception web UI** (secretary-side) count as "assigned" in AI-PACS? If yes, confirm whether that
path also sets `last_assigned_by`; if it doesn't, a different/additional server signal is needed. The
data here shows the reporting radiologist does **not** set it, and the user wants those hidden — so
`last_assigned_by` is the correct discriminator for the reported case.

---

## 8. Fix as implemented (2026-07-15)

Single point, the ingestion boundary — `modules/network/ino_assignment_refresh.py`
(NOT plugin-mirrored):

- New `require_assigner()` — reads `AIPACS_INO_ASSIGN_REQUIRE_ASSIGNER` (**default ON**;
  `=0/false/off/no` restores legacy id-only behaviour).
- `parse_assignment()` now computes
  `assigned = bool(primary_id) and (bool(last_assigned_by) or not require_assigner())`.
  The assignee identity fields (`assignee_id` / `radiologist_name` / …) are still returned
  (so a tooltip can still name the reporting radiologist); only the **`assigned` verdict**
  is gated.

Because `fetch_assignment → set_state` persists `assigned` into `ino_assignment_server_state`,
and every consumer (both column icons, the Assign right-click menu, and the "Current
assignment" card in the Assign/Referral popup) reads that one snapshot via
`assignment_display_for` / `get_assignment_details`, this **one change corrects all of them**.
No change was needed in `patient_table_widget.py`, `internal_assignment_panel.py`, or
`ino_assignment_details.py`.

**Self-healing snapshot:** the on-disk `ino_assignment_server_state` still holds the old
`assigned=True` from before the fix. It is overwritten the next time the refresh runs for a
row (every patient search, and the Refresh-Status button which forces a re-read), because
`refresh_assignments` re-invokes the gated `parse_assignment` and writes `assigned=False`. No
manual data cleanup is required.

**Left intentionally unchanged:** `merge_assignment_status`'s
`server_assigned=False & local==completed → completed` branch (a genuinely-assigned reception
that was locally marked *completed* and then cleared server-side should stay green). With the
gate in place no new local-`completed`-without-server records can form; a pre-existing one (only
possible if a user manually marked a former false-active as completed) would still show green
until re-touched — acceptable, and changing that branch would risk the legitimate case.

**Tests:** `tests/code/network/test_server_config_and_assignment_refresh.py` — added
`test_reporting_radiologist_without_assigner_is_not_assigned`,
`test_same_payload_becomes_assigned_once_an_assigner_is_present`,
`test_require_assigner_flag_off_restores_legacy_id_only`, `test_require_assigner_is_default_on`.
Existing `test_parse_assignment_reads_the_real_50210_payload` (has the assigner) and the
`merge_assignment_status` tests are unaffected. Gate logic validated standalone in-sandbox; run
the full file on Windows via `run_test.ps1` (the sandbox FUSE mount serves truncated copies —
a false SyntaxError at the unrelated `set_state(` call — so trust the host, not in-sandbox
`py_compile`).

## 9. Verification & safety

- Read-only against the server (`GET`); **no writes**. No product code changed.
- Root cause reproduced from live data (§2) + code (§3) + git (§4); the fix point is a single pure
  function at the ingestion boundary, default-on with a kill switch, and leaves the (correct) column
  unification from `c4809f16` intact.
- Isolation unchanged: `ino_assignment_refresh` imports only the isolated INO stack; no
  consultation/Drive/education coupling.
```
