"""Synthetic guards for reference proposals and visible measurement evidence."""
import hashlib
import json
from pathlib import Path
import pytest
from test_eagle_eye_total_spine import view, body, qapp
from modules.ai_imaging.eagle_eye_total_spine.measurements import measure_view
from modules.ai_imaging.eagle_eye_total_spine.annotations import overlay_primitives, annotated_image


def reference_view():
    v = view()
    v['markers'] = {'Sacral center': [240, 950], 'C7 center': [250, 30]}
    v['points'].update(L1=body(245, 780), L2=body(240, 840))
    v['rotations'] = [dict(level='T12', grade=0, direction='none')]
    return v


def test_csvl_candidates_use_available_anatomy_and_reader_rotation():
    v = reference_view(); a = measure_view(v)['curves'][0]['coronal_assessment']
    assert a['apex_csvl_candidate'] == 'T8'
    assert a['last_touched_candidate'] == 'T12'  # Cephalad, not the lowest touched level.
    assert a['stable_candidate'] == 'T12'
    assert a['neutral_candidate'] == 'T12'
    assert a['reader']['stable'] is None
    v['rotations'] = []
    assert measure_view(v)['curves'][0]['coronal_assessment']['neutral_candidate'] is None
    v['markers'] = {}
    assert measure_view(v)['curves'][0]['coronal_assessment']['apex_csvl_candidate'] is None


def test_visible_evidence_names_endplates_and_preserves_physical_angle():
    v = reference_view(); v['image']['spacing'] = (2., 1.)
    measured = measure_view(v); overlay = overlay_primitives(v, measured)
    text = ' '.join(x['text'] for x in overlay['labels'])
    assert 'T4 superior' in text and 'T12 inferior' in text and 'CSVL' in text
    assert 'Apex T8 (reader)' in text and 'Nash-Moe 0' in text
    assert measured['curves'][0]['cobb_deg'] > 60
    image = annotated_image(v, measured)
    assert image.width == 1250  # 600 px aspect-correct image plus 650 px summary.
    assert len(overlay['lines']) >= 7


def test_live_canvas_recalculates_and_clears_stale_overlays(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    e = ProjectionEditor('coronal'); v = reference_view()
    e.accept_image(v['image']); e.points = v['points']; e.curves = v['curves']; e.markers = v['markers']
    e.recalculate()
    assert e.canvas._measurement_items
    old = e.canvas._measurement_items[0]
    e.points['T4']['superior_right'][1] += 5; e.recalculate()
    assert old.scene() is None
    e.points['T4'].pop('superior_right'); e.recalculate()
    assert not e.canvas._measurement_items
    e.clear_image(); e.close()


def test_png_export_is_bound_to_json_and_pdf(tmp_path, qapp):
    from modules.ai_imaging.eagle_eye_total_spine.report import generate_report
    v = reference_view()
    folder = Path(generate_report([v], '1.2.3', root=tmp_path)['artifact_directory'])
    data = json.loads((folder/'report.json').read_text())
    artifact = data['views'][0]['annotated_image']
    assert hashlib.sha256((folder/artifact['filename']).read_bytes()).hexdigest() == artifact['sha256']
    assert 'Annotated measurement evidence' in (folder/'report.html').read_text()
