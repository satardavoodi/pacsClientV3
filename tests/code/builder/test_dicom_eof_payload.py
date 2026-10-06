"""Retain the pure EOF compatibility reader in both Client frozen cores."""
from pathlib import Path

import pytest

from builder.source_identity import input_paths

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("spec", [
    "builder/spec/appA_workstation.spec",
    "builder nuitka/AIPacs_nuitka.spec.py",
])
def test_both_cores_explicitly_retain_dicom_compatibility_reader(spec):
    assert '"PacsClient.utils.dicom_reader"' in (ROOT / spec).read_text(encoding="utf-8")


def test_snapshot_retains_compatibility_reader_and_viewer_mirrors():
    assert "PacsClient/utils/dicom_reader.py" in input_paths(ROOT)
    for name in ("decode_service.py", "lightweight_2d_pipeline.py", "pydicom_2d_backend.py"):
        relative = Path("modules/viewer/fast") / name
        source = ROOT / relative
        mirror = ROOT / "builder/plugin package/packages/viewer/payload/python" / relative
        assert source.read_bytes() == mirror.read_bytes()
        assert "PacsClient.utils.dicom_reader" in source.read_text(encoding="utf-8")
