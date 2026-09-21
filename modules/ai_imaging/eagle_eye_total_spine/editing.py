"""Reader correction primitives; coordinates always refer to the source image."""
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPen, QPainterPath, QPainterPathStroker, QPolygonF
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsSimpleTextItem, QGraphicsItem, QGraphicsPolygonItem
from ..eagle_eye_alignment.widget import LandmarkItem
from .geometry import LEVELS


def numbering_proposal(points, candidates, anchor, candidate_index):
    """Order visible bodies spatially, including an already assigned anchor."""
    bodies = [(('assigned', key), list(value.values())) for key, value in points.items()]
    bodies += [(('candidate', i), item['corners']) for i, item in enumerate(candidates)]
    selected = ('assigned', anchor) if anchor in points else ('candidate', candidate_index)
    bodies.sort(key=lambda item: sum(p[1] for p in item[1]) / len(item[1]))
    keys = [key for key, _ in bodies]
    if selected not in keys:
        raise ValueError('Select an assigned vertebra or a candidate as the anchor.')
    start = LEVELS.index(anchor) - keys.index(selected)
    if start < 0 or start + len(keys) > len(LEVELS):
        raise ValueError('Anchor would extend beyond C1-S1. Remove false detections or correct the anchor.')
    labels = dict(zip(keys, LEVELS[start:start+len(keys)]))
    return ({key: labels['assigned', key] for key in points},
            [labels['candidate', i] for i in range(len(candidates))])


def level_mapping(levels, anchor, target, sequence):
    """Shift known numbering, preserving gaps instead of filling missing bodies."""
    if anchor not in levels or target not in LEVELS:
        raise ValueError('Choose an existing anchor and a valid target level.')
    delta = LEVELS.index(target)-LEVELS.index(anchor)
    result = {}
    for level in levels:
        index = LEVELS.index(level)+(delta if sequence or level == anchor else 0)
        if not 0 <= index < len(LEVELS):
            raise ValueError('The proposed sequence extends beyond C1-S1.')
        result[level] = LEVELS[index]
    if len(set(result.values())) != len(result):
        raise ValueError('This level is occupied. Use sequence correction or choose another level.')
    order = [LEVELS.index(result[k]) for k in sorted(levels, key=LEVELS.index)]
    if order != sorted(order):
        raise ValueError('The proposed level would reverse the existing anatomical order.')
    return result


class SegmentEndpoint(LandmarkItem):
    """Endpoint drag previews its connected line; the editor commits on release."""
    segment = None

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        r = self.view.sceneRect(); p = self.pos()
        self.setPos(max(0, min(p.x(), r.width()-1)), max(0, min(p.y(), r.height()-1)))
        if self.segment is not None:
            a, b = (item.pos() for item in self.segment.handles)
            self.segment.setLine(a.x(), a.y(), b.x(), b.y())


class EditableSegment(QGraphicsLineItem):
    """Drag the segment to translate both endpoints without changing its angle."""
    def __init__(self, level, plate, handles, color, view):
        super().__init__()
        self.level, self.plate, self.handles, self.view = level, plate, handles, view
        self.setZValue(2); self.setCursor(Qt.SizeAllCursor)
        self.setToolTip(f'{level} {plate}: drag line to move; drag endpoints to rotate')
        pen = QPen(QColor(color), 2); pen.setCosmetic(True); self.setPen(pen)
        a, b = (item.pos() for item in handles)
        self.setLine(a.x(), a.y(), b.x(), b.y())
        for item in handles: item.segment = self

    def shape(self):
        path = QPainterPath(); path.moveTo(self.line().p1()); path.lineTo(self.line().p2())
        stroke = QPainterPathStroker()
        stroke.setWidth(12/max(abs(self.view.transform().m11()), .01))
        return stroke.createStroke(path)

    def boundingRect(self):
        return self.shape().boundingRect()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton: event.ignore(); return
        self._start = event.scenePos()
        self._original = [QPointF(item.pos()) for item in self.handles]
        event.accept()

    def mouseMoveEvent(self, event):
        delta = event.scenePos()-self._start; r = self.view.sceneRect()
        xs = [p.x() for p in self._original]; ys = [p.y() for p in self._original]
        dx = max(-min(xs), min(delta.x(), r.width()-1-max(xs)))
        dy = max(-min(ys), min(delta.y(), r.height()-1-max(ys)))
        a, b = [p+QPointF(dx, dy) for p in self._original]
        for item, p in zip(self.handles, (a, b)): item.setPos(p)
        self.setLine(a.x(), a.y(), b.x(), b.y()); event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()
        points = [[p.pos().x(), p.pos().y()] for p in self.handles]
        self.view.segmentChanged.emit(self.level, self.plate, points)


class LevelBadge(QGraphicsSimpleTextItem):
    def __init__(self, level, at, view):
        super().__init__('['+level+'  edit]')
        self.level, self.view = level, view
        self.setBrush(QColor('#ffffff')); self.setPos(*at)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations); self.setZValue(7)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Change this level or anchor a numbering correction')

    def paint(self, painter, option, widget=None):
        painter.fillRect(self.boundingRect(), QColor(12, 21, 34, 220))
        super().paint(painter, option, widget)

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept(); self.view.levelRequested.emit(self.level)


class CandidateBody(QGraphicsPolygonItem):
    """Select or translate an unnumbered body without inventing an anatomical level."""
    def __init__(self, index, corners, view, selected=False, region=False):
        super().__init__(QPolygonF([QPointF(*corners[i]) for i in (0, 1, 3, 2)]))
        self.index, self.corners, self.view, self.region = index, corners, view, region
        self.setZValue(1 if not region else .5)
        self.setCursor(Qt.SizeAllCursor); self.setAcceptHoverEvents(True)
        color = '#fb923c' if region else '#38bdf8'
        pen=QPen(QColor(color), 2 if selected else 1); pen.setCosmetic(True); self.setPen(pen)
        self.setBrush(QColor(56,189,248,25 if selected else 4) if not region else Qt.NoBrush)
        self.setToolTip('Drag border to move the spine region; drag corners to resize' if region else
                        'Click to select for naming; drag body to move; drag endplate endpoints to rotate')

    def shape(self):
        if not self.region:
            return super().shape()
        path=QPainterPath(); path.addPolygon(self.polygon()); path.closeSubpath()
        stroke=QPainterPathStroker(); stroke.setWidth(10/max(abs(self.view.transform().m11()),.01))
        return stroke.createStroke(path)

    def boundingRect(self):
        if not self.region: return super().boundingRect()
        return self.shape().boundingRect()

    def hoverEnterEvent(self,event):
        self.setOpacity(.7); super().hoverEnterEvent(event)

    def hoverLeaveEvent(self,event):
        self.setOpacity(1.); super().hoverLeaveEvent(event)

    def mousePressEvent(self,event):
        if event.button()!=Qt.LeftButton: event.ignore(); return
        self.start=event.scenePos(); event.accept()

    def mouseMoveEvent(self,event):
        delta=event.scenePos()-self.start; r=self.view.sceneRect()
        xs=[p[0] for p in self.corners]; ys=[p[1] for p in self.corners]
        self.setPos(max(-min(xs),min(delta.x(),r.width()-1-max(xs))),
                    max(-min(ys),min(delta.y(),r.height()-1-max(ys))))
        for handle,point in zip(getattr(self,'handles',[]),self.corners):
            handle.setPos(point[0]+self.pos().x(),point[1]+self.pos().y())
        for segment in getattr(self,'segments',[]):
            a,b=(handle.pos() for handle in segment.handles)
            segment.setLine(a.x(),a.y(),b.x(),b.y())
        event.accept()

    def mouseReleaseEvent(self,event):
        event.accept(); delta=self.pos()
        corners=[[x+delta.x(),y+delta.y()] for x,y in self.corners]
        if self.region:
            self.view.regionChanged.emit([corners[0][0],corners[0][1],corners[3][0],corners[3][1]])
        else:
            self.view.candidateChanged.emit(self.index,corners)
