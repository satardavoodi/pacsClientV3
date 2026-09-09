"""Synthetic DICOM identity and report page furniture; no clinical database access."""
import pytest
from modules.ai_imaging.eagle_eye_brain.patient_context import age_at_examination, demographics_for_report, require_same_examination
from modules.ai_imaging.eagle_eye_brain.normative import BrainDemographics, reference_assessment
from modules.ai_imaging.eagle_eye_brain.contracts import BrainError


def test_table_alignment_centers_headers_and_numbers_but_not_text():
    from html.parser import HTMLParser
    from modules.ai_imaging.eagle_eye_brain.organized_report import _table
    class Cells(HTMLParser):
        def __init__(self):
            super().__init__(); self.cells = []
        def handle_starttag(self, tag, attrs):
            if tag in ('th', 'td'):
                self.cells.append((tag, dict(attrs).get('align')))
    parser = Cells()
    parser.feed(_table(['Region','Measured','Range','Z','Percentile','Flag'],
                       [['Brainstem','21.000','17.983 - 24.068','-0.01','<0.01','Within reference range'],
                        ['Third ventricle','Not available','Not available','0.00','50.00','Review required']],
                       [20,15,20,10,15,20]))
    assert parser.cells[:6] == [('th','center')]*6
    assert parser.cells[6:12] == [('td','left'), *[('td','center')]*4, ('td','left')]
    assert parser.cells[12:15] == [('td','left')]*3


def test_qt_renderer_honors_cell_paragraph_alignment():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextDocument, QTextTable
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.organized_report import _table
    app = QApplication.instance() or QApplication([])
    doc = QTextDocument()
    doc.setHtml(_table(['Region', 'Measured', 'Range', 'Flag'],
                       [['Brainstem', '21.000', '17.983 - 24.068', 'Within reference range']],
                       [25, 20, 30, 25]))
    table = next(frame for frame in doc.rootFrame().childFrames() if isinstance(frame, QTextTable))
    for column in range(4):
        assert table.cellAt(0, column).firstCursorPosition().blockFormat().alignment() == Qt.AlignHCenter
    for column in (1, 2):
        assert table.cellAt(1, column).firstCursorPosition().blockFormat().alignment() == Qt.AlignHCenter
    for column in (0, 3):
        assert table.cellAt(1, column).firstCursorPosition().blockFormat().alignment() & Qt.AlignLeft


def test_age_uses_examination_date_and_dicoms_take_precedence():
    age, source = age_at_examination("19800101", "20200101")
    assert age == pytest.approx(40, abs=.01) and "study date" in source
    context = {"age_years": age, "sex": "F"}
    assert demographics_for_report(context, BrainDemographics(65, "male")).sex == "female"
    assert demographics_for_report({"sex": "O"}, BrainDemographics(40, "male")).sex == "unknown"
    assert age_at_examination("", "", "018M")[0] == 1.5
    assert age_at_examination("20210101", "20200101")[0] is None
    with pytest.raises(BrainError):
        require_same_examination({"study_uid": "1"}, {"study_uid": "2"})


@pytest.mark.parametrize("mixed", [False, True])
def test_dicom_identity_is_read_and_mixed_identity_rejected(tmp_path, monkeypatch, mixed):
    import pydicom
    from pydicom.dataset import Dataset
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain.patient_context import dicom_context
    paths = []
    for i in range(2):
        ds = Dataset(); ds.PatientName = "SYNTHETIC^TEST"; ds.PatientID = f"SYNTHETIC-{i if mixed else 0}"
        ds.StudyInstanceUID = "1.2.3"; ds.SeriesInstanceUID = "1.2.3.4"
        ds.PatientBirthDate = "19800101"; ds.StudyDate = "20200101"; ds.PatientSex = "F"
        ds.Manufacturer = "SIEMENS"; ds.MagneticFieldStrength = 3
        path = tmp_path / str(i)
        ds.is_implicit_VR = True; ds.is_little_endian = True
        pydicom.dcmwrite(path, ds)
        paths.append(str(path))
    monkeypatch.setattr(sitk.ImageSeriesReader, "GetGDCMSeriesIDs", lambda source: ["1.2.3.4"])
    monkeypatch.setattr(sitk.ImageSeriesReader, "GetGDCMSeriesFileNames", lambda source, uid: paths)
    read = pydicom.dcmread
    monkeypatch.setattr(pydicom, "dcmread", lambda path, **kwargs: read(path, force=True, **kwargs))
    if mixed:
        with pytest.raises(BrainError, match="differ"):
            dicom_context(tmp_path)
    else:
        context = dicom_context(tmp_path)
        assert context["identity_status"] == "DICOM series verified"
        assert context["age_years"] == pytest.approx(40, abs=.01)
        assert context["sex"] == "F"
        assert context["manufacturer"] == "SIEMENS"
        assert float(context["field_strength_t"]) == 3


def test_organized_report_repeats_header_footer_and_keeps_patient_fields(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtPdf import QPdfDocument
    from modules.ai_imaging.eagle_eye_brain.report import report_html, write_pdf
    app = QApplication.instance() or QApplication([])
    rows = [{"structure": name, "volume_cm3": value, "volume_mm3": value * 1000} for name, value in
            [("total intracranial", 1500), ("left hippocampus", 3), ("right hippocampus", 4)]]
    from modules.ai_imaging.eagle_eye_brain.anatomical_groups import CORTICAL_GROUPS, DEEP_GROUPS, TISSUE_GROUPS
    for _, names in (*CORTICAL_GROUPS, *DEEP_GROUPS, *TISSUE_GROUPS):
        for name in names:
            if name == "hippocampus":
                continue
            prefix = "ctx-{}-" if any(name in members for _, members in CORTICAL_GROUPS) else "{} "
            for side in (("lh", "rh") if prefix.startswith("ctx") else ("left", "right")):
                rows.append({"structure": prefix.format(side) + name, "volume_cm3": 123.456, "volume_mm3": 123456})
    rows.extend({"structure": side + " future atlas region", "volume_cm3": 1, "volume_mm3": 1000} for side in ("left", "right"))
    result = {"model": "SynthSeg 2.0", "posterior_rows": rows, "binary_rows": [],
              "qc_scores": {}, "model_revision": "synthetic", "flair_status": "Not supplied",
              "patient_context": {"patient_name": "SYNTHETIC^EXAMPLE", "patient_id": "TEST-ONLY", "institution": "SYNTHETIC FACILITY"},
              "normative": reference_assessment(BrainDemographics(17.7, "female"), "volbrain")}
    pdf = tmp_path / "report.pdf"
    write_pdf(report_html(result), pdf)
    document = QPdfDocument(); assert document.load(str(pdf)) == QPdfDocument.Error.None_
    assert document.pageCount() >= 5
    for n in range(document.pageCount()):
        text = document.getAllText(n).text()
        assert "AI-PACS" in text and "TEST-ONLY" in text
        assert f"Page {n + 1} of {document.pageCount()}" in text
        assert "not signed for patient release" in text
    cover = document.getAllText(0).text()
    assert "SYNTHETIC FACILITY" in cover and "1500.000" in cover
    full_text = "\n".join(document.getAllText(n).text() for n in range(document.pageCount()))
    for heading in ("Basal ganglia", "Diencephalon", "Brainstem", "Cerebellum", "Frontal lobe", "Parietal lobe", "Temporal lobe", "Occipital lobe", "Cingulate cortex", "Insular cortex", "Other measured structures"):
        assert heading in full_text
    assert "future atlas region" in full_text
    assert 'Published95%' in ''.join(full_text.split())
    assert '95%' in document.getAllText(0).text()
    page_texts = [document.getAllText(n).text() for n in range(document.pageCount())]
    section_names = ('Cerebral white matter', 'Lobar and regional cortical summary',
                     'Cortical regions: Frontal lobe', 'CSF spaces and ventricles',
                     'Basal ganglia', 'Other deep gray matter', 'Brainstem', 'Cerebellum')
    # Each compartment owns a page, rather than appearing in one mixed tissue table.
    from modules.ai_imaging.eagle_eye_brain.organized_report import PAGE
    html_pages = report_html(result).split(PAGE)
    positions = []
    for heading in section_names:
        matches = [i for i, page in enumerate(html_pages) if '<h1>' + heading + '</h1>' in page]
        assert len(matches) == 1, heading
        positions.append(matches[0])
    assert positions == sorted(set(positions))
    wm = html_pages[positions[0]]
    assert 'Right cm3' in wm and 'Left cm3' in wm
    assert 'cerebral cortex' not in wm and 'ventricle' not in wm
    csf = html_pages[positions[3]]
    for label in ('lateral ventricle', 'inferior lateral ventricle', '3rd ventricle', '4th ventricle'):
        assert label in csf
    assert 'cerebellum cortex' not in csf
    summary = next(text for text in page_texts if 'Lobar and regional cortical summary' in text)
    assert 'Lobar and regional cortical summary' in summary
    assert 'Nomatchedage/sexreference' in ''.join(summary.split())
    for index in positions:
        if section_names[positions.index(index)] != 'Lobar and regional cortical summary':
            assert '95%' in page_texts[index]
    document.close()


def test_anatomical_groups_are_disjoint_and_preserve_native_measurements():
    from modules.ai_imaging.eagle_eye_brain.anatomical_groups import CORTICAL_GROUPS, DEEP_GROUPS, TISSUE_GROUPS, group_pairs
    cortical = [name for _, names in CORTICAL_GROUPS for name in names]
    assert len(cortical) == len(set(cortical)) == 34
    definitions = (*CORTICAL_GROUPS, *DEEP_GROUPS, *TISSUE_GROUPS)
    names = [name for _, members in definitions for name in members]
    assert len(names) == len(set(names)) == 48
    assert dict(DEEP_GROUPS)["Basal ganglia"] == ("caudate", "putamen", "pallidum", "accumbens area")
    rows = [{"structure": name, "left_cm3": index + .25, "right_cm3": index + .5} for index, name in enumerate(names)]
    grouped = [row for _, members in group_pairs(rows, definitions) for row in members]
    assert len(grouped) == len(rows)
    assert all(original is grouped_row for original, grouped_row in zip(rows, grouped))
