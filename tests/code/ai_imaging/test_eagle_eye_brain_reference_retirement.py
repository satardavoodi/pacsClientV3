"""Retired research scorers cannot re-enter customer reports."""
import pytest

from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
from modules.ai_imaging.eagle_eye_brain.normative import REFERENCES, reference_assessment
from modules.ai_imaging.eagle_eye_brain.reference_report import pages


def test_only_published_volbrain_is_a_selectable_reference():
    assert {item.id for item in REFERENCES} == {'volbrain'}
    assert reference_assessment()['reference_id'] == 'volbrain'


@pytest.mark.parametrize('name', ['auto_age', 'centilebrain', 'centilebrain_freesurfer',
    'centilebrain_synthseg_research', 'potvin_freesurfer53', 'brainchart', 'slip', 'regional_review'])
def test_retired_reference_selection_is_rejected(name):
    with pytest.raises(BrainError):
        reference_assessment(reference_id=name)


def test_old_result_cannot_render_retired_reference_pages():
    assert pages({'reference_id': 'centilebrain_freesurfer', 'status': 'research_scores',
                  'rows': [], 'curves': []}) == []


def test_retired_saved_reference_is_not_republished_or_mutated():
    from modules.ai_imaging.eagle_eye_brain.normative import active_report_context
    saved = {'normative': {'reference_id': 'potvin_freesurfer53', 'z_score': 12}}
    clean = active_report_context(saved)
    assert clean['normative']['reference_id'] == 'volbrain'
    assert clean['normative']['z_score'] is None
    assert saved['normative']['z_score'] == 12
