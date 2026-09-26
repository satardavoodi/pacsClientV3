"""Independent native review surface; file, inference and report I/O stay off Qt."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import partial
from pathlib import Path
import threading
import logging

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPen, QDesktopServices, QTransform
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QTabWidget, QSplitter, QTableWidget, QTableWidgetItem,
    QFileDialog, QDoubleSpinBox, QLineEdit, QScrollArea, QGraphicsItem, QHeaderView,
    QDialog, QDialogButtonBox, QToolButton, QSizePolicy, QInputDialog, QProgressBar)

from ..eagle_eye_alignment.widget import AlignmentCanvas, LandmarkItem
from .geometry import LEVELS, CORNERS, rotation_record
from .measurements import measure_view, validate_report_views
from . import service
from .editing import EditableSegment, SegmentEndpoint, LevelBadge, level_mapping, CandidateBody

logger = logging.getLogger(__name__)


class SpineCanvas(AlignmentCanvas):
    segmentChanged = Signal(str, str, object)
    levelRequested = Signal(str)
    candidateChanged = Signal(int, object)
    regionChanged = Signal(object)

    def fit(self):
        self.setTransform(QTransform.fromScale(getattr(self, 'pixel_aspect', 1.), 1.))
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        # Measurement labels must not swallow the larger segment hit target.
        interactive = next((item for item in self.items(event.position().toPoint())
                            if isinstance(item, (LandmarkItem, EditableSegment, LevelBadge, CandidateBody))), None)
        if interactive is not None:
            target = self.manual_target; self.manual_target = None
            super().mousePressEvent(event); self.manual_target = target
        else:
            super().mousePressEvent(event)

    def measurement_overlay(self, view=None, measured=None):
        for item in getattr(self, '_measurement_items', []):
            if item.scene() is self.scene(): self.scene().removeItem(item)
        self._measurement_items = []
        if view is None: return
        from .annotations import overlay_primitives
        overlay = overlay_primitives(view, measured)
        for line in overlay['lines']:
            pen = QPen(QColor(line['color']), 1 if line['dashed'] else 2)
            pen.setCosmetic(True)
            if line['dashed']: pen.setStyle(Qt.DashLine)
            a, b = line['points']
            item = self.scene().addLine(*a, *b, pen)
            item.setAcceptedMouseButtons(Qt.NoButton)
            self._measurement_items.append(item)
        for label in overlay['labels']:
            item = self.scene().addSimpleText(label['text'])
            item.setBrush(QColor(label['color'])); item.setPos(*label['at'])
            item.setFlag(QGraphicsItem.ItemIgnoresTransformations); item.setZValue(5)
            item.setAcceptedMouseButtons(Qt.NoButton)
            self._measurement_items.append(item)

    def set_points(self, points, markers=None, pedicles=None):
        for item in [*self.items_by_key.values(), *self.lines]:
            self.scene().removeItem(item)
        self.items_by_key = {}; self.lines = []
        for level, corners in points.items():
            for key, value in corners.items():
                item = SegmentEndpoint(level, key, value, '#38bdf8' if key.startswith('superior') else '#fbbf24', self)
                self.scene().addItem(item); self.items_by_key[level, key] = item
            for a, b in ((CORNERS[0], CORNERS[1]), (CORNERS[2], CORNERS[3])):
                if a in corners and b in corners:
                    color = '#38bdf8' if a.startswith('superior') else '#fbbf24'
                    segment = EditableSegment(level, a.split('_')[0],
                        [self.items_by_key[level, a], self.items_by_key[level, b]], color, self)
                    self.scene().addItem(segment); self.lines.append(segment)
                    label = self.scene().addSimpleText(level+' '+a.split('_')[0])
                    label.setBrush(QColor(color)); label.setPos(*corners[a])
                    label.setFlag(QGraphicsItem.ItemIgnoresTransformations); label.setZValue(4)
                    label.setAcceptedMouseButtons(Qt.NoButton)
                    self.lines.append(label)
            if all(key in corners for key in CORNERS):
                at = [sum(corners[key][axis] for key in CORNERS)/4 for axis in (0, 1)]
                badge = LevelBadge(level, at, self); self.scene().addItem(badge); self.lines.append(badge)
        for level, evidence in (pedicles or {}).items():
            for key, value in evidence.items():
                item = LandmarkItem('pedicle:'+level, key, value, '#f472b6', self)
                self.scene().addItem(item); self.items_by_key['pedicle:'+level, key] = item
        for name, value in (markers or {}).items():
            item = LandmarkItem('balance', name, value, '#fbbf24', self)
            self.scene().addItem(item); self.items_by_key['balance', name] = item
            pen = QPen(QColor('#fbbf24'), 1); pen.setCosmetic(True)
            self.lines.append(self.scene().addLine(value[0], 0, value[0], self.sceneRect().height(), pen))


def combo(items, selected=None):
    widget = QComboBox(); widget.addItems(items)
    if selected is not None:
        widget.setCurrentText(selected)
    return widget


class ProjectionEditor(QWidget):
    changed = Signal()
    loadRequested = Signal(object)
    aiRequested = Signal(object)
    regionReady = Signal()

    def __init__(self, projection, parent=None):
        super().__init__(parent)
        self.projection = projection
        self.image = None; self.points = {}; self.markers = {}; self.curves = []; self.rotations = []
        self.provenance = {}; self._rows = []; self.pedicles = {}; self._undo = []
        self.region = None; self._region_start = None; self._region_item = None; self._region_handles = []
        self.candidates = []; self._candidate_lines = []; self.automatic_pair = None
        layout = QVBoxLayout(self)
        top = QHBoxLayout(); layout.addLayout(top)
        self.series = QComboBox(); self.files = QComboBox()
        self.load = QPushButton('Load selected image')
        clear = QPushButton('Clear projection')
        for w in (self.series, self.files, self.load, clear): top.addWidget(w)
        clear.clicked.connect(self.clear_image)
        self.series.currentIndexChanged.connect(self._series_changed)
        self.files.currentIndexChanged.connect(self.clear_image)
        self.load.clicked.connect(lambda: self.loadRequested.emit(self))
        split = QSplitter(); layout.addWidget(split, 1)
        self.canvas = SpineCanvas(); self.canvas.setMinimumSize(360, 440); split.addWidget(self.canvas)
        self.canvas.pointChanged.connect(self._point_changed)
        self.canvas.segmentChanged.connect(self._segment_changed)
        self.canvas.levelRequested.connect(self._image_label_selected)
        self.canvas.candidateChanged.connect(self._candidate_changed)
        self.canvas.regionChanged.connect(self._set_region)
        panel = QWidget(); controls = QVBoxLayout(panel)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(panel)
        self.review_scroll = scroll
        scroll.setMinimumWidth(350); split.addWidget(scroll); split.setStretchFactor(0, 2)
        split.setSizes([1000, 380])
        root_controls = controls
        self.review_sections = {}
        def section(title, expanded=False):
            toggle = QToolButton(); toggle.setText(title); toggle.setCheckable(True)
            toggle.setChecked(expanded); toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            content = QWidget(); inner = QVBoxLayout(content)
            def change(checked):
                content.setVisible(checked)
                toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
            toggle.toggled.connect(change); change(expanded)
            root_controls.addWidget(toggle); root_controls.addWidget(content)
            self.review_sections[title] = (toggle, content)
            return inner
        controls = section('Acquisition and scale')
        self.confirm = QCheckBox('Standing acquisition verified')
        self.confirm.setToolTip('Check the original acquisition and stitching before measuring.')
        controls.addWidget(self.confirm); self.confirm.toggled.connect(self.invalidate)
        self.orientation = combo(['Patient right on image left', 'Patient right on image right'] if projection == 'coronal'
                                 else ['Anterior on image left', 'Anterior on image right'])
        controls.addWidget(self.orientation); self.orientation.currentIndexChanged.connect(self.invalidate)
        fit = QPushButton('Fit image'); controls.addWidget(fit); fit.clicked.connect(self.canvas.fit)
        controls = section('Detection and field of view')
        if projection == 'coronal':
            self.ai_model = combo(['Yi ISBI 2020', 'ScolioVis Keypoint R-CNN'])
            self.ai_model.setToolTip('Yi expects a complete T1-L5 region. ScolioVis may return a variable number of bodies. Neither model assigns anatomical levels.')
            controls.addWidget(self.ai_model)
            self.ai = QPushButton('Suggest vertebrae inside selected region')
            controls.addWidget(self.ai); self.ai.clicked.connect(lambda: self.aiRequested.emit(self))
            text = QLabel('Select the spine region first. AI detections remain unnumbered until you assign a candidate to a level. Every candidate needs review.')
            text.setWordWrap(True); controls.addWidget(text)
        else:
            self.ai = None
            text = QLabel('Use SAM on individual bodies or place lateral endplates manually. Place S1 manually.')
            text.setWordWrap(True); controls.addWidget(text)
        if projection == 'coronal':
            region_button = QPushButton('Select spine region (two opposite corners)')
            controls.addWidget(region_button); region_button.clicked.connect(self._select_region)
            region_help = QLabel('Coronal detector: include the intended thoracic/lumbar bodies through L5. Keep the lower border above the sacrum and pelvis; exclude the head and lateral artifacts without cutting vertebral endplates.')
            region_help.setWordWrap(True); controls.addWidget(region_help)
            region_edges = QHBoxLayout(); controls.addLayout(region_edges)
            for edge in ('top', 'bottom', 'left', 'right'):
                button = QPushButton('Set '+edge+' edge')
                button.clicked.connect(lambda _checked=False, selected=edge: self._select_region_edge(selected))
                region_edges.addWidget(button)
            controls = section('Vertebral numbering', True)
            self.candidate = QComboBox(); controls.addWidget(self.candidate)
            self.candidate.currentIndexChanged.connect(self._show_candidate)
            assign = QPushButton('Assign to selected level')
            controls.addWidget(assign); assign.clicked.connect(self._assign_candidate)
            anchor = QPushButton('Number from this level')
            anchor.setToolTip('Use the selected assigned level or candidate as the anchor. Review the sequence and edit anatomical exceptions before applying.')
            controls.addWidget(anchor); anchor.clicked.connect(self._candidate_numbering)
            discard = QPushButton('Discard selected candidate')
            controls.addWidget(discard); discard.clicked.connect(self._discard_candidate)
        controls = section('Correct endplates', True)
        row = QHBoxLayout(); controls.addLayout(row)
        self.level = combo(LEVELS, 'T1' if projection == 'coronal' else 'T4')
        self.corner = combo(['Pan / drag'] + list(CORNERS) + ['C7 center', 'Sacral center' if projection == 'coronal' else 'S1 posterior superior'])
        row.addWidget(self.level); row.addWidget(self.corner)
        self.level.currentIndexChanged.connect(self._manual_changed); self.corner.currentIndexChanged.connect(self._manual_changed)
        self.placement = QLabel('Pan / drag existing points'); self.placement.setWordWrap(True)
        controls.addWidget(self.placement)
        controls.addWidget(QLabel('Superior endplate: BLUE | Inferior endplate: YELLOW'))
        plate_row = QHBoxLayout(); controls.addLayout(plate_row)
        for plate, color in (('superior', '#38bdf8'), ('inferior', '#fbbf24')):
            button = QPushButton('Place '+plate+' endplate')
            button.setStyleSheet('color: '+color)
            button.clicked.connect(lambda _checked=False, p=plate: self.corner.setCurrentText(p+'_left'))
            plate_row.addWidget(button)
        help_label = QLabel('Choose the vertebral level, then click the left and right ends of its endplate. The next endpoint is selected automatically. Drag handles to correct.')
        help_label.setWordWrap(True); controls.addWidget(help_label)
        help_label.setText('Drag the middle of an endplate to move the whole line; drag an endpoint to rotate. Click the body label between the two plates to correct numbering.')
        undo = QPushButton('Undo last correction / measurement')
        controls.addWidget(undo); undo.clicked.connect(self._undo_edit)
        controls = section('Pedicles and assisted placement')
        if projection == 'coronal':
            pedicle_row = QHBoxLayout(); controls.addLayout(pedicle_row)
            for side in ('image_left', 'image_right'):
                button = QPushButton('Left pedicle' if side == 'image_left' else 'Right pedicle')
                button.setToolTip('Place '+side.replace('_', ' ')+' pedicle center')
                button.clicked.connect(lambda _checked=False, s=side: self._place_pedicle(s))
                pedicle_row.addWidget(button)
            remove_pedicles = QPushButton('Clear pedicles / grade')
            controls.addWidget(remove_pedicles); remove_pedicles.clicked.connect(self._clear_pedicles)
            text = QLabel('Mark visible pedicle centers only. Image left/right is screen position. Body guides support reader Nash-Moe grading; no automatic rotation or degree conversion. Reassess the grade after landmark edits.')
            text.setWordWrap(True); controls.addWidget(text)
        from .sam_ui import SamControls
        self.sam = SamControls(self)
        controls.addWidget(self.sam)
        remove = QPushButton('Remove selected level'); controls.addWidget(remove); remove.clicked.connect(self._remove_level)
        remove_marker = QPushButton('Remove selected balance marker')
        controls.addWidget(remove_marker)
        remove_marker.clicked.connect(self._remove_marker)
        controls = self.review_sections['Acquisition and scale'][1].layout()
        calibration = QVBoxLayout(); controls.addLayout(calibration)
        self.row_spacing = QDoubleSpinBox(); self.col_spacing = QDoubleSpinBox()
        for w in (self.row_spacing, self.col_spacing):
            w.setRange(.000001, 100); w.setDecimals(6); w.setValue(1.)
        calibration.addWidget(QLabel('Row')); calibration.addWidget(self.row_spacing)
        calibration.addWidget(QLabel('Column')); calibration.addWidget(self.col_spacing)
        self.calibrated = QCheckBox('Verified patient-plane mm/pixel')
        controls.addWidget(self.calibrated)
        for w in (self.row_spacing, self.col_spacing): w.valueChanged.connect(self._scale_changed)
        self.calibrated.toggled.connect(self._scale_changed)
        controls = section('Curves and clinical assessment')
        controls.addWidget(QLabel('Add a curve (explicit endplates):'))
        self.kind = combo(['Scoliosis Cobb'] if projection == 'coronal' else ['Thoracic kyphosis', 'Lumbar lordosis', 'Regional sagittal angle'])
        controls.addWidget(self.kind)
        row = QHBoxLayout(); controls.addLayout(row)
        self.upper = combo(LEVELS, 'T4'); self.lower = combo(LEVELS, 'T12')
        self.endplate = combo(['inferior', 'superior'])
        for w in (self.upper, self.lower, self.endplate): row.addWidget(w)
        self.kind.currentTextChanged.connect(self._curve_defaults)
        self.apex = combo(['Not assessed'] + list(LEVELS) + [f'{a}/{b}' for a, b in zip(LEVELS, LEVELS[1:])])
        controls.addWidget(QLabel('Reader apex (body or disc)')); controls.addWidget(self.apex)
        self.assessment_fields = {}
        if projection == 'coronal':
            for key in ('stable', 'neutral', 'last_touched'):
                controls.addWidget(QLabel('Reader '+key.replace('_', ' ')+' vertebra'))
                field = combo(['Not assessed']+[k for k in LEVELS if k.startswith(('T', 'L'))])
                self.assessment_fields[key] = field; controls.addWidget(field)
        self.convexity = combo(['not assessed', 'right', 'left'])
        if projection == 'coronal': controls.addWidget(self.convexity)
        self.required = QLabel(); self.required.setWordWrap(True); controls.addWidget(self.required)
        for widget in (self.upper, self.lower, self.endplate):
            widget.currentTextChanged.connect(self._requirements)
        self._requirements()
        for title, lower in (('Edit required upper endplate', False), ('Edit required lower endplate', True)):
            button = QPushButton(title); controls.addWidget(button)
            button.clicked.connect(lambda _checked=False, lo=lower: self._edit_required(lo))
        suggest = QPushButton('Suggest maximum-angle pair from assigned levels')
        controls.addWidget(suggest); suggest.clicked.connect(self._suggest_pair)
        add = QPushButton('Add curve from selected endplates'); controls.addWidget(add); add.clicked.connect(self._add_curve)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(['Curve / endplates', 'Degrees', 'Review / apex'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setWordWrap(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers); self.table.setMinimumHeight(140)
        controls.addWidget(self.table)
        self.table.itemSelectionChanged.connect(self._selected_curve)
        confirm_curve = QPushButton('Confirm selected curve endplates and numbering')
        controls.addWidget(confirm_curve); confirm_curve.clicked.connect(self._confirm_curve)
        update_curve = QPushButton('Update selected curve with chosen levels')
        controls.addWidget(update_curve); update_curve.clicked.connect(self._update_curve)
        remove_curve = QPushButton('Remove selected curve'); controls.addWidget(remove_curve)
        remove_curve.clicked.connect(self._remove_curve)
        if projection == 'coronal':
            controls = self.review_sections['Pedicles and assisted placement'][1].layout()
            controls.addWidget(QLabel('Nash-Moe reader assessment (selected level above):'))
            row = QHBoxLayout(); controls.addLayout(row)
            self.grade = combo(['Not assessed', '0', '1', '2', '3', '4'])
            self.direction = combo(['none', 'right', 'left'])
            rotation = QPushButton('Save grade')
            for w in (self.grade, self.direction, rotation): row.addWidget(w)
            rotation.clicked.connect(self._rotation)
        controls = root_controls
        self.summary = QLabel('No measurements.'); self.summary.setWordWrap(True); controls.addWidget(self.summary)
        self.review = QCheckBox('Measurements reviewed')
        controls.addWidget(self.review); self.review.toggled.connect(lambda _checked: self.changed.emit())
        self.message = QLabel('Select a series and image.'); self.message.setWordWrap(True); controls.addWidget(self.message)
        controls.addStretch()
        self.review.setToolTip('I reviewed acquisition, scale and the landmarks used in recorded measurements.')
        for label in panel.findChildren(QLabel):
            label.setWordWrap(True)
        for field in panel.findChildren(QComboBox):
            field.setMinimumContentsLength(8)
            field.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            field.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        for button in panel.findChildren(QPushButton):
            button.setToolTip(button.toolTip() or button.text())
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        naming = QWidget(); naming_layout = QVBoxLayout(naming)
        naming_layout.addWidget(QLabel('Vertebral naming'))
        hint = QLabel('Click a body on the image, correct its endplates, then assign its level.')
        hint.setWordWrap(True); naming_layout.addWidget(hint)
        naming_layout.addWidget(QLabel('Selected vertebral level'))
        self.level.setParent(naming); naming_layout.addWidget(self.level)
        if projection == 'coronal':
            for widget in self.review_sections['Vertebral numbering']:
                root_controls.removeWidget(widget); naming_layout.addWidget(widget)
        rename = QPushButton('Correct assigned numbering')
        rename.clicked.connect(lambda: self._renumber_dialog(self.level.currentText()) if self.level.currentText() in self.points else None)
        naming_layout.addWidget(rename)
        fit_quick = QPushButton('Fit image'); fit_quick.clicked.connect(self.canvas.fit)
        naming_layout.addWidget(fit_quick)
        naming_layout.addStretch()
        self.naming_scroll = QScrollArea(); self.naming_scroll.setWidgetResizable(True)
        self.naming_scroll.setWidget(naming); self.naming_scroll.setMinimumWidth(220)
        split.insertWidget(0, self.naming_scroll); split.setStretchFactor(0,0)
        split.setStretchFactor(1,1); split.setStretchFactor(2,0)
        split.setSizes([260, 900, 350])
        from .guided_review import GuidedReview
        self.guide = GuidedReview(self, naming_layout, root_controls)
        self.guide.refresh()

    def _image_label_selected(self, level):
        if level.startswith('candidate:'):
            self.candidate.setCurrentIndex(int(level.split(':')[1]))
        else:
            self.level.setCurrentText(level)
            self._renumber_dialog(level)

    def _candidate_changed(self, index, corners):
        if self.image is None or not 0 <= index < len(self.candidates): return
        from .geometry import validate_landmarks
        try:
            validate_landmarks({'T1':dict(zip(CORNERS,corners))}, self.image['pixels'].shape)
        except ValueError as exc:
            self.message.setText(str(exc)); self._show_candidate(); return
        if corners != self.candidates[index]['corners']:
            self._remember_edit()
            self.candidates[index]['corners'] = deepcopy(corners)
            self.candidates[index]['reader_modified'] = True
            self.review.setChecked(False); self.changed.emit()
        self.candidate.blockSignals(True); self.candidate.setCurrentIndex(index); self.candidate.blockSignals(False)
        self._refresh_candidates()

    def _requirements(self, *_):
        self.required.setText('Required only: '+self.upper.currentText()+' superior (blue) and '+
                              self.lower.currentText()+' '+self.endplate.currentText()+
                              (' (yellow).' if self.endplate.currentText() == 'inferior' else ' (blue).'))

    def _edit_required(self, lower):
        self.level.setCurrentText(self.lower.currentText() if lower else self.upper.currentText())
        plate = self.endplate.currentText() if lower else 'superior'
        self.corner.setCurrentText(plate+'_left')
        self._manual_changed()

    def _selected_curve(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.curves):
            spec = self.curves[row]
            self.kind.setCurrentText(spec['name']); self.upper.setCurrentText(spec['upper'])
            self.lower.setCurrentText(spec['lower']); self.endplate.setCurrentText(spec['lower_endplate'])
            self.apex.setCurrentText(spec.get('apex') or 'Not assessed')
            self.convexity.setCurrentText(spec.get('convexity', 'not assessed'))
            for key, field in self.assessment_fields.items(): field.setCurrentText(spec.get(key) or 'Not assessed')

    def _confirm_curve(self):
        from .review_workflow import curve_evidence
        row = self.table.currentRow()
        if not 0 <= row < len(self.curves):
            self.message.setText('Select a curve row to confirm its two endplates.'); return
        if not self.confirm.isChecked():
            self.message.setText('Confirm acquisition and orientation first.'); return
        try:
            self.curves[row]['review_signature'] = curve_evidence(self.snapshot(), self.curves[row])
        except (ValueError, KeyError) as exc:
            self.message.setText(str(exc)); return
        self.invalidate()
        self.table.selectRow(row)

    def _suggest_pair(self):
        from .geometry import measure_curve, LEVELS
        choices = []
        for i, upper in enumerate(LEVELS):
            for lower in LEVELS[i+1:]:
                try:
                    r = measure_curve(self.points, upper, lower, lower_endplate=self.endplate.currentText(),
                                      spacing=self.image['spacing'])
                    choices.append(r)
                except (ValueError, KeyError, TypeError):
                    continue
        if not choices:
            self.message.setText('Place or assign at least two usable endplates first.'); return
        best = max(choices, key=lambda r: r['cobb_deg'])
        self.upper.setCurrentText(best['upper']); self.lower.setCurrentText(best['lower'])
        self.message.setText('Maximum-angle pair proposed. Verify that it represents the intended curve before adding it.')

    def _select_region(self):
        if self.image is None: return
        self.sam.reset(); self._region_start = None
        self.canvas.manual_target = ('region', 'box')
        self.message.setText('Click two opposite corners around the spine. Exclude the head and unrelated anatomy.')

    def _select_region_edge(self, edge):
        if self.image is None or self.region is None:
            self.message.setText('Select a spine region first.'); return
        self.sam.reset(); self._region_start = None
        self.canvas.manual_target = ('region', edge)
        self.message.setText('Click the image at the new '+edge+' boundary. Keep the endplates needed for measurement inside the region.')

    def _set_region(self, region):
        x0, y0, x1, y1 = region
        h, w = self.image['pixels'].shape
        if not (0 <= x0 < x1 < w and 0 <= y0 < y1 < h) or min(x1-x0, y1-y0) < 32:
            if self.region is not None: self._draw_region()
            self.message.setText('Keep a valid region at least 32 pixels wide and high.'); return False
        unchanged = list(region) == self.region
        self.region = list(region)
        self._draw_region()
        if unchanged: return True
        # Unassigned detections belong to their old inference field of view.
        self._undo.clear()
        self.candidates = []; self._refresh_candidates()
        self.canvas.manual_target = None; self._region_start = None
        self.message.setText('Region updated. Run AI again for this field of view. Assigned landmarks are preserved.')
        self.regionReady.emit()
        return True

    def _draw_region(self):
        x0,y0,x1,y1 = self.region
        for handle in getattr(self, '_region_handles', []):
            if handle.scene() is self.canvas.scene(): self.canvas.scene().removeItem(handle)
        self._region_handles = []
        if self._region_item is not None:
            self.canvas.scene().removeItem(self._region_item)
        pen = QPen(QColor('#fb923c'), 2); pen.setCosmetic(True)
        corners=[[x0,y0],[x1,y0],[x0,y1],[x1,y1]]
        self._region_item = CandidateBody(-1,corners,self.canvas,region=True)
        self.canvas.scene().addItem(self._region_item)
        for i,point in enumerate(corners):
            handle=LandmarkItem('region-handle',str(i),point,'#fb923c',self.canvas)
            self.canvas.scene().addItem(handle); self._region_handles.append(handle)

    def accept_candidates(self, result):
        self._undo.clear()
        self.candidates = result.get('candidates', [])
        self._candidate_provenance = result
        from .automatic import candidate_pair
        self.automatic_pair = candidate_pair(self.candidates, self.image['spacing'])
        self._refresh_candidates()
        self.message.setText('Proposals only: select a candidate, inspect it, choose its vertebral level, then assign. Existing manual points are preserved.')

    def _refresh_candidates(self):
        from .automatic import candidate_pair
        self.automatic_pair = candidate_pair(self.candidates, self.image['spacing']) if self.image else None
        selected = self.candidate.currentIndex()
        self.candidate.blockSignals(True)
        self.candidate.clear()
        for i, item in enumerate(self.candidates):
            self.candidate.addItem('Candidate '+str(i+1)+' | Needs review', i)
        self.candidate.setCurrentIndex(min(max(0,selected),len(self.candidates)-1))
        self.candidate.blockSignals(False)
        self._show_candidate()
        if self.automatic_pair:
            pair = self.automatic_pair
            self.summary.setText(f"Unverified maximum-angle proposal: {pair['degrees']:.1f} degrees, candidates {pair['upper']+1} / {pair['lower']+1}. Confirm anatomy and curve endpoints. Lateral angles and rotation are not automatically assessed.")

    def _show_candidate(self, *_):
        for item in self._candidate_lines:
            self.canvas.scene().removeItem(item)
        self._candidate_lines = []
        index = self.candidate.currentIndex()
        if not 0 <= index < len(self.candidates): return
        for number, candidate in enumerate(self.candidates):
            p = candidate['corners']; selected = number == index; key = 'candidate:'+str(number)
            body = CandidateBody(number,p,self.canvas,selected)
            self.canvas.scene().addItem(body); self._candidate_lines.append(body)
            body.handles=[]; body.segments=[]
            for a,b,color,plate in ((0,1,'#38bdf8','superior'),(2,3,'#fbbf24','inferior')):
                handles=[SegmentEndpoint(key,CORNERS[i],p[i],color,self.canvas) for i in (a,b)]
                for handle in handles:
                    self.canvas.scene().addItem(handle); handle.setVisible(selected)
                    self._candidate_lines.append(handle)
                body.handles.extend(handles)
                line=EditableSegment(key,plate,handles,color,self.canvas)
                body.segments.append(line)
                self.canvas.scene().addItem(line); self._candidate_lines.append(line)
                line.setOpacity(1. if selected else .55)
            label=LevelBadge(key,[max(v[0] for v in p)+8/max(abs(self.canvas.transform().m11()),.01),sum(v[1] for v in p)/4],self.canvas)
            label.setText('Candidate '+str(number+1)+' ?')
            label.setZValue(1.5)
            self.canvas.scene().addItem(label); self._candidate_lines.append(label)

        if self.automatic_pair and not self.curves:
            from .annotations import perpendicular_construction
            pair = self.automatic_pair
            upper = self.candidates[pair['upper']]['corners'][:2]
            lower = self.candidates[pair['lower']]['corners'][2:]
            construction = perpendicular_construction(upper, lower, self.image['pixels'].shape, self.image['spacing'])
            for line in construction['lines']:
                pen = QPen(QColor(line['color']), 2); pen.setCosmetic(True)
                a, b = line['points']
                item = self.canvas.scene().addLine(*a, *b, pen)
                item.setAcceptedMouseButtons(Qt.NoButton); self._candidate_lines.append(item)
            label = self.canvas.scene().addSimpleText(f"{pair['degrees']:.1f} deg | proposal")
            label.setBrush(QColor('#a3e635')); label.setPos(*construction['label_at'])
            label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            label.setAcceptedMouseButtons(Qt.NoButton); self._candidate_lines.append(label)

    def _discard_candidate(self, _checked=False, *, remember=True):
        index = self.candidate.currentIndex()
        if 0 <= index < len(self.candidates):
            if remember: self._remember_edit()
            self.candidates.pop(index); self._refresh_candidates()

    def _assign_candidate(self):
        from .geometry import validate_landmarks
        index = self.candidate.currentIndex(); level = self.level.currentText()
        if not 0 <= index < len(self.candidates): return
        if self.points.get(level):
            self.message.setText('This level already has points. Correct them directly or remove the level before replacing it.'); return
        points = dict(zip(CORNERS, self.candidates[index]['corners']))
        try: validate_landmarks({level: points}, self.image['pixels'].shape)
        except ValueError as exc:
            self.message.setText('Candidate geometry needs manual correction: '+str(exc)); return
        self._remember_edit(); self.points[level] = deepcopy(points)
        self.provenance.setdefault('per_level', {})[level] = dict(source='Reader-assigned AI candidate',
                                                                model=self._candidate_provenance.get('model'),
                                                                reader_modified=bool(self.candidates[index].get('reader_modified')))
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()
        self._discard_candidate(remember=False)

    def _curve_defaults(self, kind):
        if kind == 'Lumbar lordosis':
            self.upper.setCurrentText('L1'); self.lower.setCurrentText('S1'); self.endplate.setCurrentText('superior')
        elif kind == 'Thoracic kyphosis':
            self.upper.setCurrentText('T4'); self.lower.setCurrentText('T12'); self.endplate.setCurrentText('inferior')

    def set_inventory(self, rows):
        self._rows = rows
        self.series.clear()
        seen = set()
        for row in rows:
            if row['series_uid'] not in seen:
                self.series.addItem(row['series_label'], row['series_uid']); seen.add(row['series_uid'])

    def _series_changed(self):
        self.clear_image(); self.files.clear()
        for row in self._rows:
            if row['series_uid'] == self.series.currentData():
                self.files.addItem(row['label'], row['path'])

    def clear_image(self, *_):
        self._candidate_provenance = {}
        self.canvas.measurement_overlay()
        self.sam.reset()
        self.region = None; self._region_start = None; self._region_item = None; self._region_handles = []
        self.candidates = []; self._candidate_lines = []; self.automatic_pair = None
        if hasattr(self, 'candidate'): self.candidate.clear()
        self.image = None; self.points = {}; self.markers = {}; self.curves = []; self.rotations = []; self.provenance = {}
        self.pedicles = {}; self._undo = []; self.canvas.manual_target = None
        self.canvas.scene().clear(); self.canvas.items_by_key = {}; self.canvas.lines = []
        self.confirm.setChecked(False); self.review.setChecked(False)
        self.table.setRowCount(0); self.summary.setText('No measurements.')
        self.changed.emit()

    def accept_image(self, image):
        self.clear_image(); self.image = image
        for w in (self.row_spacing, self.col_spacing, self.calibrated): w.blockSignals(True)
        self.row_spacing.setValue(image['spacing'][0]); self.col_spacing.setValue(image['spacing'][1])
        self.calibrated.setChecked(image['calibrated'])
        for w in (self.row_spacing, self.col_spacing, self.calibrated): w.blockSignals(False)
        self.canvas.pixel_aspect = image['spacing'][1]/image['spacing'][0]
        self.canvas.load(image['pixels']); self._manual_changed()
        self.message.setText('Image loaded. Confirm acquisition and place or suggest landmarks.')
        self.changed.emit()

    def snapshot(self):
        return dict(review_protocol='selected-endplates-v1', image=self.image, points=deepcopy(self.points), markers=deepcopy(self.markers),
                    pedicles=deepcopy(self.pedicles),
                    curves=deepcopy(self.curves), rotations=deepcopy(self.rotations), provenance=deepcopy(self.provenance),
                    positive_image_right=self.orientation.currentIndex() == 1,
                    acquisition_confirmed=self.confirm.isChecked(), landmarks_reviewed=self.review.isChecked())

    def invalidate(self, *_):
        self.review.setChecked(False)
        self.changed.emit(); self.recalculate()

    def _manual_changed(self):
        key = self.corner.currentText()
        if hasattr(self, 'placement'):
            self.placement.setText('Editing '+self.level.currentText()+' | '+key.replace('_', ' ') if key in CORNERS else key)
        self.canvas.manual_target = None if key == 'Pan / drag' or self.image is None else (
            ('balance', key) if key not in CORNERS else (self.level.currentText(), key))

    def _point_changed(self, level, key, x, y):
        if self.image is None: return
        if level.startswith('candidate:'):
            index=int(level.split(':')[1]); corners=deepcopy(self.candidates[index]['corners'])
            corners[CORNERS.index(key)]=[x,y]; self._candidate_changed(index,corners); return
        if level == 'region-handle':
            box=list(self.region); side=int(key)
            box[0 if side in (0,2) else 2]=x; box[1 if side in (0,1) else 3]=y
            self._set_region(box); return
        if level == 'region':
            if key in ('top', 'bottom', 'left', 'right') and self.region is not None:
                region = list(self.region)
                index = {'left': 0, 'top': 1, 'right': 2, 'bottom': 3}[key]
                region[index] = x if key in ('left', 'right') else y
                self._set_region(region)
                return
            if self._region_start is None:
                self._region_start = (x, y)
                self.message.setText('Click the opposite corner of the spine region.')
            else:
                a, b = self._region_start
                if abs(x-a) < 32 or abs(y-b) < 32:
                    self.message.setText('Select a larger region.'); return
                self._set_region([min(a, x), min(b, y), max(a, x), max(b, y)])
            return
        if level == 'sam':
            self.sam.add_box_point(x, y)
            return
        self._remember_edit()
        if level.startswith('pedicle:'):
            body_level = level.split(':', 1)[1]
            self.pedicles.setdefault(body_level, {})[key] = [x, y]
            self.rotations = [r for r in self.rotations if r['level'] != body_level]
            self.canvas.manual_target = None
        elif level == 'balance': self.markers[key] = [x, y]
        else:
            self.points.setdefault(level, {})[key] = [x, y]
            self.rotations = [r for r in self.rotations if r['level'] != level]
            if level in self.provenance.get('per_level', {}):
                self.provenance['per_level'][level]['reader_modified'] = True
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()
        if key in CORNERS and self.canvas.manual_target == (level, key):
            self.corner.setCurrentText(key.replace('_left', '_right') if key.endswith('_left') else 'Pan / drag')

    def _remove_level(self):
        self.sam.reset()
        self._remember_edit()
        self.points.pop(self.level.currentText(), None)
        self.pedicles.pop(self.level.currentText(), None)
        self.rotations = [r for r in self.rotations if r['level'] != self.level.currentText()]
        self.provenance.get('per_level', {}).pop(self.level.currentText(), None)
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()

    def _remember_edit(self):
        self._undo.append(deepcopy({key: getattr(self, key) for key in
            ('points', 'markers', 'pedicles', 'curves', 'rotations', 'provenance', 'candidates')}))
        self._undo = self._undo[-30:]

    def _undo_edit(self):
        if not self._undo: return
        for key, value in self._undo.pop().items(): setattr(self, key, value)
        # Undo restores geometry, never a previous clinical approval.
        for curve in self.curves: curve.pop('review_signature', None)
        if hasattr(self, 'candidate'): self._refresh_candidates()
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()

    def _segment_changed(self, level, plate, pair):
        if self.image is None: return
        if level.startswith('candidate:'):
            index=int(level.split(':')[1]); corners=deepcopy(self.candidates[index]['corners'])
            offset=0 if plate=='superior' else 2
            corners[offset:offset+2]=deepcopy(pair); self._candidate_changed(index,corners); return
        from .geometry import validate_landmarks
        updates = {plate+'_left': pair[0], plate+'_right': pair[1]}
        try: validate_landmarks({level: updates}, self.image['pixels'].shape)
        except ValueError as exc:
            self.message.setText(str(exc)); self.canvas.set_points(self.points, self.markers, self.pedicles); return
        self._remember_edit()
        self.points.setdefault(level, {}).update(deepcopy(updates))
        self.provenance.setdefault('per_level', {}).setdefault(level, {})['reader_modified'] = True
        self.rotations = [r for r in self.rotations if r['level'] != level]
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()

    def _place_pedicle(self, side):
        if self.image is None: return
        self.corner.setCurrentText('Pan / drag')
        self.canvas.manual_target = ('pedicle:'+self.level.currentText(), side)
        self.placement.setText(self.level.currentText()+' | '+side.replace('_', ' ')+' pedicle center')

    def _clear_pedicles(self):
        self._remember_edit(); level = self.level.currentText()
        self.pedicles.pop(level, None); self.rotations = [r for r in self.rotations if r['level'] != level]
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()

    def _apply_level_mapping(self, mapping):
        if set(mapping) != set(self.points) or len(set(mapping.values())) != len(mapping):
            raise ValueError('Numbering must preserve each existing body exactly once.')
        if any(v not in LEVELS for v in mapping.values()): raise ValueError('Invalid vertebral level.')
        for keys in (self.pedicles, self.provenance.get('per_level', {}), [r['level'] for r in self.rotations]):
            mapped = [mapping.get(k, k) for k in keys]
            if len(set(mapped)) != len(mapped):
                raise ValueError('Numbering overlaps existing evidence at an unassigned body. Correct that level first.')
        self._remember_edit()
        self.points = {mapping[k]: v for k, v in self.points.items()}
        self.pedicles = {mapping.get(k, k): v for k, v in self.pedicles.items()}
        self.provenance['per_level'] = {mapping.get(k, k): v for k, v in self.provenance.get('per_level', {}).items()}
        for record in self.rotations: record['level'] = mapping.get(record['level'], record['level'])
        for spec in self.curves:
            spec.pop('review_signature', None)
            for key in ('upper', 'lower', 'apex', 'stable', 'neutral', 'last_touched'):
                if spec.get(key): spec[key] = '/'.join(mapping.get(k, k) for k in spec[key].split('/'))
        self.canvas.manual_target = None; self.corner.setCurrentText('Pan / drag')
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()

    def _renumber_dialog(self, anchor):
        dialog = QDialog(self); dialog.setWindowTitle('Correct vertebral numbering')
        layout = QVBoxLayout(dialog); target = combo(LEVELS, anchor); layout.addWidget(target)
        sequence = QCheckBox('Shift all assigned levels from this anchor (preserve known gaps)')
        sequence.setChecked(True); layout.addWidget(sequence)
        preview = QLabel(); layout.addWidget(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); layout.addWidget(buttons)
        pending = {}
        def update():
            pending.clear()
            try:
                pending.update(level_mapping(self.points, anchor, target.currentText(), sequence.isChecked()))
                preview.setText('\n'.join(k+' -> '+v for k, v in pending.items())+'\nReview anatomical coverage before applying.')
            except ValueError as exc: preview.setText(str(exc))
            buttons.button(QDialogButtonBox.Ok).setEnabled(bool(pending))
        target.currentIndexChanged.connect(update); sequence.toggled.connect(update); update()
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.Accepted:
            try: self._apply_level_mapping(pending)
            except ValueError as exc: self.message.setText(str(exc))

    def _candidate_numbering(self):
        from .editing import numbering_proposal
        try:
            mapping, labels = numbering_proposal(self.points, self.candidates,
                                                self.level.currentText(), self.candidate.currentIndex())
        except ValueError as exc:
            self.message.setText(str(exc)); return
        from .geometry import validate_landmarks
        dialog = QDialog(self); dialog.setWindowTitle('Review proposed candidate numbering')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Number above and below the selected anchor. Change individual rows for anatomical exceptions.'))
        table = QTableWidget(len(mapping)+len(labels), 2)
        table.setHorizontalHeaderLabels(['Body', 'Proposed level / exception'])
        fields = []
        entries = [('Assigned '+key, value) for key, value in mapping.items()]
        entries += [('Candidate '+str(i+1), value) for i, value in enumerate(labels)]
        for row, (name, value) in enumerate(entries):
            table.setItem(row, 0, QTableWidgetItem(name))
            field = combo(LEVELS, value); fields.append(field); table.setCellWidget(row, 1, field)
        layout.addWidget(table)
        checked = QCheckBox('I reviewed the body order, excluded duplicate detections, and corrected missing levels or anatomical exceptions.')
        layout.addWidget(checked)
        error = QLabel(); error.setWordWrap(True); layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); layout.addWidget(buttons)
        def validate():
            unique = len({field.currentText() for field in fields}) == len(fields)
            error.setText('' if unique else 'Each body needs a distinct level. Correct duplicate labels.')
            buttons.button(QDialogButtonBox.Ok).setEnabled(checked.isChecked() and unique)
        checked.toggled.connect(validate)
        for field in fields: field.currentIndexChanged.connect(validate)
        validate()
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.Accepted: return
        names = [field.currentText() for field in fields]
        mapping = dict(zip(mapping, names[:len(mapping)]))
        proposed = {name: dict(zip(CORNERS, item['corners']))
                    for name, item in zip(names[len(mapping):], self.candidates)}
        try:
            validate_landmarks({**{mapping[k]: v for k, v in self.points.items()}, **proposed}, self.image['pixels'].shape)
            self._apply_level_mapping(mapping)
        except ValueError as exc:
            self.message.setText(str(exc)); return
        self.points.update(deepcopy(proposed))
        for (_, default), name in zip(entries, names):
            self.provenance.setdefault('per_level', {}).setdefault(name, {}).update(
                numbering_source='Reader-reviewed anchor sequence',
                numbering_exception=name != default)
        for level in proposed:
            self.provenance.setdefault('per_level', {}).setdefault(level, {}).update(source='Reader-applied anchor sequence',
                anchor=self.level.currentText(), model=self._candidate_provenance.get('model'))
        self.candidates = []; self._refresh_candidates()
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()

    def _remove_marker(self):
        self._remember_edit()
        self.markers.pop(self.corner.currentText(), None)
        self.canvas.set_points(self.points, self.markers, self.pedicles); self.invalidate()

    def _scale_changed(self, *_):
        if self.image is not None:
            self.image = dict(self.image, spacing=(self.row_spacing.value(), self.col_spacing.value()),
                              calibrated=self.calibrated.isChecked(),
                              calibration_method='Reader-verified patient-plane scale' if self.calibrated.isChecked() else 'Unverified scale / pixel aspect')
            self.canvas.pixel_aspect = self.image['spacing'][1]/self.image['spacing'][0]
            self.canvas.fit()
            self.invalidate()

    def _add_curve(self):
        if self.image is None: return
        if len(self.curves) >= 5:
            self.message.setText('Up to five curves can be recorded per projection.'); return
        spec = dict(name=self.kind.currentText(), upper=self.upper.currentText(), lower=self.lower.currentText(),
                    lower_endplate=self.endplate.currentText(), apex='' if self.apex.currentIndex() == 0 else self.apex.currentText(),
                    convexity=self.convexity.currentText())
        spec.update({key: field.currentText() if field.currentIndex() else '' for key, field in self.assessment_fields.items()})
        snapshot = self.snapshot(); snapshot['curves'].append(spec)
        try: measure_view(snapshot)
        except (ValueError, KeyError) as exc:
            self.message.setText('Place the two endpoints of each required endplate. '+str(exc)); return
        self._remember_edit(); self.curves.append(spec); self.invalidate()

    def _update_curve(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.curves):
            self.message.setText('Select a curve row first.'); return
        history = len(self._undo); self._remember_edit()
        old = self.curves.pop(row)
        count = len(self.curves)
        self._add_curve()
        if len(self.curves) == count:
            self.curves.insert(row, old)
            del self._undo[history:]
            return
        # Keep one transaction for replacement, not the temporary remove/add.
        if len(self._undo) > 1: self._undo.pop()
        replacement = self.curves.pop()
        from .review_workflow import curve_evidence
        if old.get('review_signature') == curve_evidence(self.snapshot(), replacement):
            replacement['review_signature'] = old['review_signature']
        self.curves.insert(row, replacement)
        self.invalidate(); self.table.selectRow(row)

    def _remove_curve(self):
        row = self.table.currentRow()
        if row < 0 and self.curves:
            row = len(self.curves)-1
        if 0 <= row < len(self.curves):
            self._remember_edit(); self.curves.pop(row); self.invalidate()

    def _rotation(self):
        level = self.level.currentText()
        if self.grade.currentIndex() == 0:
            self._remember_edit(); self.rotations = [r for r in self.rotations if r['level'] != level]; self.invalidate(); return
        try: record = rotation_record(level, int(self.grade.currentText()), self.direction.currentText())
        except ValueError as exc:
            self.message.setText(str(exc)); return
        self._remember_edit(); self.rotations = [r for r in self.rotations if r['level'] != level]+[record]
        self.invalidate()

    def recalculate(self):
        if hasattr(self, 'guide'): self.guide.refresh()
        if self.projection == 'coronal' and self.image is not None:
            self._refresh_candidates()
        self.canvas.measurement_overlay()
        self.table.setRowCount(0)
        if self.image is None: return
        try: measured = measure_view(self.snapshot())
        except (ValueError, KeyError) as exc:
            self.summary.setText('Measurement incomplete: '+str(exc)); return
        self.canvas.measurement_overlay(self.snapshot(), measured)
        self.table.setRowCount(len(measured['curves']))
        for row, result in enumerate(measured['curves']):
            values = [f'{result["name"]} {result["upper"]} superior / {result["lower"]} {result["lower_endplate"]}', f'{result["cobb_deg"]:.1f}',
                      ('Confirmed' if result['endplates_reviewed'] else 'Needs review')+' / '+(result['apex'] or result['apex_candidate'] or 'Apex not assessed')]
            for col, value in enumerate(values): self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.resizeRowsToContents()
        summary = []
        for result in measured['curves']:
            a = result.get('coronal_assessment', {})
            if a:
                summary.append('Proposals (available levels only): '+', '.join(key.replace('_', ' ')+': '+str(a.get(key+'_candidate') or 'not available') for key in ('apex_csvl', 'stable', 'neutral', 'last_touched')))

        if measured['balance']:
            b = measured['balance']; summary.append(f'{b["name"]}: {b["value"]:+.2f} {b["unit"]}; positive {b["positive"]}.')
        summary += [f'{r["level"]}: Nash-Moe {r["grade"]} ({r["direction"]}), reader assessment.' for r in self.rotations]
        if not self.curves and self.automatic_pair:
            pair = self.automatic_pair
            summary.insert(0, f"Unverified maximum-angle proposal: {pair['degrees']:.1f} degrees, candidates {pair['upper']+1} / {pair['lower']+1}. Confirm anatomy and curve endpoints.")
        self.summary.setText('\n'.join(summary) or 'No balance or rotation assessment.')
        self.message.setText('Values updated. Confirm numbering and landmark accuracy before review.')


class TotalSpineWidget(QWidget):
    resultsReady = Signal()

    def __init__(self, parent=None, *, study_uid):
        super().__init__(parent)
        self.setObjectName('eagleEyeTotalSpine')
        self._automatic = False
        self.preferred_series_uid = ''
        self.study_uid = str(study_uid); self._future = None; self._kind = ''; self._target = None
        from ..analysis_progress import AnalysisProgress
        self.analysis_progress = AnalysisProgress()
        self._cancel = threading.Event(); self._disposed = False; self.report_result = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='total-spine')
        from .runtime_seal import RuntimeSeal
        self._runtime_seal = RuntimeSeal()
        executor, cancel = self._executor, self._cancel
        self.destroyed.connect(lambda *_: (cancel.set(), executor.shutdown(wait=False, cancel_futures=True)))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Total Spine Alignment | Editable research measurements'))
        row = QHBoxLayout(); layout.addLayout(row)
        self.scan = QPushButton('Find study images'); row.addWidget(self.scan)
        self.scan.clicked.connect(self.scan_study)
        self.cancel = QPushButton('Cancel task'); row.addWidget(self.cancel); self.cancel.clicked.connect(self._cancel.set)
        actions = QHBoxLayout(); layout.addLayout(actions)
        self.region_button = QPushButton('Select spine region')
        self.analyze_button = QPushButton('Detect vertebrae (AI)')
        self.measure_button = QPushButton('Measure angles')
        self.analyze_button.setToolTip('Run landmark detection inside the selected coronal region. This does not confirm clinical measurements.')
        self.measure_button.setToolTip('Choose the end vertebrae and add an angle from their endplates. No AI rerun is required after manual corrections.')
        for button in (self.region_button, self.analyze_button, self.measure_button):
            actions.addWidget(button)
        self.region_button.clicked.connect(lambda: self.tabs.currentWidget()._select_region())
        self.analyze_button.clicked.connect(lambda: self.start_ai(self.tabs.currentWidget(), requested=True))
        self.measure_button.clicked.connect(self.show_measurements)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs, 1)
        self.editors = []
        for projection, title in (('coronal', 'Coronal AP / PA'), ('lateral', 'Lateral')):
            editor = ProjectionEditor(projection); self.editors.append(editor); self.tabs.addTab(editor, title)
            editor.changed.connect(self.invalidate_report)
            editor.loadRequested.connect(self.load_image); editor.aiRequested.connect(self.start_ai)
            editor.sam.requested.connect(self.start_sam)
        self.editors[0].regionReady.connect(self._automatic_region_ready)
        self.notes = QLineEdit(); self.notes.setMaxLength(2000); self.notes.setPlaceholderText('Clinician impression (optional)')
        layout.addWidget(self.notes); self.notes.textChanged.connect(self.invalidate_report)
        row = QHBoxLayout(); layout.addLayout(row)
        self.draft = QPushButton('Generate draft PDF'); self.reviewed = QPushButton('Generate reviewed PDF')
        from ..eagle_eye_remote.settings import remote_required
        if remote_required():
            self.draft.setText('Apply on server / draft PDF')
            self.reviewed.setText('Apply on server / reviewed PDF')
        self._server_report_parent = None
        self._server_report_sources = None
        self._pending_report_handle = None
        self.open = QPushButton('Open PDF'); self.save = QPushButton('Save PDF copy')
        for w in (self.draft, self.reviewed, self.open, self.save): row.addWidget(w)
        self.draft.clicked.connect(lambda: self.generate(False)); self.reviewed.clicked.connect(lambda: self.generate(True))
        self.open.clicked.connect(self.open_pdf); self.save.clicked.connect(self.save_pdf)
        self.open_images = QPushButton('Open annotated images')
        layout.addWidget(self.open_images)
        self.open_images.clicked.connect(self.open_annotated_images)
        self.status = QLabel('Choose the coronal series and, when available, a separate lateral series.')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self._fit_timer = QTimer(self); self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_loaded_images)
        self._timer = QTimer(self); self._timer.setInterval(100); self._timer.timeout.connect(self._poll)
        self.tabs.currentChanged.connect(self._refresh)
        self._refresh()

    def show_measurements(self):
        editor = self.tabs.currentWidget()
        editor.review_scroll.show()
        editor.naming_scroll.show()
        toggle, _ = editor.review_sections['Curves and clinical assessment']
        toggle.setChecked(True)
        editor.review_scroll.ensureWidgetVisible(toggle)
        editor.upper.setFocus()
        self.status.setText('Choose the upper and lower vertebrae, then Add curve from selected endplates. Existing curve angles update when you move their endpoints.')

    def fit_loaded_images(self):
        if self._disposed: return
        for editor in self.editors:
            if editor.image is not None: editor.canvas.fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_timer.start(0)

    def begin_automatic(self, *, series_uid=''):
        self.preferred_series_uid = str(series_uid or '')
        self._automatic = True
        self._automatic_visibility(True)
        self.editors[0].ai_model.setCurrentIndex(1)
        self.status.setText('Choose the standing coronal image. After loading, mark two corners around the thoracic/lumbar spine; analysis starts automatically. Exclude the head, sacrum and pelvis.')
        self.scan_study()

    def _load_preferred_series(self, rows):
        uid = self.preferred_series_uid
        if not uid:
            return
        matches = [row for row in rows if row['series_uid'] == uid]
        if not matches:
            self.status.setText('The selected series has no available single-frame radiograph. Load it in the viewer and retry.')
            return
        positions = {row.get('view_position', '') for row in matches}
        if getattr(self, '_control_projection', None) in ('coronal', 'lateral'):
            projection = self._control_projection
        elif positions <= {'AP', 'PA'}:
            projection = 'coronal'
        elif positions <= {'LL', 'RL', 'LAT', 'LATERAL'}:
            projection = 'lateral'
        else:
            choice, accepted = QInputDialog.getItem(self, 'Total Spine projection',
                'Projection of the selected series', ['Coronal AP / PA', 'Lateral'], 0, False)
            if not accepted:
                self.status.setText('Projection selection cancelled. No analysis started.')
                return
            projection = 'coronal' if choice == 'Coronal AP / PA' else 'lateral'
        editor = self.editors[0 if projection == 'coronal' else 1]
        if projection == 'lateral':
            # The installed landmark checkpoint only supports coronal images.
            self._automatic = False
            self._automatic_visibility(False)
        self.tabs.setCurrentWidget(editor)
        editor.series.setCurrentIndex(editor.series.findData(uid))
        if len(matches) == 1:
            self.load_image(editor)
        else:
            self.status.setText('Selected series ready. Choose the image within this series and load it.')

    def _automatic_visibility(self, preparing):
        self.tabs.setTabVisible(1, not preparing)
        self.editors[0].review_scroll.setVisible(not preparing)
        self.editors[0].naming_scroll.setVisible(not preparing)
        for widget in (self.notes, self.draft, self.reviewed, self.open, self.save, self.open_images):
            widget.setVisible(not preparing)

    def _automatic_region_ready(self):
        self._refresh()
        if self._automatic:
            QTimer.singleShot(0, lambda: self.start_ai(self.editors[0]) if self._automatic and not self._disposed else None)

    def invalidate_report(self, *_):
        self.report_result = None; self._refresh()

    def _refresh(self):
        busy = self._future is not None
        pending = self._pending_report_handle is not None
        editor = self.tabs.currentWidget()
        loaded = editor is not None and editor.image is not None
        coronal = loaded and editor.projection == 'coronal'
        self.region_button.setEnabled(not busy and coronal)
        self.analyze_button.setEnabled(not busy and coronal and editor.region is not None)
        self.measure_button.setEnabled(not busy and loaded)
        self.scan.setEnabled(not busy); self.tabs.setEnabled(not busy); self.notes.setEnabled(not busy)
        self.draft.setEnabled(not busy and any(e.image is not None for e in self.editors))
        self.reviewed.setEnabled(self.draft.isEnabled())
        self.cancel.setEnabled(busy)
        self.open.setEnabled(not busy and self.report_result is not None)
        self.open_images.setEnabled(not busy and self.report_result is not None)
        self.save.setEnabled(self.open.isEnabled())
        if pending:
            self.tabs.setEnabled(False); self.scan.setEnabled(False); self.notes.setEnabled(False)
            self.region_button.setEnabled(False); self.analyze_button.setEnabled(False); self.measure_button.setEnabled(False)
            self.reviewed.setEnabled(False)
            self.draft.setText('Resume server result'); self.draft.setEnabled(not busy)

    def _submit(self, kind, function, *args, target=None):
        if self._disposed or self._future is not None: return
        self._control_error = None
        self._cancel.clear(); self._kind = kind; self._target = target
        from ..analysis_progress import AnalysisProgress
        self.analysis_progress = AnalysisProgress()
        if kind in ('inference', 'segmentation'):
            function = partial(function, progress=self.analysis_progress.update)
        if not hasattr(self, 'analysis_bar'):
            self.analysis_bar = QProgressBar(self)
            self.layout().addWidget(self.analysis_bar)
        self.analysis_bar.setRange(0, 0); self.analysis_bar.show()
        self._future = self._executor.submit(function, *args)
        stage = {'scan': 'Finding the selected study images',
                 'load': 'Reading image pixels and calibration',
                 'inference': 'Locating vertebrae and estimating endplates',
                 'segmentation': 'Segmenting the selected vertebral body',
                 'report': 'Preparing annotated images and measurements',
                 'copy': 'Saving the report copy'}.get(kind, 'Processing')
        self.status.setText(stage + '. You can continue working in PACS.')
        self._timer.start(); self._refresh()

    def scan_study(self):
        self._submit('scan', service.study_images, self.study_uid)

    def load_image(self, editor):
        path, series = editor.files.currentData(), editor.series.currentData()
        if not path or not series: return
        editor.clear_image()
        self._submit('load', service.load_view, path, self.study_uid, series, editor.projection, target=editor)

    def start_ai(self, editor, *, requested=False):
        if editor is None or editor.projection != 'coronal':
            self.status.setText('Automatic vertebral detection supports the coronal image. Use Measure angles for lateral endplates.')
            return
        if editor.image is None or (not requested and not self._automatic and not editor.confirm.isChecked()):
            self.status.setText('Load and confirm a complete standing coronal radiograph first.'); return
        self.invalidate_report()
        editor.sam.reset()
        if editor.ai_model.currentIndex() == 1:
            from .assist_service import predict_scoliovis
            function = partial(predict_scoliovis, runtime_seal=self._runtime_seal)
        else:
            function = service.predict
        if editor.region is None:
            self.status.setText('Select the spine region before requesting AI proposals.'); return
        from .review_workflow import predict_region
        self._submit('inference', partial(predict_region, predictor=function), dict(editor.image),
                     list(editor.region), self._cancel, target=editor)

    def start_sam(self, editor):
        if editor.image is None or not editor.confirm.isChecked() or editor.sam.box is None:
            self.status.setText('Load and confirm the image, select a level, and box one vertebral body.'); return
        from .assist_service import segment_body
        editor.sam.apply.setEnabled(False)
        self._submit('segmentation', partial(segment_body, runtime_seal=self._runtime_seal),
                     dict(editor.image), editor.level.currentText(),
                     list(editor.sam.box), self._cancel, target=editor)

    def generate(self, reviewed):
        from .report import generate_report
        if self._pending_report_handle is not None:
            from ..eagle_eye_remote.client import Client
            from PacsClient.utils.data_paths import AI_DIR
            self._submit('report', lambda: Client().resume(self._pending_report_handle,
                Path(AI_DIR) / 'eagle_eye', cancel=self._cancel))
            return
        views = [editor.snapshot() for editor in self.editors if editor.image is not None]
        try: validate_report_views(views, self.study_uid, reviewed=reviewed)
        except (ValueError, KeyError) as exc:
            self.status.setText(str(exc)); return
        from ..eagle_eye_remote.settings import remote_required
        if remote_required():
            from ..eagle_eye_remote.spine_review import submit
            sources = [(v['image']['identity']['series_uid'], v['image']['identity']['sop_uid']) for v in views]
            previous = self._server_report_sources
            parent = self._server_report_parent if previous and sources[:len(previous)] == previous else None
            if parent is None and self._server_report_parent is None:
                candidate = getattr(self.editors[0], '_candidate_provenance', {})
                if candidate.get('remote_analysis') and self.editors[0].image is views[0]['image']:
                    parent = candidate.get('server_job_id')
            self._server_report_sources = sources
            self._submit('report', partial(submit, parent=parent, cancel=self._cancel),
                         views, self.study_uid, reviewed, self.notes.text())
        else:
            self._submit('report', generate_report, views, self.study_uid, reviewed, self.notes.text())

    def _poll(self):
        from ..analysis_progress import display_progress
        if hasattr(self, 'analysis_bar'):
            display_progress(self.analysis_bar, self.status, self.analysis_progress)
        if self._future is None or not self._future.done(): return
        future, kind, target = self._future, self._kind, self._target
        self._future = None; self._timer.stop()
        try:
            result = future.result()
            if self._disposed or self._cancel.is_set():
                self.status.setText('Task cancelled; result was not applied.'); return
            if kind == 'scan':
                for editor in self.editors: editor.set_inventory(result)
                self.status.setText(f'{len(result)} eligible images found. Choose and load the coronal image, then mark two corners enclosing the spine. Analysis will start automatically.' if self._automatic else f'{len(result)} eligible images found. Assign each projection explicitly.')
                self._load_preferred_series(result)
            elif kind == 'load':
                target.accept_image(result); self.status.setText('Image ready for review.')
                if self._automatic:
                    target._select_region()
                    self.status.setText('Mark two opposite corners around the thoracic/lumbar spine. Exclude the head, sacrum and pelvis. The second corner starts automatic analysis.')
                elif self.preferred_series_uid and target.projection == 'lateral':
                    self.status.setText('Lateral image ready. Automatic coronal landmarks do not support this projection; use manual endplates or assisted body segmentation.')
                    self.resultsReady.emit()
            elif kind == 'inference':
                from .geometry import suggest_major_curve
                from .assist_service import image_binding
                if result.get('binding') is not None and result['binding'] != image_binding(target.image):
                    raise ValueError('The image changed. Discarded landmark result.')
                if self._automatic and not result.get('candidates'):
                    raise ValueError('No usable vertebrae detected. Reload the image and select a revised spine region.')
                target.accept_candidates(result)
                self.analysis_progress.update(4, 4, 'Editable vertebral results ready')
                if self._automatic:
                    self._automatic = False
                    self._automatic_visibility(False)
                    self.resultsReady.emit()
                self.status.setText('AI candidates ready. Assign only useful detections to verified levels; confirm required endplates before reporting.')
            elif kind == 'segmentation':
                target.sam.accept_preview(result)
                self.analysis_progress.update(4, 4, 'Segmentation preview ready')
                self.status.setText('SAM preview ready. Inspect the mask and explicitly apply usable endplates.')
            elif kind == 'report':
                self._pending_report_handle = None
                self._server_report_parent = result.get('server_job_id')
                if result.get('remote_analysis'):
                    self.draft.setText('Apply on server / draft PDF')
                self.report_result = result; self.status.setText('PDF, annotated PNG images and measurement JSON are ready in private study storage.')
            elif kind == 'copy': self.status.setText('PDF copy saved.')
        except Exception as exc:
            self._control_error = type(exc).__name__
            from ..eagle_eye_remote.client import DetachedAnalysis, AnalysisFailed
            if kind == 'report' and isinstance(exc, AnalysisFailed):
                self._pending_report_handle = None
                self.draft.setText('Apply on server / draft PDF')
            if kind == 'report' and isinstance(exc, DetachedAnalysis):
                self._pending_report_handle = exc.handle_path
                self.status.setText(str(exc))
                return
            logger.warning('Total Spine task failed: kind=%s error_type=%s', kind, type(exc).__name__)
            self.status.setText(str(exc) if isinstance(exc, (ValueError, KeyError)) else 'Task failed. Check image/model availability and retry.')
        finally:
            if hasattr(self, 'analysis_bar'):
                progress = self.analysis_progress.snapshot()
                if progress is not None and progress[0] == progress[1]:
                    self.analysis_bar.setRange(0, 100); self.analysis_bar.setValue(100)
                    self.analysis_bar.setFormat('Completed')
                else:
                    self.analysis_bar.hide()
            self._refresh()

    def open_annotated_images(self):
        if self.report_result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.report_result['artifact_directory']))

    def open_pdf(self):
        if self.report_result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.report_result['artifact_directory'])/'report.pdf')))

    def save_pdf(self):
        if not self.report_result: return
        path, _ = QFileDialog.getSaveFileName(self, 'Save Total Spine PDF', 'Total-Spine-Alignment.pdf', 'PDF (*.pdf)')
        if path:
            from ..eagle_eye_brain.study_workflow import export_pdf
            if not path.lower().endswith('.pdf'):
                path += '.pdf'
            self._submit('copy', export_pdf, dict(self.report_result), path)

    def teardown(self):
        self._disposed = True; self._cancel.set(); self._timer.stop(); self._fit_timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)
