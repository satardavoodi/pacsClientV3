# MPR Geometry — Source-vs-Build Regression Investigation (2026-06-11)

## Question
Source (VS Code run) shows correct MPR geometry/orientation; installed builds
**3.2.5** and **3.2.6** show the *old* geometry bug. Is this stale packaging, a
wrong source path, duplicate MPR code, cached compiled files, or another
build/deployment defect — and how do we stop it recurring?

## Verdict
**The regression in 3.2.5 / 3.2.6 is version chronology, not a broken pipeline.**
Current source is **`3.2.6.1`** (`pyproject.toml`). The geometry/orientation
fixes (plane-aware routing, `_view_axes`, native-plane interpolation, crosshair
always-on-top, anatomical cameras) were committed late-May → 2026-06-09 — *after*
3.2.5 and 3.2.6 were cut. Those installed builds simply never contained the fix.

The **current** pipeline packages the corrected geometry correctly, verified at
every layer (see Evidence). No rogue duplicate, no wrong source path, no stale
pyc in the packaged core.

## Evidence
1. **No rogue duplicate.** The only `zeta_mpr` copies are the live source
   (`modules/mpr/zeta_mpr`), the build outputs
   (`builder/output/stage/core/engine/...`, `.../dist/AIPacs/engine/...`), and
   throwaway agent worktrees under `.claude/worktrees/`. The `advanced_mpr`
   plugin payload is a bundled **3D Slicer** (a different feature), not the
   Python geometry.
2. **Single authoritative path.** Every `_view_axes` / `_anat_look_axis` /
   `_anatomical_camera` reference lives inside `modules/mpr/zeta_mpr/` only.
3. **Staged == source.** All six geometry files in the current staging tree are
   byte-identical to source.
4. **Frozen bytecode carries the fix.** The decisive check: extracted the PYZ
   embedded in the current `AIPacs.exe` (3.2.6.1) and confirmed every fix marker
   is present in the *marshalled* code → `PYZ_MPR_OK`. The on-disk `.py` is
   *not* the import source (see Structural risk), so this bytecode check is the
   authoritative one.

## Structural risk that was worth hardening
The PyInstaller spec uses `module_collection_mode={"modules": "pyz+py"}`
(`builder/spec/appA_workstation.spec:251`). The `modules` package is frozen into
the **PYZ bytecode** *and* written to disk as `.py`. **At runtime the PYZ
bytecode imports — the on-disk `engine/modules/...py` does not.** So an
incremental PyInstaller build (the default; full clean only with `--clean-build`)
that desynced its cache *could* embed stale geometry in the PYZ while the on-disk
`.py` still looked current — a silent regression that "looks fixed" on disk.
Nothing previously caught that. The build already force-cleans on a *PyInstaller
version* mismatch, but not on stale *app-module* bytecode.

## Fixes applied (regression prevention)
1. **Build-time PYZ gate** — `builder/audit/scripts/verify_mpr_in_pyz.py` extracts
   the frozen PYZ and asserts the corrected-geometry markers are in the marshalled
   code of the four MPR modules. Wired into `build_release.py` as
   `verify_frozen_mpr_geometry(source_dir)`, called right after bundle validation
   and before staging. Fails the release build on `PYZ_MPR_STALE`. Deliberate
   bypass: `AIPACS_ALLOW_STALE_MPR_PYZ=1` (never for a release).
2. **Runtime provenance marker** — `modules/mpr/zeta_mpr/_mpr_provenance.py`
   logs once at first MPR open: `[MPR_GEOMETRY_PROVENANCE] impl=zeta_mpr
   geometry_ok=… frozen=… loader=… version=… path=…` plus a per-symbol
   fingerprint, and logs ERROR if a stale/regressed geometry is loaded. Surfaces
   a bad build in `app.log` instead of silently.
3. **Headless regression tests** — `tests/code/mpr/test_mpr_geometry_regression.py`:
   named-case plane routing (CT axial, brain axial/sagittal/coronal, pure
   sagittal, oblique shoulder MR axial/coronal/sagittal) + a source-marker guard
   that stays in lockstep with the build gate. 13 passed (plus the existing 30 in
   `test_mpr_canonicalize.py`).

## How to cut a clean release going forward
- Build with **`python builder/build_release.py --clean-build`** for releases
  (wipes the PyInstaller + stage caches; the gate then proves the PYZ).
- The gate runs automatically; a stale build now **fails** rather than ships.
- After launching any build, confirm `app.log` shows
  `[MPR_GEOMETRY_PROVENANCE] … geometry_ok=True … frozen=True`.

## Validation performed
- Current dist `AIPacs.exe` = `3.2.6.1`, `PYZ_MPR_OK` (frozen bytecode has the fix).
- 43 headless geometry tests green (`tests/code/mpr/`).
- All edited files compile on the `.venv`.
- Live behaviour on a clean client machine and a fresh `--clean-build` are the
  human-side validation steps (no 3.2.5/3.2.6 install exists on this workstation
  to diff; they live on client machines).
