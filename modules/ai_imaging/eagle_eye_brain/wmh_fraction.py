"""Measured candidate fractions and approximate published graphical reference bands."""
import bisect
import math

from .contracts import BrainError
from .rotterdam_curve_data import LOG_QUANTILES

DOI = '10.1161/STROKEAHA.124.046731'
CENTILES = [5, 10, 25, 50, 75, 90, 95]
LOG_ALLOWANCE = 0.1  # Graph reading/interpolation allowance, NOT a confidence interval.


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def candidate_fractions(lesion_ml, brain_result):
    """Use complete disjoint posterior tissues; caller verifies examination identity."""
    rows = brain_result.get('posterior_rows', [])
    names = [r.get('structure') for r in rows]
    if len(names) != len(set(names)):
        raise BrainError('Duplicate anatomical volume rows; candidate fractions unavailable.')
    values = {r.get('structure'): r.get('volume_cm3') for r in rows}
    parts = ('cerebral white matter', 'cerebral cortex', 'cerebellum white matter',
             'cerebellum cortex', 'thalamus', 'caudate', 'putamen', 'pallidum',
             'hippocampus', 'amygdala', 'accumbens area', 'ventral DC')
    keys = [f'{side} {part}' for side in ('left', 'right') for part in parts] + ['brain-stem']
    if not all(_number(values.get(k)) and values[k] >= 0 for k in keys + ['total intracranial']):
        raise BrainError('Complete anatomical volumes are required for candidate fractions.')
    icv, brain = values['total intracranial'], sum(values[k] for k in keys)
    if not _number(lesion_ml) or not 0 <= lesion_ml <= brain <= icv or brain <= 0:
        raise BrainError('Candidate and anatomical volumes are inconsistent.')
    return dict(candidate_volume_ml=lesion_ml, icv_ml=icv, parenchyma_ml=brain,
                icv_percent=100 * lesion_ml / icv,
                parenchyma_percent=100 * lesion_ml / brain,
                denominator_method='SynthSeg posterior disjoint tissue volumes',
                status='Measured candidate fractions; segmentation review required')


def graphical_reference(age, sex, fraction_percent):
    """Return a band only; never expose a fitted-model percentile or Z-score."""
    sex = str(sex).strip().lower()
    sex = {'f': 'female', 'm': 'male'}.get(sex, sex)
    base = dict(reference_doi=DOI, method='Digitized Figure 3; cross-method estimate',
                age_range=[50, 85], exact_percentile=None, z_score=None,
                clinical_qualification=False, log_reading_allowance=LOG_ALLOWANCE)
    if not _number(age) or not 50 <= age <= 85:
        return dict(base, status='unavailable', reason='Graphical reference supports ages 50-85 only.')
    if sex not in LOG_QUANTILES or not _number(fraction_percent) or not 0 <= fraction_percent <= 100:
        return dict(base, status='unavailable', reason='Valid sex and measured WMH/ICV percentage are required.')
    index = min(int((age - 50) // 5), 6)
    weight = (age - (50 + index * 5)) / 5
    logs = [(1 - weight) * a + weight * b for a, b in
            zip(LOG_QUANTILES[sex][index], LOG_QUANTILES[sex][index + 1])]
    observed = math.log(fraction_percent) if fraction_percent > 0 else -math.inf
    lower = [0] + CENTILES
    upper = CENTILES + [100]
    lo = lower[bisect.bisect_right(logs, observed - LOG_ALLOWANCE)]
    hi = upper[bisect.bisect_left(logs, observed + LOG_ALLOWANCE)]
    band = (f'Below P{hi}' if lo == 0 else f'Above P{lo}' if hi == 100 else f'P{lo}-P{hi}')
    return dict(base, status='approximate_graphical_band', band=band,
                percentile_lower=lo, percentile_upper=hi,
                quantiles_percent=dict(zip(CENTILES, (math.exp(x) for x in logs))),
                boundary_sensitive=bisect.bisect_right(logs, observed - LOG_ALLOWANCE) !=
                                   bisect.bisect_left(logs, observed + LOG_ALLOWANCE),
                note='Graph reading/interpolation allowance does not cover segmentation or ICV-method bias.')
