"""Presentation and PDF export of immutable server marrow measurements."""
import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTabWidget, QTextBrowser, QTableWidget, QTableWidgetItem, QSlider,
    QHeaderView, QGraphicsView, QGraphicsScene, QSplitter, QPlainTextEdit)

from .lumbar_marrow import LIMITATION


def label_color(label):
    return ((int(label) * 97) % 200 + 55, (int(label) * 53) % 200 + 55, 90)


def report_html(result):
    if result.get('task') == 'lumbar_marrow_multiparametric_v1':
        from .marrow_multisequence_report import report_html as multiparametric_report
        return multiparametric_report(result)
    context_identity = result.get('patient_context', {})
    identity = ' | '.join(str(context_identity.get(k) or 'Not supplied') for k in ('patient_name', 'patient_id', 'study_date', 'accession')) if context_identity.get('study_uid') else 'Identity unavailable'
    rows = result.get('marrow_measurements', [])
    table = '<thead><tr><th>Level / color</th><th>ROI cm3</th><th>Voxels</th><th>Mean SI</th><th>Median SI</th><th>SD</th><th>Review</th></tr></thead>'
    for r in rows:
        color = '#%02x%02x%02x' % label_color(r['label'])
        values = [r['level'], number(r.get('sample_volume_mm3'), .001), str(r['sample_voxels']),
                  number(r.get('mean_si')), number(r.get('median_si')), number(r.get('std_si')), r['qc']]
        table += '<tr><td bgcolor="' + color + '">' + html.escape(values[0]) + '</td>'
        table += ''.join('<td>' + html.escape(v) + '</td>' for v in values[1:]) + '</tr>'
    context = ''.join('<li>' + html.escape(k.replace('_', ' ')) + ': ' + html.escape(str(v)) + '</li>'
                      for k, v in result.get('clinical_context', {}).items())
    preview = result.get('preview')
    image = '<p><img src="' + html.escape(Path(preview).as_uri()) + '" width="440"></p>' if preview and Path(preview).is_file() else ''
    return ('<html><head><meta name="brain-patient" content="' + html.escape(identity, quote=True) + '"><style>body{font-family:Arial;font-size:11pt;} th{background:#e2e8f0;} '
            'td,th{padding:8px;} table{border-collapse:collapse;}</style></head><body>'
            '<h1>Lumbar Bone Marrow</h1><h2>Experimental T1 signal assessment</h2>'
            '<p>Report status: Research draft / physician review required.</p>'
            '<h3>Technique and sampling</h3><p>Native T1; whole-vertebra labels eroded by 2 mm; minimum 20 sampled voxels.</p>'
            '<table border="1" cellpadding="7" cellspacing="0">' + table + '</table>'
            '<h3>How to read these measurements</h3><p>SI = signal intensity in arbitrary units. Mean and median describe the sampled signal; '
            'SD describes its spread. ROI volume is the sampled region, not red marrow volume. Colors identify vertebral levels and do not grade disease. '
            'Unreviewed means sampling boundaries require physician review; insufficient sample means no reliable statistics were calculated.</p>'
            '<h3>Physician-entered context</h3><ul>' + (context or '<li>Not provided</li>') + '</ul>'
            '<h3>Physician review notes</h3><p>' + html.escape(result.get('physician_notes', '') or 'Not entered').replace('\n', '<br>') + '</p>'
            '<h3>Limitations</h3><p>' + html.escape(LIMITATION) + '</p>' + image + '</body></html>')


def number(value, scale=1):
    return '—' if value is None else f'{value * scale:,.2f}'


def save_pdf(result, path):
    from .eagle_eye_brain.organized_report import write_paged_pdf
    write_paged_pdf(report_html(result), path, title='AI-PACS | Lumbar Bone Marrow | Research draft',
                    heading='AI-PACS | EAGLE EYE LUMBAR BONE MARROW')
    return str(path)


class MarrowReview(QWidget):
    exportRequested = Signal()
    editRequested = Signal()
    recalculateRequested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        for text, signal in [('Save PDF report...', self.exportRequested), ('Edit segmentation in 3D Slicer', self.editRequested),
                             ('Recalculate saved correction on server', self.recalculateRequested)]:
            button = QPushButton(text)
            button.clicked.connect(signal.emit)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.status = QLabel('Research draft / physician review required')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        page = QWidget()
        tab_layout = QVBoxLayout(page)
        splitter = QSplitter(Qt.Horizontal)
        tab_layout.addWidget(splitter, 1)
        image_page = QWidget()
        image_layout = QVBoxLayout(image_page)
        controls = QHBoxLayout()
        self.scene = QGraphicsScene(self)
        self.image = QGraphicsView(self.scene)
        self.image.setDragMode(QGraphicsView.ScrollHandDrag)
        for text, callback in [('Fit', self.fit), ('Zoom +', lambda: self.image.scale(1.25, 1.25)),
                               ('Zoom −', lambda: self.image.scale(.8, .8)), ('100%', self.image.resetTransform)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            controls.addWidget(button)
        image_layout.addLayout(controls)
        self.slice_slider = QSlider(Qt.Horizontal)
        self.slice_slider.setObjectName('marrowSliceSlider')
        self.slice_slider.valueChanged.connect(self.show_slice)
        self.slice_slider.hide()
        image_layout.addWidget(self.slice_slider)
        image_layout.addWidget(self.image, 1)
        self.image.setToolTip('Sagittal sampling preview. Zoom and drag to inspect; scrollbars pan the image. Use Slicer for all slices.')
        splitter.addWidget(image_page)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Level / color', 'ROI (cm³)', 'Voxels', 'Mean SI', 'Median SI', 'SD', 'QC'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setMinimumSectionSize(90)
        self.table.setStyleSheet('QHeaderView::section { padding: 8px; } QTableWidget::item { padding: 6px; }')
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        splitter.addWidget(self.table)
        splitter.setSizes([700, 700])
        self.explanation = QLabel('SI: arbitrary signal units. ROI: sampled volume after 2 mm erosion, not red marrow volume. '
                             'SD: signal spread. Colors identify L1–L5, not disease severity. Unreviewed: boundaries need inspection.')
        self.explanation.setWordWrap(True)
        tab_layout.addWidget(self.explanation)
        tabs.addTab(page, 'Image and measurements')
        self.report = QTextBrowser()
        tabs.addTab(self.report, 'Structured report')
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText('Optional physician findings, sampling concerns and comparison notes for PDF. These do not change computed measurements or approve the report.')
        tabs.addTab(self.notes, 'Physician notes')

    def showEvent(self, event):
        super().showEvent(event)
        self.fit()

    def fit(self):
        self.image.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def show_result(self, result):
        self._slice_previews = result.get('slice_previews', [])
        self.slice_slider.blockSignals(True)
        self.slice_slider.setRange(0, max(0, len(self._slice_previews)-1))
        self.slice_slider.setValue(len(self._slice_previews)//2)
        self.slice_slider.blockSignals(False)
        self.slice_slider.setVisible(bool(self._slice_previews))
        self.scene.clear()
        if result.get('preview'):
            self.scene.addPixmap(QPixmap(result['preview']))
            self.scene.setSceneRect(self.scene.itemsBoundingRect())
        rows = result.get('marrow_measurements', [])
        multi = result.get('task') == 'lumbar_marrow_multiparametric_v1'
        drop = result.get('map_kind') == 'in_opposed_signal_drop'
        prefix = 'signal_drop' if drop else 'signal_ff'
        if multi:
            self.table.setHorizontalHeaderLabels(['Level', 'Body (cm³)', 'ROI (cm³)', 'Signal drop (%)' if drop else 'Signal FF (%)', 'P10 (%)', 'P90 (%)', 'QC'])
            self.explanation.setText(('Purple to yellow: low to high signed signal drop; not fat fraction. Display colors saturate at 0-100%. ' if drop else 'Purple to yellow: low to high fat-signal ratio, 0-100%. ')+
                                     'Table values use the 2 mm body interior across all slices. This signal map does not classify edema, tumor or red marrow. Optional echo results apply only to acquired planes.')
        else:
            self.table.setHorizontalHeaderLabels(['Level / color', 'ROI (cm³)', 'Voxels', 'Mean SI', 'Median SI', 'SD', 'QC'])
            self.explanation.setText('SI: arbitrary signal units. ROI: sampled volume after 2 mm erosion, not red marrow volume. SD: signal spread. Colors identify L1–L5, not disease severity. Unreviewed: boundaries need inspection.')
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [r['level'], number(r.get('sample_volume_mm3'), .001), f"{r['sample_voxels']:,}",
                      number(r.get('mean_si')), number(r.get('median_si')), number(r.get('std_si')), r['qc']]
            if multi:
                values = [r['level'], number(r.get('body_volume_mm3'), .001), number(r.get('sample_volume_mm3'), .001),
                          number(r.get(prefix+'_median_percent')), number(r.get(prefix+'_p10_percent')),
                          number(r.get(prefix+'_p90_percent')), r['qc']]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                if j == 0 and not multi:
                    item.setBackground(QBrush(QColor(*label_color(r['label']))))
                    item.setForeground(QBrush(QColor('black')))
                self.table.setItem(i, j, item)
        self.report.setHtml(report_html(result))
        self.fit()

    def show_slice(self, index):
        paths = getattr(self, '_slice_previews', [])
        if 0 <= index < len(paths):
            self.scene.clear()
            self.scene.addPixmap(QPixmap(paths[index]))
            self.scene.setSceneRect(self.scene.itemsBoundingRect())
            self.image.setToolTip(f'Dixon slice {index+1} / {len(paths)}. Purple to yellow: low to high fat signal; not a tissue diagnosis.')
            self.fit()
