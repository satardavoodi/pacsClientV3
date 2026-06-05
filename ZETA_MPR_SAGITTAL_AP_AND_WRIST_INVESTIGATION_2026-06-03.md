# Zeta MPR — Sagittal A/P + Wrist Orientation Investigation (44608, 44573)

**Date:** 2026-06-03  **Status:** ✅ **RESOLVED & LIVE-VALIDATED** (was: investigation report).
The single general geometric rule proposed here was implemented and confirmed in the running app.
Authoritative as-built: `docs/pipelines/mpr-geometry-pipeline.md` §10b (anatomical grid-aligned
cameras) + §10c (plane-aware viewport routing).

> ## RESOLUTION (2026-06-03 — implemented & live-validated)
> The fix did **not** end up using the `Roll/Azimuth` rule sketched below; that was superseded by
> the cleaner **anatomical grid-aligned cameras** (`ZetaAnatA` = world→patient `A`, exactly the
> §1 transform `[-IOP_row, -IOP_col, slice_axis_lps]`) plus **plane-aware viewport routing**
> (each pane looks down the volume axis whose patient direction best matches that pane's
> plane-normal). Net effect on the two cases here:
> - **44608 sagittal A/P — FIXED.** The native sagittal series now renders in the **Sagittal
>   pane** with Superior at top and **Anterior/face on the viewer-LEFT**, Posterior right
>   (live-confirmed: Series 7 "Slice 9/20", crisp). The A/P reversal is gone.
> - **Wrist/limb (sagittally-positioned) — handled by the same rule:** the up axis is chosen by
>   sign from `A`, so a sagittally-acquired extremity is upright without a per-case exception.
> - Axial-acquired series are **unchanged** (routing reduces to the old look=Z/X/Y) — verified
>   live on 44608 Series 5 axial ("Slice 11/24", crisp, Anterior-top/R-left). No regression.
> Markers are now computed from the actual camera vectors (single layer, no yellow duplicate
> overlay — `ZETA_MPR_DIAG=0`). The §1 world→patient model below remains correct and is the
> foundation of the shipped fix; only the *correction mechanism* changed (cameras, not Roll).

---

## 0. Cases under review
- **44608** (brain MRI, `rahnama^abdolrasool`). Up/down already fixed. Remaining: in the
  **sagittal** reconstruction the anterior/posterior axis is reversed — the face/nose appears
  on the viewer's **right**; it should be on the **left**.
- **44573** (`VALIOLAH MOHAMADIYEH`). **This is a CT wrist** (two CT studies, series `Bone`/
  `Tissue` + oblique reformats), not an MRI — worth noting since the request said "MRI". The
  hand was positioned sagittally in the gantry; the reconstruction shows the **fingers pointing
  down**, expected up.

---

## 1. The corrected volume→patient model (important — supersedes a wrong assumption)

The earlier as-built used the field-data **DirectionMatrix** to map world→patient. That is
**wrong for the slice (Z) axis**: the matrix's third column is the *geometric IOP normal*,
but the VTK volume's world **+Z (k‑axis) follows the slice STACKING order**, which can be the
**opposite** of the normal. The correct transform (verified — see §3) is:

```
A = [ −IOP_row , −IOP_col , slice_axis_lps ]      (columns; all in patient LPS)
    where slice_axis_lps = normal × sign( (IPP_last − IPP_first) · normal )   # actual +Z stacking
```
- `A[:,0]` = patient direction of volume **+X** (= −IOP_row, after the radiological X‑flip).
- `A[:,1]` = patient direction of volume **+Y** (= −IOP_col, VTK Y convention).
- `A[:,2]` = patient direction of volume **+Z** (= the real slice‑stacking direction).

LPS sign → label: X(+L/−R), Y(+P/−A), Z(+S/−I). Screen mapping for any 2D view (parallel
projection): **screen‑up = A·view_up**, **screen‑right = A·(direction × view_up)**.

`A` reproduces every known‑correct observation (axial A‑top/L‑right for all; **shoulder
sagittal = S/P, the working case**), which the matrix‑based model did **not**.

---

## 2. Canonical (radiological) targets
| View | screen‑up | screen‑right |
|---|---|---|
| Axial | Anterior (A) | patient Left (L) |
| Sagittal | Superior (S) | **Posterior (P)** (⇒ anterior on viewer‑left / face‑left) |
| Coronal | Superior (S) | patient Left (L) |

---

## 3. Per‑case results (computed with `A`, validated against observed behaviour)

Current logic = fixed world‑axis cameras + (when **marked**, i.e. +Z‑Inferior) `Roll(180)` on
sagittal and `Azimuth(180)+Roll(180)` on coronal. A `Roll(180)` is a **180° rotation → it
flips up/down AND left/right together.**

| Case (axial input) | `slice_axis_lps` (vol +Z) | marked? | axial | sagittal | coronal |
|---|---|---|---|---|---|
| **Brain 44608 S5** | `[0.02,0.00,+1.00]` → **Superior** | **no** | A/L ✓ | **S/A ✗ (A/P reversed)** | S/L ✓ |
| Shoulder 44082 S4 (works) | `[0.26,0.45,−0.86]` → Inferior | yes | A/L ✓ | **S/P ✓** | S/L ✓ |
| Axial CT (works) | `[0,0,−1]` → Inferior | yes | A/L ✓ | S/P ✓ | S/L ✓ |
| Wrist CT 44573 `Bone` S201/202 | `[0,0,+1]` → **Superior** | **no** | A/L ✓ | **S/A ✗** | S/L ✓ |

> The brain prediction matches the report exactly: **only the sagittal A/P is wrong**; axial
> and coronal are correct. The shoulder/CT (marked) predict fully canonical, matching "works".

---

## 4. Root cause

**Both remaining defects share one root cause: the single `Roll(180)` couples the sagittal
vertical (S/I) and horizontal (A/P) axes.**

- For a **marked** volume (+Z‑Inferior: shoulder, wrist‑if‑descending, CT), `Roll(180)` flips
  **both** axes, which happens to make sagittal = S/P (correct up *and* correct A/P).
- For an **unmarked** volume (+Z‑Superior: brain 44608, the wrist `Bone` series 44573),
  no `Roll` is applied — correctly leaving the **up/down** alone (it's already Superior‑up) —
  but that also means the **horizontal A/P flip never happens**, so sagittal screen‑right stays
  **Anterior** instead of Posterior. Hence "face on the right."

You **cannot** fix this by toggling the marker: marking the brain to flip A/P would `Roll(180)`
it and put it **upside down again** (re‑introducing the regression we just fixed). The vertical
and horizontal corrections must be **decoupled**. This is the architectural limit of the
fixed‑camera + `Roll/Azimuth` design — not a per‑patient anomaly.

**Wrist 44573 specifics.** It is a CT whose axial `Bone` series stacks `+Z → Superior`
(unmarked), so it is in the same family as the brain (reconstructions miss the horizontal
flip). Because the hand was positioned *sagittally*, the finger↔forearm long axis is rotated
within the patient LPS frame, so "fingers up" is governed by whichever **patient axis** the
fingers point along after positioning — see §5 caveat.

---

## 5. Proposed general rule (one rule; no per‑case `if`s)

**Set each reconstructed view's camera directly from the patient‑canonical target via `A`,
instead of fixed world vectors + coupled `Roll/Azimuth`.** For a view with targets
`(up*, right*)` from §2:

```
view_up_world   = A⁻¹ · up*          (= Aᵀ · up*, A orthonormal)
normal_world    = A⁻¹ · (up* × right*)        # camera looks along ±this
```
i.e. pick, per view, the volume axis + sign for `view_up` and the camera side so that
`screen‑up = up*` and `screen‑right = right*`. This is fully determined by `A` (raw DICOM:
IOP row/col + IPP slice ordering). It:

- **Decouples** vertical and horizontal → fixes brain/wrist sagittal A/P **and** keeps S/I.
- **Subsumes** the current `slice_axis_lps[2] < 0` ("+Z‑Inferior") marker rule — that rule was
  only choosing the `view_up` *sign* for up/down; the general rule chooses up **and** right
  signs for all three views.
- Is **modality‑agnostic and positioning‑agnostic** — no patient/modality exceptions.
- Preserves the working cases: under this rule shoulder, CT, and the (already‑correct) brain
  axial/coronal all evaluate to the canonical targets (verified with `A` in §3).

This is exactly the matrix‑/triad‑driven camera approach used by 3D Slicer (`SliceToRAS`) and
Cornerstone3D (`MPR_CAMERA_VALUES`), adapted to this volume's `A`.

**§5 caveat (wrist / non‑anatomical positioning).** The rule orients by **patient axes**
(S/I/A/P/L/R). If the hand was positioned with fingers toward **Superior**, canonical
Superior‑up = fingers‑up ✓. If positioning rotated the fingers onto a horizontal patient axis,
the canonical patient‑axis view will be **consistent and correctly labelled** but may not place
fingers at the top — "fingers up" would then require orienting by the **anatomy long‑axis**,
which is a separate (rarer) feature, not a geometry bug. Recommend confirming the wrist's
finger direction in patient LPS before promising "fingers up"; do **not** add a wrist‑specific
flip.

---

## 6. What must NOT be done
- Do **not** flip the brain's marker to fix A/P (breaks the up/down regression fix).
- Do **not** add per‑case / per‑modality `if` branches for A/P. The §5 rule covers all tested
  cases (brain, wrist‑CT, shoulder, axial CT, oblique) with one mechanism.
- Do **not** mirror the image data to flip A/P (that breaks L/R handedness and measurements).
- If §5 is implemented, the four existing `Roll/Azimuth` correction sites
  (`_mpr_views` ×3, `_mpr_rendering`, `_mpr_series`, `_mpr_oblique`) and the `_mpr_canonicalize`
  marker logic are **replaced together** — keep them consistent (see as‑built §5/§10).

---

## 6b. Marker duplication + inconsistency (added after screenshot review)

**There are two orientation‑label layers, and they disagree because one is hardcoded:**
1. **WHITE/grey** — `_mpr_crosshair_render.py::_add_orientation_labels` (font 14, colour
   `(0.8,0.85,0.9)`), driven by the **hardcoded** `_mpr_orientation.py::_get_orientation_labels`
   (fixed tables; sag/cor use H/F). This is the production layer and is **not geometry‑aware**,
   so it is wrong whenever the rendered orientation differs from the hardcoded assumption.
2. **YELLOW** — `mpr_diagnostic_validator.py` (font 16, colour `(1.0,1.0,0.0)`, S/I/L/R/A/P
   **computed from direction vectors**), installed by `_mpr_views.py:96`
   `self._diag.install_diag_overlays()` **only when `DIAG_ENABLED`**, where
   `DIAG_ENABLED = (os.environ["ZETA_MPR_DIAG"] == "1")` (validator line 48).

**Root cause of the duplication:** the yellow layer is a **debug overlay**. It appeared only
because the recent agent launch commands set `ZETA_MPR_DIAG=1`. A normal launch (VS Code, no
`ZETA_MPR_DIAG`) shows only the white layer. So: (a) production launches must **not** set
`ZETA_MPR_DIAG`; (b) the remaining (white) layer is **hardcoded and must be replaced with
camera‑derived labels** — this is the same root as §8 of the as‑built. The yellow set is *not*
"the correct image" — it is a validator readout; do not keep it as the production marker.

**Confirms the user's principle:** the image must be oriented correctly first (via §5), then a
**single, camera‑derived** marker layer describes it. Never flip only the labels.

## 7. Recommended next step
Implement §5 behind the existing `AIPACS_ZETA_MPR_CANONICALIZE` flag (default OFF, reversible):
compute `A` in the widget from the field‑data IOP + the IPP‑derived `slice_axis_lps`, set the
three 2D cameras from the canonical triads, and retire the coupled `Roll/Azimuth` + the
`view_up`‑only marker. Then live‑validate the full matrix: **brain 44608** (sagittal A/P now
face‑left, up/down preserved), **wrist 44573**, **shoulder 44082**, **axial CT**, and the
oblique cases — confirming none of the currently‑working orientations regress. Update
`docs/pipelines/mpr-geometry-pipeline.md` §6/§8 when it lands.
