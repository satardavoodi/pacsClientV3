"""Guard: OPT-47 — large-study MPR must not crash on the FIRST open.

FIELD REPORT: opening MPR on a ~700-800 slice study crashed and closed the app on the FIRST
attempt; after relaunching, the SAME study opened fine.

ROOT CAUSE (three compounding parts, all verified in source):
 1. **GPU budget below the volume.** `_create_3d_view` set a FIXED
    `SetMaxMemoryInBytes(512 MB)`; VTK applies its own MaxMemoryFraction (default 0.75) on
    top => ~384 MB effective. 384 MiB / (512*512*2 B) = **768 slices** — exactly the reported
    700-800 range. Past the budget the mapper partitions the volume into several 3D textures
    while ALSO holding a gradient-opacity texture (`SetDisableGradientOpacity(0)`) and 4x MSAA.
    It uses `vtkGPUVolumeRayCastMapper` directly (NOT `vtkSmartVolumeMapper`), so there is **no
    CPU fallback** — a failed GPU allocation is a driver-level access violation, i.e. a silent
    process death with no Python traceback.
 2. **Host-memory triple copy.** `convert_itk2vtk` did `GetArrayFromImage` (copy #1) ->
    `arr[:, ::-1, :]` (negative-stride view) -> `if not C_CONTIGUOUS: arr.copy()` (copy #2,
    which therefore ALWAYS fired), while the CALLER still held the ITK buffer => ~1.26 GB
    transient for an 800-slice study.
 3. **Teardown released almost nothing** (`Finalize()` only) — no `ReleaseGraphicsResources`,
    so VRAM accumulated across a session. That is why a RELAUNCH (fresh VRAM) succeeded.

These tests pin the fixes. The byte-identity test is the important one: the memory saving must
NOT change a single voxel.
"""
from pathlib import Path

import numpy as np
import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "modules" / "mpr").is_dir() and (anc / "PacsClient").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _views_src() -> str:
    return (_repo_root() / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
            / "_mpr_views.py").read_text(encoding="utf-8")


def _layout_src() -> str:
    return (_repo_root() / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
            / "_mpr_layout.py").read_text(encoding="utf-8")


def _utils_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "utils"
            / "utils.py").read_text(encoding="utf-8")


# ── 1. BEHAVIOURAL: the single-copy conversion is byte-identical ──────────────
# The optimisation replaces  GetArrayFromImage -> flip-view -> .copy()
# with                       GetArrayViewFromImage -> flip-view -> ascontiguousarray.
# Both must yield the same values AND a C-contiguous, INDEPENDENT buffer.

def _legacy(vol):
    arr = vol.copy()          # GetArrayFromImage == an owning copy
    arr = arr[:, ::-1, :]
    if not arr.flags["C_CONTIGUOUS"]:
        arr = arr.copy()
    return arr


def _optimised(vol):
    arr = vol                 # GetArrayViewFromImage == a zero-copy view
    arr = arr[:, ::-1, :]
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    return arr


def test_single_copy_is_byte_identical_to_legacy():
    rng = np.random.default_rng(20260729)
    vol = rng.integers(-1024, 3071, size=(8, 6, 5), dtype=np.int16)
    legacy, opt = _legacy(vol), _optimised(vol)
    assert legacy.shape == opt.shape and legacy.dtype == opt.dtype
    assert np.array_equal(legacy, opt), "voxel values changed — geometry/quality regression!"
    assert opt.flags["C_CONTIGUOUS"], "VTK requires a contiguous buffer"


def test_optimised_result_is_independent_of_the_source_buffer():
    # vtk_image pins the array as _numpy_backing_store and OUTLIVES the ITK image, so the
    # result must NOT alias the source (that would be a use-after-free once ITK frees it).
    vol = np.arange(2 * 3 * 4, dtype=np.int16).reshape(2, 3, 4)
    out = _optimised(vol)
    before = out.copy()
    vol[:] = -999                      # simulate ITK releasing/overwriting its buffer
    assert np.array_equal(out, before), "result aliases the ITK buffer — use-after-free risk"


def test_y_flip_is_preserved():
    vol = np.arange(2 * 3 * 4, dtype=np.int16).reshape(2, 3, 4)
    assert np.array_equal(_optimised(vol), vol[:, ::-1, :])


# ── 2. BEHAVIOURAL: the GPU budget arithmetic ────────────────────────────────
# Mirrors the inline rule in _create_3d_view.

def _budget(vol_bytes, enabled=True):
    heavy = enabled and vol_bytes >= (320 * 1024 * 1024)
    very_heavy = enabled and vol_bytes >= (512 * 1024 * 1024)
    cap = 1024 * 1024 * 512
    if enabled and vol_bytes > 0:
        cap = max(cap, int(vol_bytes * 1.6))
    return cap, heavy, very_heavy


def _bytes_for(slices, w=512, h=512, bpp=2):
    return slices * w * h * bpp


def test_800_slice_volume_gets_a_cap_above_its_own_size():
    """The reported crash size. VTK also applies MaxMemoryFraction (0.75), so the cap must
    exceed the volume by a real margin or the mapper takes the partitioned path."""
    vb = _bytes_for(800)                      # ~419 MB
    cap, heavy, very_heavy = _budget(vb)
    assert cap > vb, "cap must exceed the volume"
    assert cap * 0.75 > vb, "cap must clear VTK's 0.75 MaxMemoryFraction too"
    assert heavy, "an 800-slice volume must drop the gradient texture"
    assert not very_heavy


def test_legacy_512mb_cap_was_below_the_effective_need_at_768_slices():
    """Documents the ORIGINAL defect: the fixed 512 MB cap * 0.75 = 384 MB effective, which a
    768-slice 512x512 int16 volume exactly exhausts."""
    assert _bytes_for(768) == 384 * 1024 * 1024
    assert (1024 * 1024 * 512) * 0.75 == 384 * 1024 * 1024


def test_normal_studies_are_byte_identical_to_legacy():
    # a typical 200-slice CT keeps the legacy 512 MB cap, gradient opacity ON, MSAA 4
    cap, heavy, very_heavy = _budget(_bytes_for(200))
    assert cap == 1024 * 1024 * 512 and not heavy and not very_heavy


def test_kill_switch_restores_legacy_behaviour():
    cap, heavy, very_heavy = _budget(_bytes_for(800), enabled=False)
    assert cap == 1024 * 1024 * 512 and not heavy and not very_heavy


# ── 3. SOURCE PINS: wiring + flags ───────────────────────────────────────────

def test_vrt_budget_is_wired_and_flag_gated():
    src = _views_src()
    assert 'AIPACS_MPR_VRT_GPU_BUDGET' in src
    assert "volume_mapper.SetMaxMemoryInBytes(_vrt_cap)" in src
    assert "SetDisableGradientOpacity(1 if _heavy else 0)" in src
    assert "SetMultiSamples(0 if _very_heavy else 4)" in src
    # the fixed cap must be gone as the ONLY value
    assert "SetMaxMemoryInBytes(1024 * 1024 * 512)" not in src


def test_single_copy_is_wired_and_flag_gated():
    src = _utils_src()
    assert 'AIPACS_ITK2VTK_SINGLE_COPY' in src
    assert "GetArrayViewFromImage" in src
    assert "np.ascontiguousarray(arr)" in src
    # The ITK image must NOT be dropped before the copy exists (the zero-copy view aliases
    # its buffer). Match the STATEMENT (own line), not the word inside the explanatory comment.
    body = src[src.find("def convert_itk2vtk"):]
    body = body[:body.find("return vtk_image")]
    statements = [ln.strip() for ln in body.splitlines() if not ln.strip().startswith("#")]
    assert "del itk_image" not in statements, \
        "dropping the ITK image invalidates the zero-copy view (use-after-free)"


def test_full_teardown_releases_gpu_and_host_memory():
    src = _layout_src()
    i = src.find("def cleanup(self)")
    assert i != -1
    body = src[i:i + 12000]
    assert "AIPACS_MPR_FULL_TEARDOWN" in body
    for step in ("ReleaseGraphicsResources", "RemoveAllObservers", "RemoveAllViewProps",
                 "SetInputData(None)", "self.viewers.clear()", "self.image_data = None"):
        assert step in body, f"teardown missing: {step}"
    # GL resources must be released BEFORE Finalize() (context must still be valid)
    assert body.find("ReleaseGraphicsResources") < body.rfind("Finalize()")
    # the deferred-render timer must be stopped (a pending render into a dead window)
    assert "_render_timer" in body
