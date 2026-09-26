"""Conservative, reversible MS-only separation of suspected smooth 2D bands.

These engineering thresholds are not diagnostic criteria or a normal-tissue test.
Only paired axial linear bands qualify. Rounded caps remain for manual review.
"""
import numpy as np

VERSION = 'paired-axial-bands-1'
PARAMETERS = dict(min_length_mm=12., max_pca_width_mm=3., max_local_width_mm=3.2,
                  min_elongation=6., max_ventricle_distance_p95_mm=5.,
                  max_tangent_dot_median=.35, max_tangent_dot_p90=.75,
                  min_ap_alignment=.8, max_pair_ap_offset_mm=8.,
                  max_pair_length_ratio=2., max_in_plane_spacing_mm=1., max_axial_obliquity_degrees=30.,
                  max_end_fragment_extent_mm=3.)


def separate_bands(raw, anatomy, *, context, cancel=None):
    import SimpleITK as sitk
    from .contracts import BrainError
    from .lesions import measure_mask
    measure_mask(anatomy, raw)  # Exact grid, binary mask, no implicit resampling.
    values = sitk.GetArrayFromImage(anatomy)
    if not np.isfinite(values).all() or not np.isin(values, np.arange(20)).all():
        raise BrainError('Band review requires valid MindGlide anatomical labels.')
    binary = sitk.GetArrayFromImage(raw) > 0
    removed = np.zeros_like(binary)
    audit = dict(version=VERSION, parameters=dict(PARAMETERS), status='not_applied_context',
                 clinical_qualification=False, excluded_component_count=0,
                 excluded_voxel_count=0, component_ids=[], pairs=[],
                 interpretation='Suspected smooth bands, not confirmed normal tissue',
                 reference='https://doi.org/10.1093/brain/awz144')

    def finish():
        kept = sitk.GetImageFromArray((binary & ~removed).astype(np.uint8))
        band = sitk.GetImageFromArray(removed.astype(np.uint8))
        kept.CopyInformation(raw); band.CopyInformation(raw)
        audit['excluded_voxel_count'] = int(removed.sum())
        return kept, band, audit

    if context != 'ms':
        return finish()
    direction = np.array(raw.GetDirection()).reshape(3, 3)
    spacing = np.array(raw.GetSpacing()[:2])
    if (abs(direction[2, 2]) < np.cos(np.deg2rad(PARAMETERS['max_axial_obliquity_degrees']))
            or spacing.max() > PARAMETERS['max_in_plane_spacing_mm'] or min(raw.GetSize()[:2]) < 4):
        audit['status'] = 'not_applied_geometry'
        return finish()
    if not np.any(values == 9):
        audit['status'] = 'not_applied_missing_ventricles'
        return finish()
    components = sitk.GetArrayFromImage(sitk.ConnectedComponent(raw, True))
    unsafe, proposals = set(), []
    for z in range(len(values)):
        if cancel is not None and cancel.is_set():
            raise BrainError('Band review cancelled.')
        if not binary[z].any():
            continue
        mask2 = sitk.GetImageFromArray(binary[z].astype(np.uint8)); mask2.SetSpacing(tuple(spacing))
        labels = sitk.GetArrayFromImage(sitk.ConnectedComponent(mask2, True))
        vent = values[z] == 9
        if not vent.any():
            unsafe.update(int(x) for x in np.unique(components[z][binary[z]]))
            continue
        vent2 = sitk.GetImageFromArray(vent.astype(np.uint8)); vent2.SetSpacing(tuple(spacing))
        field = sitk.SignedMaurerDistanceMap(vent2, squaredDistance=False, useImageSpacing=True)
        distances = sitk.GetArrayFromImage(field)
        smooth = sitk.GetArrayFromImage(sitk.SmoothingRecursiveGaussian(field, .8))
        gy, gx = np.gradient(smooth, spacing[1], spacing[0])
        vent_xy = np.argwhere(vent)[:, ::-1] * spacing
        mid = (direction[:, :2] @ vent_xy.mean(0))[0]
        seeds = []
        for label in range(1, int(labels.max()) + 1):
            select = labels == label
            component = int(components[z][select][0])
            xy = np.argwhere(select)[:, ::-1] * spacing
            distance = float(np.percentile(distances[select], 95))
            # Direction is unstable in a few end-fragment pixels. These cannot
            # seed exclusion; they are compatible only with a proven long pair.
            if (max(np.ptp(xy, axis=0) + spacing) <= PARAMETERS['max_end_fragment_extent_mm']
                    and distance <= PARAMETERS['max_ventricle_distance_p95_mm']):
                continue
            if len(xy) < 4:
                unsafe.add(component); continue
            eig, axes = np.linalg.eigh(np.cov(xy.T, bias=True))
            width, length = np.sqrt(12 * np.maximum(eig, 0))
            projection = (xy - xy.mean(0)) @ axes
            bins = np.floor((projection[:, 1] - projection[:, 1].min()) / 2.).astype(int)
            local_widths = [np.ptp(projection[bins == b, 0]) + spacing.min()
                            for b in np.unique(bins)]
            normal_length = np.hypot(gx[select], gy[select])
            dot = np.abs(gx[select] * axes[0, 1] + gy[select] * axes[1, 1]) / np.maximum(normal_length, 1e-6)
            axis = direction[:, :2] @ axes[:, 1]
            # Protect the entire connected component if ANY slice has a bulge,
            # broad/focal profile, radial extension or missing ventricle support.
            compatible = (width <= PARAMETERS['max_pca_width_mm']
                          and max(local_widths) <= PARAMETERS['max_local_width_mm']
                          and distance <= PARAMETERS['max_ventricle_distance_p95_mm']
                          and abs(axis[1]) >= PARAMETERS['min_ap_alignment']
                          and np.median(dot) <= PARAMETERS['max_tangent_dot_median']
                          and np.percentile(dot, 90) <= PARAMETERS['max_tangent_dot_p90'])
            if not compatible:
                unsafe.add(component); continue
            if length < PARAMETERS['min_length_mm'] or length / max(width, .01) < PARAMETERS['min_elongation']:
                continue
            center = direction[:, :2] @ xy.mean(0)
            seeds.append(dict(component=component, center=center, axis=axis, length=float(length),
                              width=float(width), distance_p95=distance))
        for i, left in enumerate(seeds):
            for right in seeds[i + 1:]:
                if (left['component'] == right['component']
                        or (left['center'][0] - mid) * (right['center'][0] - mid) >= 0
                        or abs(left['center'][1] - right['center'][1]) > PARAMETERS['max_pair_ap_offset_mm']
                        or max(left['length'], right['length']) / min(left['length'], right['length']) > PARAMETERS['max_pair_length_ratio']
                        or abs(np.dot(left['axis'], right['axis'])) < .9):
                    continue
                proposals.append((z, left, right))
    selected = set()
    for z, first, second in proposals:
        ids = {first['component'], second['component']}
        if ids & unsafe:
            continue
        selected.update(ids)
        audit['pairs'].append(dict(native_slice=z, component_ids=sorted(ids),
                                   length_mm=[first['length'], second['length']],
                                   effective_width_mm=[first['width'], second['width']]))
    removed[:] = np.isin(components, sorted(selected)) & binary
    audit.update(status='applied' if selected else 'no_confident_pair',
                 excluded_component_count=len(selected), component_ids=sorted(selected))
    return finish()
