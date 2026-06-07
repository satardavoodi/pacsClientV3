"""Imaging-center identity: persistence, media manifest, viewer banner."""

import json

import pytest
from pydicom.uid import generate_uid

from modules.cd_burner import center_identity
from modules.cd_burner.cd_burn_manager import BurnOptions, CDBurnWorker

from .conftest import write_ct_slice


@pytest.fixture()
def config_root(tmp_path, monkeypatch):
    import aipacs_runtime

    monkeypatch.setattr(aipacs_runtime, "roaming_config_root", lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Persistence (enter once, reload forever)
# ---------------------------------------------------------------------------

def test_identity_round_trip_and_key_preservation(config_root):
    # Pre-existing settings must survive (same file as the viewer config)
    config_file = config_root / "lightviewer_settings.json"
    config_file.write_text(
        json.dumps({"viewer_mode": "default", "disc_label": "X"}), encoding="utf-8"
    )

    assert center_identity.save_center_identity(
        "Alizadeh Imaging Center", "Tehran, Valiasr St. 12", "+98 21 1234567"
    )

    loaded = center_identity.load_center_identity()
    assert loaded["center_name"] == "Alizadeh Imaging Center"
    assert loaded["center_address"] == "Tehran, Valiasr St. 12"
    assert loaded["center_phone"] == "+98 21 1234567"

    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["viewer_mode"] == "default"  # untouched
    assert saved["disc_label"] == "X"


def test_identity_defaults_empty_when_unconfigured(config_root):
    loaded = center_identity.load_center_identity()
    assert loaded == {"center_name": "", "center_address": "", "center_phone": ""}


# ---------------------------------------------------------------------------
# BurnOptions → media manifest + START_HERE
# ---------------------------------------------------------------------------

def test_center_identity_helper_on_options():
    empty = BurnOptions()
    assert empty.center_identity() is None

    options = BurnOptions(center_name="C", center_phone=" 123 ")
    identity = options.center_identity()
    assert identity == {"name": "C", "address": "", "phone": "123"}


def test_support_files_carry_center_identity(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    worker = CDBurnWorker(
        studies=[],
        burn_to_disc=False,
        options=BurnOptions(
            center_name="Alizadeh Imaging Center",
            center_address="Tehran",
            center_phone="+98 21 1234567",
        ),
    )
    worker._write_portable_support_files(
        str(staging), fileset_label="PATIENT_CD", volume_label="PATIENT CD"
    )

    manifest = json.loads((staging / "AIPACS_MEDIA_INFO.json").read_text(encoding="utf-8"))
    assert manifest["center"] == {
        "name": "Alizadeh Imaging Center",
        "address": "Tehran",
        "phone": "+98 21 1234567",
    }

    readme = (staging / "START_HERE.txt").read_text(encoding="utf-8")
    assert "Created by: Alizadeh Imaging Center" in readme
    assert "Phone: +98 21 1234567" in readme


def test_support_files_without_identity_omit_center(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    worker = CDBurnWorker(studies=[], burn_to_disc=False)
    worker._write_portable_support_files(
        str(staging), fileset_label="PATIENT_CD", volume_label="PATIENT CD"
    )
    manifest = json.loads((staging / "AIPACS_MEDIA_INFO.json").read_text(encoding="utf-8"))
    assert "center" not in manifest
    assert "Created by:" not in (staging / "START_HERE.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Portable viewer: manifest reader + header banner
# ---------------------------------------------------------------------------

def test_load_media_info_reads_center(tmp_path):
    from modules.cd_burner.portable_viewer.media_scan import load_media_info

    (tmp_path / "AIPACS_MEDIA_INFO.json").write_text(
        json.dumps({"center": {"name": "C1", "address": "A1", "phone": "P1"}}),
        encoding="utf-8",
    )
    info = load_media_info(str(tmp_path))
    assert info["center"]["name"] == "C1"

    assert load_media_info(str(tmp_path / "missing")) == {}
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "AIPACS_MEDIA_INFO.json").write_text("{not json", encoding="utf-8")
    assert load_media_info(str(tmp_path / "broken")) == {}


def test_viewer_shows_center_banner(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    study_uid, series_uid = generate_uid(), generate_uid()
    write_ct_slice(tmp_path, series_uid, study_uid, 1)
    (tmp_path / "AIPACS_MEDIA_INFO.json").write_text(
        json.dumps({
            "center": {
                "name": "Alizadeh Imaging Center",
                "address": "Tehran",
                "phone": "+98 21 1234567",
            }
        }),
        encoding="utf-8",
    )

    # show_welcome=False: the banner lives on the viewer page of the stack
    # (welcome-page identity display is covered by test_welcome_page.py).
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        assert not window.center_header.isVisibleTo(window)  # hidden by default

        window._apply_media_info(str(tmp_path))
        assert window.center_header.isVisibleTo(window)
        text = window.center_header.text()
        assert "Alizadeh Imaging Center" in text
        assert "Tehran" in text
        assert "+98 21 1234567" in text
        assert "Alizadeh Imaging Center" in window.windowTitle()

        # Media without identity → banner hides again
        window._apply_media_info(str(tmp_path / "nowhere"))
        assert not window.center_header.isVisibleTo(window)
    finally:
        window._pool.waitForDone(3000)
        window.close()
