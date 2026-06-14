# Master plan — viewer / download / geometry hardening + H1 (2026-06-14)

Consolidates this session's investigations (pipeline review, 46271 download fix, H1
header-rescan, geometry deep-dive across VTK / MPR / slice-ordering / reference-lines /
zeta-sync) into one prioritized, **regression-safe** roadmap. Source docs:
`docs/reports/PIPELINE_REVIEW_OPEN_THUMB_DOWNLOAD_DRAGDROP_2026-06-14.md`,
`docs/reports/GEOMETRY_EVAL_VTK_MPR_2026-06-14.md`,
`docs/plans/performance/H1_HEADER_RESCAN_DEPENDENCY_ANALYSIS_2026-06-14.md`.

---

## 1. Already shipped this session (committed, verified)

| commit | change | verification |
|---|---|---|
| 535732e | manual drag-drop always replaces viewport (`force_reload`) | prior session |
| 6cfe868 | fix drop regression (thread `force_reload` through `_PWSeriesMixin`) | 16 guards; live 11/11 drops OK |
| 4844417 | stage logging (drop/unload/resync) + pipeline review doc | baseline-proven 0 new failures |
| 1e3c997 | KPI + conflict + test-baseline doc | — |
| d5b825a | DM dedup `DownloadTask.series_list` (fix 46271 423988 phantom) | 6 guards; **user-confirmed 46271 OK** |
| 641d6d9 | FAST `[SERIES UNLOAD]` + `[THUMB-MISS]` observability | 16 drop guards; not mirrored |

These are done and not revisited below. (Concurrent work `da681a9`/`1b6a2ed`/`d2bcb2e` —
FAST colour/overlay for 46382 — landed on top; independent of this plan.)

---

## 2. Consolidated findings (the as-built truth)

**Pipeline (open/thumbnail/download/sync/drag-drop):** sound. Manual drop wins via
`force_reload` (bypasses all 6 same-series no-ops, last-drop-wins via `expected_token`).
Proposals P1 (instance-level partial-series resume) and P2 (thumbnail refresh on download
completion) were found **already implemented** on verification — no work needed.

**46271 inflated download count:** root-caused to a duplicated `series_list` inflating
`total_image_count`; fixed centrally by de-duping in `DownloadTask`. The clean reopen shows
no duplicates (the inflation came from accumulated session state) — the guard is a safety net.

**H1 (viewer re-reads DICOM headers, ~800–1424 ms):** two scan subsystems —
Track 1 metadata (`image_io._build_metadata_headers_only`; DB alternative exists, gated off)
and Track 2 FAST pixel-pipeline (`dicom_header_scan.scan_series_header_entries`). DB
completeness (304,779 instances): IOP/IPP/pixel_spacing **99.4%** present; `slice_thickness`
**99.1% NULL** and `spacing_between_slices` **99.5% NULL** (a **downloader write gap** — the
source files have them); `photometric_interpretation`/`samples_per_pixel` **columns absent**;
**12.4% of series have no instance rows** (import/offline-cloud path).

**Geometry invariant (the key result):** inter-slice z-spacing is derived from **IPP deltas**
everywhere — VTK (`source_geometry.py:370`), FAST (`pydicom_2d_backend._attach_spacing_between_slices:521`),
MPR (SimpleITK on IPP-sorted files). Slice ordering (IPP-projection sort, re-applied after DB
read), reference lines (plane-plane intersection in LPS), and zeta sync (`modules/zeta_sync/`,
100% LPS-world-based) all hard-depend only on **IOP + IPP + PixelSpacing** (≈99–100% in DB).
The 99%-NULL `slice_thickness`/`spacing` tags are display/fallback only (the one consumer,
the FAST through-plane slab, self-heals to IPP-derived median). **⇒ DB-served geometry is
safe across the entire stack.**

**Robustness holes found:** (a) zeta MPR has **no spacing validation** (unlike VTK's
jitter/validity checks); (b) `test_display_geometry` has **stale assertions** (the intended
`matrix[2,3]=-1.0` 1-based→0-based offset) that fail and thus **mask real regressions**.

---

## 3. The plan (tiered; each item: change · files · risk · SAFETY · acceptance)

### Tier 1 — Safe hardening (do first; no clinical-behavior change)

**T1.1 Document + guard the IPP-derived z-spacing invariant.**
- Change: a guard test asserting z-spacing is computed from IPP (not the tags) in
  source_geometry + pydicom_2d_backend; add a one-line code comment at each derivation site.
- Risk: **none** (test + comment only).
- Safety: no runtime change.
- Acceptance: test passes; future code that trusts the NULL tag for spacing fails the guard.

**T1.2 Add spacing validation to zeta MPR.**
- Change: in `StandardMPRViewer` (mpr_viewer/widget.py) after `self.spacing` is set, validate
  `spacing[i] > 0`; log a warning on non-positive or high IPP jitter; sane single-slice
  handling. **Warn/log only — never drop or rescale data.**
- Risk: low (log-only; no geometry mutation).
- Safety: gated `AIPACS_MPR_SPACING_VALIDATE` (default on, log-only); no behavior change to
  rendering; coordinate with concurrent zeta-MPR VRT work (independent code path).
- Acceptance: MPR opens unchanged; warning appears only on genuinely bad spacing; mpr suite green.

**T1.3 Fix the stale `test_display_geometry` assertions.**
- Change: update the identity-expecting cases to expect the intended `matrix[2,3]=-1.0`.
- Risk: **none** (test-only); un-masks real geometry regressions.
- Safety: confirm against the documented 1-based→0-based intent before editing.
- Acceptance: `test_display_geometry` green; the geometry suite can again catch regressions.

### Tier 2 — H1 Phase 0: DB foundation (prerequisite for the perf win)

**T2.1 Fix the downloader write gap** (persist `slice_thickness` + `spacing_between_slices`).
- Change: pin + fix the drop in `series_downloader._save_series_instances_to_db` /
  `dicom_db` insert so the read values are written.
- Risk: medium (download_manager is guarded + plugin-mirrored).
- Safety: additive only; existing geometry unaffected (it uses IPP, not these); run
  `tests/code/download_manager`; **sync + verify plugin mirror**.
- Acceptance: new downloads have non-NULL slice_thickness/spacing; dedup + resume guards green.

**T2.2 Add `photometric_interpretation` + `samples_per_pixel` columns + write them.**
- Change: additive schema columns (default NULL/MONOCHROME2/1) + downloader writes them.
- Risk: low-medium (additive schema, backward-compatible).
- Safety: columns nullable with safe defaults; readers fall back; no migration of behavior.
- Acceptance: new rows populated; old rows NULL (handled by fallback).

**T2.3 Lazy backfill of existing rows** (slice_thickness/spacing + new columns).
- Change: off-thread, idempotent backfill (read header once, fill NULLs).
- Risk: medium (touches the live DB).
- Safety: off-thread, never blocks UI; idempotent; back up DB first; rate-limited.
- Acceptance: NULL rates drop; no UI stall; no DB corruption (WAL checkpoint clean).

**T2.4 Per-series completeness self-check** (the safety gate for Phase 1).
- Change: a helper that returns DB-vs-disk decision per series (DB row count == on-disk file
  count AND required geometry fields non-NULL).
- Risk: low (read-only decision).
- Safety: **defaults to disk** (current behavior) unless DB proven complete.
- Acceptance: returns disk for the 12.4% no-row / NULL series; DB only for complete ones.

### Tier 3 — H1 Phase 1/2: the perf win (gated, reversible)

**T3.1 Track 1 — DB metadata path** (captures the ~1424 ms).
- Change: land `_ensure_study_pk_for_db_metadata` (study_pk upfront) + flip
  `AIPACS_VIEWER_DB_METADATA`.
- Risk: medium-high (changes the load path).
- Safety: **env flag (default off → on only after validation)** + **disk fallback** on any
  completeness-check miss + **golden compare** (T4) before flip. IPP-derivation preserved.
- Acceptance: golden compare exact-match; open latency 1424 ms → ~20–60 ms; viewer/MPR/sync
  unchanged visually.

**T3.2 Track 2 — FAST pixel-pipeline geometry from DB** (the second scan).
- Change: build `DicomHeaderEntry` from DB rows (needs T2.2 columns); disk fallback.
- Risk: medium-high.
- Safety: flag + disk fallback + golden compare; only after T2 complete.
- Acceptance: golden compare exact-match; second header scan eliminated for complete series.

---

## 4. No-regression strategy ("don't break anything")

Every change in this plan obeys these guarantees:

1. **Flag-gated + default = current behavior.** Each behavioral change (T1.2, T2.x, T3.x) is
   behind an env flag whose default reproduces today's behavior; rollback = flip the flag.
2. **Disk fallback never removed.** The header-scan path stays the fallback at every DB site;
   any DB miss / NULL / count-mismatch silently falls back to disk.
3. **Golden compare before any DB-path flip (T3).** An automated test builds metadata both
   ways (DB vs header) over a sample of studies (CT, MR, multi-frame, RGB/colour, doc #100000,
   multi-study) and requires **exact** match on IOP/IPP/pixel_spacing/derived-slice_step/
   rows/cols/WL/rescale/photometric/samples + identical slice order. No flip without a pass.
4. **Clinical invariants (never violated):** never drop/truncate real image data or geometry;
   geometry z-spacing always IPP-derived; cross-patient isolation guards preserved;
   FAST mode never instantiates VTK windows.
5. **Regression baseline (measured 2026-06-14, HEAD d2bcb2e).** `download_manager + viewer +
   system + ui_services` = **73 failed, 1757 passed, 20 skipped, 1 xfailed**. The 73 are
   PRE-EXISTING (geometry R30/`test_display_geometry`, B34/B35 prefetch, stage1/2 FAST
   migration, theme retint) and were **unchanged** across this session's commits + the
   concurrent colour work (passes rose, failures flat) — i.e. zero regressions introduced.
   **Any change here must keep the failure set ≤ this baseline**; a new failure is a
   regression to fix before commit. (Tier 1's T1.3 will REDUCE the baseline by greening the
   stale `test_display_geometry` cases.) Run the four suites after each change and diff.
6. **Guard tests per change** (source + behavioral) committed with the change.
7. **Plugin-mirror sync + verify** for any mirrored file (download_manager core/models, etc.):
   `tools/dev/sync_plugin_mirrors.py` then `verify_plugin_mirrors.py`.
8. **DB safety for T2.3:** back up `dicom.db` first; off-thread; idempotent; WAL checkpoint.
9. **One change per commit, each independently revertable**; high-risk items (T2, T3) land
   separately and are validated live on the source build before the next.

---

## 5. Recommended sequence

1. **Tier 1** (T1.1 → T1.3): safe, immediate, un-masks regressions and closes the MPR hole.
2. **Tier 2** (T2.1 → T2.4): DB foundation; T2.1 (write gap) is also a standalone correctness
   bug worth fixing regardless of H1.
3. **Tier 3** (T3.1 → T3.2): only after Tier 2 + a green golden compare; gives the latency win.

Stop after any tier — each is independently valuable and safe. Tier 1 alone improves
robustness and test integrity with effectively zero risk; the H1 latency win (Tier 3) is
optional and fully reversible.

---

## 6. Acceptance / definition of done (per change)

- Targeted guard tests green; broad suite shows **no new failures vs the §5 baseline**;
- compile clean; plugin mirror verified (if applicable);
- behavior flag defaults to current behavior; disk fallback exercised in a test;
- for T3: golden compare passes and a live source-build open/drag/MPR/sync spot-check matches
  the header-path result;
- memory + the relevant as-built doc updated.
