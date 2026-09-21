"""Reader-selected single-body SAM preview and explicit endplate acceptance."""
from copy import deepcopy
import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QColor, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel

from .mask_geometry import validate_box
from .assist_service import image_binding


class SamControls(QWidget):
    requested = Signal(object)

    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.box = None
        self.first = None
        self.preview = None
        self.graphics = []
        layout = QVBoxLayout(self)
        self.choose = QPushButton('Select body box for SAM')
        self.run = QPushButton('Segment selected body')
        self.apply = QPushButton('Use proposed endplates for selected level')
        self.clear = QPushButton('Clear SAM preview')
        self.status = QLabel('SAM: select a C1-L5 level and box one vertebral body. S1 uses manual landmarks.')
        self.status.setWordWrap(True)
        for widget in (self.choose, self.run, self.apply, self.clear, self.status):
            layout.addWidget(widget)
        self.run.setEnabled(False); self.apply.setEnabled(False)
        self.choose.clicked.connect(self.select_box)
        self.run.clicked.connect(lambda: self.requested.emit(self.editor))
        self.apply.clicked.connect(self.accept_endplates)
        self.clear.clicked.connect(self.reset)
        editor.level.currentIndexChanged.connect(self.reset)

    def reset(self, *_):
        for item in self.graphics:
            self.editor.canvas.scene().removeItem(item)
        self.graphics = []
        self.box = self.first = self.preview = None
        self.run.setEnabled(False); self.apply.setEnabled(False)
        self.editor._manual_changed()
        self.status.setText('Select a vertebral level and box one body for a new SAM proposal.')

    def select_box(self):
        self.reset()
        if self.editor.image is None:
            self.status.setText('Load an image first.'); return
        if self.editor.level.currentText() == 'S1':
            self.status.setText('Place S1 superior endplate landmarks manually.'); return
        self.editor.corner.setCurrentIndex(0)
        self.editor.canvas.manual_target = ('sam', 'box')
        self.status.setText('Click two opposite corners of a box enclosing only the vertebral body.')

    def add_box_point(self, x, y):
        if self.first is None:
            self.first = (x, y)
            self.status.setText('Now click the opposite box corner.')
            return
        a, b = self.first
        box = [min(a, x), min(b, y), max(a, x), max(b, y)]
        self.first = None
        try:
            validate_box(box, self.editor.image['pixels'].shape)
        except ValueError as exc:
            self.status.setText(str(exc)); return
        self.box = box
        self.editor.canvas.manual_target = None
        pen = QPen(QColor('#fb923c'), 2); pen.setCosmetic(True)
        item = self.editor.canvas.scene().addRect(box[0], box[1], box[2]-box[0], box[3]-box[1], pen)
        item.setZValue(2); self.graphics.append(item)
        self.run.setEnabled(True)
        self.status.setText('Box ready. Confirm acquisition, then segment this body.')

    def accept_preview(self, result):
        image = self.editor.image
        if (image is None or result['binding'] != image_binding(image) or
                result['level'] != self.editor.level.currentText()):
            raise ValueError('The image or selected vertebral level changed. Discarded SAM result.')
        # Remove the previous mask/box before painting the replacement.
        self.reset()
        self.preview = result
        self.box = list(result['box'])
        mask = result['mask']
        rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
        rgba[mask] = [34, 197, 94, 85]
        h, w = mask.shape
        image_qt = QImage(rgba.data, w, h, w*4, QImage.Format_RGBA8888).copy()
        item = self.editor.canvas.scene().addPixmap(QPixmap.fromImage(image_qt))
        item.setPos(*result['origin']); item.setZValue(.5); self.graphics.append(item)
        proposal = result.get('proposal')
        if proposal:
            p = proposal['points']
            pen = QPen(QColor('#fb923c'), 2); pen.setCosmetic(True)
            for endplate in ('superior', 'inferior'):
                line = self.editor.canvas.scene().addLine(*p[endplate+'_left'], *p[endplate+'_right'], pen)
                line.setZValue(2); self.graphics.append(line)
        self.apply.setEnabled(proposal is not None)
        self.run.setEnabled(True)
        quality = f"SAM estimated mask quality: {result['score']:.2f} (not clinical accuracy). "
        self.status.setText(quality + (result['proposal_error'] or
            'Review the green mask and orange endplates. Apply, then drag blue points to correct.'))

    def accept_endplates(self):
        result = self.preview
        image = self.editor.image
        if not result or not result.get('proposal'):
            return
        if (image is None or not self.editor.confirm.isChecked() or
                result['binding'] != image_binding(image) or result['level'] != self.editor.level.currentText()):
            self.status.setText('Reconfirm the current image and vertebral level before applying.'); return
        level = result['level']
        self.editor._remember_edit()
        self.editor.rotations = [r for r in self.editor.rotations if r['level'] != level]
        self.editor.points[level] = deepcopy(result['proposal']['points'])
        provenance = self.editor.provenance
        provenance.setdefault('per_level', {})[level] = dict(
            method=result['model'], weight_sha256=result['weight_sha256'], mask_sha256=result['mask_sha256'],
            box=result['box'], mask_score=result['score'], fit=result['proposal'], reader_applied=True)
        provenance['model'] = 'Editable landmarks with SAM-assisted per-level endplates'
        self.editor.canvas.set_points(self.editor.points, self.editor.markers, self.editor.pedicles)
        self.editor.invalidate()
        # Preview contours must not remain over the subsequently editable lines.
        self.reset()
        self.status.setText('Endplates applied. Check both lines on the source image and correct the blue handles.')
