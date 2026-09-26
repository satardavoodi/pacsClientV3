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
    identities = {}
    for value in segment_labels(original, manifest.get('lesion', False)):
        name = manifest.get('label_names', {}).get(str(int(value)), 'Lesion candidates' if manifest.get('lesion') else 'Label ' + str(int(value)))
        segment_id = segmentation.GetSegmentation().AddEmptySegment('', name)
        slicer.util.updateSegmentBinaryLabelmapFromArray(segment_array(original, value), segmentation, segment_id, image)
        identities[segment_id] = int(value)
    slicer.mrmlScene.RemoveNode(labels)
    slicer.util.selectModule('SegmentEditor')
    editor = slicer.modules.segmenteditor.widgetRepresentation().self().editor
    editor.setSegmentationNode(segmentation); editor.setSourceVolumeNode(image)
    slicer.util.setSliceViewerLayers(background=image)
    panel = qt.QDialog(slicer.util.mainWindow())
    panel.setWindowTitle('AI-PACS manual correction')
    panel.setModal(False)
    layout = qt.QVBoxLayout(panel)
    layout.addWidget(qt.QLabel('Edit existing segments. Save here, then recalculate in AI-PACS.'))
    layout.addWidget(qt.QLabel('Select a segment and Paint, Erase or Draw. Hold the left mouse button to edit.\n'
                              'The brush outline shows the area being changed. Use the slice controls to review other slices.'))
    effects = qt.QHBoxLayout()
    for title in ('Paint', 'Erase', 'Draw'):
        effect_button = qt.QPushButton(title)
        effect_button.connect('clicked()', lambda checked=False, name=title: editor.setActiveEffectByName(name))
        effects.addWidget(effect_button)
    layout.addLayout(effects)
    open_editor = qt.QPushButton('Open Segment Editor')
    open_editor.connect('clicked()', lambda: slicer.util.selectModule('SegmentEditor'))
    layout.addWidget(open_editor)
    button = qt.QPushButton('Save correction for AI-PACS')
    layout.addWidget(button)
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
            slicer.util.infoDisplay('Saved. Return to AI-PACS and click Recalculate corrected report.')
        except Exception as exc:
            slicer.util.errorDisplay(str(exc))
    button.connect('clicked()', save)
    panel.show()
    slicer._aipacsManualReviewPanel = panel


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        (Path(os.environ['AIPACS_MANUAL_REVIEW']) / 'editor-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
