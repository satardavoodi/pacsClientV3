# -*- coding: utf-8 -*-
"""Guard: the 3D Cursor must identify which view each viewer shows.

Live defect (2026-07-14, patient 50016 R-CC / R-MLO): the instruction dialog said
"Please click the Nipple point in viewer **View**" and the guided flow fell back to
the legacy dialogs — because the pickers read ONLY
`image_viewer.metadata['series']['laterality' / 'view_position']`, which is EMPTY on
real mammograms (the view lives in the DICOM header). `imaging_tab.
_extract_view_data_from_widget` (which feeds the correlator) already had the DICOM
fallback, which is why the correlation worked while the UI could not name the view.

`view_identity.resolve_view_identity` is now the single resolver:
    metadata → DICOM header (ImageLaterality/Laterality + ViewPosition) → free text.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.ai_imaging.ai_module_ui.cursor_3d.view_identity import (  # noqa: E402
    parse_view_from_text,
    resolve_view_identity,
    view_label,
)
from modules.ai_imaging.ai_module_ui.cursor_3d.guided_workflow import (  # noqa: E402
    ViewSlot,
    plan_cursor3d_steps,
)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class _FakeViewer:
    def __init__(self, metadata):
        self.metadata = metadata


class _FakeWidget:
    def __init__(self, metadata=None):
        self.image_viewer = _FakeViewer(metadata or {})


def _write_mg_dicom(path: Path, laterality="R", view="MLO", description=""):
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    ds = Dataset()
    ds.Modality = "MG"
    ds.Rows = 2048
    ds.Columns = 1024
    if laterality:
        ds.ImageLaterality = laterality
    if view:
        ds.ViewPosition = view
    if description:
        ds.SeriesDescription = description
    fm = FileMetaDataset()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.2"
    fm.MediaStorageSOPInstanceUID = "1.2.3.4"
    ds.file_meta = fm
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    try:
        ds.save_as(str(path), enforce_file_format=False)
    except TypeError:
        ds.save_as(str(path), write_like_original=True)


# ---------------------------------------------------------------------------
# 1. Pure text parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("R-CC", ("R", "CC")),
    ("R CC", ("R", "CC")),
    ("RCC", ("R", "CC")),
    ("L_MLO", ("L", "MLO")),
    ("LMLO", ("L", "MLO")),
    ("Right CC", ("R", "CC")),
    ("Left MLO", ("L", "MLO")),
    ("R XCCL", ("R", "XCCL")),          # longest view wins over a bare CC match
    ("Breast", ("", "")),
    ("", ("", "")),
])
def test_parse_view_from_text(text, expected):
    assert parse_view_from_text(text) == expected


# ---------------------------------------------------------------------------
# 2. Resolution ladder
# ---------------------------------------------------------------------------

def test_metadata_is_used_when_present():
    w = _FakeWidget({"series": {"laterality": "L", "view_position": "MLO"}})
    assert resolve_view_identity(w) == ("L", "MLO")
    assert view_label(w) == "L-MLO"


def test_dicom_header_fallback_when_metadata_empty(tmp_path):
    """THE LIVE CASE: empty series metadata, view only in the DICOM header."""
    dcm = tmp_path / "IM0.dcm"
    _write_mg_dicom(dcm, laterality="R", view="MLO")

    w = _FakeWidget({
        "series": {"laterality": "", "view_position": ""},
        "instances": [{"instance_path": str(dcm)}],
    })
    assert resolve_view_identity(w) == ("R", "MLO")
    assert view_label(w) == "R-MLO"          # never the bare "View" fallback again


def test_series_description_fallback(tmp_path):
    dcm = tmp_path / "IM0.dcm"
    _write_mg_dicom(dcm, laterality="", view="", description="R CC MAMMO")

    w = _FakeWidget({"series": {}, "instances": [{"instance_path": str(dcm)}]})
    assert resolve_view_identity(w) == ("R", "CC")


def test_unknown_view_returns_empty_and_never_guesses():
    w = _FakeWidget({"series": {}})           # nothing at all
    assert resolve_view_identity(w) == ("", "")
    assert view_label(w) == "View"


def test_result_is_cached_on_the_widget(tmp_path):
    dcm = tmp_path / "IM0.dcm"
    _write_mg_dicom(dcm, laterality="L", view="CC")
    w = _FakeWidget({"series": {}, "instances": [{"instance_path": str(dcm)}]})

    assert resolve_view_identity(w) == ("L", "CC")
    dcm.unlink()                              # a click must never pay a re-read
    assert resolve_view_identity(w) == ("L", "CC")


# ---------------------------------------------------------------------------
# 3. End to end: the live study now plans the guided flow
# ---------------------------------------------------------------------------

def test_guided_flow_now_plans_for_the_live_case(tmp_path):
    """50016: R-CC in viewer 0, R-MLO in viewer 1, view only in the DICOM header."""
    cc = tmp_path / "cc.dcm"
    mlo = tmp_path / "mlo.dcm"
    _write_mg_dicom(cc, laterality="R", view="CC")
    _write_mg_dicom(mlo, laterality="R", view="MLO")

    widgets = [
        _FakeWidget({"series": {}, "instances": [{"instance_path": str(cc)}]}),
        _FakeWidget({"series": {}, "instances": [{"instance_path": str(mlo)}]}),
    ]
    slots = []
    for i, w in enumerate(widgets):
        lat, vp = resolve_view_identity(w)
        slots.append(ViewSlot(viewer_index=i, laterality=lat, view_position=vp))

    steps = plan_cursor3d_steps(slots)
    assert steps is not None, "the guided flow must no longer fall back on this study"
    assert [s.key for s in steps] == ["nipple_mlo", "nipple_cc", "pectoral_mlo"]
    by_key = {s.key: s for s in steps}
    assert by_key["nipple_mlo"].viewer_index == 1      # MLO is the right-hand viewer
    assert by_key["nipple_cc"].viewer_index == 0
    assert by_key["nipple_cc"].view_label == "R-CC"
    assert by_key["pectoral_mlo"].view_label == "R-MLO"
