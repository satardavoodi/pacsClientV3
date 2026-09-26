"""Lazy Eagle Eye Brain tab; all file/model/registration work runs off the GUI thread."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import queue
import threading

from PySide6.QtCore import QTimer, QUrl, Qt, QElapsedTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QFileDialog, QComboBox, QCheckBox, QFrame, QApplication, QDoubleSpinBox,
                               QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QProgressBar)

from .contracts import BrainError, BrainPlan
from .normative import BrainDemographics, REFERENCES, reference_assessment


class BrainVolumetryWidget(QWidget):
    def __init__(self, parent=None, *, study_uid=None):
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="EagleEyeBrain")
        self._cancel = threading.Event()
        self._messages = queue.Queue()
        self._future = None
        self._result = None
        self.study_uid = study_uid
        self._selected_series = None
        self._selected_flair = None
        self._supplementary = []
        self._future_kind = 'analysis'
        # Cleanup callbacks capture only worker-owned state, never a deleted widget.
        cancel, executor = self._cancel, self._executor
        self.destroyed.connect(lambda: (cancel.set(), executor.shutdown(wait=False, cancel_futures=True)))
        QApplication.instance().aboutToQuit.connect(cancel.set)
        layout = QVBoxLayout(self)
        title = QLabel("Eagle Eye Brain")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #60a5fa;")
        layout.addWidget(title)
        description = QLabel("1. Select images    2. Review patient details    3. Analyze")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.study_button = QPushButton('Select MRI series')
        self.study_button.setEnabled(bool(study_uid))
        self.study_button.clicked.connect(self.start_study_segmentation)
        layout.addWidget(self.study_button)
        self.t1 = self._source_row(layout, "3D T1-weighted")
        self.flair = self._source_row(layout, "3D FLAIR (optional review)")
        self.input_summary = QLabel('One primary T1 is required. Up to two supplementary T1 series are optional.')
        self.input_summary.setWordWrap(True)
        layout.addWidget(self.input_summary)
        section = QLabel('Patient details')
        section.setStyleSheet('font-size: 15px; font-weight: bold; color: #60a5fa;')
        layout.addWidget(section)
        demographic_row = QHBoxLayout()
        self.age = QDoubleSpinBox()
        self.age.setRange(-1, 120)
        self.age.setDecimals(2)
        self.age.setSpecialValueText("Not supplied")
        self.age.setValue(-1)
        self.sex = QComboBox()
        for label, value in (("Not supplied", "unknown"), ("Female", "female"), ("Male", "male")):
            self.sex.addItem(label, value)
        demographic_row.addWidget(QLabel("Age at examination (years)"))
        demographic_row.addWidget(self.age)
        demographic_row.addWidget(QLabel("Sex for reference model"))
        demographic_row.addWidget(self.sex)
        layout.addLayout(demographic_row)
        note = QLabel("Age and sex are filled from the selected DICOM series when available.")
        note.setWordWrap(True)
        layout.addWidget(note)
        advanced_toggle = QCheckBox('Advanced options and reference details')
        layout.addWidget(advanced_toggle)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        self.advanced.hide()
        advanced_toggle.toggled.connect(self.advanced.setVisible)
        layout.addWidget(self.advanced)
        self.reference = QComboBox()
        for item in REFERENCES:
            self.reference.addItem(item.name, item.id)
        advanced_layout.addWidget(self.reference)
        self.reference_status = QLabel()
        self.reference_status.setWordWrap(True)
        advanced_layout.addWidget(self.reference_status)
        self.reference.currentIndexChanged.connect(self._update_reference)
        self.age.valueChanged.connect(self._update_reference)
        self.sex.currentIndexChanged.connect(self._update_reference)
        self._update_reference()
        row = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.addItem("Standard", "standard")
        self.profile.addItem("Robust (for difficult contrast; review required)", "robust")
        row.addWidget(QLabel("Segmentation profile"))
        row.addWidget(self.profile)
        advanced_layout.addLayout(row)
        self.confirm = QCheckBox("I verified the selected images and examination.")
        layout.addWidget(self.confirm)
        confirmation_detail = QLabel("The selected images belong to the same examination, cover the full brain, "
                                     "and T1 is weighted imaging rather than a quantitative T1 map.")
        confirmation_detail.setWordWrap(True)
        advanced_layout.addWidget(confirmation_detail)
        controls = QHBoxLayout()
        self.run = QPushButton("Run brain volumetry")
        self.run.setMinimumHeight(38)
        self.run.setStyleSheet("background: #2563a6; color: white; font-weight: bold; border-radius: 6px; padding: 8px;")
        self.run.clicked.connect(self._start)
        controls.addWidget(self.run)
        self.regenerate = QPushButton("Report from completed analysis")
        self.regenerate.clicked.connect(self._regenerate)
        advanced_layout.addWidget(self.regenerate)
        self.cancel = QPushButton("Cancel")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self._cancel.set)
        controls.addWidget(self.cancel)
        self.output = QPushButton("Open result folder")
        self.output.setEnabled(False)
        self.output.clicked.connect(self._open_output)
        self.pdf = QPushButton("Open PDF report")
        self.pdf.setEnabled(False)
        self.pdf.clicked.connect(self._open_pdf)
        self.save_pdf = QPushButton('Save PDF report...')
        self.save_pdf.setEnabled(False)
        self.save_pdf.clicked.connect(self._save_pdf)
        layout.addLayout(controls)
        self.status = QLabel("Ready to select images. Model availability is checked when analysis starts.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setAccessibleName('Brain analysis activity')
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMinimumHeight(12)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.progress_detail = QLabel()
        self.progress_detail.setWordWrap(True)
        layout.addWidget(self.progress_detail)
        self._elapsed = QElapsedTimer()
        self.result_panel = QFrame()
        self.result_panel.setObjectName('brainResultPanel')
        self.result_panel.setStyleSheet(
            'QFrame#brainResultPanel { border: 1px solid #52718c; border-radius: 10px; }')
        result_layout = QVBoxLayout(self.result_panel)
        result_layout.setContentsMargins(20, 18, 20, 18)
        result_layout.setSpacing(14)
        self.comparison_button = QPushButton('Open T1 comparison PDF')
        self.comparison_button.hide()
        self.comparison_button.clicked.connect(self._open_comparison)
        result_layout.addWidget(self.comparison_button)
        self.report = QLabel()
        self.report.setWordWrap(True)
        self.report.setTextFormat(Qt.TextFormat.RichText)
        self.report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        result_layout.addWidget(self.report)
        actions = QHBoxLayout()
        for button in (self.save_pdf, self.pdf, self.output):
            button.setMinimumHeight(38)
            actions.addWidget(button)
        self.save_pdf.setStyleSheet(
            'QPushButton { background: #2563a6; color: white; border-radius: 6px; padding: 8px 16px; }'
            'QPushButton:hover { background: #1d4f87; }'
            'QPushButton:disabled { background: #576574; color: #d1d5db; }')
        self.pdf.setToolTip('Open the full report in your default PDF viewer.')
        self.save_pdf.setToolTip('Choose where to save a complete copy of this report.')
        result_layout.addLayout(actions)
        self._manual_session = None
        self._pending_manual_review = False
        self.manual_edit = QPushButton('Manual correction in 3D Slicer')
        self.manual_edit.setObjectName('brainManualCorrection')
        self.manual_edit.clicked.connect(self._manual_open)
        result_layout.addWidget(self.manual_edit)
        self.manual_recalculate = QPushButton('Recalculate corrected report')
        self.manual_recalculate.setObjectName('brainManualRecalculate')
        self.manual_recalculate.setEnabled(False)
        self.manual_recalculate.clicked.connect(self._manual_recalculate)
        result_layout.addWidget(self.manual_recalculate)
        layout.addWidget(self.result_panel)
        layout.addStretch(1)
        self.result_panel.hide()
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._poll)

    def _source_row(self, layout, title):
        row = QHBoxLayout()
        row.addWidget(QLabel(title))
        field = QLineEdit()
        row.addWidget(field, 1)
        if self.study_uid:
            field.setReadOnly(True)
            field.setPlaceholderText('Choose from this examination')
            button = QPushButton('Choose study series')
            button.clicked.connect(self.start_study_segmentation)
            row.addWidget(button)
            layout.addLayout(row)
            return field
        for text, directory in (("NIfTI", False), ("DICOM series", True)):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, target=field, folder=directory: self._pick(target, folder))
            row.addWidget(button)
        layout.addLayout(row)
        return field

    def _pick(self, target, directory):
        if directory:
            path = QFileDialog.getExistingDirectory(self, "Select one DICOM series")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Select brain image", "", "NIfTI (*.nii *.nii.gz)")
        if path:
            target.setText(path)

    def _start(self):
        if self._pending_manual_review:
            self.status.setText('Resume the pending server correction before starting another analysis.')
            return
        if self._future is not None or not self.confirm.isChecked() or not self.t1.text().strip():
            self.status.setText("Select the T1 image and confirm its protocol and examination identity.")
            return
        if self.study_uid and (not self._selected_series or self._selected_series['path'] != self.t1.text().strip()):
            self.status.setText('Choose the T1 MPRAGE series from this examination first.')
            return
        self._cancel.clear()
        self._result = None
        self.report.clear()
        self.result_panel.hide()
        self.output.setEnabled(False)
        self.pdf.setEnabled(False)
        self.save_pdf.setEnabled(False)
        self.study_button.setEnabled(False)
        self._future_kind = 'analysis'
        self.run.setEnabled(False)
        self.regenerate.setEnabled(False)
        self.cancel.setEnabled(True)
        self.status.setText("Preparing analysis")
        # Snapshot all GUI state now. The worker never reads a widget or live PACS state.
        sources = self.t1.text().strip(), self.flair.text().strip()
        plan = BrainPlan(profile=self.profile.currentData())
        demographics = self._demographics()
        reference_id = self.reference.currentData()
        cancel, messages = self._cancel, self._messages
        study_uid = self.study_uid
        selected = dict(self._selected_series) if self._selected_series else None
        selected_flair = dict(self._selected_flair) if self._selected_flair else None
        supplementary = [dict(row) for row in self._supplementary]
        def execute():
            from PacsClient.utils.data_paths import AI_DIR
            from .service import run_analysis
            from .study_workflow import run_study_analysis, patient_output_root
            root = Path(AI_DIR) / 'eagle_eye'
            if study_uid:
                from .multi_t1 import run_multi_t1
                return run_multi_t1(sources[0], study_uid, selected['series_uid'], root=root, supplementary=supplementary,
                                          flair_source=sources[1],
                                          flair_series_uid=selected_flair['series_uid'] if selected_flair else None,
                                          plan=plan, cancel=cancel, progress=messages.put,
                                          demographics=demographics, reference_id=reference_id)
            from .patient_context import dicom_context
            context = dicom_context(sources[0])
            output_root = patient_output_root(root, context) if context.get('study_uid') else root/'brain'/'unidentified'
            return run_analysis(*sources, output_root, plan=plan,
                                cancel=cancel, progress=messages.put, demographics=demographics,
                                reference_id=reference_id)
        self._future = self._executor.submit(execute)
        self._begin_progress()

    def _begin_progress(self):
        self._control_error = None
        self._elapsed.start()
        self.progress_bar.show()
        self._update_progress()
        self.timer.start()

    def _update_progress(self, finished=None):
        seconds = self._elapsed.elapsed() // 1000 if self._elapsed.isValid() else 0
        duration = f'{seconds // 60:02d}:{seconds % 60:02d}'
        if finished:
            self.progress_bar.hide()
            self.progress_detail.setText(f'{finished} | Elapsed {duration}')
        else:
            detail = ('Cancellation requested; waiting for the current operation to stop.'
                      if self._cancel.is_set() else
                      'Analysis is in progress. Some stages can take several minutes; time remaining is unavailable.')
            self.progress_detail.setText(f'Elapsed {duration} | {detail}')

    def _poll(self):
        if self._future is not None:
            self._update_progress()
        while True:
            try:
                self.status.setText(self._messages.get_nowait())
            except queue.Empty:
                break
        if self._future is None or not self._future.done():
            return
        future, self._future = self._future, None
        self.timer.stop()
        self.run.setEnabled(True)
        self.regenerate.setEnabled(True)
        self.cancel.setEnabled(False)
        self.study_button.setEnabled(bool(self.study_uid))
        if self._future_kind == 'export':
            self.save_pdf.setEnabled(bool(self._result and self._result.get('pdf_available')))
        try:
            result = future.result()
        except (BrainError, ValueError) as exc:
            self._control_error = type(exc).__name__
            self._update_progress('Stopped')
            self.status.setText(str(exc))
        except Exception as exc:
            self._control_error = 'AnalysisError'
            self._update_progress('Stopped')
            from ..eagle_eye_remote.client import DetachedAnalysis, AnalysisFailed
            if isinstance(exc, AnalysisFailed) and self._future_kind == 'manual_recalculate':
                self._pending_manual_review = False
                self.manual_edit.setEnabled(True)
                self.manual_recalculate.setText('Apply mask on server / recalculate')
                self.status.setText('The server did not complete the correction. Your local draft is retained; you can retry.')
                return
            if isinstance(exc, DetachedAnalysis) and self._future_kind == 'manual_recalculate':
                self._pending_manual_review = True
                for button in (self.run, self.regenerate, self.study_button, self.manual_edit):
                    button.setEnabled(False)
                self.manual_recalculate.setText('Resume server correction')
                self.manual_recalculate.setEnabled(True)
                self.status.setText(str(exc))
                return
            if self._future_kind == 'export':
                self.status.setText('Could not save the PDF. Close any open destination file or choose another folder and retry.')
            elif self._future_kind == 'series':
                self.status.setText('Could not load this examination\'s series. Open the study and try again.')
            else:
                self.status.setText("Analysis failed. Verify image geometry, model installation and available memory.")
        else:
            self._update_progress('Completed')
            if self._future_kind == 'demographics':
                self._apply_demographics(result)
                if getattr(self, 'start_after_inputs', False) and not self._cancel.is_set():
                    self._start()
                return
            if self._future_kind == 'series':
                if not self._cancel.is_set():
                    self._choose_t1_series(result)
                return
            if self._future_kind == 'export':
                self.status.setText('PDF report saved to your selected location.')
                self.save_pdf.setEnabled(True)
                return
            if self._future_kind == 'manual_open':
                self._manual_session = result
                self.manual_recalculate.setEnabled(not self._result.get('longitudinal'))
                self.manual_recalculate.setText('Apply mask on server / recalculate' if self._result.get('remote_analysis') else 'Recalculate corrected report')
                self.status.setText('Edit existing segments in Slicer, then save the correction. PACS remains available.')
                return
            if self._future_kind != 'manual_recalculate' or result.get('remote_analysis'):
                self._manual_session = None
                self.manual_recalculate.setEnabled(False)
            self._result = result
            self._pending_manual_review = False
            self.manual_edit.setEnabled(True)
            self.comparison_button.setVisible(bool(result.get("t1_consistency_pdf")))
            self.report.setText(
                '<h2>Ready for review</h2>'
                '<p><b>Brain volumetry report</b> &nbsp; | &nbsp; '
                + str(len(result.get('posterior_rows', []))) + ' volume measurements</p>'
                '<p>Global volumes &bull; White matter &bull; Cortex and lobes &bull; CSF<br>'
                'Basal ganglia &bull; Deep gray matter &bull; Brainstem &bull; Cerebellum &bull; Medial temporal</p>'
                '<p>Open the complete PDF for measurements, available reference ranges and image review. '
                'The report requires radiologist review before patient release.</p>')
            self.result_panel.show()
            if result.get('manual_rows'):
                self.report.setText('<h2>Manual measurement addendum ready</h2><p>Corrected binary-label volumes, '
                                    'original binary volumes and available reference intervals. '
                                    'Original SynthSeg posterior results remain separate.</p>')
            reference_status = ("Published volBrain reference intervals are included."
                                if result.get('normative', {}).get('status') == 'published_intervals'
                                else "Published reference intervals are unavailable; review the report explanation.")
            self.status.setText("Report ready for review. " + reference_status)
            self.output.setEnabled(True)
            self.pdf.setEnabled(bool(result.get("pdf_available")))
            self.save_pdf.setEnabled(bool(result.get('pdf_available')))

    def _manual_open(self):
        if self._future is not None or not self._result:
            return
        if self._result.get('remote_analysis') and not self._result.get('review_assets'):
            self.status.setText('This older result has no editable reference bundle. Update the server and run the analysis again.')
            return
        if self._manual_session:
            self.status.setText('A manual review session is already open. Save its correction in Slicer, then recalculate here.')
            return
        from copy import deepcopy
        from .manual_review import prepare_review
        self._future_kind = 'manual_open'
        self._cancel.clear()
        self.status.setText('Preparing a separate segmentation copy for manual review')
        self._future = self._executor.submit(prepare_review, deepcopy(self._result))
        self._begin_progress()

    def _manual_recalculate(self):
        if self._future is not None or not self._manual_session:
            return
        from .manual_review import recalculate_review
        self._future_kind = 'manual_recalculate'
        self._cancel.clear()
        self.status.setText('Sending the corrected mask to Eagle Eye Server for recalculation' if self._result.get('remote_analysis') else 'Recalculating corrected measurements and report')
        self._future = self._executor.submit(recalculate_review, self._manual_session,
                                            cancel=self._cancel, progress=self._messages.put)
        self.cancel.setEnabled(True)
        self._begin_progress()

    def _demographics(self):
        return BrainDemographics(None if self.age.value() < 0 else self.age.value(), self.sex.currentData())

    def _regenerate(self):
        if self._future is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose the completed examination's result.json", "", "Brain result (result.json)")
        if not path:
            return
        demographics, reference_id = self._demographics(), self.reference.currentData()
        dicom_source = self.t1.text().strip() or None
        self._cancel.clear()
        self._result = None
        self.report.clear()
        self.result_panel.hide()
        self.output.setEnabled(False)
        self.pdf.setEnabled(False)
        self.save_pdf.setEnabled(False)
        self._future_kind = 'analysis'
        self.run.setEnabled(False)
        self.regenerate.setEnabled(False)
        self.cancel.setEnabled(True)
        self.status.setText("Generating a separate report from completed measurements")
        cancel = self._cancel
        study_uid = self.study_uid
        def execute():
            from PacsClient.utils.data_paths import AI_DIR
            from .study_workflow import regenerate_patient_report
            return regenerate_patient_report(path, Path(AI_DIR) / 'eagle_eye', study_uid=study_uid,
                                     demographics=demographics, reference_id=reference_id, cancel=cancel,
                                     dicom_source=dicom_source)
        self._future = self._executor.submit(execute)
        self._begin_progress()

    def _update_reference(self, *args):
        assessment = reference_assessment(self._demographics(), self.reference.currentData())
        self.reference_status.setText(" ".join(assessment["reasons"]))

    def _open_pdf(self):
        if self._result and self._result.get("pdf_available"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._result["artifact_directory"]) / "report.pdf")))

    def _open_output(self):
        if self._result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._result["artifact_directory"]))))

    def choose_study_workflow(self):
        if self._future is not None or not self.study_uid:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Eagle Eye Brain | Choose analysis')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('What would you like to analyse?'))
        segmentation = QPushButton('Whole Brain Segmentation | T1 MPRAGE')
        segmentation.clicked.connect(dialog.accept)
        layout.addWidget(segmentation)
        lesions = QPushButton('White-matter Lesions | T1 + 3D FLAIR')
        selected = []
        lesions.clicked.connect(lambda: (selected.append('lesions'), dialog.accept()))
        layout.addWidget(lesions)
        layout.addWidget(QLabel('Lesion analysis requires the separate Eagle Eye LST-AI package.'))
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        if selected:
            from .lesion_widget import BrainLesionWidget
            from ..background_analysis import BackgroundAnalysisDialog
            popup = BackgroundAnalysisDialog(self)
            popup.setWindowTitle('Eagle Eye | White-matter lesions')
            popup.resize(900, 680)
            child = BrainLesionWidget(popup, study_uid=self.study_uid)
            child_layout = QVBoxLayout(popup)
            child_layout.addWidget(child)
            popup.bind_analysis(child)
            popup.show()
            child.start_study_segmentation()
            self._lesion_popup = popup
            return
        self.start_study_segmentation()

    def start_study_segmentation(self):
        """Continue an explicitly selected segmentation function with the series popup."""
        if self._future is not None or not self.study_uid:
            return
        from .study_workflow import load_study_series
        self._future_kind = 'series'
        self._cancel.clear()
        self._future = self._executor.submit(load_study_series, str(self.study_uid))
        self.run.setEnabled(False)
        self.regenerate.setEnabled(False)
        self.study_button.setEnabled(False)
        self.cancel.setEnabled(True)
        self.status.setText('Loading MRI series from the current examination...')
        self._begin_progress()

    def _apply_controlled_series(self, rows):
        inputs = getattr(self, '_control_inputs', None)
        if inputs is None: return False
        from .controlled_inputs import select_brain_inputs
        try:
            lesions = hasattr(self, 'primary_disease')
            first, second = select_brain_inputs(rows, inputs, lesions=lesions)
            if lesions:
                index = self.primary_disease.findData(inputs.get('clinical_context'))
                if index <= 0: raise ValueError('A supported clinical_context is required for lesion analysis.')
                self.primary_disease.setCurrentIndex(index)
            self._selected_series, self._selected_flair = first, second
            self._supplementary = []
            self.t1.setText(first['path'])
            self.flair.setText(second['path'] if second else '')
            self.confirm.setChecked(True)
            self._control_error = None
            self._load_demographics()
        except ValueError as error:
            self._control_error = str(error)
            self.status.setText(str(error))
        return True

    def _choose_t1_series(self, rows):
        if self._apply_controlled_series(rows): return
        dialog = QDialog(self)
        dialog.setWindowTitle('Select the 3D T1 MPRAGE series')
        dialog.resize(720, 420)
        layout = QVBoxLayout(dialog)
        label = QLabel('Choose one full-brain T1-weighted / MPRAGE series for segmentation. '
                       'Open or download unavailable series in the viewer, then try again.')
        label.setWordWrap(True)
        layout.addWidget(label)
        choices = QListWidget()
        for row in rows:
            state = '' if row['available'] else ' | Not downloaded'
            hint = ' | T1 candidate' if row['preferred'] else ''
            item = QListWidgetItem(f"Series {row['number']} | {row['description']} | {row['image_count']} images{hint}{state}")
            item.setData(Qt.UserRole, row)
            if not row['available']:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
            choices.addItem(item)
        layout.addWidget(choices)
        layout.addWidget(QLabel('Supplementary T1 series for independent consistency review (up to two)'))
        extra = QListWidget()
        extra.setObjectName('supplementaryT1')
        extra.setMaximumHeight(100)
        for row in rows:
            if row['available']:
                item = QListWidgetItem(f"Series {row['number']} | {row['description']}")
                item.setData(Qt.UserRole, row)
                item.setCheckState(Qt.Unchecked)
                extra.addItem(item)
        layout.addWidget(extra)
        layout.addWidget(QLabel('Optional 3D FLAIR from this examination (registration and review only)'))
        flair_choices = QComboBox()
        flair_choices.setObjectName('brainFlairSeries')
        flair_choices.addItem('No FLAIR selected', None)
        for row in rows:
            if row['available']:
                hint = ' | FLAIR candidate' if 'flair' in row['description'].lower() else ''
                flair_choices.addItem(f"Series {row['number']} | {row['description']} | {row['image_count']} images{hint}", row)
        layout.addWidget(flair_choices)
        verified = QCheckBox('I confirm all selected T1 series are full-brain 3D T1-weighted images, not T1 maps or FLAIR.')
        flair_verified = QCheckBox('I confirm the optional series is full-brain 3D FLAIR.')
        flair_verified.setObjectName('brainFlairConfirmed')
        layout.addWidget(verified)
        layout.addWidget(flair_verified)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Use selected images')
        buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        def update():
            primary = choices.currentItem().data(Qt.UserRole) if choices.currentItem() else None
            flair = flair_choices.currentData()
            valid_flair = not flair or (flair_verified.isChecked() and primary
                                        and flair['series_uid'] != primary['series_uid'])
            selected_extra = [extra.item(i).data(Qt.UserRole) for i in range(extra.count()) if extra.item(i).checkState() == Qt.Checked]
            ids = [r['series_uid'] for r in selected_extra]
            valid_extra = len(ids) <= 2 and primary and primary['series_uid'] not in ids and (not flair or flair['series_uid'] not in ids)
            buttons.button(QDialogButtonBox.Ok).setEnabled(bool(primary and verified.isChecked() and valid_flair and valid_extra))
        extra.itemChanged.connect(update)
        choices.itemSelectionChanged.connect(update)
        preferred_uid = getattr(self, 'preferred_series_uid', '')
        if preferred_uid:
            for index in range(choices.count()):
                item = choices.item(index)
                row = item.data(Qt.UserRole)
                if row['series_uid'] == preferred_uid and row['available']:
                    choices.setCurrentItem(item)
                    break
        flair_choices.currentIndexChanged.connect(update)
        flair_verified.toggled.connect(update)
        verified.toggled.connect(update)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            self.status.setText('Series selection cancelled. No analysis started.')
            return
        self._selected_series = dict(choices.currentItem().data(Qt.UserRole))
        self.t1.setText(self._selected_series['path'])
        self._selected_flair = dict(flair_choices.currentData()) if flair_choices.currentData() else None
        self.flair.setText(self._selected_flair['path'] if self._selected_flair else '')
        self._supplementary = [dict(extra.item(i).data(Qt.UserRole)) for i in range(extra.count()) if extra.item(i).checkState() == Qt.Checked]
        self.input_summary.setText(f'Primary T1 selected | {len(self._supplementary)} supplementary T1 series | FLAIR ' + ('selected' if self._selected_flair else 'not selected'))
        self.confirm.setChecked(True)
        self._load_demographics()

    def _load_demographics(self):
        from .patient_context import dicom_context
        self._apply_demographics({})
        self._result = None
        self.result_panel.hide()
        self.pdf.setEnabled(False)
        self.save_pdf.setEnabled(False)
        self.output.setEnabled(False)
        self._future_kind = 'demographics'
        self._cancel.clear()
        self.run.setEnabled(False)
        self.study_button.setEnabled(False)
        self.regenerate.setEnabled(False)
        self.status.setText('Reading patient details from the selected DICOM series...')
        self._future = self._executor.submit(dicom_context, self.t1.text())
        self._begin_progress()

    def _apply_demographics(self, context):
        age = context.get('age_years')
        self.age.setValue(age if age is not None else -1)
        self.age.setReadOnly(age is not None)
        sex = {'F': 'female', 'M': 'male'}.get(context.get('sex'), 'unknown')
        self.sex.setCurrentIndex(self.sex.findData(sex))
        self.sex.setEnabled(not bool(context.get('sex')))
        self.sex.setStyleSheet('QComboBox:disabled { color: #94a3b8; }')
        self.status.setText('Images selected. Review patient details, then click Run brain volumetry.')

    def _open_comparison(self):
        if self._result and self._result.get('t1_consistency_pdf'):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._result['t1_consistency_pdf']))

    def _save_pdf(self):
        if self._future is not None or not self._result or not self._result.get('pdf_available'):
            return
        destination, _ = QFileDialog.getSaveFileName(self, 'Save brain PDF report', 'Eagle-Eye-Brain.pdf', 'PDF report (*.pdf)')
        if not destination:
            return
        if not destination.lower().endswith('.pdf'):
            self.status.setText('Please save the report with a .pdf filename.')
            return
        from .study_workflow import export_pdf
        self._future_kind = 'export'
        self._future = self._executor.submit(export_pdf, dict(self._result), destination)
        self.save_pdf.setEnabled(False)
        self.run.setEnabled(False)
        self.regenerate.setEnabled(False)
        self.study_button.setEnabled(False)
        self.status.setText('Saving PDF report...')
        self._begin_progress()
