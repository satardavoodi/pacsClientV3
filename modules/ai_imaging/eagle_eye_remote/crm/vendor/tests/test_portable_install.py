"""What has to be true before this installer runs on somebody else's server.

Everything here started as a fact about the Razi machine that had quietly become
a fact about the product: a drive letter, a clinic's name, one site's folder
layout, one person's user account. Each of them works perfectly until the day
the installer is run on a second computer.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


from reception_crm import runtime
from reception_crm.local import integrity
from reception_crm.server import config as server_config

REPO = Path(__file__).resolve().parents[1]
ISS = REPO / "installer" / "ReceptionCrmServer.iss"
ROLES_TEMPLATE = REPO / "config" / "roles.example.json"


# --------------------------------------------------------------------------- #
# 1. No drive letter this machine happens to have
# --------------------------------------------------------------------------- #
def test_the_fallback_data_root_is_on_a_drive_that_always_exists():
    """It used to be `D:\\RAZI crm`. On a reception server without a D: drive
    the service could not create its data folder and would not start."""
    fallback = str(runtime.DEFAULT_DATA_ROOT)
    assert "RAZI" not in fallback.upper(), "one clinic's name in every clinic's default path"
    program_data = os.getenv("ProgramData") or r"C:\ProgramData"
    assert fallback.lower().startswith(program_data.lower())


def test_the_fallback_is_a_fallback_and_the_config_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("RECEPTION_CRM_DATA_ROOT", str(tmp_path / "elsewhere"))
    assert runtime.data_root() == tmp_path / "elsewhere"


# --------------------------------------------------------------------------- #
# 2. No other clinic's name or account shipped as a default
# --------------------------------------------------------------------------- #
def test_the_installer_offers_no_default_centre_name():
    """A pre-filled centre is one clinic's identity handed to the next, and a
    centre that does not match roles.json rejects every login."""
    text = ISS.read_text(encoding="utf-8", errors="replace")
    assert not re.search(r"ConfigPage\.Values\[1\]\s*:=\s*'RAZI'", text)
    assert re.search(r"ConfigPage\.Values\[1\]\s*:=\s*''", text)


def test_the_installer_computes_the_data_folder_instead_of_hardcoding_it():
    text = ISS.read_text(encoding="utf-8", errors="replace")
    assert "DefaultDataFolder" in text
    assert not re.search(r"ConfigPage\.Values\[2\]\s*:=\s*'D:\\RAZI crm'", text)


def test_the_installer_rewrites_the_roles_template_rather_than_copying_it():
    """The template names a centre and an owner. Copied verbatim onto another
    server it authorises a stranger and rejects everyone real."""
    text = ISS.read_text(encoding="utf-8", errors="replace")
    seeding = text.split("RolesFile := ConfigDir", 1)[1]
    assert "StringChangeEx(Lines[I], '\"RAZI\"'" in seeding
    assert "StringChangeEx(Lines[I], '\"vahid\"'" in seeding


def test_a_silent_install_seeds_no_roles_file_at_all():
    """No wizard means no answers. Substituting '' names a centre of ""; copying
    the template verbatim authorises a user from THIS clinic as owner on the
    next one, while refusing everybody real there. So it must write nothing and
    let `describe` report the absence."""
    text = ISS.read_text(encoding="utf-8", errors="replace")
    seeding = text.split("RolesFile := ConfigDir", 1)[1]
    guard = seeding.split("if (Center = '') or (Owner = '') then", 1)
    assert len(guard) == 2, "the silent-install guard is gone"
    body = guard[1].split("end;", 1)[0]
    assert "Exit" in body
    assert "SaveStringsToFile" not in body, "silent install still writes a roles.json"


def test_the_roles_template_still_carries_the_markers_the_installer_replaces():
    """If the template is reworded, the substitution silently stops working and
    a fresh install goes back to authorising 'vahid' at centre 'RAZI'."""
    template = ROLES_TEMPLATE.read_text(encoding="utf-8")
    assert '"RAZI"' in template
    assert '"vahid"' in template
    assert '"display_name": "Vahid"' in template


# --------------------------------------------------------------------------- #
# 3. No single site's folder layout compiled in
# --------------------------------------------------------------------------- #
def test_the_storage_roots_come_from_configuration(monkeypatch):
    monkeypatch.setenv(
        integrity.ENV_FILE_ROOTS, os.pathsep.join([r"E:\somewhere", r"F:\else"])
    )
    assert integrity.file_roots() == (r"E:\somewhere", r"F:\else")


def test_unconfigured_storage_roots_fall_back_to_the_vendors_usual_layout(monkeypatch):
    monkeypatch.delenv(integrity.ENV_FILE_ROOTS, raising=False)
    assert integrity.file_roots() == integrity.DEFAULT_FILE_ROOTS


def test_an_empty_setting_does_not_disable_the_check(monkeypatch):
    """An empty allow-list would check nothing and report zero broken links,
    which reads as good news rather than as a misconfiguration."""
    monkeypatch.setenv(integrity.ENV_FILE_ROOTS, "")
    assert integrity.file_roots() == integrity.DEFAULT_FILE_ROOTS
    assert server_config._file_roots([]) == server_config.DEFAULT_FILE_ROOTS
    assert server_config._file_roots(None) == server_config.DEFAULT_FILE_ROOTS


def test_the_configured_roots_are_resolved_per_call_not_at_import(monkeypatch):
    """`apply_to_environment()` runs at service start, AFTER this module is
    imported. A constant captured at import time would always be the default."""
    monkeypatch.setenv(integrity.ENV_FILE_ROOTS, r"E:\first")
    assert integrity.file_roots() == (r"E:\first",)
    monkeypatch.setenv(integrity.ENV_FILE_ROOTS, r"E:\second")
    assert integrity.file_roots() == (r"E:\second",)


def test_the_answer_names_the_roots_it_used(monkeypatch):
    """At a site whose images live elsewhere every path falls outside the list,
    the check examines nothing, and '0 broken links' looks like good news."""
    monkeypatch.setenv(integrity.ENV_FILE_ROOTS, r"E:\somewhere")

    class _Col:
        def find(self, *a, **k):
            return _Cursor()

        def count_documents(self, *a, **k):
            return 0

    class _Cursor:
        def sort(self, *a, **k):
            return self

        def limit(self, n):
            return self

        def __iter__(self):
            return iter(())

    monkeypatch.setattr(integrity, "reception_db", lambda: {"document_attachments": _Col()})
    result = integrity.broken_file_links()
    assert result["knownRoots"] == [r"E:\somewhere"]
    assert "knownRoots" in result["note"]


def test_the_config_publishes_the_roots_for_the_checker_to_read(monkeypatch, tmp_path):
    """The two halves have to agree: server/config.py writes the variable and
    local/integrity.py reads it. A rename on one side is a silent no-op."""
    monkeypatch.setattr(
        "reception_crm.local_host.resolve_reception_host", lambda port, **kw: "10.0.0.1"
    )
    cfg = server_config.ServerConfig(
        center="X",
        data_root=tmp_path,
        reception=server_config.ReceptionConfig(
            username="u", password="p", file_roots=(r"E:\a", r"E:\b")
        ),
    )
    server_config.apply_to_environment(cfg)
    assert integrity.file_roots() == (r"E:\a", r"E:\b")


# --------------------------------------------------------------------------- #
# 4. The shipped package has no path only this machine has
# --------------------------------------------------------------------------- #
def test_no_shipped_module_hardcodes_this_clinics_data_folder():
    """`D:\\RAZI crm` may survive as a legacy *fallback* in the config search
    path, but nothing may still treat it as where data goes."""
    offenders = []
    for path in (REPO / "reception_crm").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "RAZI crm" not in line:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # a comment explaining the history is fine
            if re.search(r"``[^`]*RAZI crm[^`]*``", line):
                continue  # prose in a docstring, quoted as markup, not a live path
            if "config" in line and "Path(" in line:
                continue  # legacy config search location, harmless and documented
            offenders.append(f"{path.name}:{number}: {stripped}")
    assert not offenders, "still writing to this one clinic's folder:\n" + "\n".join(offenders)
