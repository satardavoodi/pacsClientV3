"""Synthetic geometry guards for the independent spatial-input experiment."""
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image


def _plane(identifier, block, origin, orientation, member):
    from tools.eagle_eye_bench.spatial_packet import SlicePlane
    return SlicePlane(identifier, block, member, origin, orientation, (1., 1.),
                      (20, 20), 'synthetic-shared-frame')


def test_spatial_order_uses_plane_normal_and_preserves_all_members():
    from tools.eagle_eye_bench.spatial_packet import build_manifest
    orientation = (0., 1., 0., 0., 0., -1.)
    planes = [_plane('s3', 'sag-central', (6., 0., 20.), orientation, 3),
              _plane('s1', 'sag-central', (0., 0., 20.), orientation, 1),
              _plane('s2', 'sag-central', (3., 0., 20.), orientation, 2)]
    doc = build_manifest(planes, {'sag-central': [1, 2, 3]})
    block = doc['blocks'][0]
    assert block['ordered_image_ids'] == ['s1', 's2', 's3']
    assert block['adjacent_plane_distances_mm'] == [3., 3.]
    assert block['order_direction'] == 'patient_right_to_left'
    assert 'synthetic-shared-frame' not in str(doc)


def test_spatial_packet_rejects_missing_members_and_cross_frame_geometry():
    from tools.eagle_eye_bench.spatial_packet import build_manifest
    a = _plane('a', 'ax', (0., 0., 0.), (1., 0., 0., 0., 1., 0.), 1)
    with pytest.raises(ValueError, match='membership'):
        build_manifest([a], {'ax': [1, 2]})
    with pytest.raises(ValueError, match='reference'):
        build_manifest([a, replace(a, image_id='b', member=2, reference_key='other')], {'ax':[1,2]})


def test_separate_groups_cannot_be_collapsed_by_sorting():
    from tools.eagle_eye_bench.spatial_packet import build_manifest
    orientation = (1., 0., 0., 0., 1., 0.)
    planes = [_plane('a', 'ax-one', (0., 0., 30.), orientation, 1),
              _plane('b', 'ax-two', (0., 0., 10.), orientation, 2)]
    doc = build_manifest(planes, {'ax-one':[1], 'ax-two':[2]})
    assert len(doc['blocks']) == 2
    assert all(b['adjacent_plane_distances_mm'] == [] for b in doc['blocks'])


def test_axial_sagittal_intersection_is_clipped_in_display_pixels():
    from tools.eagle_eye_bench.spatial_packet import intersection
    sag = _plane('s', 'sag', (5., 0., 20.), (0.,1.,0.,0.,0.,-1.), 1)
    ax = _plane('a', 'ax', (0., 0., 10.), (1.,0.,0.,0.,1.,0.), 1)
    segment = np.array(intersection(sag, ax))
    assert np.allclose(segment[:,1], 10.)
    assert sorted(segment[:,0]) == [0.,19.]
    reverse = np.array(intersection(ax,sag))
    assert np.allclose(reverse[:,0],5.)


def test_locator_does_not_modify_original_pixels(tmp_path):
    from tools.eagle_eye_bench.spatial_packet import render_locator
    sag = _plane('s', 'sag', (5., 0., 20.), (0.,1.,0.,0.,0.,-1.), 1)
    ax = _plane('a', 'ax', (0.,0.,10.), (1.,0.,0.,0.,1.,0.),1)
    source = Image.fromarray(np.arange(400,dtype=np.uint8).reshape(20,20))
    before = source.tobytes()
    audit = render_locator(sag,[ax],source,tmp_path/'guide.png')
    assert source.tobytes() == before
    assert audit['intersections'][0]['image_id'] == 'a'
    assert audit['diagnostic_pixels_modified'] is False


def test_irregular_spacing_is_reported_and_duplicate_planes_rejected():
    from tools.eagle_eye_bench.spatial_packet import build_manifest
    orientation = (1.,0.,0.,0.,1.,0.)
    planes = [_plane(str(i),'ax',(0.,0.,z),orientation,i) for i,z in enumerate([20.,17.,14.,4.],1)]
    block=build_manifest(planes,{'ax':[1,2,3,4]})['blocks'][0]
    assert block['adjacent_plane_distances_mm'] == [3.,3.,10.]
    assert block['sampling_status'] == 'irregular_or_gapped'
    with pytest.raises(ValueError, match='duplicate'):
        build_manifest([planes[0],replace(planes[0],image_id='b',member=2)],{'ax':[1,2]})


def test_oblique_cropped_anisotropic_planes_keep_physical_intersections():
    from tools.eagle_eye_bench.spatial_packet import intersection
    sag = replace(_plane('s', 'sag', (5., 0., 20.),
                         (0., 1., 0., 0., 0., -1.), 1), spacing=(.5, 2.))
    ax = replace(_plane('a', 'ax', (0., 0., 15.),
                        (1., 0., 0., 0., 1., 0.), 1), spacing=(1.5, .8))
    original = np.array(intersection(sag, ax))
    assert np.allclose(original[:, 1], 10.)
    assert np.allclose(sorted(original[:, 0]), [0., 14.25])
    angle = np.deg2rad(23.)
    rotation = np.array([[np.cos(angle), 0., np.sin(angle)],
                         [0., 1., 0.], [-np.sin(angle), 0., np.cos(angle)]])

    def transform(plane):
        row, col = plane.axes
        return replace(plane, origin=tuple(rotation @ np.array(plane.origin) + [50., -20., 8.]),
                       orientation=tuple(np.concatenate((rotation @ row, rotation @ col))))

    rotated_sag, rotated_ax = transform(sag), transform(ax)
    assert np.allclose(intersection(rotated_sag, rotated_ax), original)
    cropped = replace(rotated_sag, origin=tuple(rotated_sag.point(2., 3.)), size=(18, 17))
    segment = np.array(intersection(cropped, rotated_ax))
    assert np.allclose(segment[:, 1], 7.)
    assert np.allclose(sorted(segment[:, 0]), [0., 12.25])
    for point in segment:
        delta = cropped.point(*point) - np.array(rotated_ax.origin)
        assert abs(delta @ rotated_ax.normal) < 1e-8


def test_correspondence_cards_pair_every_plane_without_marking_clean_panels(tmp_path):
    from tools.eagle_eye_bench.spatial_packet import render_correspondence_cards
    sag = _plane('s', 'sag', (5., 0., 20.), (0.,1.,0.,0.,0.,-1.), 1)
    axials = [_plane('a2','ax',(0.,0.,8.),(1.,0.,0.,0.,1.,0.),2),
              _plane('a1','ax',(0.,0.,12.),(1.,0.,0.,0.,1.,0.),1)]
    pixels = {'s':Image.new('RGB',(20,20),(51,71,91)),
              'a1':Image.new('RGB',(20,20),(81,101,121)),
              'a2':Image.new('RGB',(20,20),(111,131,151))}
    before = {k:v.tobytes() for k,v in pixels.items()}
    audit = render_correspondence_cards(sag,axials,pixels,tmp_path,expected_members=[1,2])
    assert [c['axial_image_id'] for c in audit['cards']] == ['a1','a2']
    assert audit['complete_membership'] is True
    assert audit['cards'][1]['distance_from_previous_mm'] == 4.
    for card in audit['cards']:
        rendered = Image.open(tmp_path/card['file']).convert('RGB')
        for key,identifier in [('clean_sagittal_panel','s'),('clean_axial_panel',card['axial_image_id'])]:
            panel=card[key]
            original=pixels[identifier].crop(tuple(panel['source_crop_xyxy']))
            expected=original.resize(tuple(panel['display_size']),Image.Resampling.LANCZOS)
            assert rendered.crop(tuple(panel['canvas_xyxy'])).tobytes()==expected.tobytes()
        assert card['locator_line_count']==1
    assert before=={k:v.tobytes() for k,v in pixels.items()}


def test_correspondence_cards_reject_incomplete_groups_before_writing(tmp_path):
    from tools.eagle_eye_bench.spatial_packet import render_correspondence_cards
    sag = _plane('s','sag',(5.,0.,20.),(0.,1.,0.,0.,0.,-1.),1)
    ax = _plane('a','ax',(0.,0.,10.),(1.,0.,0.,0.,1.,0.),1)
    with pytest.raises(ValueError,match='membership'):
        render_correspondence_cards(sag,[ax],{'s':Image.new('RGB',(20,20)),
                                           'a':Image.new('RGB',(20,20))},tmp_path,
                                    expected_members=[1,2])
    assert not list(tmp_path.iterdir())
