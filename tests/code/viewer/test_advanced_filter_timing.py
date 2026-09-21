"""Filter timing must not alter synthetic pixels, geometry or expose metadata."""
import hashlib
import logging
import re

import numpy as np
import pytest
import SimpleITK as sitk


@pytest.mark.parametrize("modality,expected", [
    ("MR", "12efacc07584c5aa49713354361cbe749859a61cd585709b9e98ce72632bfc15"),
    ("CT", "c21409fb8aadf56d9b418651868eea4b3a51aa53dafc44f6ed8bd44af959a8de"),
])
def test_stage_timing_preserves_baseline_pixels_and_geometry(tmp_path, caplog, modality, expected):
    from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters
    settings = tmp_path / "filters.json"
    settings.write_text("{}")
    image = sitk.GetImageFromArray(np.random.default_rng(51).integers(-100, 2000, (8, 32, 40), dtype=np.int16))
    image.SetSpacing((.7, .8, 2))
    image.SetOrigin((3, 4, 5))
    with caplog.at_level(logging.INFO):
        output = apply_filters(image, {"series": {"modality": modality, "series_name": "SENSITIVE_SENTINEL"}}, settings, max_itk_threads=1)
    assert hashlib.sha256(sitk.GetArrayFromImage(output).tobytes()).hexdigest() == expected
    assert output.GetSpacing() == image.GetSpacing()
    assert output.GetOrigin() == image.GetOrigin()
    assert output.GetDirection() == image.GetDirection()
    assert output.GetPixelID() == image.GetPixelID()
    records = [r.getMessage() for r in caplog.records if "[ADVANCED-FILTER-KPI]" in r.getMessage()]
    assert len(records) == 1
    message = records[0]
    assert "SENSITIVE_SENTINEL" not in message
    assert str(settings) not in message
    for stage in ["prepare", "noise", "anti_alias", "multiscale", "laplacian", "adaptive", "finalize"]:
        match = re.search(stage + r"_ms=([0-9.]+)", message)
        assert match and float(match.group(1)) >= 0


@pytest.mark.parametrize("failure", [False, True])
def test_skipped_or_failed_filters_do_not_claim_completion(tmp_path, monkeypatch, caplog, failure):
    from PacsClient.pacs.patient_tab.utils import image_filters
    settings = tmp_path / "filters.json"
    settings.write_text('{}' if failure else '{"MR": {"enabled": false}}')
    image = sitk.Image([8, 8, 8], sitk.sitkInt16)
    if failure:
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic filter failure")
        monkeypatch.setattr(image_filters.sitk, "SmoothingRecursiveGaussian", fail)
    threads = sitk.ProcessObject.GetGlobalDefaultNumberOfThreads()
    import sys
    priority = None
    if sys.platform == "win32":
        import ctypes
        priority = ctypes.windll.kernel32.GetThreadPriority(ctypes.windll.kernel32.GetCurrentThread())
    try:
        with caplog.at_level(logging.INFO):
            if failure:
                with pytest.raises(RuntimeError, match="synthetic filter failure"):
                    image_filters.apply_filters(image, {"series": {"modality": "MR"}}, settings)
            else:
                assert image_filters.apply_filters(image, {"series": {"modality": "MR"}}, settings) is image
        assert not any("[ADVANCED-FILTER-KPI]" in r.getMessage() for r in caplog.records)
    finally:
        sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(threads)
        if priority is not None:
            ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), priority)
