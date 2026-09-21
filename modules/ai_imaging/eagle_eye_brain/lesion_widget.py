"""Study-bound lesion input UI, sharing the Brain worker/progress/export shell."""
from pathlib import Path

from PySide6.QtWidgets import (QLabel, QCheckBox, QDialog, QVBoxLayout, QComboBox,
                               QDialogButtonBox, QLineEdit, QHBoxLayout)

from .widget import BrainVolumetryWidget


class BrainLesionWidget(BrainVolumetryWidget):
    def __init__(self, parent=None, *, study_uid=None):
        super().__init__(parent, study_uid=study_uid)
        for label in self.findChildren(QLabel):
            if label.text() == 'Eagle Eye Brain':
                label.setText('Eagle Eye | White-matter lesions')
            elif label.text() == '3D FLAIR (optional review)':
                label.setText('3D FLAIR (required)')
            elif label.text() == 'Sex for reference model':
                label.setText('Sex')
        for checkbox in self.findChildren(QCheckBox):
            if checkbox.text() == 'Advanced options and reference details':
                checkbox.hide()
        self.input_summary.setText('Select one T1 and one 3D FLAIR. LST-AI measures lesion candidates for review.')
        self.run.setText('Analyze white-matter lesions')
        self.regenerate.hide()
        self.advanced.hide()
        self.confirm.setText('I verified full-brain T1 and 3D FLAIR from this examination.')
        from .lesion_indication import INDICATIONS
        row = QHBoxLayout()
        title = QLabel('Primary disease / report context')
        title.setStyleSheet('font-weight: bold; color: #60a5fa;')
        row.addWidget(title)
        self.primary_disease = QComboBox()
        self.primary_disease.setObjectName('lesionPrimaryDisease')
        self.primary_disease.addItem('Select clinical context', None)
        for key, label in INDICATIONS.items():
            self.primary_disease.addItem(label, key)
        row.addWidget(self.primary_disease)
        self.layout().insertLayout(9, row)
        self.clinical_note = QLineEdit()
        self.clinical_note.setMaxLength(500)
        self.clinical_note.setPlaceholderText('Clinical details (optional; supplied by the clinician)')
        self.layout().insertWidget(10, self.clinical_note)
        self.ms_comparison = QCheckBox('Compare previous and current MS examinations')
        self.ms_comparison.setObjectName('lesionMSComparison')
        self.ms_comparison.hide()
        self.layout().insertWidget(11, self.ms_comparison)
        self._comparison_pair = None
        self._selecting_comparison = False
        self.fazekas = QComboBox()
        self.fazekas.setObjectName('clinicianFazekasOverall')
        self.fazekas.addItem('Fazekas (clinician): not provided', None)
        for grade, label in enumerate(('None', 'Mild', 'Moderate', 'Severe')):
            self.fazekas.addItem(f'Fazekas {grade} - {label} (clinician rating)', grade)
        self.layout().insertWidget(11, self.fazekas)
        self.fazekas.hide()
        self.primary_disease.currentIndexChanged.connect(self._context_changed)
        self.ms_comparison.toggled.connect(self._comparison_changed)

    def _context_changed(self):
        self.fazekas.setVisible(self.primary_disease.currentData() == 'svd')
        is_ms = self.primary_disease.currentData() == 'ms'
        self.ms_comparison.setVisible(is_ms)
        if not is_ms:
            self.ms_comparison.setChecked(False)

    def _comparison_changed(self):
        self._comparison_pair = None
        self.study_button.setText('Select previous and current MRI series' if self.ms_comparison.isChecked()
                                  else 'Select MRI series')
        self.input_summary.setText('Select T1 and 3D FLAIR for each examination. Dates come from DICOM. '
                                   'Both examinations are processed; change candidates require review.'
                                   if self.ms_comparison.isChecked() else
                                   'Select one T1 and one 3D FLAIR from this examination.')

    def start_study_segmentation(self):
        if not self.ms_comparison.isChecked():
            self._selecting_comparison = False
            return super().start_study_segmentation()
        if self._future is not None:
            return
        from .lesion_longitudinal import load_patient_examinations
        self._selecting_comparison = True
        self.primary_disease.setEnabled(False)
        self.ms_comparison.setEnabled(False)
        self._cancel.clear()
        self._future_kind = 'series'
        self.study_button.setEnabled(False)
        self.run.setEnabled(False)
        self.status.setText('Loading MRI examinations linked to this patient')
        self._future = self._executor.submit(load_patient_examinations, self.study_uid)
        self._begin_progress()

    def _choose_comparison_series(self, examinations):
        if len(examinations) < 2:
            self.status.setText('Import the previous MRI under the same patient before comparison. Two examinations are required.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('MS comparison: previous and current MRI')
        dialog.resize(780, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Select a full-brain T1 and 3D FLAIR for each date. Conventional T2 SPACE is not FLAIR.'))
        selectors = []
        for title in ('Previous MRI', 'Current MRI'):
            layout.addWidget(QLabel(title))
            study, t1, flair = QComboBox(), QComboBox(), QComboBox()
            study.addItem('Select examination date', None)
            for exam in examinations:
                study.addItem(f'{exam["date"]} | {len(exam["series"])} MR series', exam)
            def populate(index, source=study, targets=(t1, flair)):
                exam = source.currentData()
                for target, role in zip(targets, ('T1', '3D FLAIR')):
                    target.clear(); target.addItem('Select ' + role, None)
                    for row in (exam['series'] if exam else []):
                        if row['available']:
                            target.addItem(f'Series {row["number"]} | {row["description"]} | {row["image_count"]} images', row)
            study.currentIndexChanged.connect(populate)
            for control in (study, t1, flair):
                layout.addWidget(control)
            selectors.append((study, t1, flair))
        verified = QCheckBox('I verified the same patient, full-brain T1 and FLAIR, and previous/current examinations.')
        layout.addWidget(verified)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        def update():
            values = [[c.currentData() for c in group] for group in selectors]
            valid = verified.isChecked() and all(all(v) for v in values)
            if valid:
                valid = values[0][0]['study_uid'] != values[1][0]['study_uid'] and all(v[1]['series_uid'] != v[2]['series_uid'] for v in values)
            buttons.button(QDialogButtonBox.Ok).setEnabled(bool(valid))
        for group in selectors:
            for control in group:
                control.currentIndexChanged.connect(update)
        verified.toggled.connect(update)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons); update()
        if dialog.exec() != QDialog.Accepted:
            return
        pair = []
        for study, t1, flair in selectors:
            pair.append(dict(study_uid=study.currentData()['study_uid'],
                             t1=dict(t1.currentData()), flair=dict(flair.currentData())))
        self._comparison_pair = pair
        self._selected_series, self._selected_flair = pair[1]['t1'], pair[1]['flair']
        self.t1.setText(self._selected_series['path']); self.flair.setText(self._selected_flair['path'])
        self.confirm.setChecked(True)
        self.input_summary.setText('Previous: ' + selectors[0][0].currentData()['date'] +
                                   ' | Current: ' + selectors[1][0].currentData()['date'] +
                                   '. DICOM identity and chronology are checked before processing.')
        self._load_demographics()

    def _choose_t1_series(self, rows):
        if self._selecting_comparison:
            self._selecting_comparison = False
            return self._choose_comparison_series(rows)
        dialog = QDialog(self)
        dialog.setWindowTitle('Select T1 and 3D FLAIR')
        dialog.resize(720, 280)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Select the two inputs from this examination.'))
        combos = []
        for title, name in [('3D T1-weighted', 'lesionT1Series'), ('3D FLAIR', 'lesionFlairSeries')]:
            layout.addWidget(QLabel(title))
            combo = QComboBox()
            combo.setObjectName(name)
            combo.addItem('Select a series', None)
            for row in rows:
                if row['available']:
                    combo.addItem(f"Series {row['number']} | {row['description']} | {row['image_count']} images", row)
            layout.addWidget(combo)
            combos.append(combo)
        preferred_uid = getattr(self, 'preferred_series_uid', '')
        for row in rows:
            if row['series_uid'] != preferred_uid or not row['available']:
                continue
            role = 0 if row.get('preferred') else (1 if 'flair' in row.get('description', '').lower() else None)
            if role is not None:
                combo = combos[role]
                for index in range(1, combo.count()):
                    if combo.itemData(index)['series_uid'] == preferred_uid:
                        combo.setCurrentIndex(index)
                        break
        verified = QCheckBox('Both series cover the full brain; the FLAIR is not a conventional T2 SPACE sequence.')
        layout.addWidget(verified)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Use selected images')
        def update():
            first, second = [c.currentData() for c in combos]
            buttons.button(QDialogButtonBox.Ok).setEnabled(bool(first and second and verified.isChecked()
                                                                and first['series_uid'] != second['series_uid']))
        for combo in combos:
            combo.currentIndexChanged.connect(update)
        verified.toggled.connect(update)
        update()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            self.status.setText('Selection cancelled. No analysis started.')
            return
        self._selected_series, self._selected_flair = [dict(c.currentData()) for c in combos]
        self.t1.setText(self._selected_series['path'])
        self.flair.setText(self._selected_flair['path'])
        self.confirm.setChecked(True)
        self._load_demographics()

    def _apply_demographics(self, context):
        super()._apply_demographics(context)
        self.status.setText('Review patient details, then click Analyze white-matter lesions.')

    def _start(self):
        if self._future is not None:
            return
        if not self.confirm.isChecked() or not self._selected_series or not self._selected_flair:
            self.status.setText('Select and verify T1 and 3D FLAIR from this examination.')
            return
        indication, note = self.primary_disease.currentData(), self.clinical_note.text()
        fazekas = self.fazekas.currentData() if indication == 'svd' else None
        if indication is None:
            self.status.setText('Select the primary disease / reporting context before analysis.')
            return
        comparison = self.ms_comparison.isChecked()
        pair = self._comparison_pair
        if comparison and (indication != 'ms' or not pair):
            self.status.setText('Select the previous and current MRI series for MS comparison.')
            return
        first, second = dict(self._selected_series), dict(self._selected_flair)
        study_uid, demographics = self.study_uid, self._demographics()
        if first['path'] != self.t1.text() or second['path'] != self.flair.text():
            self.status.setText('Select both series again from this examination.')
            return
        self._cancel.clear()
        self._result = None
        self.result_panel.hide()
        for button in (self.run, self.regenerate, self.study_button, self.pdf, self.save_pdf, self.output):
            button.setEnabled(False)
        self.cancel.setEnabled(True)
        self._future_kind = 'analysis'
        cancel, messages = self._cancel, self._messages
        self.primary_disease.setEnabled(False)
        self.clinical_note.setEnabled(False)
        self.fazekas.setEnabled(False)
        self.ms_comparison.setEnabled(False)
        def execute():
            from PacsClient.utils.data_paths import AI_DIR
            from .lesions import run_lesions
            if comparison:
                from .lesion_longitudinal import run_comparison
                return run_comparison(*pair, root=Path(AI_DIR) / 'eagle_eye', cancel=cancel,
                                      progress=messages.put, clinical_note=note)
            return run_lesions(first['path'], second['path'], study_uid=study_uid,
                               t1_uid=first['series_uid'], flair_uid=second['series_uid'],
                               root=Path(AI_DIR) / 'eagle_eye', cancel=cancel,
                               progress=messages.put, demographics=demographics,
                               primary_disease=indication, clinical_note=note, fazekas_overall=fazekas)
        self.status.setText('Preparing local lesion analysis')
        self._future = self._executor.submit(execute)
        self._begin_progress()

    def _poll(self):
        pending = self._future is not None
        super()._poll()
        if self._future is None:
            self.primary_disease.setEnabled(True)
            self.clinical_note.setEnabled(True)
            self.fazekas.setEnabled(True)
            self.ms_comparison.setEnabled(True)
        if pending and self._future is None and self._future_kind in ('analysis', 'manual_recalculate') and self._result:
            metrics = self._result['metrics']
            self.report.setText('<h2>Lesion candidates ready for review</h2>'
                                f'<p><b>{metrics["candidate_count"]} candidates</b> | '
                                f'<b>{metrics["total_volume_cm3"]:.3f} cm3</b></p>'
                                '<p>Review the complete FLAIR mask and MRI before interpretation. '
                                'These results do not establish an MS diagnosis.</p>')
            if self._result.get('longitudinal'):
                c = self._result['longitudinal']
                self.report.setText('<h2>MS comparison ready for review</h2>'
                                    f'<p>{c["possible_new"]} possible new | '
                                    f'{c["possible_enlarged"]} possible enlarged candidates</p>'
                                    '<p>Experimental comparison. Review registration and masks before confirming change.</p>')
            self.status.setText('Lesion report ready. Open the result folder for the native FLAIR mask.')
