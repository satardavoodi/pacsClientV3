"""Interactive isolated Slicer review with explicit label-preserving export."""
import os
import json
import time
from pathlib import Path


def review_group(name, lesion=False):
    """Display-only grouping. Never merge labels or infer lobar measurements."""
    if lesion:
        return 'White-matter lesion candidates'
    name = name.lower().replace('-', ' ').replace('_', ' ')
    compact = name.replace(' ', '')
    for terms, group in (
        (('hippocamp', 'amygdala', 'entorhinal', 'parahippocamp'), 'Medial temporal'),
        (('cerebell',), 'Cerebellum'),
        (('caudate', 'putamen', 'pallid', 'accumbens'), 'Basal ganglia'),
        (('thalam', 'ventraldc'), 'Thalamus / Diencephalon'),
        (('brainstem',), 'Brainstem'),
        (('ventricle', 'csf', 'choroid'), 'CSF / Ventricles'),
        (('whitematter', 'corpuscallosum'), 'Cerebral white matter'),
        (('cingulate',), 'Cortex / Cingulate'),
        (('insula',), 'Cortex / Insula'),
        (('frontal', 'parsopercularis', 'parstriangularis', 'parsorbitalis',
          'precentral', 'paracentral'), 'Cortex / Frontal'),
        (('parietal', 'supramarginal', 'postcentral', 'precuneus'), 'Cortex / Parietal'),
        (('temporal', 'bankssts', 'fusiform'), 'Cortex / Temporal'),
        (('occipital', 'lingual', 'cuneus', 'pericalcarine'), 'Cortex / Occipital'),
        (('cortex', 'ctx'), 'Cortex / Other'),
    ):
        if any(term in compact for term in terms):
            return group
    return 'Other structures'


def paired_layout_xml():
    xml = '<layout type="vertical">'
    for orientation in ('Axial', 'Coronal', 'Sagittal'):
        xml += '<item><layout type="horizontal">'
        for role, title in (('Raw', 'Raw'), ('Overlay', 'Segmentation')):
            xml += ('<item><view class="vtkMRMLSliceNode" singletontag="BrainReview%s%s">'
                    '<property name="orientation" action="default">%s</property>'
                    '<property name="viewlabel" action="default">%s | %s</property>'
                    '</view></item>') % (orientation, role, orientation, orientation, title)
        xml += '</layout></item>'
    return xml + '</layout>'


def configure_review_display(display, overlay_ids):
    display.SetAllSegmentsVisibility(False)
    display.RemoveAllViewNodeIDs()
    for node_id in overlay_ids:
        display.AddViewNodeID(node_id)
    display.SetOpacity2DFill(0.15)
    display.SetOpacity2DOutline(1.0)


def remove_review_observers(observers):
    """Release paired-navigation and visibility callbacks with their panel."""
    for node, tag, callback in observers:
        node.RemoveObserver(tag)


def retain_review_state(owner, panel, state):
    """PythonQt widgets reject arbitrary Python attributes in packaged Slicer."""
    owner._aipacsManualReviewPanel = panel
    owner._aipacsManualReviewState = state


def reveal_review_window(slicer, window):
    """Release the early startup guard for both readiness and visible failures."""
    guard = getattr(slicer, '_aipacsBrainVisibilityGuard', None)
    if guard is not None:
        guard.release(window)
    else:
        window.show()


def publish_review_state(status):
    """Atomic, launch-bound acknowledgement; never include patient data."""
    token = os.environ.get('AIPACS_MANUAL_REVIEW_TOKEN')
    directory = os.environ.get('AIPACS_MANUAL_REVIEW')
    if not token or not directory:
        return
    target = Path(directory) / 'editor-state.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'token': token, 'status': status}), encoding='utf-8')
    temporary.replace(target)


def _qt_value(owner, name):
    """Support PythonQt properties and ordinary Qt getter methods."""
    value = getattr(owner, name)
    return value() if callable(value) else value


# Shared presentation is staged beside this script for the separate native process.
_chrome_module = None


def common_chrome():
    global _chrome_module
    if _chrome_module is None:
        import importlib.util
        path = Path(__file__).with_name('viewer_chrome.py')
        if not path.is_file():
            path = Path(__file__).resolve().parents[2] / 'mpr/advanced_3d_slicer/slicer_custom_app/viewer_chrome.py'
        spec = importlib.util.spec_from_file_location('aipacs_viewer_chrome', path)
        _chrome_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_chrome_module)
    return _chrome_module


def review_tool_icon(qt, name):
    return common_chrome().review_tool_icon(qt, name)


def brand_review_editor(qt, editor):
    return common_chrome().brand_review_editor(qt, editor)


def brand_review_chrome(qt, window):
    return common_chrome().install(qt, window)


def prepare_presentation(qt, slicer, window):
    """Let queued layout constraints settle before exposing the editor frame."""
    window.setAttribute(qt.Qt.WA_DontShowOnScreen, True)
    window.ensurePolished()
    window.show()  # Logical show calculates dock/layout sizes off desktop.
    started = time.monotonic()
    previous, unchanged = None, 0

    def settle():
        nonlocal previous, unchanged
        try:
            layout = window.layout()
            if layout is not None:
                layout.activate()
            sizes = [_qt_value(window, name) for name in ('size', 'minimumSizeHint', 'sizeHint')]
            signature = tuple(_qt_value(size, axis) for size in sizes for axis in ('width', 'height'))
            unchanged = unchanged + 1 if signature == previous else 0
            previous = signature
            if unchanged < 3 and time.monotonic() - started < 2:
                qt.QTimer.singleShot(50, settle)
                return
            slicer.util.resetSliceViews()
            if getattr(slicer, '_aipacsBrainVisibilityGuard', None) is None:
                window.setAttribute(qt.Qt.WA_DontShowOnScreen, False)
            reveal_review_window(slicer, window)
            publish_review_state('ready')
        except Exception:
            show_review_failure(slicer)

    qt.QTimer.singleShot(0, settle)


def show_review_failure(slicer):
    """Keep initialization errors visible, or exit when no UI can be constructed."""
    publish_review_state('error')
    window = slicer.util.mainWindow()
    if window is None:
        slicer.app.quit()
        return
    reveal_review_window(slicer, window)
    slicer.util.errorDisplay('Brain review could not be initialized. See editor-error.txt in the review session.')


def install_paired_views(slicer, image, segmentation):
    """Pair navigation while keeping segmentation out of all raw panes."""
    manager = slicer.app.layoutManager()
    manager.layoutLogic().GetLayoutNode().AddLayoutDescription(989, paired_layout_xml())
    manager.setLayout(989)
    pairs, observers = [], []
    busy = [False]

    def sync(source, target):
        if busy[0]:
            return
        busy[0] = True
        try:
            target.GetSliceToRAS().DeepCopy(source.GetSliceToRAS())
            target.SetFieldOfView(*source.GetFieldOfView())
            target.SetXYZOrigin(*source.GetXYZOrigin())
            target.UpdateMatrices()
        finally:
            busy[0] = False

    for orientation in ('Axial', 'Coronal', 'Sagittal'):
        widgets = [manager.sliceWidget('BrainReview' + orientation + role)
                   for role in ('Raw', 'Overlay')]
        for widget in widgets:
            composite = widget.mrmlSliceCompositeNode()
            composite.SetBackgroundVolumeID(image.GetID())
            composite.SetForegroundVolumeID(None)
            composite.SetLabelVolumeID(None)
            composite.SetLinkedControl(False)
        raw, overlay = [widget.mrmlSliceNode() for widget in widgets]
        pairs.append((raw, overlay))
        for source, target in ((raw, overlay), (overlay, raw)):
            callback = lambda caller, event, target=target: sync(caller, target)
            observers.append((source, source.AddObserver('ModifiedEvent', callback), callback))
    configure_review_display(segmentation.GetDisplayNode(), [pair[1].GetID() for pair in pairs])
    slicer.util.resetSliceViews()
    return pairs, observers


def replace_native_segment_list(native, container):
    """Reuse Slicer's table frame and height grip; keep the native model alive."""
    native.parent().layout().replaceWidget(native, container)
    native.hide()
    container.show()


def install_anatomy_browser(qt, editor, segmentation, identities, lesion=False):
    """Checkboxes control visibility; selecting a leaf chooses the edit target."""
    import slicer
    native = slicer.util.findChild(editor, 'SegmentsTableView')
    container = qt.QWidget(native.parent())
    container.setObjectName('AIPacsBrainSegmentList')
    layout = qt.QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    tree = qt.QTreeWidget(container)
    tree.setObjectName('AIPacsBrainAnatomyTree')
    tree.setHeaderLabels(['Name'])
    tree.setMinimumHeight(260)
    tree.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
    tree.setToolTip('Expand an anatomical group. Check visibility or select a segment to edit. '
                    'Drag the lower edge of this list to change its height.')
    tree.setAlternatingRowColors(True)
    leaves, groups = {}, {}
    display = segmentation.GetDisplayNode()
    for segment_id in identities:
        segment = segmentation.GetSegmentation().GetSegment(segment_id)
        group = review_group(segment.GetName(), lesion)
        if group not in groups:
            parent = qt.QTreeWidgetItem(tree, [group])
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            parent.setFlags(parent.flags() | qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsAutoTristate)
            parent.setCheckState(0, qt.Qt.Unchecked)
            groups[group] = parent
        leaf = qt.QTreeWidgetItem(groups[group], [segment.GetName()])
        leaf.setFlags(leaf.flags() | qt.Qt.ItemIsUserCheckable)
        leaf.setCheckState(0, qt.Qt.Unchecked)
        leaf.setData(0, qt.Qt.UserRole, segment_id)
        color = qt.QColor.fromRgbF(*segment.GetColor())
        swatch = qt.QPixmap(12, 12)
        swatch.fill(color)
        leaf.setIcon(0, qt.QIcon(swatch))
        leaves[segment_id] = leaf
    tree.sortItems(0, qt.Qt.AscendingOrder)

    def changed(item, column):
        segment_id = item.data(0, qt.Qt.UserRole)
        if segment_id in identities:
            display.SetSegmentVisibility(segment_id, item.checkState(0) == qt.Qt.Checked)

    def selected(item, previous):
        if item is None:
            return
        segment_id = item.data(0, qt.Qt.UserRole)
        if segment_id in identities:
            item.setCheckState(0, qt.Qt.Checked)
            editor.setCurrentSegmentID(segment_id)

    def refresh(caller=None, event=None):
        tree.blockSignals(True)
        try:
            for segment_id, leaf in leaves.items():
                leaf.setCheckState(0, qt.Qt.Checked if display.GetSegmentVisibility(segment_id)
                                   else qt.Qt.Unchecked)
        finally:
            tree.blockSignals(False)

    tree.connect('itemChanged(QTreeWidgetItem*,int)', changed)
    tree.connect('currentItemChanged(QTreeWidgetItem*,QTreeWidgetItem*)', selected)
    observer = display.AddObserver('ModifiedEvent', refresh)
    layout.addWidget(tree)
    hide = qt.QPushButton('Hide all regions')
    hide.connect('clicked()', lambda: display.SetAllSegmentsVisibility(False))
    layout.addWidget(hide)
    replace_native_segment_list(native, container)
    # Keep PythonQt callbacks alive for the lifetime of the review panel.
    return tree, (display, observer, refresh), (changed, selected)


def segment_array(labels, value):
    import numpy as np
    return (labels == value).astype(np.uint8)


def segment_labels(labels, lesion=False):
    import numpy as np
    return [1] if lesion else [int(value) for value in np.unique(labels) if value != 0]


def install_review_controls(editor_widget, panel):
    """Keep correction controls inside the native Segment Editor module panel."""
    editor_widget.layout().insertWidget(0, panel)
    panel.show()



def import_segments(slicer, labels, segmentation, original, names, lesion=False):
    """Import the shared labelmap once; retain sparse anatomical label values."""
    expected = set(segment_labels(original, lesion))
    if not original.any():
        if lesion:
            return {segmentation.GetSegmentation().AddEmptySegment('', 'Lesion candidates'): 1}
        return {}
    if not slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labels, segmentation):
        raise ValueError('Could not import the original segmentation.')
    container = segmentation.GetSegmentation()
    identities = {}
    for segment_id in container.GetSegmentIDs():
        segment = container.GetSegment(segment_id)
        value = int(segment.GetLabelValue())
        if value not in expected or value in identities.values():
            raise ValueError('Imported segmentation label identity does not match the original.')
        segment.SetName(names.get(str(value), 'Lesion candidates' if lesion else 'Label ' + str(value)))
        identities[segment_id] = value
    if lesion and not identities:
        identities[container.AddEmptySegment('', 'Lesion candidates')] = 1
    if set(identities.values()) != expected:
        raise ValueError('Imported segmentation is missing original labels.')
    return identities


def main():
    import numpy as np
    import qt
    import slicer
    # --no-main-window disables construction entirely and cannot be used here.
    # The Windows launcher starts hidden; keep the real window hidden during IO.
    window = slicer.util.mainWindow()
    if window is None:
        raise RuntimeError('Interactive brain review requires a constructed Slicer main window.')
    window.hide()
    directory = Path(os.environ['AIPACS_MANUAL_REVIEW'])
    (directory / 'editor-process.json').write_text(
        json.dumps({'pid': os.getpid(), 'script': str(Path(__file__).resolve())}), encoding='utf-8')
    manifest = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    image = slicer.util.loadVolume(str(directory / 'image.nii.gz'))
    input_mask = directory / 'editor-input.nii.gz'
    labels = slicer.util.loadLabelVolume(str(input_mask if input_mask.is_file() else directory / 'original.nii.gz'))
    original = slicer.util.arrayFromVolume(labels).copy()
    segmentation = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLSegmentationNode', 'Manual correction')
    segmentation.CreateDefaultDisplayNodes()
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(image)
    slicer.app.pauseRender()
    modifying = segmentation.StartModify()
    try:
        identities = import_segments(slicer, labels, segmentation, original,
                                     manifest.get('label_names', {}), manifest.get('lesion', False))
    finally:
        segmentation.EndModify(modifying)
        slicer.app.resumeRender()
    slicer.mrmlScene.RemoveNode(labels)
    slicer.util.selectModule('SegmentEditor')
    editor_widget = slicer.modules.segmenteditor.widgetRepresentation()
    editor = editor_widget.self().editor
    editor.setSegmentationNode(segmentation); editor.setSourceVolumeNode(image)
    pairs, observers = install_paired_views(slicer, image, segmentation)
    panel = qt.QWidget(editor_widget)
    panel.setObjectName('AIPacsManualCorrectionPanel')
    layout = qt.QVBoxLayout(panel)
    layout.setContentsMargins(4, 8, 4, 8)
    layout.setSpacing(6)
    title = qt.QLabel('AI-PACS | Brain segmentation review')
    title.setStyleSheet('font-weight: bold; color: #60a5fa;')
    layout.addWidget(title)
    hint = qt.QLabel('Left: raw image. Right: segmentation. Select a region to show and edit it. '
                    'All regions start hidden; display selection does not change volumes.')
    hint.setWordWrap(True)
    layout.addWidget(hint)
    browser = install_anatomy_browser(qt, editor, segmentation, identities,
                                     manifest.get('lesion', False))
    effects = qt.QHBoxLayout()
    for title in ('Paint', 'Erase', 'Draw'):
        effect_button = qt.QPushButton(title)
        effect_button.setIcon(review_tool_icon(qt, title))
        effect_button.connect('clicked()', lambda checked=False, name=title: editor.setActiveEffectByName(name))
        effects.addWidget(effect_button)
    layout.addLayout(effects)
    button = qt.QPushButton('Save correction for AI-PACS')
    layout.addWidget(button)
    status = qt.QLabel('Saved corrections can be applied on the server from AI-PACS.')
    status.setWordWrap(True)
    layout.addWidget(status)
    def save():
        try:
            if segmentation.GetSegmentation().GetNumberOfSegments() != len(identities):
                raise ValueError('Edit existing segments; do not add or delete segment identities.')
            values = np.zeros(original.shape, dtype=original.dtype)
            for segment_id, value in identities.items():
                if segmentation.GetSegmentation().GetSegment(segment_id) is None:
                    raise ValueError('An original segment identity was removed.')
                mask = slicer.util.arrayFromSegmentBinaryLabelmap(segmentation, segment_id, image).astype(bool)
                if np.any(mask & (values != 0)):
                    raise ValueError('Segments overlap. Resolve overlap before saving.')
                values[mask] = value
            node = slicer.modules.volumes.logic().CreateAndAddLabelVolume(slicer.mrmlScene, image, 'Corrected labels')
            slicer.util.updateVolumeFromArray(node, values)
            if not slicer.util.saveNode(node, str(directory / 'corrected.nii.gz')):
                raise ValueError('Correction could not be saved.')
            slicer.mrmlScene.RemoveNode(node)
            status.setText('Correction saved. Return to AI-PACS and click Apply mask on server '
                           '(or Recalculate corrected report for a local analysis).')
        except Exception as exc:
            status.setText('Correction was not saved: ' + str(exc))
        finally:
            button.setEnabled(True)
            button.setText('Save correction for AI-PACS')
    def request_save():
        button.setEnabled(False)
        button.setText('Saving correction...')
        status.setText('Preparing the corrected labelmap. Please wait.')
        button.repaint()
        qt.QTimer.singleShot(0, save)
    button.connect('clicked()', request_save)
    install_review_controls(editor_widget, panel)
    chrome = brand_review_chrome(qt, window)
    branding = chrome.editor
    retain_review_state(slicer, panel, (pairs, observers, browser, branding, chrome))
    panel.connect('destroyed(QObject*)',
                  lambda *args: remove_review_observers(observers + [browser[1]]))
    # Finish queued native layout work before the first desktop-visible frame.
    prepare_presentation(qt, slicer, window)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        (Path(os.environ['AIPACS_MANUAL_REVIEW']) / 'editor-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        import slicer
        show_review_failure(slicer)
        raise
