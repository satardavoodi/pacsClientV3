"""Guard: a DICOM instance must not be dropped because of the payload KEY NAME.

Roshana, 2026-07-12 (second log batch). After the missing-SeriesNumber fix, the
metadata fetch succeeded and the download started — but every instance was
skipped:

    📥 Downloading series 900001 (2 images)
    ⚠️ Empty DICOM data for instance 1
    ⚠️ Empty DICOM data for instance 1
    ✅ Series 900001 complete: 0 downloaded, 0 skipped
    [INCOMPLETE_SERIES] on_disk=0 expected=2 — server may not hold all instances
    ⚠️ No DICOM files found in …\\900001

The client read the bytes from ONE key (`dicom_data`), but the service contract
itself defines them under two names — `DicomInstanceResponse.dicom_data` and
`DicomImageInfo.image_data` ("Raw DICOM file bytes") — and server builds differ.
A server answering with `image_data` looked exactly like a server returning an
empty image: the series "completed" with 0 files and the study never displayed.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.download_manager.network.socket_client import (  # noqa: E402
    _INSTANCE_PAYLOAD_KEYS,
    _extract_instance_payload,
)


def test_the_documented_key_is_used_unchanged():
    """The healthy case must be byte-identical — every other center."""
    payload, key = _extract_instance_payload({"dicom_data": "QUJD", "instance_number": 1})
    assert payload == "QUJD"
    assert key == "dicom_data"


def test_image_data_is_accepted():
    """DicomImageInfo.image_data — 'Raw DICOM file bytes' per the .proto."""
    payload, key = _extract_instance_payload({"image_data": "QUJD", "instance_number": 1})
    assert payload == "QUJD"
    assert key == "image_data"


def test_camel_case_variants_are_accepted():
    for key_name in ("dicomData", "imageData", "fileData"):
        payload, key = _extract_instance_payload({key_name: "QUJD"})
        assert payload == "QUJD", key_name
        assert key == key_name


def test_documented_key_wins_over_variants():
    payload, key = _extract_instance_payload({"image_data": "WRONG", "dicom_data": "RIGHT"})
    assert payload == "RIGHT"
    assert key == "dicom_data"


def test_an_empty_variant_never_shadows_a_populated_one():
    """`dicom_data: ""` + `image_data: <bytes>` must still download the image."""
    payload, key = _extract_instance_payload({"dicom_data": "", "image_data": "QUJD"})
    assert payload == "QUJD"
    assert key == "image_data"


def test_bytes_payloads_are_accepted():
    payload, key = _extract_instance_payload({"dicom_data": b"QUJD"})
    assert payload == b"QUJD"


def test_a_genuinely_empty_instance_reports_nothing():
    """The server really sent no bytes — the caller then logs the entry shape."""
    payload, key = _extract_instance_payload({"instance_number": 1, "file_size": 0})
    assert payload == ""
    assert key == ""


def test_never_raises_on_garbage():
    for junk in (None, [], "text", 5, {"dicom_data": None}, {"dicom_data": 123}):
        assert _extract_instance_payload(junk) == ("", "")


def test_both_documented_proto_names_are_covered():
    assert "dicom_data" in _INSTANCE_PAYLOAD_KEYS
    assert "image_data" in _INSTANCE_PAYLOAD_KEYS


def test_download_loop_uses_the_tolerant_extractor_and_logs_the_shape():
    src = (REPO_ROOT / "modules" / "download_manager" / "network" / "socket_client.py").read_text(
        encoding="utf-8", errors="replace"
    )
    # The fatal single-key read must not come back.
    assert "instance_data.get('dicom_data', '')" not in src
    assert "_extract_instance_payload(instance_data)" in src
    # And the empty branch must dump the entry SHAPE, so the next field log
    # settles "wrong key" vs "server has no pixel data" definitively.
    assert "[EMPTY_INSTANCE_PAYLOAD]" in src
    assert "Entry shape" in src


def test_plugin_mirror_has_the_same_fix():
    mirror = (
        REPO_ROOT / "builder" / "plugin package" / "packages" / "download_manager"
        / "payload" / "python" / "modules" / "download_manager" / "network" / "socket_client.py"
    ).read_text(encoding="utf-8", errors="replace")
    assert "_extract_instance_payload" in mirror
    assert "instance_data.get('dicom_data', '')" not in mirror
