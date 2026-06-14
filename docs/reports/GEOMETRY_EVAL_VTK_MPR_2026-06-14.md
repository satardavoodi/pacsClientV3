# Geometry evaluation & manipulation — VTK (Advanced 2D) and zeta MPR (2026-06-14)

**Status:** investigation only (no code changed). Deep-dive requested after the H1
header-rescan analysis, focused on how geometry is **evaluated** (built/validated) and
**manipulated** (display transforms, reslice) in the two most geometry-demanding
consumers: the Advanced/VTK 2D viewer and the standard MPR (zeta_mpr). It also **corrects
the H1 risk framing** below.

## Headline (the load-bearing invariant)

**Across every viewer, inter-slice z-spacing is derived from ImagePositionPatient (IPP)
deltas projected on the IOP normal — NOT from the `SliceThickness` / `SpacingBetweenSlices`
DICOM tags.** Verified in three independent paths:
- Advanced/VTK: `source_geometry.py:370-392` — `slice_step = mean(|Δ(IPP·normal)|)`; the
  tags are **never read** in the geometry modules.
- FAST 2D / lazy volume: `pydicom_2d_backend._attach_spacing_between_slices` (:521-526)
  computes `spacing = median(|Δ(IPP·normal)|)` and writes it into
  `spacing_between_slices`; the lazy-volume consumer (`pydicom_lazy_volume.py:309-313`)
  reads that **computed** value, with `slice_thickness or 1.0` only as a single-slice
  last resort.
- MPR: `SimpleITK.ImageSeriesReader` reads the DICOM files and derives spacing from IPP;
  instances are IPP-sorted first (`image_io.py:2374-2381`).

Required geometry inputs are therefore **IOP + IPP + PixelSpacing**, all of which the DB
holds at ~99% (IOP/IPP/pixel_spacing 99.4% non-NULL). `SliceThickness`/`SpacingBetweenSlices`
(~99% NULL in the DB) are **display metadata / last-resort fallbacks**, not the geometry
source.

---

## 1. VTK / Advanced 2D — evaluation + manipulation

**Evaluation — `SourceGeometry.build_from_instances` (`modules/viewer/geometry/source_geometry.py`):**
builds the raw `ijk→LPS` 4×4 from IOP (row/col cosines → slice normal), IPP[0] (origin),
PixelSpacing (in-plane), and the IPP-derived `slice_step` (z). Validates determinant
(`<1e-6` → non-invertible → invalid), orthonormality (`ortho_err>0.02` warn), and spacing
jitter (`std` of IPP gaps > 1mm → `spacing_err` warn). Emits `[GEOMETRY_SOURCE_CONTRACT]`.
**Hard-fails (valid=False, viewer refuses to render) only on missing/degenerate IOP or
IPP** — exactly the fields the DB reliably has. Per-frame geometry kicks in when IOP
varies >2°.

**Manipulation — `DisplayGeometry` (`display_geometry.py`):** view ops `apply_y_flip`,
`apply_x_flip`, `apply_rotate_cw_90/ccw_90`, `reset`, composed into `display_to_raw`, with
`effective_display_ijk_to_lps = source_raw_to_LPS @ display_to_raw` recomputed and
re-validated (invertibility) on each change. `vtk_bridge.apply_source_geometry_to_vtk`
pushes origin + spacing (column norms) + direction matrix to the `vtkImageData`.
Measurements/markers/reference-lines go through `GeometryAPI` (LPS↔display).

**`[R30_FIX] matrix[2,3]=-1.0` is INTENTIONAL**, not a bug: display indices are 1-based
`[1..N]`, raw VTK is 0-based `[0..N-1]`, so `raw_k = display_k − 1`. The
`tests/code/viewer/test_display_geometry.py` cases that assert `np.eye(4)` are therefore
**stale** (they pre-date the 1-based convention) — they are part of the 73 pre-existing
viewer-suite failures and currently **mask real geometry regressions**. Fixing those tests
is a genuine geometry-investment item.

---

## 2. zeta MPR — evaluation + manipulation

**Evaluation:** `StandardMPRViewer` takes `self.spacing = image_data.GetSpacing()`
(`mpr_viewer/widget.py:146-149`) straight from the `vtkImageData`, which came from
`convert_itk2vtk` (`utils.py:182`) ← `SimpleITK.ImageSeriesReader` (IPP-derived spacing).
So MPR spacing is IPP-derived **via SimpleITK reading the files** — a path **separate from
the FAST metadata dict / DB**.

**Manipulation:** oblique reslicing (`_mpr_oblique.py:79-107`) computes sample distances
from `image_data.GetBounds()` (which depend on `self.spacing[2]`); crosshair move / scroll
/ rotate update reslice axes; the measurement ruler uses `self.mpr_viewer.spacing[look_axis]`
directly (`mpr_measurement_tools.py:144`).

**Gap found:** zeta_mpr has **no spacing validation** — no guard for zero/missing/
non-uniform z-spacing, no jitter check (unlike `source_geometry`'s `spacing_err`). If
spacing were ever wrong (e.g. a future DB-fed MPR with the tags trusted instead of
IPP-derived), the volume aspect, oblique angles, and z-measurements would be silently
wrong. Today it's safe because SimpleITK derives spacing from IPP, but the lack of a guard
is a latent robustness hole worth closing.

---

## 3. Correction to the H1 risk assessment

The earlier H1 doc (`H1_HEADER_RESCAN_DEPENDENCY_ANALYSIS_2026-06-14.md`) called the
`slice_thickness`/`spacing_between_slices` DB write-gap (D1) the **headline blocker** for
geometry. **This deeper investigation downgrades that:** because z-spacing is IPP-derived
everywhere, a DB-served metadata dict that carries per-instance **IPP** (99.4% present)
feeds the *same* IPP derivation — so geometry stays correct even with those tags NULL. D1
is therefore **defense-in-depth / display-accuracy**, not a geometry-correctness gate:
- It still matters for: overlay text ("Thk: 3.0mm"), the single-slice fallback, and the
  reference-line slab criterion (`dicom_sync_geometry.py:567`, which already falls back to
  `typical_spacing`).
- The real H1 gate for geometry is narrower: **preserve the IPP-derivation in any
  DB-served path** (never substitute the NULL tag), keep the per-series completeness check
  + disk fallback, resolve `study_pk` up front (D4), and golden-compare before flipping
  the flag.
- **MPR is not in H1's blast radius** (it loads via SimpleITK-from-files, not the FAST
  metadata dict). If H1 were ever extended to feed MPR from the DB, the volume builder MUST
  reconstruct z-spacing from IPP deltas — trusting the DB tag would break MPR.

Net: H1 for the in-scope FAST/VTK 2D path is **lower geometry risk than first stated**;
the dependency is "serve IPP + run the IPP derivation," which the DB already supports.

---

## 4. Geometry-investment items (recommended, independent of H1)

1. **Document + guard the IPP-derived-z-spacing invariant** as the canonical rule for all
   viewers (VTK, FAST, MPR). Any metadata/DB path must compute z from IPP, never trust the
   `SpacingBetweenSlices`/`SliceThickness` tag as primary.
2. **Add spacing validation to zeta_mpr** (z-spacing > 0; warn + log on IPP jitter or
   non-uniform spacing; sane single-slice handling) to match `source_geometry`'s checks —
   closes the silent-corruption hole.
3. **Fix the stale `test_display_geometry` assertions** (`matrix[2,3]=-1.0` is intended) so
   the geometry suite is green and can catch real regressions.
4. (Optional, defense-in-depth) **Phase 0 D1**: persist `slice_thickness`/
   `spacing_between_slices` + backfill — useful for overlays/fallbacks, no longer a
   geometry blocker.

All read-only so far; each item above is a separate, test-gated change pending approval.

---

## 5. Addendum — slice ordering, reference lines, zeta sync (2026-06-14)

Three more geometry consumers evaluated; all reinforce the IPP invariant and add **no new
H1 blockers**.

**Slice ordering — IPP-projection sort, applied regardless of metadata source.** The
authoritative order is `slice_pos = dot(IPP, slice_normal)` ascending, tie-broken by
instance_number → sop_uid → instance_path (`advanced_geometry_contract.py:~529, ~657`;
legacy `series_geometry_index.py:204`). Crucially, the DB returns rows
`ORDER BY instance_number, sop_uid, instance_path` (`database/manager.py:260`) — explicitly
a *stable retrieval order, NOT the anatomical order* — and the viewer **re-sorts by IPP
geometry after retrieval** (`image_io.py` DB fast path → `build_series_geometry_index` →
`dicom_files_for_itk`). So DB-served instances get correct geometric order. **No dependency
on slice_thickness/spacing.** Falls back to instance_number order only if IOP/IPP missing;
duplicate IPP → deterministic tie-break.

**Reference lines — plane–plane intersection in LPS.**
`geometry_api.reference_line_in_viewport` (:221-369) solves the two slice planes' line of
intersection (three-plane 3×3 solve), parameterizes it, projects endpoints to the target's
display coords, and clips to image bounds; near-parallel planes → no line (returns None).
The Advanced/VTK path uses `patient_toolbar/reference_line.py` (`rl_clip_plane_with_quad`,
`rl_lps_to_target_index`) with the same LPS math. Depends on IOP/IPP/pixel_spacing only —
**not** slice_thickness/spacing.

**Zeta sync — dedicated `modules/zeta_sync/` (geometry_utils, sync_manager, sync_context,
sync_types) + `_pw_sync.py` orchestration.** Synchronization is **100% LPS-world-based**,
not index-based: a source position → patient-LPS world coord (via that series' IOP/IPP/
spacing) → nearest target slice by **physical position scan** (`find_closest_slice_physical`,
handles sparse/discontinuous stacks), never a naive `k_src→k_tgt` offset. Cross-frame-of-
reference sync is intentionally blocked; missing geometry → graceful None (no crash).

**The one slice_thickness consumer is safe.** `dicom_sync_geometry.py:552-574` (FAST
through-plane "slab" gate) uses `slice_thickness` if present, else falls back to
`typical_spacing = median(|Δ(IPP·normal)|)` (IPP-derived), else (single slice) accepts. So
with the DB's ~99%-NULL `slice_thickness`, it self-heals to the IPP-derived median — correct
for contiguous stacks and gap-aware for sparse ones. No hard dependency on the NULL tag.

**Net:** slice ordering, reference lines, and zeta sync are all LPS/IPP-geometry-based with
graceful degradation, and **H1-safe** (hard deps = IOP/IPP/pixel_spacing, all ~99-100% in
DB). This widens the §3 conclusion: the *entire* geometry-consumer stack — VTK 2D, MPR,
ordering, reference lines, sync — is robust to DB-served geometry as long as IPP is served
and the IPP-derivation is preserved. The investment items in §4 (document/guard the IPP
invariant, add MPR spacing validation, fix stale geometry tests) remain the recommended
work.
