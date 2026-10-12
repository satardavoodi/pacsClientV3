"""Descriptive Dixon signals; magnitude chemical shift loss is not fat fraction."""
import numpy as np
from .marrow_quantitative import fat_volume_statistics, erode_physical


def measurements(images, labels, names, affine):
    import SimpleITK as sitk
    ip = sitk.GetArrayFromImage(images['primary']).astype(float)
    has_fw = 'fat' in images and 'water' in images
    if has_fw:
        rows, ratio = fat_volume_statistics(*(sitk.GetArrayFromImage(images[r]) for r in ('fat','water')), labels, names, affine)
    else:
        rows, ratio = fat_volume_statistics(np.zeros_like(ip), np.ones_like(ip), labels, names, affine)
        for row in rows:
            for key in ('signal_ff_median_percent','signal_ff_p10_percent','signal_ff_p90_percent'):
                row[key] = None
    if 'opposed' in images:
        op = sitk.GetArrayFromImage(images['opposed']).astype(float)
        drop = np.divide(ip-op, ip, out=np.full(ip.shape,np.nan), where=(labels>0)&(ip>0))
        for row in rows:
            mask = erode_physical(labels==row['label'],affine) & np.isfinite(drop)
            values = drop[mask]
            for key, value in zip(('signal_drop_p10_percent','signal_drop_median_percent','signal_drop_p90_percent'),
                                  np.percentile(values,[10,50,90])*100 if len(values)>=20 else [None]*3):
                row[key] = float(value) if value is not None else None
            if not has_fw:
                row['sample_voxels'] = int(mask.sum())
                row['sample_volume_mm3'] = float(mask.sum()*abs(np.linalg.det(affine[:3,:3])))
                row['qc'] = 'body_mask_review_required' if len(values)>=20 else 'insufficient_sample'
        if not has_fw:
            ratio = drop
    return rows, ratio, 'fat_water_signal_ratio' if has_fw else 'in_opposed_signal_drop'
