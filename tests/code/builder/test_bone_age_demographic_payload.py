"""Both shared Slicer editions retain the lightweight demographic contract."""
from pathlib import Path
from builder.eagle_eye_client_payload import stage_client


def test_shared_client_payload_contains_demographic_validation(tmp_path):
    target = stage_client(tmp_path)
    root = Path('modules/ai_imaging/eagle_eye_remote')
    assert (target/'demographics.py').read_bytes() == (root/'demographics.py').read_bytes()
    assert not (target/'demographics_ui.py').exists()
