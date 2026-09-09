"""Lazy Eagle Eye Brain tab; all file/model/registration work runs off the GUI thread."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import queue
import threading

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QFileDialog, QComboBox, QCheckBox, QFrame, QApplication, QDoubleSpinBox,
                               QDialog, QDialogButtonBox, QListWidget, QListWidgetItem)

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
        self._future_kind = 'analysis'
        # Cleanup callbacks capture only worker-owned state, never a deleted widget.
        cancel, executor = self._cancel, self._executor
        self.destroyed.connect(lambda: (cancel.set(), executor.shutdown(wait=False, cancel_futures=True)))
        QApplication.instance().aboutToQuit.connect(cancel.set)
        layout = QVBoxLayout(self)
        title = QLabel("Eagle Eye Brain | Local volumetry")
        layout.addWidget(title)
        description = QLabel("Select a full-head 3D T1-weighted / MPRAGE and optional 3D FLAIR. "
                             "Outputs remain local and require segmentation review. "
                             "The report includes available age/sex reference intervals, regional volumes "
                             "and scientific references. Save the completed PDF to your chosen folder.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.study_button = QPushButton('Choose brain analysis and study series')
        self.study_button.setEnabled(bool(study_uid))
        self.study_button.clicked.connect(self.choose_study_workflow)
        layout.addWidget(self.study_button)
        self.t1 = self._source_row(layout, "3D T1-weighted")
        self.flair = self._source_row(layout, "3D FLAIR (optional)")
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
        note = QLabel("DICOM age and sex take precedence when available. For older completed jobs, select the original T1 DICOM series above to bind patient details.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.reference = QComboBox()
        for item in REFERENCES:
            self.reference.addItem(item.name, item.id)
        layout.addWidget(self.reference)
        self.reference_status = QLabel()
        self.reference_status.setWordWrap(True)
        layout.addWidget(self.reference_status)
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
        layout.addLayout(row)
        self.confirm = QCheckBox("I verified the selected images belong to the same examination, "
                                 "cover the full brain, and T1 is weighted imaging rather than a quantitative T1 map.")
        layout.addWidget(self.confirm)
        controls = QHBoxLayout()
        self.run = QPushButton("Run brain volumetry")
        self.run.clicked.connect(self._start)
        controls.addWidget(self.run)
        self.regenerate = QPushButton("Report from completed analysis")
        self.regenerate.clicked.connect(self._regenerate)
        controls.addWidget(self.regenerate)
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
        self.result_panel = QFrame()
        self.result_panel.setObjectName('brainResultPanel')
        self.result_panel.setStyleSheet(
            'QFrame#brainResultPanel { border: 1px solid #52718c; border-radius: 10px; }')
        result_layout = QVBoxLayout(self.result_panel)
        result_layout.setContentsMargins(20, 18, 20, 18)
        result_layout.setSpacing(14)
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
        self.status.setText("Preparing local analysis")
        # Snapshot all GUI state now. The worker never reads a widget or live PACS state.
        sources = self.t1.text().strip(), self.flair.text().strip()
        plan = BrainPlan(profile=self.profile.currentData())
        demographics = self._demographics()
        reference_id = self.reference.currentData()
        cancel, messages = self._cancel, self._messages
        study_uid = self.study_uid
        selected = dict(self._selected_series) if self._selected_series else None
        def execute():
            from PacsClient.utils.data_paths import AI_DIR
            from .service import run_analysis
            from .study_workflow import run_study_analysis, patient_output_root
            root = Path(AI_DIR) / 'eagle_eye'
            if study_uid:
                return run_study_analysis(sources[0], study_uid, selected['series_uid'], root=root,
                                          plan=plan, cancel=cancel, progress=messages.put,
                                          demographics=demographics, reference_id=reference_id)
            from .patient_context import dicom_context
            context = dicom_context(sources[0])
            output_root = patient_output_root(root, context) if context.get('study_uid') else root/'brain'/'unidentified'
            return run_analysis(*sources, output_root, plan=plan,
                                cancel=cancel, progress=messages.put, demographics=demographics,
                                reference_id=reference_id)
        self._future = self._executor.submit(execute)
        self.timer.start()

    def _poll(self):
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
        except BrainError as exc:
            self.status.setText(str(exc))
        except Exception:
            if self._future_kind == 'export':
                self.status.setText('Could not save the PDF. Close any open destination file or choose another folder and retry.')
            elif self._future_kind == 'series':
                self.status.setText('Could not load this examination\'s series. Open the study and try again.')
            else:
                self.status.setText("Analysis failed. Verify image geometry, model installation and available memory.")
        else:
            if self._future_kind == 'series':
                if not self._cancel.is_set():
                    self._choose_t1_series(result)
                return
            if self._future_kind == 'export':
                self.status.setText('PDF report saved to your selected location.')
                self.save_pdf.setEnabled(True)
                return
            self._result = result
            self.report.setText(
                '<h2>Ready for review</h2>'
                '<p><b>Brain volumetry report</b> &nbsp; | &nbsp; '
                + str(len(result.get('posterior_rows', []))) + ' volume measurements</p>'
                '<p>Global volumes &bull; White matter &bull; Cortex and lobes &bull; CSF<br>'
                'Basal ganglia &bull; Deep gray matter &bull; Brainstem &bull; Cerebellum &bull; Medial temporal</p>'
                '<p>Open the complete PDF for measurements, available reference ranges and image review. '
                'The report requires radiologist review before patient release.</p>')
            self.result_panel.show()
            reference_status = ("Published volBrain reference intervals are included."
                                if result.get('normative', {}).get('status') == 'published_intervals'
                                else "Published reference intervals are unavailable; review the report explanation.")
            self.status.setText("Report ready for review. " + reference_status)
            self.output.setEnabled(True)
            self.pdf.setEnabled(bool(result.get("pdf_available")))
            self.save_pdf.setEnabled(bool(result.get('pdf_available')))

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
        self.timer.start()

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
        lesions = QPushButton('Lesion Detection | Coming soon')
        lesions.setEnabled(False)
        layout.addWidget(lesions)
        layout.addWidget(QLabel('Lesion analysis with 3D T2 SPACE / FLAIR is planned and is not available yet.'))
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
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
        self.timer.start()

    def _choose_t1_series(self, rows):
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
        verified = QCheckBox('I confirm this is full-brain 3D T1-weighted imaging, not a T1 map or FLAIR.')
        layout.addWidget(verified)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Run segmentation')
        buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        def update():
            buttons.button(QDialogButtonBox.Ok).setEnabled(bool(choices.currentItem()) and verified.isChecked())
        choices.itemSelectionChanged.connect(update)
        verified.toggled.connect(update)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            self.status.setText('Series selection cancelled. No analysis started.')
            return
        self._selected_series = dict(choices.currentItem().data(Qt.UserRole))
        self.t1.setText(self._selected_series['path'])
        self.flair.clear()
        self.confirm.setChecked(True)
        self._start()

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
        self.timer.start()
