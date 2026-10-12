"""Server-owned signal measurements; signal fractions are not cell percentages."""
import numpy as np

SPECTRAL_SOURCE = 'https://github.com/TJPBray/MAGORINO/blob/main/Fitting/models/MultiPeakFatSingleR2.m'
FAT_AMPLITUDES = np.array([.087, .694, .128, .004, .039, .048])
FAT_SHIFTS_PPM = np.array([-3.9, -3.5, -2.7, -2.04, -.49, .50])


def signal_model(te_seconds, field_tesla, fat_fraction, r2star):
    te = np.asarray(te_seconds, float)
    spectrum = np.sum(FAT_AMPLITUDES[:, None] * np.exp(
        2j * np.pi * 42.58 * field_tesla * FAT_SHIFTS_PPM[:, None] * te), axis=0)
    return np.abs(1 - np.asarray(fat_fraction)[..., None] +
                  np.asarray(fat_fraction)[..., None] * spectrum) * np.exp(-np.asarray(r2star)[..., None] * te)


def fit_signal(signal, te_seconds, field_tesla):
    """Gaussian ROI-mean fit; keep the optimum on each side of 50% visible."""
    signal, te = np.asarray(signal, float), np.asarray(te_seconds, float)
    if (signal.ndim != 1 or te.shape != signal.shape or len(te) < 6
            or not np.isfinite(signal).all() or not np.isfinite(te).all()
            or np.any(signal < 0) or signal.max() <= 0 or np.any(te <= 0)
            or np.any(np.diff(te) <= 0) or not np.isfinite(field_tesla) or not .1 < field_tesla < 10):
        raise ValueError('At least six ordered distinct positive echoes and finite magnitude signal are required.')
    fractions, rates = np.linspace(0, 1, 501), np.arange(0, 1001, 2.)
    base = signal_model(te, field_tesla, fractions, 0)
    models = (base[:, None, :] * np.exp(-rates[None, :, None] * te)).reshape(-1, len(te))
    norm = np.sum(models * models, axis=1)
    dot = models @ signal
    amplitudes = dot / norm
    errors = np.maximum(0, np.sum(signal * signal) - dot * dot / norm).reshape(len(fractions), len(rates))
    branches = []
    for start, end in [(0, 251), (251, 501)]:
        fi, ri = np.unravel_index(np.argmin(errors[start:end]), errors[start:end].shape)
        fi += start
        index = fi * len(rates) + ri
        prediction = amplitudes[index] * models[index]
        branches.append(dict(fat_signal_fraction=float(fractions[fi]), r2star_s_inverse=float(rates[ri]),
            t2star_ms=float(1000/rates[ri]) if rates[ri] > 0 else None,
            amplitude=float(amplitudes[index]), sse=float(errors[fi,ri]),
            relative_rmse_percent=float(100*np.sqrt(np.mean((signal-prediction)**2))/signal.max()),
            predicted=prediction.tolist(), boundary=bool(fi in (0,250,251,500) or ri in (0,len(rates)-1))))
    return dict(branches=branches, selection='unresolved', clinical_ambiguity_resolved=False,
                best_residual_branch=int(np.argmin([b['sse'] for b in branches])),
                observed=signal.tolist(), te_ms=(1000*te).tolist(),
                method='six_peak_magnitude_gaussian_roi_mean', noise_floor_corrected=False, t1_corrected=False)


def select_branch(branches, dixon_percentiles, alignment_confirmed, protocol=None):
    """Compare acquisitions using an explicitly conditional spoiled-GRE T1 model.

    T1 values are sensitivity assumptions, not measurements or population normals.
    Iron can invalidate water-T1 >= fat-T1. No direct nearest-fraction matching.
    """
    result=dict(selection='unresolved',dixon_supported_branch=None,conditional_t1_supported_branch=None,
                clinical_ambiguity_resolved=False,prior_kind='spoiled_GRE_T1_sensitivity_not_calibration',
                alignment_confirmed=alignment_confirmed)
    if protocol is None or not np.isfinite(dixon_percentiles).all():
        return result
    values=[protocol.get(k) for k in ('dixon_tr_ms','dixon_flip_degrees','echo_tr_ms','echo_flip_degrees')]
    if any(v is None for v in values) or not np.isfinite(values).all() or min(values)<=0:
        return result
    dtr,dfa,etr,efa=values
    if max(dfa,efa)>=90:
        return result
    def factor(tr,fa,t1):
        e=np.exp(-tr/t1);angle=np.deg2rad(fa)
        return np.sin(angle)*(1-e)/(1-np.cos(angle)*e)
    fat,water=np.meshgrid(np.linspace(150,500,71),np.linspace(400,2000,101))
    eligible=water>=fat
    echo_bias=factor(etr,efa,fat)/factor(etr,efa,water)
    dixon_bias=factor(dtr,dfa,fat)/factor(dtr,dfa,water)
    ranges=[]
    for b in branches:
        f=b['fat_signal_fraction']
        proton=f/(echo_bias*(1-f)+f)
        predicted=proton*dixon_bias/(proton*dixon_bias+1-proton)
        ranges.append([float(predicted[eligible].min()),float(predicted[eligible].max())])
    lo,median,hi=dixon_percentiles
    candidates=[i for i,(a,b) in enumerate(ranges) if a<=median<=b]
    # Three percentage points is an explicit sensitivity guard band, not a
    # calibrated confidence bound. Require separation from the other branch.
    supported=None
    if len(candidates)==1:
        i=candidates[0];other=ranges[1-i]
        if hi<other[0]-.03 or lo>other[1]+.03:
            if not branches[i].get('boundary') and branches[i].get('relative_rmse_percent',0)<=15:
                supported=i
    result.update(conditional_t1_supported_branch=supported,predicted_dixon_signal_ranges=ranges,
        t1_sensitivity_assumptions={'fat_t1_ms':[150,500],'water_t1_ms':[400,2000],
          'water_t1_at_least_fat_t1':True,'spoiled_GRE_steady_state':True,
          'measured_t1':False,'differential_r2star_and_vendor_reconstruction_bias_corrected':False},
        protocol=protocol)
    if supported is not None:
        result['selection']='conditional_T1_supported_'+('low_fat' if supported==0 else 'high_fat') if alignment_confirmed else 'alignment_review_required'
        result['dixon_supported_branch']=supported if alignment_confirmed else None
    return result


def body_labels(vertebra_labels, body_mask):
    labels, body = np.asarray(vertebra_labels), np.asarray(body_mask)
    if labels.ndim != 3 or labels.shape != body.shape or not np.isfinite(labels).all():
        raise ValueError('Body and level masks must have identical 3D geometry.')
    return np.where(body > 0, labels, 0).astype(np.uint8)


def erode_physical(mask, affine, radius_mm=2):
    import SimpleITK as sitk
    spacing = np.linalg.norm(np.asarray(affine)[:3,:3], axis=0)
    image = sitk.GetImageFromArray(np.pad(np.asarray(mask,np.uint8),1))
    image.SetSpacing(tuple(spacing))
    distance = sitk.SignedMaurerDistanceMap(image, insideIsPositive=True, squaredDistance=False, useImageSpacing=True)
    return sitk.GetArrayFromImage(distance)[1:-1,1:-1,1:-1] >= radius_mm


def fat_volume_statistics(fat, water, labels, names, affine):
    fat, water, labels = np.asarray(fat,float), np.asarray(water,float), np.asarray(labels)
    if fat.shape != water.shape or fat.shape != labels.shape or fat.ndim != 3:
        raise ValueError('Dixon and body labels must occupy the same 3D grid.')
    if not np.isfinite(fat).all() or not np.isfinite(water).all() or np.any(fat<0) or np.any(water<0):
        raise ValueError('Dixon requires nonnegative finite magnitude images.')
    denominator = fat + water
    ratio = np.divide(fat, denominator, out=np.full(fat.shape,np.nan), where=(labels>0)&(denominator>0))
    voxel_volume = abs(float(np.linalg.det(np.asarray(affine)[:3,:3])))
    if not np.isfinite(voxel_volume) or voxel_volume <= 0:
        raise ValueError('Invalid voxel volume.')
    rows = []
    for label,name in sorted(names.items(),key=lambda p:p[1]):
        body = labels==label
        if not body.any():
            continue
        roi = erode_physical(body,affine)
        valid = roi & np.isfinite(ratio)
        values = ratio[valid]
        row = dict(level=name,label=int(label),body_voxels=int(body.sum()),
            body_volume_mm3=float(body.sum()*voxel_volume),sample_voxels=int(valid.sum()),
            sample_volume_mm3=float(valid.sum()*voxel_volume),spatial_slices=int(np.count_nonzero(body.any(axis=(1,2)))),
            signal_ff_median_percent=None,signal_ff_p10_percent=None,signal_ff_p90_percent=None,
            qc='insufficient_sample' if len(values)<20 else 'body_mask_review_required')
        row['body_touches_volume_boundary']=bool(any(np.take(body,i,axis=axis).any()
            for axis in range(3) for i in (0,-1)))
        if len(values)>=20:
            row.update(zip(('signal_ff_p10_percent','signal_ff_median_percent','signal_ff_p90_percent'),
                           map(float,np.percentile(values,[10,50,90])*100)))
        rows.append(row)
    return rows,ratio
