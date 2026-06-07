"""Guards for plain-key series study-path correction (45033 s8, 2026-06-07).

Live failure: patient 45033 is multi-study (MR study + DOC study). The tab's
import_folder_path pointed at the DOC study while the MR study was the
sidebar primary, so dropping MR series 8 made the disk loader scan the DOC
folder (path_scan candidates=1 probes=0 matches=0 mode=not_found) and the
load failed forever — including all progressive retries after the series'
download landed.

Fix: ``_resolve_plain_series_study_path`` adopts the series' own
``_server_series_info`` entry's series_path parent whenever the passed study
path does not actually contain the series folder (multi-study invariant:
the entry is the disk authority). These tests pin that contract.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def resolver():
    from PacsClient.pacs.patient_tab.ui.patient_ui._vc_load import _VCLoadMixin

    def make(server_series_info):
        host = SimpleNamespace(parent_widget=SimpleNamespace(
            _server_series_info=server_series_info
        ))
        return lambda key, path, entry=None: _VCLoadMixin._resolve_plain_series_study_path(
            host, key, path, entry
        )

    return make


def _mk_study(tmp_path, name, series_numbers):
    study = tmp_path / name
    for sn in series_numbers:
        (study / str(sn)).mkdir(parents=True)
        (study / str(sn) / "Instance_0001.dcm").write_bytes(b"x" * 16)
    return study


def test_corrects_to_entry_study_when_tab_path_lacks_series(resolver, tmp_path):
    """THE 45033 case: tab path = DOC study (no '8'), entry points at MR study."""
    doc = _mk_study(tmp_path, "doc_study", ["100000"])
    mr = _mk_study(tmp_path, "mr_study", ["5", "6", "8"])
    resolve = resolver({"8": {"series_path": str(mr / "8")}})

    out = resolve("8", str(doc))
    assert out == str(mr)


def test_noop_when_tab_path_contains_series(resolver, tmp_path):
    """Common case must stay zero-cost and unchanged."""
    mr = _mk_study(tmp_path, "mr_study", ["8"])
    resolve = resolver({"8": {"series_path": str(tmp_path / "other" / "8")}})
    assert resolve("8", str(mr)) is None


def test_corrects_even_when_series_not_downloaded_yet(resolver, tmp_path):
    """Series folder absent everywhere, but the entry names the right study:
    point at the correct study so post-download retries find the files."""
    doc = _mk_study(tmp_path, "doc_study", ["100000"])
    mr = _mk_study(tmp_path, "mr_study", ["5"])  # no '8' yet
    resolve = resolver({"8": {"series_path": str(mr / "8")}})
    assert resolve("8", str(doc)) == str(mr)


def test_fail_open_without_entry_or_path(resolver, tmp_path):
    doc = _mk_study(tmp_path, "doc_study", ["100000"])
    assert resolver({})("8", str(doc)) is None
    assert resolver({"8": {}})("8", str(doc)) is None
    assert resolver({"8": {"series_path": ""}})("8", str(doc)) is None


def test_fail_open_when_entry_parent_missing(resolver, tmp_path):
    doc = _mk_study(tmp_path, "doc_study", ["100000"])
    resolve = resolver({"8": {"series_path": str(tmp_path / "ghost_study" / "8")}})
    assert resolve("8", str(doc)) is None


def test_explicit_entry_argument_wins(resolver, tmp_path):
    doc = _mk_study(tmp_path, "doc_study", ["100000"])
    mr = _mk_study(tmp_path, "mr_study", ["8"])
    resolve = resolver({})  # registry empty — entry passed explicitly
    out = resolve("8", str(doc), {"series_path": str(mr / "8")})
    assert out == str(mr)


def test_loader_calls_resolver_for_unresolved_plain_keys():
    """Source guard: _load_single_series_on_demand must consult the resolver
    in its multi-study block."""
    src = (
        Path(__file__).resolve().parents[3]
        / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_load.py"
    ).read_text(encoding="utf-8", errors="ignore")
    assert "_resolve_plain_series_study_path(" in src
    assert src.index("def _resolve_plain_series_study_path") < src.index(
        "def _load_single_series_on_demand"
    )
