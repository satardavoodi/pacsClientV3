from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INSTALLER_DIR = ROOT / "builder" / "installer"


def test_installer_places_eula_and_third_party_notice_in_legal_folder():
    source = (INSTALLER_DIR / "AIPacs_Setup.iss").read_text(encoding="utf-8")
    assert 'Source: "EULA.txt"; DestDir: "{app}\\Legal"' in source
    assert 'Source: "THIRD_PARTY_NOTICES.txt"; DestDir: "{app}\\Legal"' in source


def test_notice_identifies_release_and_excludes_gpl_libjpeg_from_dependencies():
    source = (INSTALLER_DIR / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
    assert "Release: 3.6.5" in source
    assert "python-gdcm 3.2.6" in source
    assert "pyjpegls 1.5.1" in source
    assert "GPL-3.0 pylibjpeg-libjpeg distribution is intentionally not part" in source


def test_installer_eula_distinguishes_document_revision_from_product_version():
    source = (INSTALLER_DIR / "EULA.txt").read_text(encoding="utf-8")
    assert "Document revision 3.0.2 (applies to AI-PACS release 3.6.5)" in source
