"""Study-owned panoramic review; filesystem/network/model work stays on one worker."""
from concurrent.futures import ThreadPoolExecutor
import threading
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QCheckBox, QTableWidget, QTableWidgetItem, QDoubleSpinBox)
from . import dental_panorama as service


class DentalPanoramaWidget(QWidget):
    def __init__(self, parent=None, *, study_uid):
        super().__init__(parent)
        self.study_uid = study_uid
        self.image = None
        self.result = None
        self._future = None
        self._cancel = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='DentalPanorama')
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(service.LIMITATION))
        controls = QHBoxLayout(); layout.addLayout(controls)
        self.files = QComboBox(); controls.addWidget(self.files)
        self.scan = QPushButton('Refresh study images'); controls.addWidget(self.scan)
        self.load = QPushButton('Load selected'); controls.addWidget(self.load)
        self.browse = QPushButton('Select DICOM'); controls.addWidget(self.browse)
        self.confirm = QCheckBox('I confirm this is a complete panoramic dental image')
        layout.addWidget(self.confirm)
        self.run = QPushButton('Analyze Panoramic | Eagle Eye Server'); layout.addWidget(self.run)
        self.status = QLabel('Select one panoramic DICOM image from this study.'); layout.addWidget(self.status)
        self.preview = QLabel(); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumHeight(180)
        layout.addWidget(self.preview)
        filter_row = QHBoxLayout(); layout.addLayout(filter_row)
        filter_row.addWidget(QLabel('Display score cutoff (not a diagnostic threshold)'))
        self.cutoff = QDoubleSpinBox(); self.cutoff.setRange(0, 1); self.cutoff.setSingleStep(.05); self.cutoff.setValue(.5)
        filter_row.addWidget(self.cutoff)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(['FDI tooth', 'Candidate finding', 'Model score'])
        layout.addWidget(self.table)
        self.scan.clicked.connect(self.scan_study)
        self.load.clicked.connect(lambda: self.load_path(self.files.currentData()))
        self.browse.clicked.connect(self.browse_image)
        self.run.clicked.connect(self.start_analysis)
        self.confirm.toggled.connect(self.refresh)
        self.cutoff.valueChanged.connect(self.render_results)
        self._timer = QTimer(self); self._timer.setInterval(100); self._timer.timeout.connect(self.poll)
        self.refresh()

    def refresh(self):
        busy = self._future is not None
        for control in (self.files, self.scan, self.load, self.browse, self.confirm):
            control.setEnabled(not busy)
        self.run.setEnabled(not busy and self.image is not None and self.confirm.isChecked())

    def submit(self, kind, fn, *args):
        if self._future is not None:
            return
        self._kind = kind
        self._cancel.clear()
        self._future = self._executor.submit(fn, *args)
        self._timer.start(); self.refresh()

    def scan_study(self):
        self.submit('scan', service.study_images, self.study_uid)

    def browse_image(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select panoramic DICOM', '', 'DICOM (*.dcm *.dicom);;All files (*)')
        if path:
            self.load_path(path)

    def load_path(self, path):
        if path:
            self.result = None; self.table.setRowCount(0); self.confirm.setChecked(False)
            self.image = None; self.status.setText('Reading selected panoramic image...')
            self.submit('load', service.load_image, path, self.study_uid)

    def start_analysis(self):
        if self.image is not None and self.confirm.isChecked() and self._future is None:
            self.result = None; self.table.setRowCount(0)
            self.status.setText('Analyzing on Eagle Eye Server. Results require physician review...')
            self.submit('analyze', service.analyze, self.image, self._cancel)

    def poll(self):
        if self._future is None or not self._future.done():
            return
        future, self._future = self._future, None
        self._timer.stop()
        try:
            value = future.result()
            if self._kind == 'scan':
                self.files.clear()
                for row in value:
                    self.files.addItem(row['label'], row['path'])
                self.status.setText(f'{len(value)} study images available. Select the panoramic image.')
            elif self._kind in ('load', 'saved'):
                if self._kind == 'load':
                    self.image = value
                a = value['pixels']; h, w = a.shape
                display = QImage(a.data, w, h, a.strides[0], QImage.Format_Grayscale8).copy()
                self.preview.setPixmap(QPixmap.fromImage(display).scaled(1000, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                if self._kind == 'saved':
                    self.result = value['result']; self.render_results()
                else:
                    self.status.setText('Image ready. Confirm panoramic acquisition, then click Analyze.')
            else:
                self.result = value; self.render_results()
        except Exception as exc:
            self.status.setText(str(exc))
        self.refresh()

    def restore_saved_result(self, result):
        self.image = None
        self.result = None
        self.table.setRowCount(0)
        self.submit('saved', service.load_saved, result, self.study_uid)

    def render_results(self):
        if self.result is None:
            return
        rows = [r for r in self.result['dental_scores'] if r['score'] >= self.cutoff.value()]
        rows.sort(key=lambda r: (int(r['fdi']), -r['score']))
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, text in enumerate((row['fdi'], row['finding'].replace('_', ' '), f"{row['score']:.4f}")):
                self.table.setItem(i, j, QTableWidgetItem(text))
        self.status.setText(f'Research draft: {len(rows)} entries above display cutoff; 256 scores returned. '
                            'Lower scores do not establish a normal tooth. Physician review pending.')

    def teardown(self):
        self._cancel.set(); self._timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
