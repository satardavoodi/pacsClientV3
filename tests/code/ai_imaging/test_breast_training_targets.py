"""Protect complete multi-lesion and overlapping-label training targets."""
import pytest

from tools.eagle_eye.breast_training_targets import assign_partitions, group_annotations, partition


def row(image='image-a', study='study-a', labels="['Suspicious Calcification']", box=(1, 2, 10, 20)):
    return dict(image_id=image, study_id=study, split='training', width='100', height='100',
                finding_categories=labels, **dict(zip(('xmin', 'ymin', 'xmax', 'ymax'), map(str, box))))


def test_all_calcification_boxes_in_one_image_share_one_training_target():
    records = [row(), row(box=(30, 40, 50, 60)), row(labels="['Mass']")]
    images = group_annotations(records)
    assert len(images) == 1
    assert images[0]['boxes'] == [[1., 2., 10., 20.], [30., 40., 50., 60.]]


def test_mass_cooccurrence_does_not_replace_calcification_label():
    images = group_annotations([row(), row(labels="['Mass', 'Suspicious Calcification']")])
    assert len(images[0]['boxes']) == 1
    assert images[0]['box_labels'] == [['Mass', 'Suspicious Calcification']]


def test_normal_and_mass_only_images_have_no_suspicious_calcification_targets():
    images = group_annotations([row(image='normal', labels="['No Finding']"),
                                row(image='mass', labels="['Mass']")])
    assert all(image['boxes'] == [] for image in images)


def test_bad_geometry_or_conflicting_identity_fails_closed():
    with pytest.raises(ValueError, match='geometry'):
        group_annotations([row(box=(30, 2, 10, 20))])
    with pytest.raises(ValueError, match='identity'):
        group_annotations([row(), row(study='different-study')])


def test_partition_keeps_study_views_together_and_marks_inspected_test():
    assert partition('study-a', 'training', 'seed') == partition('study-a', 'training', 'seed')
    assert partition('study-a', 'test', 'seed') == 'publisher_test_previously_inspected'
    with pytest.raises(ValueError, match='split'):
        partition('study-a', 'unknown', 'seed')


def test_reference_clipping_requires_opt_in_and_preserves_original_geometry():
    record = row(box=(-2, 2, 103, 20))
    with pytest.raises(ValueError, match='geometry'):
        group_annotations([record])
    image = group_annotations([record], clip_out_of_bounds=True)[0]
    assert image['boxes'] == [[0., 2., 100., 20.]]
    assert image['reference_box_corrections'][0]['original'] == [-2., 2., 103., 20.]


def test_rare_calcification_with_mass_is_represented_in_all_development_partitions():
    rows = [row(image=f'image-{i}', study=f'study-{i}', labels="['Mass', 'Suspicious Calcification']")
            for i in range(10)]
    rows.append(row(image='extra-view', study='study-0', labels="['No Finding']"))
    images = group_annotations(rows)
    assignments, strata = assign_partitions(images, 'seed')
    assert set(assignments.values()) == {'train', 'validation', 'calibration'}
    assert strata == {'calc_with_coannotated_mass': 10}
    assert len(assignments) == 10
    assert assign_partitions(list(reversed(images)), 'seed') == (assignments, strata)
