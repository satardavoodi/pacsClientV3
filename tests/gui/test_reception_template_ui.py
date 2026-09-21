"""Synthetic offscreen worker, filtering, and selection tests (not live acceptance)."""
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from modules.EchoMind import normal_templates as nt
from modules.EchoMind import reception_templates as rt
from modules.EchoMind.viewer_chat.reception_template_dialog import ReceptionTemplateDialog, _WORKERS


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def drain(app, predicate):
    until = time.monotonic() + 3
    while not predicate() and time.monotonic() < until:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def catalog():
    records = []
    for sid, name, mod, owner in (("a", "A shared", "MRI", "other"),
                                  ("b", "Z mine", "MRI", "me"),
                                  ("c", "CT template", "CT", "me")):
        rec, _ = nt.normalize_record({"id": sid, "Name": name, "Html": "No joint effusion.", "Modality": mod})
        rec["reception"] = {"owner_id": owner, "personnel_id": "", "personnel_name": ""}
        records.append(rec)
    return {"records": records, "modalities": ["CT", "MRI"], "user_id": "me", "personnel_id": "", "skipped": 0}


def test_modality_and_own_first_with_explicit_review(app):
    dialog = ReceptionTemplateDialog(modality="MR")
    dialog._received(True, (("url", "token", "profile"), catalog()))
    assert dialog.items.count() == 2
    assert "Z mine" in dialog.items.item(0).text()
    dialog.items.setCurrentRow(0)
    assert dialog.preview.toPlainText() == "No joint effusion."
    assert not dialog.import_button.isEnabled()
    dialog.confirm_normal.setChecked(True)
    assert dialog.import_button.isEnabled()
    dialog.items.setCurrentRow(1)
    assert not dialog.confirm_normal.isChecked()
    dialog.modality.setCurrentIndex(0)
    assert dialog.items.count() == 3
    dialog.deleteLater()


def test_fetch_and_save_run_off_gui_thread(app, monkeypatch, tmp_path):
    connection = ("http://example.test", "synthetic", "profile")
    threads = []
    def fetch(_self):
        threads.append(threading.get_ident())
        return catalog()
    monkeypatch.setattr(rt, "current_connection", lambda: connection)
    monkeypatch.setattr(rt.ReceptionTemplates, "fetch", fetch)
    monkeypatch.setattr(nt, "library_path", lambda: str(tmp_path / "library.json"))
    original = rt.import_selected
    def save(rec):
        threads.append(threading.get_ident())
        return original(rec)
    monkeypatch.setattr(rt, "import_selected", save)
    dialog = ReceptionTemplateDialog(modality="MRI")
    dialog._fetch()
    drain(app, lambda: not dialog._busy)
    dialog.items.setCurrentRow(0)
    dialog.confirm_normal.setChecked(True)
    dialog._import()
    drain(app, lambda: not dialog._busy and not _WORKERS)
    assert len(nt.load_library()) == 1
    assert len(threads) == 2 and all(t != threading.get_ident() for t in threads)
    dialog.deleteLater()


def test_changed_connection_cannot_import(app, monkeypatch, tmp_path):
    monkeypatch.setattr(nt, "library_path", lambda: str(tmp_path / "library.json"))
    monkeypatch.setattr(rt, "current_connection", lambda: ("new", "new", "new"))
    dialog = ReceptionTemplateDialog(modality="MRI")
    dialog._received(True, (("old", "old", "old"), catalog()))
    dialog.items.setCurrentRow(0)
    dialog.confirm_normal.setChecked(True)
    dialog._import()
    drain(app, lambda: not dialog._busy and not _WORKERS)
    assert "changed" in dialog.status.text()
    assert nt.load_library() == []
    dialog.deleteLater()


def test_close_while_fetching_keeps_worker_alive_without_late_ui(app, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(rt, "current_connection", lambda: ("http://example.test", "synthetic", "profile"))
    def fetch(_self):
        gate.wait(2)
        return catalog()
    monkeypatch.setattr(rt.ReceptionTemplates, "fetch", fetch)
    dialog = ReceptionTemplateDialog()
    dialog._fetch()
    dialog.reject()
    gate.set()
    drain(app, lambda: not _WORKERS)
    assert not dialog._catalog
    dialog.deleteLater()


def test_page_modality_reaches_library_default(app):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QToolButton
    from modules.EchoMind.viewer_chat.ai_chat_pages import OneChatPage
    composer = SimpleNamespace(btn_modality=QToolButton(), _selected_modality=None)
    OneChatPage._set_modality_text(SimpleNamespace(composer=composer), "OBSTETRIC ULTRASOUND")
    assert composer._selected_modality == "OBSTETRIC ULTRASOUND"


def test_settings_import_refreshes_open_composer_without_replacing_active_text(app, monkeypatch, tmp_path):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import UnifiedComposer
    from modules.EchoMind.viewer_chat.reception_template_dialog import library_events
    monkeypatch.setattr(nt, "library_path", lambda: str(tmp_path / "library.json"))
    old, new = catalog()["records"][:2]
    assert nt.save_library([old])
    composer = UnifiedComposer()
    composer._nt_apply_record(old)
    composer._buf_normal_template = "An intentional local template edit."
    library_events.imported.emit([old, new])
    assert composer.cmb_nt_names.findData(new["id"]) >= 0
    assert composer._nt_active_id == old["id"]
    assert composer._buf_normal_template == "An intentional local template edit."
    composer.deleteLater()

def test_batch_organization_and_review_edit_publish_off_thread(app, monkeypatch, tmp_path):
    from modules.EchoMind.viewer_chat.reception_template_dialog import OrganizedTemplateReviewDialog
    monkeypatch.setattr(nt, 'library_path', lambda: str(tmp_path / 'library.json'))
    connection=('url','token','profile')
    monkeypatch.setattr(rt, 'current_connection', lambda:connection)
    threads=[]
    prepare = rt.prepare_template_languages
    def translate(text, **kwargs):
        threads.append(threading.get_ident())
        return prepare(text, complete=lambda p: {'lines':p['lines']})
    monkeypatch.setattr(rt, 'prepare_template_languages', translate)
    def complete(payload):
        threads.append(threading.get_ident())
        return {'groups':[{'section':'Region','kind':'normal_candidate',
                           'ids':[b['id'] for b in payload['blocks']]}]}
    monkeypatch.setattr(rt, '_organizer_completion', complete)
    dialog=ReceptionTemplateDialog(modality='MRI')
    dialog._received(True,(connection,catalog()))
    dialog.items.selectAll()
    assert dialog.organize_button.isEnabled()
    dialog._organize()
    drain(app,lambda:not dialog._busy and not _WORKERS)
    assert len(rt.load_organized_templates())==2
    assert nt.load_library()==[]
    review=OrganizedTemplateReviewDialog()
    drain(app,lambda:not review._busy and not _WORKERS)
    assert review.items.count()==2
    review.editor.setPlainText('The final physician-edited normal statement.')
    assert review._dirty and not review.items.isEnabled()
    original_save=rt.save_organized_edit
    def save(*args,**kwargs):
        threads.append(threading.get_ident())
        return original_save(*args,**kwargs)
    monkeypatch.setattr(rt,'save_organized_edit',save)
    assert not review.save_button.isEnabled()
    review._generate_languages()
    drain(app,lambda:not review._busy and not _WORKERS)
    assert nt.load_library() == []
    assert review.save_button.isEnabled()
    review._save()
    drain(app,lambda:not review._busy and not _WORKERS)
    assert nt.template_body_text(nt.load_library()[0])=='The final physician-edited normal statement.'
    assert nt.load_library()[0]['translations']['en'] == review.english_preview.toPlainText()
    assert nt.load_library()[0]['translations']['fa'] == review.persian_preview.toPlainText()
    assert all(t!=threading.get_ident() for t in threads)
    assert not review._dirty and review.items.isEnabled()
    review.reject();dialog.reject()
    review.deleteLater();dialog.deleteLater()


def test_cancel_organization_after_refresh_uses_current_event(app, monkeypatch, tmp_path):
    monkeypatch.setattr(nt,'library_path',lambda:str(tmp_path/'library.json'))
    monkeypatch.setattr(rt,'current_connection',lambda:('http://example.test','token','profile'))
    monkeypatch.setattr(rt.ReceptionTemplates,'fetch',lambda _:catalog())
    gate=threading.Event();entered=threading.Event()
    def complete(payload):
        entered.set();gate.wait(2)
        return {'groups':[{'section':'X','kind':'normal_candidate','ids':[b['id'] for b in payload['blocks']]}]}
    monkeypatch.setattr(rt,'_organizer_completion',complete)
    dialog=ReceptionTemplateDialog(modality='MRI');dialog._fetch()
    drain(app,lambda:not dialog._busy)
    dialog.items.setCurrentRow(0);dialog._organize()
    drain(app,entered.is_set)
    dialog.cancel_button.click();gate.set()
    drain(app,lambda:not dialog._busy and not _WORKERS)
    assert not rt.load_organized_templates()
    assert 'Stopped' in dialog.status.text()
    dialog.reject();dialog.deleteLater()
