"""Source-tagged adult reference context, not a diagnostic classifier."""
from copy import deepcopy
from datetime import datetime

VERSION = '2026-09-15.1'
SOURCES = (
    ('1', 'ESSKA osteotomy consensus, 2024, Table 1', 'https://doi.org/10.1002/ksa.12256'),
    ('2', 'Evaluation of the 3-D weight-bearing normal adult knee, 2014', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC4017250/'),
    ('3', 'MacDessi et al. CPAK, 2021', 'https://doi.org/10.1302/0301-620X.103B2.BJJ-2020-1050.R1'),
    ('4', 'Post-traumatic knee arthritis and coronal malalignment, 2024', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC11368894/'),
    ('5', 'Automatic assessment of lower limb deformities, 2025', 'https://doi.org/10.1186/s12891-025-08784-9'),
)
REFERENCE = {
    'hka_deg': dict(text='0 +/- 3 deg neutral band [2]',kind='neutral_band',low=-3,high=3,unit='deg',source='2'),
    'mldfa_deg': dict(text='85-90 deg [1]',kind='adult_reference_range',low=85,high=90,unit='deg',source='1'),
    'mpta_deg': dict(text='85-90 deg [1]',kind='adult_reference_range',low=85,high=90,unit='deg',source='1'),
    'jlca_deg': dict(text='0-2 deg [1]',kind='adult_reference_range',low=0,high=2,unit='deg',source='1'),
    'ldta_deg': dict(text='86-92 deg [5]',kind='adult_reference_range',low=86,high=92,unit='deg',source='5'),
    'ahka_deg': dict(text='-2 to +2 deg; CPAK neutral [3]',kind='classification_band',low=-2,high=2,unit='deg',source='3'),
    'jlo_deg': dict(text='177-183 deg; CPAK neutral [3]',kind='classification_band',low=177,high=183,unit='deg',source='3'),
    'mad': dict(text='8 +/- 7 mm medial [4]',kind='published_summary',center=8,spread=7,unit='mm',source='4'),
    **{key:dict(text='No fixed range; age/stature dependent',kind='no_universal_range')
       for key in ('femur_length','tibia_length','limb_length')},
    'lld': dict(text='0 mm = equality; no universal normal cutoff',kind='no_universal_range'),
    'lld_percent': dict(text='0% = equality; no universal normal cutoff',kind='no_universal_range'),
}


def age_at_study(image):
    context=image.get('identity',{})
    try:
        birth=datetime.strptime(context['birth_date'],'%Y%m%d').date()
        study=datetime.strptime(context['study_date'],'%Y%m%d').date()
        if birth>study:return None
        return study.year-birth.year-((study.month,study.day)<(birth.month,birth.day))
    except (KeyError,ValueError,TypeError):return None


def reference_text(key,image):
    entry=REFERENCE[key]
    age=age_at_study(image)
    if age is not None and age<18 and entry['kind']!='no_universal_range':
        return 'Adult reference not applicable (<18 years)'
    text=entry['text']
    if key=='mad' and not image.get('calibrated'):
        text+='; not comparable to px'
    return text


def scope_text(image):
    age=age_at_study(image)
    scope=('Adult references not applicable to this child.' if age is not None and age<18 else
           'Adult literature references; age unavailable, applicability unverified.' if age is None else
           'General adult literature references; not individually matched.')
    return scope+' Neutral/CPAK bands are classifications, not normality or surgical targets. No automatic abnormality flags.'


def reference_manifest(image):
    entries=deepcopy(REFERENCE)
    for key,entry in entries.items():entry['display_text']=reference_text(key,image)
    return dict(version=VERSION,population='adult',age_at_study=age_at_study(image),
                scope=scope_text(image),entries=entries,sources=SOURCES)
