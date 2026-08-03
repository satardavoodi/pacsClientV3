"""Guard: the Normal Template tab's picker, badge and Clear semantics.

Real offscreen Qt. These are the behaviours a source-pin could not prove:

* the library is loaded at construction, so templates survive a restart — the
  old widget re-read a JSON file on every launch and remembered nothing;
* the picker carries template IDs, not just display names, so two templates
  with the same name cannot be confused;
* choosing a template puts EXACTLY the text that will be sent to the model into
  the editor (what you see is what is sent);
* **Clear means "use no template", NOT "delete my library"** — with a saved
  library the old wipe would have destroyed the physician's work;
* the bar says WHICH template is in use. The old label only ever said how many
  were loaded, so a session restored from disk showed "Upload JSON first…"
  while a template was actually in effect.
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.EchoMind import normal_templates as nt  # noqa: E402

_FILE = json.dumps([
    {"Name": "12 - MRI Knee Right",
     "Html": "<p>Both menisci demonstrate normal morphology and signal intensity.</p>"},
    {"Name": "CT Abdomen", "Html": "<p>Liver: normal.</p>"},
    {"Name": "Thyroid US", "Html": "<p>Normal thyroid.</p>"},
])


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def saved_library(tmp_path, monkeypatch):
    path = tmp_path / "library.json"
    monkeypatch.setattr(nt, "library_path", lambda: str(path))
    records, problems = nt.parse_templates(_FILE, source_file="mine.json")
    assert not problems
    assert nt.save_library(records)
    return records


@pytest.fixture
def composer(qapp, saved_library):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import UnifiedComposer

    c = UnifiedComposer()
    c.switch_tab("normal_template")
    yield c
    c.deleteLater()


def _ids(combo):
    return [combo.itemData(i) for i in range(combo.count())]


# ─────────────────────────────────────────────────────────────────────────────

def test_the_saved_library_is_loaded_at_construction(composer, saved_library):
    """The daily re-upload is gone."""
    assert len(composer._nt_records) == len(saved_library)
    assert composer.cmb_nt_names.isEnabled()
    assert composer.cmb_nt_names.count() == len(saved_library) + 1  # + "— no template —"


def test_the_picker_carries_ids_not_just_names(composer, saved_library):
    ids = _ids(composer.cmb_nt_names)
    assert ids[0] == "", "the first entry is the deliberate 'no template' choice"
    assert set(ids[1:]) == {r["id"] for r in saved_library}


def test_the_picker_is_type_to_search(composer):
    """A physician with 60 templates cannot scroll a flat combo."""
    from PySide6.QtCore import Qt

    assert composer.cmb_nt_names.isEditable()
    comp = composer.cmb_nt_names.completer()
    assert comp is not None
    assert comp.filterMode() == Qt.MatchContains
    assert comp.caseSensitivity() == Qt.CaseInsensitive


def test_the_picker_labels_show_number_modality_and_region(composer, saved_library):
    labels = [composer.cmb_nt_names.itemText(i) for i in range(composer.cmb_nt_names.count())]
    assert any(l.startswith("#12 ·") and "MRI" in l and "Knee" in l for l in labels)


def test_choosing_a_template_puts_the_sent_text_in_the_editor(composer, saved_library):
    knee = next(r for r in saved_library if r["name"].endswith("Knee Right"))
    idx = composer.cmb_nt_names.findData(knee["id"])
    composer.cmb_nt_names.setCurrentIndex(idx)

    expected = nt.template_body_text(knee)
    assert composer.box.toPlainText().strip() == expected.strip()
    assert composer.get_normal_template_plain_text().strip() == expected.strip()
    assert "<p>" not in composer.get_normal_template_plain_text(), "HTML must not reach the model"


def test_the_badge_names_the_active_template(composer, saved_library):
    knee = next(r for r in saved_library if r["name"].endswith("Knee Right"))
    composer.cmb_nt_names.setCurrentIndex(composer.cmb_nt_names.findData(knee["id"]))
    assert "in use" in composer.lbl_nt_info.text()
    assert "Knee Right" in composer.lbl_nt_info.text()


def test_the_badge_reports_the_library_size_when_nothing_is_chosen(composer, saved_library):
    assert "3 saved" in composer.lbl_nt_info.text()
    assert "in use" not in composer.lbl_nt_info.text()


def test_clear_deselects_but_keeps_the_library(composer, saved_library):
    """THE regression this guards: Clear used to wipe the loaded templates.
    Against a saved library that would delete the physician's work."""
    knee = saved_library[0]
    composer.cmb_nt_names.setCurrentIndex(composer.cmb_nt_names.findData(knee["id"]))
    assert composer._nt_active_id == knee["id"]

    composer._on_nt_clear_clicked()

    assert composer._nt_active_id == ""
    assert composer.get_normal_template_plain_text() == ""
    assert len(composer._nt_records) == len(saved_library), "Clear deleted the library"
    assert nt.load_library(), "Clear wrote an empty library to disk"
    assert composer.cmb_nt_names.count() == len(saved_library) + 1


def test_the_no_template_entry_deselects(composer, saved_library):
    composer.cmb_nt_names.setCurrentIndex(composer.cmb_nt_names.findData(saved_library[0]["id"]))
    composer.cmb_nt_names.setCurrentIndex(0)
    assert composer._nt_active_id == ""
    assert composer.get_normal_template_plain_text() == ""


def test_free_text_that_matches_nothing_snaps_back(composer, saved_library):
    knee = saved_library[0]
    composer.cmb_nt_names.setCurrentIndex(composer.cmb_nt_names.findData(knee["id"]))
    composer.cmb_nt_names.lineEdit().setText("zzz not a template")
    composer._on_nt_search_committed()
    assert composer.cmb_nt_names.currentData() == knee["id"]
    assert composer._nt_active_id == knee["id"]


def test_an_edit_in_the_editor_is_what_gets_sent(composer, saved_library):
    """The template is a starting point, not a lock."""
    composer.cmb_nt_names.setCurrentIndex(composer.cmb_nt_names.findData(saved_library[0]["id"]))
    composer.box.setPlainText("Both menisci normal. No effusion. EDITED BY THE PHYSICIAN.")
    assert "EDITED BY THE PHYSICIAN" in composer.get_normal_template_plain_text()


def test_the_toolbar_height_is_unchanged(composer):
    """`_nt_bar_fixed_h` feeds the composer height maths — growing this bar is
    what pushed the action row out of the window in July."""
    assert composer._nt_bar_fixed_h == 44
    assert composer.nt_bar.height() == 44


def test_the_manage_button_exists_and_is_wired(composer):
    assert composer.btn_nt_manage is not None
    assert composer.btn_nt_manage.isEnabled()


def test_kill_switch_restores_the_legacy_dropdown(qapp, saved_library, monkeypatch):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import UnifiedComposer

    monkeypatch.setenv("AIPACS_ECHOMIND_TEMPLATE_LIBRARY", "0")
    c = UnifiedComposer()
    try:
        assert c._nt_records == [], "the library must not load when the flag is off"
        assert not c.cmb_nt_names.isEditable(), "legacy picker is a plain dropdown"
        assert c.cmb_nt_names.itemText(0) == "Upload JSON first…"
    finally:
        c.deleteLater()


# ─────────────────────────────────────────────────────────────────────────────
#  The manager dialog
# ─────────────────────────────────────────────────────────────────────────────

def test_the_dialog_searches_filters_and_previews(qapp, saved_library):
    from modules.EchoMind.viewer_chat.normal_template_dialog import (
        NormalTemplateLibraryDialog,
    )

    dlg = NormalTemplateLibraryDialog(None, records=saved_library,
                                      active_id=saved_library[0]["id"])
    try:
        assert dlg.lst.count() == 3
        dlg.ed_search.setText("knee")
        assert dlg.lst.count() == 1
        dlg.ed_search.setText("")
        idx = dlg.cmb_modality.findText("CT")
        assert idx > 0, "the modality filter is populated from the library"
        dlg.cmb_modality.setCurrentIndex(idx)
        assert dlg.lst.count() == 1
        assert "Liver" in dlg.txt_preview.toPlainText(), "preview shows the template body"
    finally:
        dlg.deleteLater()


def test_the_dialog_marks_the_active_template(qapp, saved_library):
    from modules.EchoMind.viewer_chat.normal_template_dialog import (
        NormalTemplateLibraryDialog,
    )

    dlg = NormalTemplateLibraryDialog(None, records=saved_library,
                                      active_id=saved_library[1]["id"])
    try:
        marked = [dlg.lst.item(i).text() for i in range(dlg.lst.count())
                  if dlg.lst.item(i).text().startswith("●")]
        assert len(marked) == 1 and "CT Abdomen" in marked[0]
    finally:
        dlg.deleteLater()


def test_the_dialog_renames_and_persists(qapp, saved_library):
    from modules.EchoMind.viewer_chat.normal_template_dialog import (
        NormalTemplateLibraryDialog,
    )

    dlg = NormalTemplateLibraryDialog(None, records=saved_library)
    try:
        dlg.ed_search.setText("thyroid")
        assert dlg.lst.count() == 1
        dlg.ed_name.setText("Thyroid — screening")
        dlg.cmb_edit_modality.setCurrentText("SONOGRAPHY")
        assert dlg.btn_save_meta.isEnabled()
        dlg._save_metadata()
        names = [r["name"] for r in nt.load_library()]
        assert "Thyroid — screening" in names, "the rename did not reach disk"
    finally:
        dlg.deleteLater()
