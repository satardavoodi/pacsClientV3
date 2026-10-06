"""Interactive isolated Slicer review with explicit label-preserving export."""
import os
import json
from pathlib import Path


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
    directory = Path(os.environ['AIPACS_MANUAL_REVIEW'])
    manifest = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    image = slicer.util.loadVolume(str(directory / 'image.nii.gz'))
    labels = slicer.util.loadLabelVolume(str(directory / 'original.nii.gz'))
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
    slicer.util.setSliceViewerLayers(background=image)
    panel = qt.QWidget(editor_widget)
    panel.setObjectName('AIPacsManualCorrectionPanel')
    layout = qt.QVBoxLayout(panel)
    layout.setContentsMargins(4, 8, 4, 8)
    layout.setSpacing(6)
    title = qt.QLabel('AI-PACS | Segmentation correction')
    title.setStyleSheet('font-weight: bold; color: #60a5fa;')
    layout.addWidget(title)
    hint = qt.QLabel('Select any segment below, edit its boundary, then save the correction.')
    hint.setWordWrap(True)
    layout.addWidget(hint)
    effects = qt.QHBoxLayout()
    for title in ('Paint', 'Erase', 'Draw'):
        effect_button = qt.QPushButton(title)
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
    slicer._aipacsManualReviewPanel = panel


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        (Path(os.environ['AIPACS_MANUAL_REVIEW']) / 'editor-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
