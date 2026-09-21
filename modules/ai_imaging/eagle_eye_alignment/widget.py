"""Owned alignment review surface; all DICOM/model/export I/O is off-thread."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QColor, QImage, QPixmap, QPen, QPainter, QDesktopServices
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,
    QCheckBox,QFileDialog,QDoubleSpinBox,QTableWidget,QTableWidgetItem,QGraphicsView,
    QGraphicsScene,QGraphicsEllipseItem,QGraphicsItem,QSplitter,QLineEdit,QHeaderView)

from .geometry import LANDMARKS,MEASUREMENT_LABELS,measure_bilateral
from . import service
from .references import reference_text, scope_text


class LandmarkItem(QGraphicsEllipseItem):
    def __init__(self,side,key,point,color,view):
        super().__init__(-5,-5,10,10)
        self.side,self.key,self.view=side,key,view
        self.setBrush(QColor(color));self.setPen(QPen(Qt.white,1))
        self.setFlags(QGraphicsItem.ItemIsMovable|QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(3);self.setToolTip(f'{side}: {key.replace("_"," ")}')
        self.setPos(*point)

    def mouseReleaseEvent(self,event):
        super().mouseReleaseEvent(event)
        rect=self.scene().sceneRect();p=self.pos()
        self.setPos(max(0,min(p.x(),rect.width()-1)),max(0,min(p.y(),rect.height()-1)))
        self.view.pointChanged.emit(self.side,self.key,self.pos().x(),self.pos().y())


class AlignmentCanvas(QGraphicsView):
    pointChanged=Signal(str,str,float,float)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self));self.setBackgroundBrush(QColor('#080d16'))
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.manual_target=None;self.items_by_key={};self.lines=[]

    def load(self,pixels):
        self.scene().clear();self.items_by_key={};self.lines=[]
        a=np.ascontiguousarray(pixels);h,w=a.shape
        image=QImage(a.data,w,h,a.strides[0],QImage.Format_Grayscale8).copy()
        self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(0,0,w,h);self.fit()

    def fit(self):self.fitInView(self.sceneRect(),Qt.KeepAspectRatio)

    def wheelEvent(self,event):
        factor=1.2 if event.angleDelta().y()>0 else 1/1.2
        if .01 < self.transform().m11()*factor < 30:self.scale(factor,factor)
        event.accept()

    def mousePressEvent(self,event):
        if self.manual_target and event.button()==Qt.LeftButton and not isinstance(self.itemAt(event.pos()),LandmarkItem):
            p=self.mapToScene(event.pos())
            if self.sceneRect().contains(p):self.pointChanged.emit(*self.manual_target,p.x(),p.y())
            event.accept();return
        super().mousePressEvent(event)

    def set_points(self,points):
        for item in [*self.items_by_key.values(),*self.lines]:self.scene().removeItem(item)
        self.items_by_key={};self.lines=[]
        for side,color in (('R','#38bdf8'),('L','#fb923c')):
            p=points.get(side,{})
            for key,point in p.items():
                item=LandmarkItem(side,key,point,color,self)
                self.scene().addItem(item);self.items_by_key[side,key]=item
            ankle=None
            if 'ankle_lateral' in p and 'ankle_medial' in p:
                ankle=np.mean([p['ankle_lateral'],p['ankle_medial']],axis=0)
            pairs=[(p.get('hip'),p.get('knee')),(p.get('knee'),ankle),(p.get('hip'),ankle)]
            pairs.extend((p.get(prefix+'_lateral'),p.get(prefix+'_medial')) for prefix in ('femur','tibia','ankle'))
            for a,b in pairs:
                if a is not None and b is not None:
                    pen=QPen(QColor(color),1.5);pen.setCosmetic(True)
                    line=self.scene().addLine(*a,*b,pen);line.setZValue(1);self.lines.append(line)


class AlignmentWidget(QWidget):
    def __init__(self,parent=None,*,study_uid):
        super().__init__(parent)
        self.setObjectName('eagleEyeAlignmentView')
        self.study_uid=str(study_uid or '')
        self.image=None;self.points={'R':{},'L':{}};self.metrics=None;self.provenance={}
        self._file_rows=[];self.report_result=None
        self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='alignment')
        self._cancel=threading.Event();self._future=None;self._kind='';self._disposed=False
        cancel,executor=self._cancel,self._executor
        self.destroyed.connect(lambda *_:(cancel.set(),executor.shutdown(wait=False,cancel_futures=True)))
        layout=QVBoxLayout(self)
        heading=QLabel('Eagle Eye Alignment View');heading.setStyleSheet('font-size:22px;font-weight:600')
        layout.addWidget(heading)
        series_row=QHBoxLayout();layout.addLayout(series_row)
        series_row.addWidget(QLabel('Primary alignment series'))
        self.series=QComboBox();series_row.addWidget(self.series,1)
        self.series.currentIndexChanged.connect(self._series_changed)
        toolbar=QHBoxLayout();layout.addLayout(toolbar)
        self.scan=QPushButton('Find study images');self.files=QComboBox();self.files.setMinimumWidth(220)
        self.load=QPushButton('Load selected image');self.browse=QPushButton('Open DICOM')
        for widget in (self.scan,self.files,self.load,self.browse):toolbar.addWidget(widget)
        self.scan.clicked.connect(self.scan_study);self.load.clicked.connect(self.load_selected)
        self.browse.clicked.connect(self.browse_image)
        splitter=QSplitter();layout.addWidget(splitter,1)
        self.canvas=AlignmentCanvas();self.canvas.setMinimumSize(420,500);splitter.addWidget(self.canvas)
        panel=QWidget();panel.setMinimumWidth(490);controls=QVBoxLayout(panel);splitter.addWidget(panel);splitter.setStretchFactor(0,2)
        self.confirm=QCheckBox('Standing AP, complete hips-to-ankles;\npatient right is on image left.')
        controls.addWidget(self.confirm)
        orientation=QHBoxLayout();controls.addLayout(orientation)
        self.flip=QPushButton('Flip horizontally');fit=QPushButton('Fit image')
        orientation.addWidget(self.flip);orientation.addWidget(fit)
        self.flip.clicked.connect(self.flip_image);fit.clicked.connect(self.canvas.fit)
        runrow=QHBoxLayout();controls.addLayout(runrow)
        self.run=QPushButton('Suggest landmarks with AI');self.cancel=QPushButton('Cancel')
        runrow.addWidget(self.run);runrow.addWidget(self.cancel)
        self.run.clicked.connect(self.start_ai);self.cancel.clicked.connect(self._cancel.set)
        self.manual=QComboBox();self.manual.addItem('Pan / drag existing points',None)
        for side in ('R','L'):
            for key in LANDMARKS:self.manual.addItem(f'{side} | {key.replace("_"," ")}',(side,key))
        controls.addWidget(QLabel('Manual placement: choose a point, then click its location.'))
        controls.addWidget(self.manual);self.manual.currentIndexChanged.connect(self._manual_changed)
        self.canvas.pointChanged.connect(self._point_changed)
        self.spacing_label=QLabel('Load a full-length DICOM image.');self.spacing_label.setWordWrap(True)
        controls.addWidget(self.spacing_label)
        calibration=QHBoxLayout();controls.addLayout(calibration)
        self.row_spacing=QDoubleSpinBox();self.col_spacing=QDoubleSpinBox()
        for spin in (self.row_spacing,self.col_spacing):spin.setDecimals(6);spin.setRange(.000001,100);spin.setValue(1.)
        calibration.addWidget(QLabel('Row mm/px'));calibration.addWidget(self.row_spacing)
        calibration.addWidget(QLabel('Column mm/px'));calibration.addWidget(self.col_spacing)
        self.calibrated=QCheckBox('Verified patient-plane scale (DICOM or known-length marker).')
        controls.addWidget(self.calibrated)
        self.calibrated.toggled.connect(self._calibration_changed)
        self.row_spacing.valueChanged.connect(self._calibration_changed);self.col_spacing.valueChanged.connect(self._calibration_changed)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Measurement','Right','Left','Adult reference / context'])
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers);controls.addWidget(self.table,1)
        self.summary=QLabel('HKA: negative varus / positive valgus. MAD: positive medial.');self.summary.setWordWrap(True)
        controls.addWidget(self.summary)
        self.review=QCheckBox('I reviewed all landmarks, orientation and calibration.');controls.addWidget(self.review)
        self.indication=QLineEdit();self.comparison=QLineEdit();self.impression=QLineEdit()
        for edit,label in ((self.indication,'Clinical indication'),(self.comparison,'Comparison'),(self.impression,'Clinician impression')):
            edit.setPlaceholderText(label+' (optional)');edit.setMaxLength(500);controls.addWidget(edit)
            edit.textChanged.connect(self._invalidate_review)
        self.export=QPushButton('Generate reviewed PDF report');controls.addWidget(self.export)
        report_row=QHBoxLayout();controls.addLayout(report_row)
        self.open_pdf=QPushButton('Open PDF');self.save_pdf=QPushButton('Save PDF copy')
        report_row.addWidget(self.open_pdf);report_row.addWidget(self.save_pdf)
        self.open_pdf.clicked.connect(self._open_pdf);self.save_pdf.clicked.connect(self._save_pdf)
        self.export.clicked.connect(self.save_report);self.review.toggled.connect(self._refresh_controls)
        self.confirm.toggled.connect(self._invalidate_review)
        self.status=QLabel('Select an image from this examination.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self._timer=QTimer(self);self._timer.setInterval(100);self._timer.timeout.connect(self._poll)
        self._refresh_controls()

    def _submit(self,kind,fn,*args):
        if self._future is not None or self._disposed:return
        self._kind=kind;self._cancel.clear();self._future=self._executor.submit(fn,*args)
        self._timer.start();self._refresh_controls()

    def scan_study(self):
        self.status.setText('Finding local images from this examination...')
        self._submit('scan',service.study_images,self.study_uid)

    def _series_changed(self):
        self.image=None;self.points={'R':{},'L':{}};self.metrics=None;self.report_result=None
        self.provenance={};self.table.setRowCount(0);self.canvas.scene().clear()
        self.canvas.items_by_key={};self.canvas.lines=[]
        self.confirm.setChecked(False);self.review.setChecked(False)
        self.summary.setText('Select the complete alignment image from the primary series.')
        self.files.clear()
        for row in self._file_rows:
            if row['series_uid']==self.series.currentData():self.files.addItem(row['label'],row['path'])
        self._refresh_controls()

    def load_selected(self):
        path=self.files.currentData()
        if path:self._load_path(path)

    def browse_image(self):
        path,_=QFileDialog.getOpenFileName(self,'Select alignment DICOM','','DICOM (*.dcm *.dicom);;All files (*)')
        if path:self._load_path(path)

    def _load_path(self,path):
        self.review.setChecked(False)
        self.status.setText('Reading DICOM pixels and calibration...')
        self._submit('load',service.load_image,path,self.study_uid,self.series.currentData())

    def _apply_image(self,image):
        self.image=image;self.points={'R':{},'L':{}};self.provenance={};self.metrics=None
        self.report_result=None;self.summary.setText('Review orientation, then locate the landmarks.')
        self.confirm.setChecked(False);self.review.setChecked(False)
        for spin,value in zip((self.row_spacing,self.col_spacing),image['spacing']):
            spin.blockSignals(True);spin.setValue(value);spin.blockSignals(False)
        self.calibrated.blockSignals(True);self.calibrated.setChecked(image['calibrated']);self.calibrated.blockSignals(False)
        self.spacing_label.setText(image['calibration_method'])
        self.canvas.load(image['pixels']);self.table.setRowCount(0)
        self.status.setText('Verify upright orientation and complete coverage, then suggest or place landmarks.')
        self._refresh_controls()

    def flip_image(self):
        if self.image is None or self._future is not None:return
        image=dict(self.image);image['pixels']=np.ascontiguousarray(image['pixels'][:,::-1])
        image['flipped']=not image.get('flipped',False);self._apply_image(image)

    def start_ai(self, *, automatic=False):
        if self.image is None or (not automatic and not self.confirm.isChecked()):return
        self.review.setChecked(False);self.status.setText('Local AI is locating hip, knee and ankle landmarks...')
        self._submit('ai',service.predict,dict(self.image),self._cancel)

    def _manual_changed(self):self.canvas.manual_target=self.manual.currentData()

    def _point_changed(self,side,key,x,y):
        if self.image is None or self._future is not None:return
        self.points[side][key]=[x,y];self.provenance['manually_edited']=True
        # Defer scene replacement until the current mouse event returns.
        QTimer.singleShot(0,self._redraw_points)

    def _redraw_points(self):
        if self._disposed:return
        self.canvas.set_points(self.points);self._recalculate()

    def _invalidate_review(self):
        self.report_result=None;self.review.setChecked(False);self._refresh_controls()

    def _calibration_changed(self):
        if self.image is None:return
        self.image['spacing']=(self.row_spacing.value(),self.col_spacing.value())
        self.image['calibrated']=self.calibrated.isChecked()
        self.image['calibration_method']='Operator-verified patient-plane scale' if self.image['calibrated'] else 'Unverified scale; lengths in pixels'
        self._recalculate()

    def _recalculate(self):
        self.report_result=None;self.review.setChecked(False);self.metrics=None;self.table.setRowCount(0)
        try:
            service.validate_points(self.points,self.image['pixels'].shape)
            self.metrics=measure_bilateral(self.points,self.image['spacing'],calibrated=self.image['calibrated'])
        except (ValueError,KeyError,TypeError) as error:
            self.status.setText(str(error) if isinstance(error,ValueError) else 'Place all eight landmarks on each leg.')
            self._refresh_controls();return
        rows=[k for k in self.metrics['R'] if k!='length_unit'];self.table.setRowCount(len(rows))
        for row,key in enumerate(rows):
            unit='deg' if key.endswith('_deg') else self.metrics['R']['length_unit']
            self.table.setItem(row,0,QTableWidgetItem(MEASUREMENT_LABELS[key]+' ('+unit+')'))
            for col,side in enumerate(('R','L'),1):self.table.setItem(row,col,QTableWidgetItem(f'{self.metrics[side][key]:.2f}'))
            item=QTableWidgetItem(reference_text(key,self.image));item.setToolTip(scope_text(self.image))
            self.table.setItem(row,3,item)
        for column,width in ((0,145),(1,54),(2,54)):self.table.setColumnWidth(column,width)
        self.table.resizeRowsToContents()
        shorter={'R':'Right shorter','L':'Left shorter','equal':'Equal projected lengths'}[self.metrics['shorter_side']]
        self.summary.setText(f"Right minus left projected length: {self.metrics['lld']:.2f} {self.metrics['R']['length_unit']}.\n"
                             f"Relative difference: {self.metrics['lld_percent']:.2f}% ({shorter}).\n"
                             '100 x absolute difference / longer limb; pixel-aspect corrected. Assumes common magnification.\n'
                             +reference_text('lld_percent',self.image)+'.\n'
                             'HKA: negative varus / positive valgus. MAD: positive medial. JLCA: unsigned.\n'+scope_text(self.image))
        self.status.setText('Review the landmarks. Drag a point to correct it; the measurements update on release.')
        self._refresh_controls()

    def save_report(self):
        if self.metrics is None or not self.review.isChecked() or not self.confirm.isChecked():return
        self._generate_pdf(landmarks_reviewed=True)

    def _generate_pdf(self,landmarks_reviewed=False):
        from .report import generate_report
        notes=dict(indication=self.indication.text(),comparison=self.comparison.text(),impression=self.impression.text())
        provenance=deepcopy(self.provenance);provenance['acquisition_reviewed']=self.confirm.isChecked()
        self.status.setText('Generating the three-page Alignment PDF...')
        self._submit('report',generate_report,deepcopy(self.image),deepcopy(self.points),provenance,notes,landmarks_reviewed)

    def _open_pdf(self):
        if self.report_result:
            from pathlib import Path
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.report_result['artifact_directory'])/'report.pdf')))

    def _save_pdf(self):
        if not self.report_result:return
        from ..eagle_eye_brain.study_workflow import export_pdf
        path,_=QFileDialog.getSaveFileName(self,'Save Alignment PDF','Alignment-report.pdf','PDF report (*.pdf)')
        if not path:return
        if not path.lower().endswith('.pdf'):path+='.pdf'
        self._submit('export',export_pdf,deepcopy(self.report_result),path)

    def _poll(self):
        if self._future is None or not self._future.done():return
        future,self._future=self._future,None;self._timer.stop()
        if self._disposed:return
        try:
            result=future.result()
            if self._cancel.is_set():self.status.setText('Operation cancelled.');return
            if self._kind=='scan':
                self._file_rows=result;self.series.blockSignals(True);self.series.clear()
                self.series.addItem('Choose the primary alignment series...',None)
                seen=set()
                for row in result:
                    if row['series_uid'] not in seen:
                        seen.add(row['series_uid']);self.series.addItem(row['series_label'],row['series_uid'])
                self.series.blockSignals(False);self._series_changed()
                self.status.setText(f'{len(seen)} local series available. Assign the primary alignment series.')
                uid = getattr(self, 'preferred_series_uid', '')
                if uid:
                    index = self.series.findData(uid)
                    if index < 0:
                        self.status.setText('The selected series is not available locally. Load it in the viewer and retry.')
                    else:
                        self.series.setCurrentIndex(index)
                        if self.files.count() == 1:
                            self.load_selected()
            elif self._kind=='load':
                self._apply_image(result)
                uid = getattr(self, 'preferred_series_uid', '')
                if uid and result.get('identity', {}).get('series_uid') == uid:
                    self.start_ai(automatic=True)
            elif self._kind=='ai':
                self.points=result['landmarks'];self.provenance={k:v for k,v in result.items() if k!='landmarks'}
                self.provenance['initial_landmarks']=deepcopy(result['landmarks'])
                self._redraw_points()
                if self.metrics is not None:self._generate_pdf()
            elif self._kind=='report':
                self.report_result=result;self.status.setText('Three-page PDF ready. Open it to review or save a copy.')
            elif self._kind=='export':self.status.setText('PDF copy saved.')
        except Exception as error:
            self.status.setText(str(error) if isinstance(error,ValueError) else 'The operation failed. Check the image or destination and try again.')
        finally:self._refresh_controls()

    def _refresh_controls(self):
        busy=self._future is not None;loaded=self.image is not None
        for widget in (self.scan,self.series,self.files):widget.setEnabled(not busy)
        for widget in (self.load,self.browse):widget.setEnabled(not busy and self.series.currentData() is not None)
        for widget in (self.indication,self.comparison,self.impression):widget.setEnabled(loaded and not busy)
        for widget in (self.open_pdf,self.save_pdf):widget.setEnabled(self.report_result is not None and not busy)
        for widget in (self.flip,self.manual,self.row_spacing,self.col_spacing,self.calibrated,self.confirm,self.canvas):widget.setEnabled(loaded and not busy)
        self.run.setEnabled(loaded and not busy and self.confirm.isChecked())
        self.review.setEnabled(self.metrics is not None and not busy and self.confirm.isChecked())
        self.export.setEnabled(self.metrics is not None and not busy and self.review.isChecked() and self.confirm.isChecked())
        self.cancel.setEnabled(busy and self._kind!='export')

    def teardown(self):
        self._disposed=True;self._cancel.set();self._timer.stop()
        self._executor.shutdown(wait=False,cancel_futures=True)

    def hideEvent(self,event):
        if self._future is None or self._kind in ('scan', 'load'):
            self._cancel.set()
        super().hideEvent(event)
