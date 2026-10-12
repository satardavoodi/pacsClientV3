"""Study-bound client form; all segmentation and measurements run on Eagle Eye Server."""
from concurrent.futures import ThreadPoolExecutor
import threading
from shiboken6 import isValid

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QComboBox, QCheckBox,
                               QPushButton, QLabel, QTextBrowser, QLineEdit)

from .lumbar_marrow import CLINICAL_FIELDS, LIMITATION, validate_parameters


def analyze_series(row, study_uid, params, cancel):
    from pathlib import Path
    from PacsClient.utils.data_paths import AI_DIR
    from .eagle_eye_remote.client import Client
    from .eagle_eye_remote.routing import reference
    client = Client()
    if 'lumbar-marrow' not in client.json('/v1/capabilities').get('modules', []):
        raise ValueError('Update the Eagle Eye Server candidate to enable Lumbar Bone Marrow. No job was submitted.')
    if params.get('mode') == 'multiparametric' and client.json('/v1/capabilities').get('marrow_multisequence_protocol', 0) < params.get('input_protocol', 1):
        raise ValueError('Update Eagle Eye Server to enable full-stack Dixon and multi-echo analysis. No job was submitted.')
    study, ref = reference(row['path'])
    if study != study_uid or ref['series_uid'] != row['series_uid']:
        raise ValueError('Selected series identity changed. Reload the series list.')
    from .eagle_eye_brain.patient_context import dicom_context
    context = dicom_context(row['path'])
    if context.get('study_uid') and (context['study_uid'] != study or context.get('series_uid') != ref['series_uid']):
        raise ValueError('Report identity differs from selected series.')
    selected = {'primary': ref}
    for role, source in row.get('marrow_inputs', {}).items():
        other_study, other = reference(source['path'])
        if other_study != study or other['series_uid'] != source['series_uid']:
            raise ValueError('All marrow inputs must belong to the selected examination.')
        selected[role] = other
    result = client.analyze('lumbar-marrow', study, selected, params,
                            Path(AI_DIR) / 'eagle_eye' / 'marrow', cancel=cancel)
    result['patient_context'] = context
    report = Path(result['report_html'])
    return result, report.read_text(encoding='utf-8'), str(report)


class LumbarMarrowWidget(QWidget):
    resultsReady = Signal()

    def __init__(self, parent=None, *, study_uid, preferred_series_uid='', load_inputs=True):
        super().__init__(parent)
        self.study_uid = str(study_uid)
        self.preferred_series_uid = preferred_series_uid
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='marrow-client')
        self._future = None
        self._future_kind = ''
        self._result = None
        self._control_error = None
        self._cancel = threading.Event()
        self._disposed = False
        layout = QVBoxLayout(self)
        note = self.method_note = QLabel(LIMITATION)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.mode = QComboBox()
        self.mode.setObjectName('marrowMode')
        self.mode.addItem('Native T1 signal assessment', 't1')
        self.mode.addItem('Full-stack T1 / T2 / Dixon evaluation', 'multiparametric')
        layout.addWidget(self.mode)
        self.series = QComboBox()
        self.series.setObjectName('marrowT1Series')
        layout.addWidget(self.series)
        self.confirm = QCheckBox('I confirm this is lumbar precontrast T1 without fat suppression, not Dixon or a T1 map.')
        self.confirm.setObjectName('marrowT1Confirmed')
        layout.addWidget(self.confirm)
        self.input_panel = QWidget()
        inputs = QFormLayout(self.input_panel)
        self.extra_series = {}
        for role, text in [('opposed','Dixon opposed-phase (required)'),('t1','Sagittal native T1 (required)'),
                           ('t2','Sagittal T2 (required)'),('stir','Sagittal STIR (optional)'),
                           ('multiecho','Magnitude multi-echo (optional)'),('fat','Dixon fat (optional pair)'),
                           ('water','Dixon water (optional pair)')]:
            combo = QComboBox()
            combo.setObjectName('marrowInput_'+role)
            inputs.addRow(text,combo)
            self.extra_series[role] = combo
        self.alignment = QCheckBox('I reviewed Dixon / multi-echo anatomical alignment; allow descriptive Dixon branch guidance')
        self.alignment.setObjectName('marrowAlignmentConfirmed')
        inputs.addRow(self.alignment)
        layout.addWidget(self.input_panel)
        self.input_panel.hide()
        self._series_rows = []
        self.mode.currentIndexChanged.connect(self.mode_changed)
        for combo in (self.series, *self.extra_series.values()):
            combo.currentIndexChanged.connect(self.input_changed)
        form = QFormLayout()
        self.fields = {}
        for key in CLINICAL_FIELDS:
            field = QLineEdit()
            field.setPlaceholderText('Optional; leave blank if unknown')
            field.setObjectName('marrow_' + key)
            self.fields[key] = field
            form.addRow(key.replace('_', ' '), field)
        self.emh = QComboBox()
        self.emh.addItems(['unknown', 'absent', 'present'])
        form.addRow('EMH (physician-entered)', self.emh)
        layout.addLayout(form)
        self.reload = QPushButton('Reload MRI series')
        self.reload.clicked.connect(self.load_series)
        layout.addWidget(self.reload)
        self.run = QPushButton('Run experimental T1 analysis on server')
        self.run.setObjectName('marrowRun')
        self.run.clicked.connect(self.start)
        layout.addWidget(self.run)
        self.cancel = QPushButton('Cancel analysis')
        self.cancel.clicked.connect(self._cancel.set)
        self.cancel.setEnabled(False)
        layout.addWidget(self.cancel)
        self.status = QLabel('Ready')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        from .lumbar_marrow_review import MarrowReview
        self.review_page = MarrowReview()
        self.review_page.setObjectName('marrowReviewPage')
        self.report = self.review_page.report
        self.report.setObjectName('marrowReport')
        self._review_session = None
        self.review_page.exportRequested.connect(self.export_pdf)
        self.review_page.editRequested.connect(self.edit_segmentation)
        self.review_page.recalculateRequested.connect(self.recalculate)
        self.review_page.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.poll)
        if load_inputs:
            self.load_series()

    def restore_saved_result(self, result):
        from .eagle_eye_brain.saved_results import _same_study
        if not _same_study(result, self.study_uid):
            raise ValueError('Saved result belongs to another examination.')
        self._result = dict(result)
        self.review_page.show_result(self._result)
        self.status.setText('Saved research draft restored. No new analysis was submitted.')
        self.resultsReady.emit()

    def _busy(self, value):
        for control in (self.run, self.reload, self.series, self.confirm, self.emh, self.mode, self.alignment, *self.extra_series.values(), *self.fields.values()):
            control.setEnabled(not value)
        self.cancel.setEnabled(value)

    def load_series(self):
        if self._future is not None:
            return
        from .marrow_inputs import load_series as load_study_series
        self._cancel.clear()
        self._future_kind = 'series'
        self._control_error = None
        self._future = self._executor.submit(load_study_series, self.study_uid)
        self._busy(True)
        self.status.setText('Loading MRI series...')
        self._timer.start()

    def start(self):
        if self._future is not None:
            return
        try:
            row = self.series.currentData()
            if not row:
                raise ValueError('Select a downloaded lumbar T1 series.')
            clinical = {key: float(field.text().strip()) for key, field in self.fields.items() if field.text().strip()}
            clinical['emh'] = self.emh.currentText()
            params = dict(t1_confirmed=self.confirm.isChecked(), clinical=clinical)
            if self.mode.currentData() == 'multiparametric':
                params = dict(mode='multiparametric', input_protocol=2, inputs_confirmed=self.confirm.isChecked(),
                              alignment_confirmed=self.alignment.isChecked(), clinical=clinical)
                from .marrow_multisequence import validate_parameters as validate_multi
                validate_multi(params)
                selected = {role: combo.currentData() for role,combo in self.extra_series.items() if combo.currentData()}
                from .marrow_inputs import require_roles
                require_roles({'primary', *selected}, 2)
                if len({row['series_uid'], *(x['series_uid'] for x in selected.values())}) != len(selected)+1:
                    raise ValueError('Each role must use a distinct series.')
                row = dict(row, marrow_inputs=selected)
            else:
                validate_parameters(params)
        except ValueError:
            self.status.setText('Select and confirm the required distinct series from this examination; check numeric clinical values.')
            return
        self._cancel.clear()
        self._result = None
        self._control_error = None
        self.report.clear()
        self._future_kind = 'analysis'
        self._future = self._executor.submit(analyze_series, dict(row), self.study_uid, params, self._cancel)
        self._busy(True)
        self.status.setText('Server analysis running; CPU segmentation may take several minutes.')
        self._timer.start()

    def poll(self):
        if self._disposed:
            return
        if self._future is None or not self._future.done():
            return
        future, kind = self._future, self._future_kind
        self._future = None
        self._timer.stop()
        self._busy(False)
        if self._cancel.is_set():
            self.status.setText('Cancelled. No report displayed.')
            return
        try:
            value = future.result()
            if kind in ('pdf', 'edit'):
                if kind == 'edit':
                    self._review_session = value
                self.review_page.status.setText('PDF saved.' if kind == 'pdf' else 'In Slicer, save the correction, then recalculate on server.')
                return
            if kind == 'series':
                self._series_rows = value
                self.series.clear()
                self.series.addItem('Not selected', None)
                self.confirm.setChecked(False)
                for combo in self.extra_series.values():
                    combo.clear()
                    combo.addItem('Not selected', None)
                for row in value:
                    if row['available']:
                        self.series.addItem(f"Series {row['number']} | {row['description']} | {row['image_count']} images", row)
                        for combo in self.extra_series.values():
                            combo.addItem(f"Series {row['number']} | {row['description']} | {row['image_count']} images", row)
                        if self.mode.currentData() != 'multiparametric' and row['series_uid'] == self.preferred_series_uid:
                            self.series.setCurrentIndex(self.series.count() - 1)
                if self.mode.currentData() == 'multiparametric':
                    self.suggest_inputs()
                else:
                    self.status.setText('Select the lumbar T1 acquisition and confirm it before running.')
            else:
                from PySide6.QtCore import QUrl
                self._result, content, path = value
                self.report.document().setBaseUrl(QUrl.fromLocalFile(path))
                self.review_page.show_result(self._result)
                self._review_session = None
                self.status.setText('Research draft ready. Review sampling overlays; not approved for patient delivery.')
                self.resultsReady.emit()
        except Exception as error:
            # Do not expose transport exceptions, patient identities or filesystem paths.
            self._control_error = 'Analysis failed. Check server availability, source completeness and model package.'
            self.status.setText(str(error) if isinstance(error, ValueError) else self._control_error)
            self.review_page.status.setText(self.status.text())

    def _review_work(self, kind, callback, *args):
        if self._future is not None or not self._result or self._disposed:
            return
        self._cancel.clear()
        self._future_kind = kind
        self._future = self._executor.submit(callback, *args)
        self._busy(True)
        self.review_page.status.setText('Working...')
        self._timer.start()

    def export_pdf(self):
        from PySide6.QtWidgets import QFileDialog
        from .lumbar_marrow_review import save_pdf
        if self._future is not None or not self._result:
            return
        path, _ = QFileDialog.getSaveFileName(self.review_page, 'Save research draft PDF', 'lumbar-marrow.pdf', 'PDF (*.pdf)')
        if path:
            if not path.lower().endswith('.pdf'):
                path += '.pdf'
            result = dict(self._result, physician_notes=self.review_page.notes.toPlainText())
            self._review_work('pdf', save_pdf, result, path)

    def edit_segmentation(self):
        from .eagle_eye_brain.manual_review import prepare_review
        if not (self._result or {}).get('review_assets'):
            self.review_page.status.setText('This earlier result has no editable reference volume. Run analysis again on the updated server.')
            return
        self._review_work('edit', prepare_review, dict(self._result))

    def recalculate(self):
        if not self._review_session:
            self.review_page.status.setText('Open segmentation in Slicer and save the correction first.')
            return
        from .lumbar_marrow_revision import submit
        self._review_work('analysis', submit, self._review_session, self._cancel)

    def teardown(self):
        if self._disposed:
            return
        self._disposed = True
        self._cancel.set()
        self._timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
        if isValid(self.review_page):
            self.review_page.deleteLater()

    def mode_changed(self):
        multi = self.mode.currentData() == 'multiparametric'
        self.method_note.setText('Research draft. Full-stack vertebral-body masks, in/opposed signal loss and optional Dixon F/(F+W) signal maps; '
                                 'STIR and multi-echo are optional; echo fits apply to acquired planes. Inspect numbering, boundaries and alignment. '
                                 'TR/flip-aware branch comparison is conditional on assumed T1 values. '
                                 'Outputs are not calibrated PDFF, hematopoietic-cell percentages or iron concentration.'
                                 if multi else LIMITATION)
        self.input_panel.setVisible(multi)
        if multi:
            self.series.setCurrentIndex(0)
            self.suggest_inputs()
        self.confirm.setChecked(False)
        self.alignment.setChecked(False)
        self.confirm.setText('I confirm the primary series is Dixon in-phase and the selected T1, T2 and opposed-phase roles are correct; optional roles are reviewed.' if multi
                             else 'I confirm this is lumbar precontrast T1 without fat suppression, not Dixon or a T1 map.')
        self.run.setText('Run full-stack marrow evaluation on server' if multi else 'Run experimental T1 analysis on server')
        self.status.setText('Required: sagittal T1, T2 and matching Dixon in/opposed-phase. STIR and multi-echo are optional.' if multi
                            else 'Primary: native precontrast T1 without fat suppression.')

    def input_changed(self):
        self.confirm.setChecked(False)
        self.alignment.setChecked(False)

    def suggest_inputs(self):
        from .marrow_inputs import suggest
        proposed = suggest(self._series_rows)
        for role, combo in [('primary', self.series), *self.extra_series.items()]:
            # Preserve a manual selection; suggestions only fill unselected roles.
            if combo.currentData():
                continue
            uid = proposed.get(role)
            for i in range(combo.count()):
                row = combo.itemData(i)
                if row and row['series_uid'] == uid:
                    combo.setCurrentIndex(i)
                    break
        self.status.setText('Sequence suggestions loaded. Review or change every role; ambiguous matches remain unselected. STIR and multi-echo are optional.')
