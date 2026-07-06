# Clinical Reliability Audit — Series Identity + Target-Context Identity

**Date:** 2026-07-05
**Scope:** the full identity chain `Server → Download → Database → Disk → Cache → UI/Thumbnail → Drag-and-Drop → Viewport`, plus target-context identity (which viewport / layout slot / study container a series lands in).
**Question asked:** can data from different patients, studies, previous exams, or similarly-numbered series ever be mixed, and is the *place* a series is assigned always correct?
**Method:** four parallel code audits (download/disk/DB, caches, drag→viewport, thumbnail/UI + previous-exam) + a runtime-log analysis of the most recent multi-study session, followed by first-hand re-verification of the highest-stakes code regions.

---

## 1. Verdict

**The identity chain is clinically sound against the catastrophic failure mode — silently displaying one patient's or study's pixels as if they were another's.** That outcome is structurally prevented at storage level and blocked at display level, and the most recent runtime session shows **zero identity violations** across every guard.

The residual risk is concentrated in **one architectural smell** — several in-memory viewer caches (including ZetaBoost) are keyed by the **bare series number, not study-scoped** — whose worst *observed* outcome is a **display miss / render abort** (a visible reliability defect: a blank or "stuck on the previous series" viewport), **not** a silent misread. It is currently masked by three independent compensating guards. The correct structural fix is already written up (the 48952 report) and deferred; it should be prioritized because defense-in-depth that relies on reactive drop-and-reload is more fragile than correct-by-construction keying.

Two failure modes must be kept distinct throughout this audit:

| Failure mode | Clinical severity | Found? |
|---|---|---|
| **Silent misread** — wrong patient/study/series shown *as if correct* | Catastrophic | **Not found.** Structurally prevented + gated + zero log violations. |
| **Display miss** — correct series fails to show / wrong series shows then is blocked (blank/stuck viewport) | Reliability defect (visible to user) | **One latent surface** (bare-number cache keying), masked by guards. |

---

## 2. The identity model, as actually built

Every series is anchored to two DICOM-derived, globally-unique identifiers and one hierarchy:

- **`SeriesInstanceUID` (`series_uid`)** — globally unique per DICOM. This is the real identity key in the download task, the database, the DM→UI status bridge, the progressive-binding layer, and (critically) the viewport identity gate.
- **`StudyInstanceUID` (`study_uid`)** — globally unique per DICOM; the disk-folder key and the study-scope for every series-number lookup.
- **`patient_id`** — resolved from the **study's own server metadata**, never from "the patient the user happened to click."

`series_number` is treated correctly as **study-local only** — the `SeriesDescriptor` contract states it *"must never be treated as globally unique"* (`PacsClient/utils/patient_study_set.py:77-97`). The multi-study UI layer adds an **offset display key** = `study_slot * 1_000_000 + original_series_number` so that a previous exam's "series 4" (key `1000004`) is never confused with the current study's "series 4" (key `4`) at the UI/drag level.

This is the right model. The failures that exist are all in *places that don't honor it consistently*, not in the model itself.

---

## 3. Stage-by-stage verdict

| Stage | Identity key used | Collision-safe? | Evidence |
|---|---|---|---|
| **Download task** | `DownloadTask.study_uid` + `patient_id`; each `SeriesInfo` carries `series_uid` (validated non-empty) + `series_number` | **Yes** | `modules/download_manager/core/models.py:60-83,124-149`; de-dup keys `uid:`-first `:162-198` |
| **Disk storage** | `SOURCE_PATH/<study_uid>/<folder>/` — **patient-blind, study-scoped**; intra-study same-number disambiguated by `series_uid` | **Yes (strongest layer)** | `series_downloader.py:286-288` (explicitly excludes `patient_id`), `core/series_folder.py:57-103` (`[SERIES_NUMBER_COLLISION]`) |
| **Database** | `series.series_uid TEXT UNIQUE` (global) + `study_fk → studies.study_pk`; every number lookup scoped by `study_pk` | **Yes** | `database/dicom_db.py:103-122`; study-scoped lookup `:1273-1274`; cross-study reassignment guard `:663-687` |
| **Decode / L2 pixel cache** | file **path** (embeds `study_uid` folder) + policy tag + `::f{frame}` for multi-frame; partitioned under `{study_uid_hash}/` | **Yes** | `lightweight_2d_pipeline.py` `_decode_cache_key`; `disk_pixel_cache.py` |
| **Thumbnail store** | `(study_uid, series_number)` | **Yes** | `modules/storage/thumbnail_store.py:88,112` |
| **VTK volume cache** | `(study_uid, series_uid)`, Advanced-side only, default-OFF | **Yes** | `PacsClient/utils/volume_cache.py:33-37`; Fast viewer never reaches it |
| **ZetaBoost disk L2 (SQLite)** | `PRIMARY KEY(tab_key, series_number)` = `(study_uid, series_number)` | **Yes** | `modules/zeta_boost/disk_cache.py:73` |
| **ZetaBoost in-memory cache** | **bare `series_number`** (per-tab dict) | **No — see §5** | `modules/zeta_boost/cache_engine/_zb_cache.py:19,47,138` |
| **Viewer memory dicts** (`_hot_series_cache` / `_series_cache` / `_series_number_to_index`) | **bare `series_number`**; validated by `_entry_is_valid` (series-number string + object identity, **not** study_uid) | **No — see §5** | `_vc_backend.py:758-858`, `_entry_is_valid:766-789` |
| **DM → UI status bridge** | globally-unique **`series_uid`**; sibling admitted only via this-patient's own `series_uid → number` map | **Yes** | `home_download_service.py:386-414` `_belongs_to_open_thumbnails` |
| **Drag payload** | offset **display key** only (bare int); full identity re-derived at drop | **Yes (indirectly) — see §6** | `thumbnail_manager.py:638-640,1553`; `_vw_dragdrop.py:46-60,302-308` |
| **Viewport load resolution** | `_resolve_canonical_series_identity(key)` → `(study_uid, orig_series, series_uid)` from the entry itself | **Yes** | `_vc_load.py:2002-2032`; entry-authority `:94,492-502`; poison guard `:299-333` |
| **Viewport display (render choke point)** | **`series_uid`** (primary) + `study_uid` (secondary), stamped per-viewport | **Yes** | `qt_fast_container.py:621-668` `[IDENTITY-GATE]` |

---

## 4. Confirmed protections (the "what is working" list)

These were verified in code and, where noted, corroborated by the most recent runtime logs.

**Storage identity is correct-by-construction.** Disk folders are `SOURCE_PATH/<study_uid>/<series>/` with `patient_id` *deliberately excluded* — so a same-numbered series in two different studies physically cannot share a directory. The DB keys series on the globally-unique `series_uid`, with `series_number` a nullable attribute that is only ever resolved within a `study_pk`. Intra-study same-number collisions (two distinct `series_uid` sharing a number — a real data-loss case that had occurred) are disambiguated by a deterministic `series_uid`-suffixed folder.

**Cross-patient study isolation is authoritative on server `patient_id`.** `merge_study_uids` drops any study whose server owner ≠ the target patient, keeping only the selected, sanctioned, and unknown-owner studies (`patient_study_set.py:221-243`). **Runtime proof:** the most recent session dropped **33 foreign studies** (`phase=study_uid_cross_patient_dropped`, `requested_patient_id != owner_patient_id`) — the guard is not theoretical, it fires.

**Previous-exam merge only ADDs, never weakens.** Each previous exam keeps its **own** `study_uid` + `patient_id`; disk stays patient-blind; a foreign exam enters the current viewer **only** through the `sanctioned_uids` allow-list, populated solely on an explicit user row-click from server-verified National-ID linkage — never from caller/current context. The four automatic cross-patient guards (open / reconcile / resync / back-fill) are untouched. **Runtime proof:** `[PREVIOUS-EXAM] merged study=…49106 owner_pid=49106 (sanctioned, metadata-only)` — the prior kept its own patient/study identity, distinct from the host.

**The DM→UI status bridge is cross-patient- and cross-study-sibling-safe.** Every progress/completion signal carries the globally-unique `series_uid`. A sibling-study event is admitted into *this* patient's thumbnail lane only when its `series_uid` is in *this* patient's own `series_uid → number` map — a map built solely from this patient's `server_series_info`, so a foreign patient's UID can never resolve. Progressive binding (`display_key_awaiting_series_uid`) matches on `series_uid`, so two studies each with a "series 302" bind to the correct viewport by UID, not number.

**The viewport display gate keys on the strongest available signal.** `[IDENTITY-GATE]` (`qt_fast_container.py:621-668`, default-on) blocks a render whose incoming `series_uid` ≠ the per-viewport intended `series_uid`, **before** the previous bridge is torn down. The design comment is exactly right: a previous exam's series that was downloaded/saved under the wrong `study_uid` in the DB carries the *current* study_uid in its metadata (so study-only signals falsely match), but its `series_uid` still exposes the mismatch. This is genuinely robust — it is immune to DB study-poisoning. **Runtime proof:** 17 gate evaluations in the latest session, **`study_mismatch=False uid_mismatch=False` on every one** — no wrong-study render was ever attempted.

**Multi-study load resolution is correct.** Every `[MULTI-STUDY LOAD]` line in the logs resolved a *plain* key to the primary study folder and an *offset* key to its own secondary study folder, corroborated by `[VIEWPORT-LOAD-TRACE]` (`study_path == resolved_study` in all 13 traces). The primary-series **poison guard** (`_vc_load.py:299-333`) — a plain `< 1_000_000` key always belongs to the primary study, so a poisoned tab path is re-resolved to the primary — was verified in code and shows correct behavior in the logs. No `ViewportLoadFailed`, no native fault, no "already deleted" crash in the session.

---

## 5. Primary open gap — bare-number keying in the in-memory viewer caches (MEDIUM, latent, masked)

> **STATUS 2026-07-05: ADDRESSED (offscreen-verified, NEEDS-LIVE-VERIFY).** A flag-gated
> hardening (`AIPACS_CACHE_STUDY_IDENTITY`, default on) now makes study identity an
> intrinsic, positively-checked property of every viewer cache entry — see §5.1 below.
> Tracked as **OPT-17** in the master plan (§9/§15). The deeper ZetaBoost store-key
> reformat was deliberately **not** done (it breaks the digit-only warmup callback) and
> remains a larger staged item.

This is the one finding that all four audits converged on, and I re-verified it directly.

**What is true:**

- The **study-scoped key builder exists but is dead for lookups.** `_full_cache_key` returns `(study_uid, str(series_number))` (`_vc_cache.py:215-217`) — but nothing passes it to ZetaBoost. `_full_cache_get` calls `self.zeta_boost.query(str(series_number))` — the **bare number** (`_vc_cache.py:269,277`).
- **ZetaBoost's in-memory dict is keyed by the bare number.** `query`/`get`/`put`/`invalidate_series` all do `key = str(series_number)` against `self._cache` (`_zb_cache.py:19,47,138,263`). (Its *disk* L2 is correctly `(study_uid, series_number)` — only the memory tier is unscoped.)
- **The viewer's own dicts are bare-number too.** `_hot_series_cache` / `_series_cache` / `_series_number_to_index` are keyed by `str(series_number)`, and their validator `_entry_is_valid` checks the series-number **string** and **object identity** of the cached vtk/meta against `lst_thumbnails_data[idx]` — but **never compares `study_uid`** (`_vc_backend.py:766-789`).

**Why it is currently not a silent-misread hazard — three independent compensating guards:**

1. **The offset-key scheme separates studies at the key level within a tab.** A previous exam's series is keyed `1000004`, the current one `4` — different dict keys — so within one tab these caches don't actually hold two entries under the same bare string. Cross-study wrong-hits are prevented by the *key namespace*, not by an explicit study check.
2. **`_cache_entry_study_matches`** (`_vc_cache.py:219-252`) re-validates every ZetaBoost hit: it reads the cached entry's `study_uid`, resolves what study the key currently maps to, and on disagreement **drops the entry and forces a clean reload** (`[CACHE-STUDY-MISMATCH]`). This is the explicit fix for "viewport shows the previous series after multiple drag-and-drops."
3. **The viewport identity gate** (§4) blocks any wrong-study render that slips through, keyed on `series_uid`.

**Why it is still a real (lower-grade) defect:**

- `_cache_entry_study_matches` **fails open** — it returns "keep the entry" when the cached entry has no `study_uid`, or when the resolver is unavailable, or returns empty (`:232-236,244`). It can only *prove* a mismatch; it cannot *guarantee* identity.
- The viewer dict tiers 1-3 have **no study check at all** — only tier 4 (`_full_cache_get`) applies the study-match guard.
- The **observed** manifestation (report `MULTISTUDY_CURRENT_SERIES_DISPLAY_MISS_48952_2026-07-04.md`) is a **cache miss → render abort** (`_get_series_by_number_fast("2")` misses all tiers → `ViewportLoadingStateCleared series=None` → the previous exam stays on screen). That is a **display-availability defect**, visible to the user — not a silent wrong-patient read. The logs for the latest session show 36 first-tier `cache_result=miss` events, all cascading to `result=ok` (no resulting wrong display), so the symptom did not reproduce there — but no code fix is present either, so it remains standing on colliding multi-study same-numbered series.

**Recommended fix (already scoped, deferred):** study-scope the ZetaBoost memory key and the three viewer dicts to `(study_uid, series_number)` — matching the already-correct `_full_cache_key` and disk-L2 key — as the dedicated pass the 48952 report calls for (broad blast radius → must be done with a full `tests/code/viewer` run). A collision-proof `VolumeCache` keyed by `(study_uid, series_uid)` already exists in the tree (`volume_cache.py`) but is introduced **unused**; wiring it in is the structural endgame. Until then, the fragile part is that isolation depends on reactive drop-and-reload rather than correct keying.

### 5.1 Fix shipped 2026-07-05 (`AIPACS_CACHE_STUDY_IDENTITY`, default on) — OPT-17

Investigating the fix revealed *why* the "obvious" recommendation above (reformat the cache key to `study::num`) is **unsafe to apply blind**: the ZetaBoost warmup callback `_zeta_boost_load_series` (`patient_widget_viewer_controller.py:648,701`) hard-requires a **digit-only** key (`if not sn.isdigit(): return True`; `series_number=int(sn)`), so a composite key would silently break all series warmup. The engine is otherwise key-transparent, so the *store* re-key is containable — but it needs the warmup callback reworked to parse the composite back to a per-study disk number, which needs live GUI validation. That remains a **larger staged item**.

Instead, the shipped fix makes study identity **intrinsic to every cache entry's value and positively checked at every read tier**, which closes the two holes this section named without touching keys, the engine, warmup, or disk:

1. **`_full_cache_put` stamps `study_uid` at write time** (`_vc_cache.py`) — gap-fill only, resolved via `_resolve_canonical_series_identity`. Guarantees the read-side guard can never fail-open on a missing `study_uid` for an entry we wrote (closes the fail-open hole).
2. **`_entry_is_valid` (tiers 1-3) now rejects a cross-study entry** (`_vc_backend.py`) — compares the cached tuple's stored `study_uid` against the study the display key resolves to; on a positive mismatch it returns "invalid" → caller treats it as a miss → clean reload (closes the "tiers 1-3 have no study check" hole).
3. **Tier-4 fail-open branch is now logged** (`_cache_entry_study_matches`) so any legacy un-stamped entry is observable.

Guarantees: **multi-study-gated + positive-mismatch-only ⇒ single-study tabs and correctly-cached hits are byte-identical**; the check is availability-biased (a mismatch causes a reload, never a blank), with the fail-closed viewport `series_uid` identity-gate as the true clinical backstop. Kill switch `AIPACS_CACHE_STUDY_IDENTITY=0`. Guard: `tests/code/viewer/test_cache_study_identity.py` (11 green — truth-table + source-pins). Offscreen-verified; **NEEDS-LIVE-VERIFY** on a multi-study / previous-exam tab (watch `[CACHE-STUDY-IDENTITY] tier reject` → each reject must be followed by a correct reload, never a stuck viewport).

---

## 6. Other findings, ranked

| # | Severity | Finding | Location | Status / recommendation |
|---|---|---|---|---|
| 1 | ~~**MEDIUM** (latent, masked)~~ → **ADDRESSED 2026-07-05** | Bare-number keying in in-memory viewer + ZetaBoost caches (see §5) | `_zb_cache.py`, `_vc_cache.py:266-297`, `_vc_backend.py:758-858` | **Hardened via OPT-17 (§5.1):** study identity now stamped at put + positively checked at every read tier (`AIPACS_CACHE_STUDY_IDENTITY`, default on; 11 guard tests). NEEDS-LIVE-VERIFY. Store-key reformat still deferred (breaks digit-only warmup callback). |
| 2 | **MEDIUM** (guarded, config) | DB `series_uid` is *globally* UNIQUE (DICOM-correct). A **non-conformant duplicated** SeriesInstanceUID across studies would `UPDATE` the row's `study_fk` unless enforcement is on | `dicom_db.py:105`, guard `:663-687` | `[CrossStudyReassignment]` guard is **observe-only** by default. **Recommend defaulting `AIPACS_DB_ENFORCE_OWNER=1` for clinical builds.** |
| 3 | **LOW** (design, not defect) | Drag payload carries only the offset display key; full identity re-derived at drop | `_vw_dragdrop.py:46-60`; `thumbnail_manager.py:638-640` | Safe (offset key encodes the study slot; each tab owns its `_server_series_info` namespace). A self-describing payload (study_uid + series_uid) would remove the dependence on correct re-derivation. |
| 4 | **LOW** | DM `series_uid` degrades to a bare number if the task lookup misses | `_dm_workers.py:333` | Cannot cross-patient leak (a bare number won't match a foreign UID map); add a defensive log/guard only. |
| 5 | **LOW** | Study-completeness *probe* uses bare `series_number`, not the collision-safe folder resolver | `executor.py:96-99` | Read-only SKIP heuristic; cannot cause a collision or data loss (at worst a needless re-download). |
| 6 | **LOW** | Empty-UID number-fallback in task de-dup could collapse two same-number series **if both lack a UID** | `models.py:180-193` | Real server metadata always has UIDs; only the same-study viewer drag payload lacks them. No live path. |
| 7 | **INFO** | Reception-metadata `study_uid` can differ from the real on-disk `StudyInstanceUID` (48101) | `_pw_previous_exams.py:441-464` | A *display-failure* (exam won't render), not an identity leak — wrong images are never shown. Already instrumented via `[PREV-EXAM-UID]`. |
| 8 | **INFO** (verification debt) | Identity gate + poison guard are marked NEEDS-LIVE-VERIFY on 48912/48952 | — | The latest logs show both green (17 gate evals, 0 violations; all multi-study loads correct). Fold a formal live pass into the next clinical-lane session. |

---

## 7. Answers to the specific validation questions

- **Download Manager entries match the exact series being downloaded** — Yes. Keyed on `study_uid` + `patient_id` + per-series `series_uid`; `series_number` is never an identity.
- **Thumbnail UI items match the correct patient/study/series** — Yes. Offset-key scheme with permanent first-seen slot order; each entry stamps its own `study_uid`, original number, and absolute `series_path`. No raw `study_uid/series_number` disk joins in the thumbnail layer.
- **Drag-and-drop payloads preserve exact identity** — Yes, *indirectly*. The payload carries the offset key (which encodes the study slot); full `(study_uid, orig_series, series_uid)` is re-derived at drop within the correct tab namespace. Robust, though not self-describing (finding #3).
- **Viewport assignments match the correct patient/study/series** — Yes. Target cell is the exact dropped-on container (`vtk_widget=self`, `flag_change_selected_widget=False`); node lists are per-tab; the display gate keys on `series_uid`.
- **Cache entries are not reused for the wrong patient/study/series/target** — **Mostly.** Disk, DB, decode, thumbnail, volume, and ZetaBoost-disk caches are study-scoped and safe. The in-memory ZetaBoost + viewer dicts are bare-number-keyed (finding #1), masked by three guards; worst observed outcome is a display miss, not a wrong-patient read.
- **A previous-study series cannot be placed into a current-study viewport incorrectly** — Correct in the latest logs (gate + poison guard + entry-authority all green). The structural cache gap could still cause a *miss/stuck* symptom, not a silent wrong placement.
- **A current-study series cannot be confused with a previous-study series** — Correct: different offset keys, `series_uid`-keyed gate.
- **A series from another patient cannot be selected via similar numbering/naming/cache path** — Correct: server-`patient_id` isolation (33 foreign studies dropped at runtime) + study-scoped disk/DB + UID-keyed bridge.
- **The wrong viewport / layout / patient tab** — No cross-tab or cross-cell hazard found; target identity is sound.

---

## 8. Bottom line

The **"person + chair"** test the request framed — *which series, and which seat* — passes on both axes for the dangerous case. **Series identity** is anchored to the globally-unique `SeriesInstanceUID` at storage, database, download-bridge, and the display choke point; **target identity** (viewport cell, layout slot, patient tab, current-vs-previous container) is per-tab and per-container with a `series_uid`-keyed gate at the moment of render. Server `patient_id` is authoritative for patient isolation and demonstrably drops foreign studies at runtime. A **silent cross-patient / cross-study misread is structurally prevented and was not observed.**

The single meaningful weakness was **architectural, not behavioral**: a set of in-memory viewer caches (ZetaBoost memory tier + three viewer dicts) keyed on the bare `series_number` instead of `(study_uid, series_number)`, leaning on the offset-key namespace, a fail-open study-match guard, and the identity gate to stay safe. Its realistic worst case is a **visible display miss**, not a silent misread.

**Update 2026-07-05 — the weakness is now hardened (§5.1, OPT-17).** Study identity is stamped into every cache entry at write time and positively checked at every read tier (`AIPACS_CACHE_STUDY_IDENTITY`, default on, 11 guard tests green), so a wrong-study entry can no longer be returned even if the offset/slot invariants regressed — closing both named holes (fail-open guard + un-checked tiers 1-3) without the risk of the store-key reformat (which would break the digit-only warmup callback). It is offscreen-verified and **NEEDS-LIVE-VERIFY** on a multi-study source-build session.

**Remaining recommended actions, in order:** (1) default `AIPACS_DB_ENFORCE_OWNER=1` in clinical builds (cheap, closes finding #2); (2) live-verify OPT-17 on a multi-study / previous-exam tab, then consider the larger staged store-key reformat only with the warmup callback reworked; (3) formally live-verify the identity gate + poison guard on 48912/48952 and fold the result into the master plan's §15 history.

---

*Audit basis: static review of `modules/download_manager/*`, `database/dicom_db.py`, `PacsClient/utils/{patient_study_set,previous_exams,volume_cache}.py`, `PacsClient/pacs/patient_tab/ui/patient_ui/{_vc_cache,_vc_load,_vc_switch,_vc_backend}.py` + `vtk_widget/qt_fast_container.py`, `modules/zeta_boost/cache_engine/_zb_cache.py`, `PacsClient/pacs/workstation_ui/home_ui/home_download_service.py`, `_pw_thumbnails.py`, `_pw_previous_exams.py`; plus runtime analysis of `user_data/logs/{app,viewer_diagnostics,download_diagnostics}.log` for the 2026-07-05 00:16–01:12 multi-study session. Highest-stakes regions independently re-read line-by-line.*
