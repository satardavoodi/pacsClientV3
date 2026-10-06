"""Versioned historical Brush/Greulich-Pyle reference calculator.

Source: Gaskin et al., Skeletal Development of the Hand and Wrist (2011),
Tables 1 and 2, printed pages 8-9 (modified from Greulich and Pyle, 1959).
Normal-distribution percentiles are estimates, not local-population validation.
Linear interpolation is an implementation approximation, not an atlas method.
"""
import math

REFERENCE_ID = 'GP1959-Brush-via-Gaskin2011-tables1-2-v1'
REFERENCE_NAME = 'Greulich-Pyle / Brush historical reference (Gaskin 2011, Tables 1-2)'

MALE = [
 (3,3.01,.69),(6,6.09,1.13),(9,9.56,1.43),(12,12.74,1.97),
 (18,19.36,3.52),(24,25.97,3.92),(30,32.40,4.52),(36,38.21,5.08),
 (42,43.89,5.40),(48,49.04,6.66),(54,56,8.36),(60,62.43,8.79),
 (72,75.46,9.17),(84,88.20,8.91),(96,101.38,9.10),(108,113.90,9),
 (120,125.68,9.79),(132,137.32,10.09),(144,148.82,10.38),
 (156,158.39,10.44),(168,170.02,10.72),(180,182.72,11.32),
 (192,195.32,12.86),(204,206.21,13.05)]
FEMALE = [
 (3,3.02,.72),(6,6.04,1.16),(9,9.05,1.36),(12,12.04,1.77),
 (18,18.22,3.49),(24,24.16,4.64),(30,30.96,5.37),(36,36.63,5.97),
 (42,43.50,7.48),(48,50.14,8.98),(54,60.06,10.73),(60,66.21,11.65),
 (72,78.50,10.23),(84,89.30,9.64),(96,100.66,10.23),(108,113.86,10.74),
 (120,125.66,11.73),(132,137.87,11.94),(144,149.62,10.24),
 (156,162.28,10.67),(168,174.25,11.30),(180,183.62,9.23),(192,189.44,7.31)]

def calculate(chronological_months, bone_months, sex):
    sex = {'M':'Male','F':'Female','male':'Male','female':'Female'}.get(sex,sex)
    if sex not in ('Male', 'Female'):
        raise ValueError('Confirmed binary model/reference sex is required.')
    if any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v)
           for v in (chronological_months, bone_months)):
        raise ValueError('Finite ages are required.')
    if not 0 <= bone_months <= 228:
        raise ValueError('Bone age outside current model output range.')
    rows = MALE if sex == 'Male' else FEMALE
    if not rows[0][0] <= chronological_months <= rows[-1][0]:
        raise ValueError('Age outside reference range; extrapolation prohibited.')
    for lo, hi in zip(rows, rows[1:]):
        if lo[0] <= chronological_months <= hi[0]:
            weight=(chronological_months-lo[0])/(hi[0]-lo[0])
            mean=lo[1]+weight*(hi[1]-lo[1])
            sd=lo[2]+weight*(hi[2]-lo[2])
            break
    z=(bone_months-mean)/sd
    below = bone_months < mean-2*sd and not math.isclose(bone_months,mean-2*sd,abs_tol=1e-9)
    above = bone_months > mean+2*sd and not math.isclose(bone_months,mean+2*sd,abs_tol=1e-9)
    return dict(available=True,reference_id=REFERENCE_ID,reference_name=REFERENCE_NAME,
        reference_mean_months=mean, reference_sd_months=sd,
        reference_range_2sd_months=[mean-2*sd,mean+2*sd],
        z_score=z, estimated_reference_percentile=50*math.erfc(-z/math.sqrt(2)),
        difference_from_chronological_months=bone_months-chronological_months,
        category='Below reference range' if below else
                 'Above reference range' if above else 'Within reference range',
        normal_distribution_assumed=True, model_confidence_interval=False)
