"""TS-1 guard tests: compressed-DICOM codec plugins must be bundled WITH their
entry-point metadata in the shipped installer.

Root cause these pin
--------------------
pylibjpeg builds its decoder table from ``importlib.metadata`` ENTRY POINTS, not
from importability.  `builder/spec/appA_workstation.spec` (the spec that builds
the customer installer) bundled the codec modules but never called
``copy_metadata``, so in the frozen build pylibjpeg registered ZERO decoders and
every JPEG 2000 / JPEG-lossless / JPEG-LS image failed to decode — silently,
because every import-based capability probe still reported the codecs present.

Measured on this repo before the fix:
    decoders registered (normal):            12
    decoders registered (metadata stripped):  0

The Nuitka spec, the legacy AIPacs.spec and the Lite Viewer all handled this
correctly; only the shipped spec did not.
"""
from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SPEC_DIR = PROJECT_ROOT / "builder" / "spec"
APP_A_SPEC = SPEC_DIR / "appA_workstation.spec"

if str(SPEC_DIR) not in sys.path:
    sys.path.insert(0, str(SPEC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --------------------------------------------------------------------------
# the mechanism itself
# --------------------------------------------------------------------------

def test_pylibjpeg_resolves_decoders_through_entry_points_not_imports():
    """The premise of the whole fix: importability is NOT what registers a decoder."""
    pytest.importorskip("pylibjpeg")
    eps = metadata.entry_points()
    groups = eps.groups if hasattr(eps, "groups") else list(eps)
    assert "pylibjpeg.pixel_data_decoders" in groups, (
        "pylibjpeg discovers decoders via this entry-point group; if it is absent "
        "the codec dist-info is missing and nothing compressed will decode"
    )


def test_required_transfer_syntaxes_have_a_registered_decoder():
    pytest.importorskip("pylibjpeg")
    from pylibjpeg.utils import get_pixel_data_decoders

    from builder.release_gate import REQUIRED_DECODER_UIDS

    decoders = set(get_pixel_data_decoders() or {})
    missing = sorted(uid for uid in REQUIRED_DECODER_UIDS if uid not in decoders)
    assert not missing, (
        "no decoder registered for: "
        + ", ".join(f"{u} ({REQUIRED_DECODER_UIDS[u]})" for u in missing)
    )


def test_stripping_metadata_kills_every_decoder(monkeypatch):
    """Reproduce the frozen-build failure: modules importable, metadata gone."""
    pytest.importorskip("pylibjpeg")
    import importlib

    import pylibjpeg.utils as pu

    before = len(pu.get_pixel_data_decoders() or {})
    assert before > 0, "precondition: decoders present in the dev environment"

    class _EmptyEPs(list):
        groups: list = []

        def select(self, **_kw):
            return []

    monkeypatch.setattr(metadata, "entry_points", lambda *a, **k: _EmptyEPs())
    importlib.reload(pu)
    try:
        after = len(pu.get_pixel_data_decoders() or {})
    finally:
        monkeypatch.undo()
        importlib.reload(pu)

    assert after == 0, (
        "expected the stripped-metadata build to register zero decoders; got "
        f"{after}. If this changes, the guard below may no longer describe the "
        "real failure mode."
    )
    assert len(pu.get_pixel_data_decoders() or {}) == before, "reload must restore"


# --------------------------------------------------------------------------
# the shipped spec
# --------------------------------------------------------------------------

def test_shipped_spec_bundles_codec_entrypoint_metadata():
    src = APP_A_SPEC.read_text(encoding="utf-8")
    assert "copy_metadata" in src, (
        "appA_workstation.spec builds the CUSTOMER INSTALLER and must bundle codec "
        "dist-info; without it JPEG 2000 / JPEG-lossless / JPEG-LS silently fail"
    )
    assert "codec_metadata_datas(copy_metadata)" in src


def test_shipped_spec_declares_codec_hidden_imports():
    src = APP_A_SPEC.read_text(encoding="utf-8")
    assert "codec_hiddenimports()" in src


def test_shipped_spec_adds_metadata_to_datas_before_dedup():
    """The copy_metadata result must land in `datas` while it can still be deduped."""
    src = APP_A_SPEC.read_text(encoding="utf-8")
    add_at = src.index("codec_metadata_datas(copy_metadata)")
    dedup_at = src.index("datas = list(dict.fromkeys(datas))")
    assert add_at < dedup_at, "codec metadata must be added to datas before the dedup line"


# --------------------------------------------------------------------------
# the shared definition
# --------------------------------------------------------------------------

def test_spec_utils_exposes_a_single_codec_source_of_truth():
    import spec_utils

    assert set(spec_utils.CODEC_PACKAGES) == {"pylibjpeg", "libjpeg", "openjpeg", "rle"}
    assert spec_utils.CODEC_PACKAGES["libjpeg"] == "pylibjpeg-libjpeg"
    assert spec_utils.CODEC_PACKAGES["openjpeg"] == "pylibjpeg-openjpeg"
    assert spec_utils.CODEC_PACKAGES["rle"] == "pylibjpeg-rle"


def test_codec_metadata_datas_never_raises_on_a_missing_codec():
    """A codec absent from the build env must be reported and skipped, not fatal —
    the release gate is what stops such a build, not an exception mid-spec."""
    import spec_utils

    def _boom(dist):
        raise LookupError(f"no metadata for {dist}")

    assert spec_utils.codec_metadata_datas(_boom) == []


def test_codec_metadata_datas_collects_every_distribution():
    import spec_utils

    seen = []

    def _fake(dist):
        seen.append(dist)
        return [(f"{dist}.dist-info/METADATA", f"{dist}.dist-info")]

    out = spec_utils.codec_metadata_datas(_fake)
    assert seen == list(spec_utils.CODEC_PACKAGES.values())
    assert len(out) == len(spec_utils.CODEC_PACKAGES)


def test_release_gate_codec_map_matches_spec_utils():
    """Two copies exist by necessity (the gate must not import PyInstaller specs);
    pin them together so they cannot drift."""
    import spec_utils

    from builder.release_gate import CODEC_DISTRIBUTIONS

    assert CODEC_DISTRIBUTIONS == spec_utils.CODEC_PACKAGES


# --------------------------------------------------------------------------
# the release gate
# --------------------------------------------------------------------------

def test_pre_build_gate_includes_the_codec_check():
    from builder import release_gate

    names = [c.name for c in release_gate.run_pre_build_gate()]
    assert "codec_plugins_build_env" in names


def test_post_stage_gate_includes_the_metadata_check():
    from builder import release_gate

    src = (PROJECT_ROOT / "builder" / "release_gate.py").read_text(encoding="utf-8")
    i = src.index("def run_post_stage_gate")
    block = src[i:i + 700]
    assert "check_stage_codec_metadata(core)" in block
    assert hasattr(release_gate, "check_stage_codec_metadata")


def test_codec_build_env_check_passes_in_this_environment():
    from builder.release_gate import check_codec_plugins_available

    pytest.importorskip("pylibjpeg")
    check = check_codec_plugins_available()
    assert check.status == "PASS", check.details


def test_stage_metadata_check_fails_when_dist_info_absent(tmp_path):
    from builder.release_gate import check_stage_codec_metadata

    core = tmp_path / "core"
    (core / "engine").mkdir(parents=True)
    # modules present, metadata absent — exactly the shipped-bug shape
    for mod in ("libjpeg", "openjpeg", "rle", "pylibjpeg"):
        (core / "engine" / mod).mkdir()

    check = check_stage_codec_metadata(core)
    assert check.status == "FAIL"
    assert any("ZERO decoders" in d for d in check.details)


def test_stage_metadata_check_passes_with_dist_info_and_entry_points(tmp_path):
    from builder.release_gate import CODEC_DISTRIBUTIONS, check_stage_codec_metadata

    core = tmp_path / "core"
    core.mkdir(parents=True)
    for dist in CODEC_DISTRIBUTIONS.values():
        d = core / f"{dist.replace('-', '_')}-9.9.9.dist-info"
        d.mkdir()
        (d / "METADATA").write_text("Name: " + dist, encoding="utf-8")
        (d / "entry_points.txt").write_text(
            "[pylibjpeg.pixel_data_decoders]\n1.2.840.10008.1.2.4.90 = openjpeg:decode_pixel_data\n",
            encoding="utf-8",
        )

    check = check_stage_codec_metadata(core)
    assert check.status == "PASS", check.details


def test_stage_metadata_check_fails_when_entry_points_txt_missing(tmp_path):
    """dist-info present but no entry_points.txt is the SAME failure — decoders=0."""
    from builder.release_gate import CODEC_DISTRIBUTIONS, check_stage_codec_metadata

    core = tmp_path / "core"
    core.mkdir(parents=True)
    for dist in CODEC_DISTRIBUTIONS.values():
        d = core / f"{dist.replace('-', '_')}-9.9.9.dist-info"
        d.mkdir()
        (d / "METADATA").write_text("Name: " + dist, encoding="utf-8")

    check = check_stage_codec_metadata(core)
    assert check.status == "FAIL"
    assert any("entry_points.txt MISSING" in d for d in check.details)


# --------------------------------------------------------------------------
# the on-disk detection tool
# --------------------------------------------------------------------------

def test_scan_tool_is_read_only():
    src = (PROJECT_ROOT / "tools" / "diagnostics" / "scan_compressed_studies.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("shutil.move", "shutil.copy", "os.replace", "os.remove",
                      "unlink(", "rmtree", "save_as("):
        assert forbidden not in src, f"detection tool must not mutate storage ({forbidden})"


def test_scan_tool_classifies_transfer_syntaxes(tmp_path, monkeypatch):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless, generate_uid

    sys.path.insert(0, str(PROJECT_ROOT / "tools" / "diagnostics"))
    import scan_compressed_studies as tool

    def _mk(path: Path, ts):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ts
        ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        path.parent.mkdir(parents=True, exist_ok=True)
        ds.save_as(str(path), write_like_original=False)

    root = tmp_path / "dicom"
    _mk(root / "study_plain" / "1" / "Instance_0001.dcm", ExplicitVRLittleEndian)
    _mk(root / "study_comp" / "2" / "Instance_0001.dcm", JPEG2000Lossless)
    # mixed study: one series raw, one compressed
    _mk(root / "study_mixed" / "1" / "Instance_0001.dcm", ExplicitVRLittleEndian)
    _mk(root / "study_mixed" / "2" / "Instance_0001.dcm", JPEG2000Lossless)

    out = tmp_path / "report.json"
    rc = tool.main(["--root", str(root), "--sample", "0", "--json", str(out)])
    assert rc == 0

    import json as _json
    data = _json.loads(out.read_text(encoding="utf-8"))
    assert data["studies_total"] == 3
    assert data["studies_affected"] == 2
    assert set(data["affected"]) == {"study_comp", "study_mixed"}
    assert data["mixed_studies"] == ["study_mixed"]
    assert str(JPEG2000Lossless) in data["affected"]["study_comp"]["transfer_syntaxes"]
