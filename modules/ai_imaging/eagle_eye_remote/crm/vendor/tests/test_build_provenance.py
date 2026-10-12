"""A build must be able to say how it was made.

Version identity answered "which build is this". This answers the question that
came next, and only because a deploy raised it: a 1.21.0 installer came out
5.8 MB smaller than 1.20.1 with no code change, because `build_server_exe.ps1`
was handed the project virtualenv instead of the system interpreter and the
virtualenv had no `cryptography`. PyInstaller bundles what the interpreter it is
given can import, so the contents of a release depended on whose
`site-packages` the builder pointed at — recorded nowhere, and visible only as a
file size someone happened to compare.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reception_crm import build_provenance

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_cache():
    build_provenance.build_info.cache_clear()
    yield
    build_provenance.build_info.cache_clear()


def test_running_from_source_says_so_rather_than_inventing_values(monkeypatch, tmp_path):
    """"Not built" and "built by something unknown" are different facts."""
    monkeypatch.setattr(build_provenance, "BUILD_INFO_PATH", tmp_path / "absent.json")

    info = build_provenance.build_info()

    assert info["available"] is False
    assert "not from a build" in info["reason"]
    assert "python" not in info


def test_an_unreadable_file_is_not_reported_as_an_absent_one(monkeypatch, tmp_path):
    """A missing file is normal in a checkout; a corrupt one is a broken artefact.

    Collapsing them would hide the second inside the first — the same shape as
    the lexicon defect this project already paid for.
    """
    broken = tmp_path / "build_info.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(build_provenance, "BUILD_INFO_PATH", broken)

    info = build_provenance.build_info()

    assert info["available"] is False
    assert "unreadable" in info["reason"]


def test_a_real_build_info_is_reported_with_what_was_bundled(monkeypatch, tmp_path):
    written = tmp_path / "build_info.json"
    written.write_text(json.dumps({
        "version": "1.22.0",
        "python": {"version": "3.13.5", "executable": r"C:\Python313\python.exe"},
        "optional_packages": {"cryptography": True, "requests": True, "PySide6": False},
    }), encoding="utf-8")
    monkeypatch.setattr(build_provenance, "BUILD_INFO_PATH", written)

    info = build_provenance.build_info()

    assert info["available"] is True
    assert info["version"] == "1.22.0"
    assert info["python"] == "3.13.5"
    assert info["interpreter"].endswith("python.exe")
    assert info["bundled_optional"] == ["cryptography", "requests"]
    assert info["absent_optional"] == ["PySide6"]


def test_health_reports_the_build():
    source = (ROOT / "reception_crm" / "adapters" / "http_api.py").read_text(encoding="utf-8")
    assert '"build": build_info(),' in source


def test_the_spec_bundles_the_provenance_file():
    spec = (ROOT / "scripts" / "ReceptionCrmServer.spec").read_text(encoding="utf-8")
    assert "build_info.json" in spec


def test_the_build_script_records_provenance_before_building():
    """Order matters: recorded BEFORE PyInstaller runs, compared against the last build.

    Written afterwards it would describe a machine rather than the build, and
    the comparison has to read the previous file before `dist` is cleared.
    """
    script = (ROOT / "scripts" / "build_server_exe.ps1").read_text(encoding="utf-8")
    record = script.index("write_build_info.py")
    clear = script.index("Remove-Item \"$ProjectRoot\\dist\\ReceptionCrmServer\"")
    build = script.index("-m PyInstaller")
    assert record < clear < build, "provenance must be recorded before dist is cleared"
    assert "--compare" in script, "and compared with the previous build"


def test_the_comparison_warns_when_an_optional_package_disappears():
    """The exact regression that produced the 5.8 MB delta."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "write_build_info", ROOT / "scripts" / "write_build_info.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["write_build_info"] = module
    spec.loader.exec_module(module)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        previous = Path(tmp) / "prev.json"
        previous.write_text(json.dumps({
            "python": {"executable": r"C:\Python313\python.exe"},
            "optional_packages": {"cryptography": True},
        }), encoding="utf-8")

        warnings = module.compare({
            "python": {"executable": r"D:\project\.venv\Scripts\python.exe"},
            "optional_packages": {"cryptography": False},
        }, previous)

    joined = "\n".join(warnings)
    assert "interpreter changed" in joined
    assert "cryptography" in joined
