"""Bounded GUI-only inspection and redacted control pixels; no clinical canvas."""
import hashlib
import json
import re
from uuid import uuid4

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtWidgets import (QApplication,QAbstractButton,QComboBox,QLineEdit,
    QAbstractSpinBox,QSlider,QWidget,QTabWidget)
from .secretary_ui_source_catalog import SOURCE_CATALOG

RECORDS=SOURCE_CATALOG['controls']
LABELS={str(r.get(key) or '').strip() for r in RECORDS if not r['sensitive']
        for key in ('label','setToolTip','setPlaceholderText','setAccessibleName','setText')}
LABELS.update(option for r in RECORDS if not r['sensitive'] for option in r['options'])
LABELS.discard('')
NAMES={r['name'].split('.')[-1] for r in RECORDS}
SENSITIVE=re.compile(r'password|credential|api.?key|secret|token|license.?key',re.I)


def assert_gui():
    from PySide6.QtCore import QThread
    app=QApplication.instance()
    if app is None or QThread.currentThread()!=app.thread():
        raise RuntimeError('UI observation requires the GUI thread')


def _name(widget):
    parent=widget.parent()
    candidates=[widget]
    for _ in range(8):
        if parent is None:break
        for key,value in vars(parent).items():
            if any(value is candidate for candidate in candidates) and key in NAMES:return key
        if type(parent).__name__ in ('LoginLineField','LoginComboField','LoginDateField','LoginNumberField','CustomCheckbox'):
            candidates.append(parent)
        parent=parent.parent()
    name=widget.objectName()
    return name if name in NAMES else ''


def collect(root):
    assert_gui()
    if not isinstance(root,QWidget) or not root.isVisible():
        raise ValueError('The requested UI surface is not visible')
    controls=[];handles=[]
    hidden=[]
    widgets=root.findChildren(QWidget)
    truncated=False
    for widget in widgets:
        if not isinstance(widget,(QAbstractButton,QComboBox,QLineEdit,QAbstractSpinBox,QSlider)) or not widget.isVisibleTo(root):continue
        if len(controls)>=100:
            truncated=True;break
        name=_name(widget)
        hints=[widget.accessibleName(),widget.toolTip()]
        if isinstance(widget,QAbstractButton):hints.insert(0,widget.text())
        if isinstance(widget,QLineEdit):hints.append(widget.placeholderText())
        sensitive=bool(SENSITIVE.search(name+' '+' '.join(hints)))
        if isinstance(widget,QLineEdit) and widget.echoMode()!=QLineEdit.Normal:sensitive=True
        label=next((h.strip() for h in hints if h.strip() in LABELS),'') if not sensitive else ''
        point=widget.mapTo(root,QPoint(0,0))
        row={'control_id':str(len(controls)+1),'kind':type(widget).__name__,
            'name':name if not sensitive else '', 'label':label or (name if not sensitive and name else 'Unlabelled control'),
            'enabled':widget.isEnabled(),'visible':True,'local_only':sensitive,
            'bounds':[point.x(),point.y(),widget.width(),widget.height()],
            'execution':'use_registered_typed_action_only'}
        safe_pixels=bool(label) and not sensitive
        if isinstance(widget,QComboBox):
            row['options']=[{'index':i,'label':widget.itemText(i) if widget.itemText(i) in LABELS else 'Local-only option'}
                            for i in range(min(widget.count(),100))]
            row['options_truncated']=widget.count()>100
            row['current_index']=widget.currentIndex()
            safe_pixels=safe_pixels and widget.currentText() in LABELS
        elif isinstance(widget,QAbstractButton):
            row['checked']=widget.isChecked() if widget.isCheckable() else None
            safe_pixels=safe_pixels and (not widget.text() or widget.text() in LABELS)
        else:
            row['value']='redacted'
            safe_pixels=False
            if isinstance(widget,QSlider):row['range']=[widget.minimum(),widget.maximum()]
        controls.append(row);handles.append((widget,safe_pixels))
        if not sensitive and isinstance(widget,(QLineEdit,QAbstractSpinBox)):
            hidden.append(widget.text())
    # Only static software navigation labels may leave the client.
    navigation_labels = {'Server Settings','Viewer Configuration','AI','Installation & Updates',
        'Consultation & Education','Tools Settings','Image Filter','Light Viewer','EchoMind',
        'Eagle Eye','Agent','Local','Server','Import'}
    navigation = []
    for tabs in [root, *root.findChildren(QTabWidget)]:
        if not isinstance(tabs,QTabWidget) or not tabs.isVisibleTo(root):
            continue
        label = tabs.tabText(tabs.currentIndex())
        navigation.append({'current_label':label if label in navigation_labels else 'Local-only page',
                           'current_index':tabs.currentIndex()})
        if len(navigation) >= 20:
            break
    # Include object identity locally so replacement of a visually identical page invalidates a capture.
    nonce=getattr(root,'_secretary_ui_binding_nonce',None)
    if nonce is None:
        nonce=uuid4().hex;root._secretary_ui_binding_nonce=nonce
    digest=hashlib.sha256(json.dumps([nonce,id(root),[id(w) for w,_ in handles],controls,hidden,navigation,
        str(getattr(root,'study_uid','') or '')],sort_keys=True).encode()).hexdigest()
    return {'version':1,'snapshot_id':str(uuid4()),'context_digest':digest,
            'scope':'redacted_controls_only_no_clinical_images','controls':controls,'navigation':navigation,
            'truncated':truncated,'width':root.width(),'height':root.height()},handles


def capture(root):
    metadata,handles=collect(root)
    width,height=metadata['width'],metadata['height']
    if not 0<width<=4096 or not 0<height<=2160:raise ValueError('UI surface exceeds capture bounds')
    image=QImage(width,height,QImage.Format_RGB32);image.fill(QColor('#101a28'))
    painter=QPainter(image)
    try:
        for row,(widget,safe) in zip(metadata['controls'],handles):
            x,y,w,h=row['bounds']
            if safe:
                painter.drawPixmap(x,y,widget.grab())
            else:
                painter.fillRect(x,y,w,h,QColor('#26364a'))
        painter.setPen(QColor('#9bb2c8'))
        painter.drawText(8,16,'Redacted UI controls; clinical images and field values excluded')
    finally:painter.end()
    return metadata,image.copy()


def encode(metadata,image):
    """Detached QImage encoding belongs on a worker, with no QObject access."""
    from modules.Identity.thread_guard import assert_off_gui_thread
    from PySide6.QtCore import QBuffer,QByteArray,QIODevice
    import base64
    assert_off_gui_thread('Secretary UI image encoding')
    if image.width()>1024 or image.height()>768:
        image=image.scaled(1024,768,Qt.KeepAspectRatio,Qt.SmoothTransformation)
    data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer,'PNG'):raise ValueError('UI image encoding failed')
    raw=bytes(data)
    if len(raw)>98304:raise ValueError('Redacted UI image exceeds size limit')
    return {'version':1,'snapshot_id':metadata['snapshot_id'],'context_digest':metadata['context_digest'],
        'sha256':hashlib.sha256(raw).hexdigest(),'width':image.width(),'height':image.height(),
        'scope':metadata['scope'],'image':base64.b64encode(raw).decode('ascii')}
