"""The build must be able to say what it is.

Three files declared a version and none of them agreed: `0.1.0` in
`reception_crm/__init__.py` and `pyproject.toml`, `1.20.1` in the server
installer. `/api/health` published no version field at all, so the running
server could not be asked. Every "server 1.20.1 is deployed" in this project's
notes rested on the filename of the installer someone had copied over — which
is a fact about a file, not about the process answering requests.

That is the same shape as defects this project has already paid for: a control
that cannot be observed is not a control. It matters most where it shows least
— a benchmark scores a build and a defect is closed against a build, and both
records name a version that nothing checked.

These tests do not care WHICH version it is. They care that there is exactly
one answer and that the server will tell you.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import reception_crm

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SERVER_ISS = ROOT / "installer" / "ReceptionCrmServer.iss"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def pyproject_version() -> str:
    for line in PYPROJECT.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("version"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise AssertionError("pyproject.toml declares no version")


def installer_version() -> str:
    text = SERVER_ISS.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'#define\s+AppVersion\s+"([^"]+)"', text)
    assert match, "ReceptionCrmServer.iss declares no AppVersion"
    return match.group(1)


def test_the_version_is_a_version():
    assert SEMVER.match(reception_crm.__version__), reception_crm.__version__


def test_package_and_pyproject_agree():
    assert reception_crm.__version__ == pyproject_version()


def test_package_and_server_installer_agree():
    """Bumping the shipped installer must bump what the server reports.

    The desktop Agent installer is a separate product line with its own
    version and is deliberately not tied to this one — coupling them would
    force a meaningless bump of one product every time the other shipped.
    """
    assert reception_crm.__version__ == installer_version()


def test_health_reports_the_version():
    """Read out of the source rather than by standing up a server.

    The health payload is built inline in `do_GET`, so there is no function to
    call; what this pins is that the key is present and is fed from the single
    source of truth, not from a literal that would drift again.
    """
    source = (ROOT / "reception_crm" / "adapters" / "http_api.py").read_text(encoding="utf-8")
    assert '"version": __version__' in source, (
        "/api/health must report the package version, and must take it from "
        "__version__ rather than repeating a literal"
    )


@pytest.mark.parametrize("path", [PYPROJECT, SERVER_ISS])
def test_the_files_this_guards_still_exist(path: Path):
    """A rename must fail here rather than silently stop checking anything."""
    assert path.is_file(), path
