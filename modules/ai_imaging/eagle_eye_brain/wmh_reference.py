"""Published WMH normalization and explicit, fail-closed reference readiness.

This is not a fitted percentile model. The publication and its supplement do
not supply the GAMLSS spline coefficients needed to reproduce its CDF.
"""
import math
from html import escape

from .contracts import BrainError

REFERENCE_DOI = '10.3390/diagnostics16152460'
REFERENCE_TIV_ML = 1409.0


def normalize_volume_ml(native_volume_ml, spm12_tiv_ml):
    """Apply the published scalar normalization; caller must supply SPM12 TIV.

    This helper does not estimate TIV or establish image identity/provenance.
    Never substitute brain parenchymal volume, SynthSeg ICV or rigid MNI volume.
    """
    for value in (native_volume_ml, spm12_tiv_ml):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise BrainError('WMH volume and SPM12 TIV must be finite numbers in mL.')
    if native_volume_ml < 0 or spm12_tiv_ml <= 0 or native_volume_ml > spm12_tiv_ml:
        raise BrainError('Require 0 <= WMH volume <= positive SPM12 TIV, both in mL.')
    return native_volume_ml / spm12_tiv_ml * REFERENCE_TIV_ML


def reference_status(result):
    """Describe actual current capability, including for older saved results.

    Ignore any stale cached percentile. No offline fitted model or SPM12 TIV
    producer is integrated in this pipeline yet. Age eligibility is separate
    from model availability and is never a claim of clinical qualification.
    """
    from .wmh_fraction import graphical_reference, _number
    fractions = result.get('svd_spatial', {}).get('candidate_fractions', {})
    volume, icv = fractions.get('candidate_volume_ml'), fractions.get('icv_ml')
    measured = result.get('metrics', {}).get('total_volume_cm3')
    if (_number(volume) and _number(icv) and _number(measured)
            and icv > 0 and 0 <= volume <= icv and math.isclose(volume, measured, abs_tol=1e-9)):
        status = graphical_reference(result.get('age_years'), result.get('sex'), 100 * volume / icv)
        status.update(percentile=None, fractions=fractions, icv_percent=100 * volume / icv)
        return status
    age = result.get('age_years')
    known = not isinstance(age, bool) and isinstance(age, (int, float))
    known = known and math.isfinite(age)
    age_status = ('not supplied' if not known else
                  'within reference age range' if 40 <= age <= 95 else 'outside reference age range')
    sex = str(result.get('sex') or '').strip().lower()
    return {
        'reference_doi': REFERENCE_DOI, 'reference_age_years': [40, 95],
        'age_status': age_status, 'sex_available': sex in {'f', 'm', 'female', 'male'},
        'status': 'not_calculated', 'percentile': None, 'z_score': None,
        'normalized_volume_ml': None,
        'missing_requirements': [
            'Same-examination SPM12 total intracranial volume has not been computed.',
            'The fitted age/sex and acquisition-specific GAMLSS model is not installed.',
            'Segmentation and reference-pipeline compatibility require verification.',
        ],
    }


def reference_html(result):
    status = reference_status(result)
    if 'fractions' in status:
        f = status['fractions']
        text = ('<h2>Age-adjusted WMH burden: approximate graphical reference</h2>'
                f'<p>Candidate volume: {f["candidate_volume_ml"]:.3f} mL; '
                f'intracranial volume: {f["icv_ml"]:.1f} mL; '
                f'WMH candidates / ICV: <b>{status["icv_percent"]:.4f}%</b>.</p>')
        if status['status'] == 'approximate_graphical_band':
            q = status['quantiles_percent']
            text += (f'<p>Age/sex graphical band: <b>{escape(status["band"])}</b>. '
                     f'Approximate P5-P95 reference interval: {q[5]:.4f}-{q[95]:.4f}% of ICV.</p>')
            if status['boundary_sensitive']:
                text += '<p>Close to a plotted percentile boundary; the displayed band spans the reading allowance.</p>'
        else:
            text += '<p>Percentile unavailable: ' + escape(status['reason']) + '</p>'
        return text + (
            '<p>Estimated from published age/sex curves, not a fitted individual percentile or Z-score. '
            'Graph reading/interpolation allowance: +/-0.1 natural-log units; not a confidence interval. '
            'LST candidates and SynthSeg ICV differ from the reference pipeline; method bias is not quantified. '
            'Low detected burden does not exclude disease or missed lesions. Segmentation requires review.</p>'
            '<p>Reference: Kilinc et al., Stroke 2024;55:2863-2871, Figure 3. '
            'doi:10.1161/STROKEAHA.124.046731. Rotterdam Study: 5,402 participants, '
            '11,465 scans. Digitized support: ages 50-85; no extrapolation. '
            'WMH burden reference, separate from regional brain volumetry.</p>')
    age = result.get('age_years')
    age_text = (f'{age:.2f} years' if status['age_status'] != 'not supplied' else 'Not supplied')
    return (
        '<h2>Age-adjusted WMH burden</h2><p>Age/sex percentile: not calculated.</p>'
        '<p>Age: ' + escape(age_text) + ' — ' + escape(status['age_status']) +
        ' (40–95 years). Sex for reference: ' +
        ('available' if status['sex_available'] else 'not supplied or unsupported') + '.</p>'
        '<p>' + '<br>'.join(escape(x) for x in status['missing_requirements']) + '</p>'
        '<p>Published normalization: native total lesion volume / SPM12 TIV × 1409 mL. '
        'A native volume, a published median, or a Fazekas grade does not determine an individual percentile.</p>'
        '<p>Reference: Boccali et al., Diagnostics 2026;16:2460. doi:' + REFERENCE_DOI +
        '. Separate models were developed for 2D and 3D FLAIR. '
        'These norms concern WMH burden, not regional brain-volume norms.</p>'
    )
