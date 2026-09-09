"""Windows frozen-build guards for Qt/ICU DLL resolution."""

from builder import build_release


def test_main_bundle_removes_foreign_icu_without_deleting_webengine_data(tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    foreign_icu = engine / "icuuc.dll"
    foreign_data = engine / "icudt78.dll"
    webengine_data = engine / "icudtl.dat"
    foreign_icu.write_bytes(b"foreign-poppler-icu")
    foreign_data.write_bytes(b"foreign-poppler-data")
    webengine_data.write_bytes(b"qt-webengine-data")

    removed = build_release.remove_foreign_qt_icu_dlls(tmp_path)

    assert {path.name for path in removed} == {"icuuc.dll", "icudt78.dll"}
    assert not foreign_icu.exists()
    assert not foreign_data.exists()
    assert webengine_data.read_bytes() == b"qt-webengine-data"
