"""Opt-in synthetic provider checks for measurements and paired-organ edits."""
import json
import os
import re

import pytest

pytestmark = [pytest.mark.live, pytest.mark.skipif(
    os.environ.get('AIPACS_TEST_TEMPLATE_MODEL') != '1', reason='Provider opt-in required')]


def plain(value):
    return re.sub(r'<[^>]+>', ' ', json.dumps(value, ensure_ascii=False)).lower()


@pytest.fixture(scope='module')
def templates():
    from modules.EchoMind import normal_templates as nt, reception_templates as rt
    from modules.EchoMind.settings_store import get_echomind_api_key
    from modules.EchoMind.api_manager import Manage
    Manage.instance().detect_center(get_echomind_api_key())
    sources = {
        'uterus': '<p>The uterus measures ___ x ___ mm.</p><p>The myometrium is homogeneous.</p>',
        'kidneys': '<p>The right kidney measures ___ mm in length.</p>'
                   '<p>The left kidney measures ___ mm in length.</p>'
                   '<p>Both renal cortices demonstrate normal echogenicity.</p>'
                   '<p>No hydronephrosis is seen in either kidney.</p>',
        'uterus_three': '<p>The uterus measures ___ x ___ x ___ mm.</p>',
    }
    result = {}
    for key, body in sources.items():
        rec, _ = nt.normalize_record({'id':key, 'Name':'Synthetic ultrasound '+key,
                                      'Modality':'US', 'Html':body})
        result[key] = rt.organize_template(rec)['edited_text']
    return result


def generate(template, message):
    from modules.EchoMind.viewer_chat.openai_reporter import reporter
    result = reporter(message, modality='SONOGRAPHY', normal_template=template)
    return json.loads(result['content'].replace('<|end|>', '').strip())


@pytest.mark.parametrize('first', [24, 74])
def test_uterus_preserves_two_dimensions_and_source_units(templates, first):
    output = generate(templates['uterus'], f'The uterus measures {first} by 34.')
    text = plain(output)
    assert re.search(rf'{first}\s*(?:x|by|×|&times;)\s*34\s*mm', text), text
    assert '___' not in text
    assert 'homogeneous' in text


def test_kidney_lengths_stay_on_the_correct_side(templates):
    output = generate(templates['kidneys'], 'Right renal length is 105 mm. Left renal length is 98 mm.')
    text = plain(output)
    assert re.search(r'right[^.;]{0,100}105', text), text
    assert re.search(r'left[^.;]{0,100}98', text), text
    assert '___' not in text


def test_left_cortex_abnormality_preserves_only_right_normal_cortex(templates):
    output = generate(templates['kidneys'], 'Right kidney length is 105 mm. Left kidney length is 98 mm. '
                      'Left renal cortical echogenicity is decreased. The right renal cortex is normal.')
    normal = plain(output.get('Normal Findings', ''))
    pathology = plain(output.get('Pathological Findings', ''))
    assert 'both renal cortices' not in normal, normal
    assert 'right' in normal and ('echogenicity' in normal or 'cortex' in normal), normal
    assert 'left' in pathology and 'decreased' in pathology, pathology
    assert 'hydronephrosis' in normal, normal
    assert '105' in plain(output) and '98' in plain(output)


def test_missing_third_dimension_is_never_fabricated(templates):
    output = generate(templates['uterus_three'], 'The uterus measures 74 by 34 mm. Only two dimensions are available.')
    text = plain(output)
    assert '74' in text and '34' in text, text
    assert not re.search(r'74\s*(?:x|by|×|&times;)\s*34\s*(?:x|by|×|&times;)\s*\d', text), text
    assert '___' not in text


def test_unprovided_left_kidney_length_is_not_filled_from_right(templates):
    output = generate(templates['kidneys'], 'Right renal length is 105 mm. Left renal length was not provided.')
    text = plain(output)
    assert re.search(r'right[^.;]{0,100}105', text), text
    assert not re.search(r'left[^.;]{0,60}(?:measures|length is|length of)\s*\d', text), text
    assert '___' not in text


def test_latest_corrected_uterine_measurement_wins(templates):
    output = generate(templates['uterus'], 'The uterus measures 24 by 34 mm. Correction: replace 24 with 74; final dimensions 74 by 34 mm.')
    text = plain(output)
    assert re.search(r'74\s*(?:x|by|×|&times;)\s*34\s*mm', text), text
    assert not re.search(r'\b24\b', text), text


def test_mammography_keeps_benign_details_and_separate_density(templates):
    from modules.EchoMind.viewer_chat.openai_reporter import reporter
    source = ('No suspicious calcification is seen in either breast.\n'
              'Skin thickness is normal bilaterally.\n'
              '===== BEGIN TEMPLATE_FIELDS =====\n'
              'BC: A (Almost entirely fatty.)\nBC: B (Scattered fibroglandular density.)\n'
              'BC: C (Heterogeneously dense.)\nBC: D (Extremely dense.)\n'
              '===== END TEMPLATE_FIELDS =====')
    result = reporter('Breast composition C. Multiple circumscribed nodules are present in both breasts. '
                      'Benign-appearing lymph nodes are seen in both axillae. Ultrasound correlation is recommended. '
                      'BI-RADS 2 in both breasts.', modality='MAMOGRAPHY', normal_template=source)
    output = json.loads(result['content'].replace('<|end|>', '').strip())
    pathology = plain(output.get('Pathological Findings', ''))
    assert 'circumscribed' in pathology and 'multiple' in pathology, pathology
    assert 'bilateral' in pathology or 'both breasts' in pathology, pathology
    assert 'ultrasound' in plain(output), plain(output)
    assert 'heterogeneously dense' in plain(output.get('Breast Composition', ''))
    axilla = plain(output.get('Axillary Evaluation', ''))
    assert 'benign' in axilla and ('both' in axilla or 'bilateral' in axilla), axilla
    assert 'pectoralis' not in plain(output)
