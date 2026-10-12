"""Frozen B25/B33 CPU localizer adapter. Research candidate, not a clinical runner."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

FROZEN = {
    'hdog-original-state-only-20261003.pt': 'd3c98b42420fd8a5e0b564b4806acf0e34e44b381da088d2c555d63941f39888',
    'headonly_binary_candidate_bce-not-qualified.pt': '00392b28a3dc8a725a2657c810f413219df19f6fd2e0e76661891c5daed8e436',
    'physical_peak_extraction_20261005.py': '8695a0260ed44b622a0a576409e9ed5c97aef383888132fe77c7c1c7e4a38fb8',
    'morphology_stage_20261005.py': 'e2a7ba7234bb380a406612351a926fbcfab184947a4772d3dd85fb140ba651c7',
    'air_context_v2_20261005.py': '04f77063974f98f1775c4c740fa4712ac7db989fcad14358ecfae1d8be6f7616',
}
CUTOFF = .000316227766


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def windows(shape):
    """Match the frozen HDog order, including the final overlapping edge tile."""
    axes = []
    for length in shape:
        if length < 512:
            raise ValueError('Native dimensions below 512 are unsupported.')
        starts = list(range(0, length - 512 + 1, 256))
        if starts[-1] + 512 != length:
            starts.append(length - 512)
        axes.append(starts)
    return [(t, t + 512, l, l + 512) for t in axes[0] for l in axes[1]]


def pixels(ds):
    """Frozen normalization with explicit stored-code MONOCHROME1 polarity support."""
    import numpy as np
    photometric = str(ds.get('PhotometricInterpretation', ''))
    if (photometric not in ('MONOCHROME1', 'MONOCHROME2')
            or float(ds.get('RescaleSlope', 1)) != 1
            or float(ds.get('RescaleIntercept', 0)) != 0
            or int(ds.get('PixelRepresentation', -1)) != 0
            or int(ds.get('BitsAllocated', 0)) != 16
            or int(ds.get('NumberOfFrames', 1)) != 1):
        raise ValueError('Unsupported calcium pixel contract.')
    spacing = np.asarray(ds.get('PixelSpacing', []), float)
    if spacing.shape != (2,) or not np.isfinite(spacing).all() or (spacing <= 0).any():
        raise ValueError('Verified positive PixelSpacing is required.')
    raw = ds.pixel_array
    if raw.ndim != 2 or min(raw.shape) < 512 or np.ptp(raw) == 0:
        raise ValueError('Invalid native image.')
    if photometric == 'MONOCHROME1':
        bits = int(ds.get('BitsStored', 0))
        if (not 1 <= bits <= 16 or int(ds.get('HighBit', -1)) != bits - 1
                or ds.get('ModalityLUTSequence') or ds.get('VOILUTSequence')
                or ds.get('PresentationLUTSequence')
                or str(ds.get('PresentationLUTShape', 'INVERSE')) != 'INVERSE'):
            raise ValueError('Unsupported MONOCHROME1 transform contract.')
        maximum = (1 << bits) - 1
        if raw.min() < 0 or raw.max() > maximum:
            raise ValueError('Pixel values exceed the declared stored-bit range.')
        padding = None
        if ds.get('PixelPaddingValue') is not None:
            low = int(ds.get('PixelPaddingValue'))
            high = int(ds.get('PixelPaddingRangeLimit', low))
            padding = (raw >= min(low, high)) & (raw <= max(low, high))
        raw = maximum - raw
        if padding is not None:
            raw = raw.copy()
            raw[padding] = 0
        if np.ptp(raw) == 0:
            raise ValueError('No valid calcium intensity range.')
    im = raw.astype(float) / 65535
    if im.max() <= 1 / 16:
        im *= 16
    im = (np.floor(im * 65535).astype(np.uint16) >> 8).astype(np.float32) / 255
    return im, spacing


def probability_map(im, net):
    import numpy as np
    import torch
    h, w = im.shape
    prob = np.zeros(im.shape, np.float32)
    coverage = np.zeros(im.shape, bool)
    with torch.inference_mode():
        for t, b, l, r in windows(im.shape):
            patch = net(torch.from_numpy(im[t:b, l:r] * 2 - 1)[None, None])[0, 0].numpy()
            if patch.shape != (512, 512) or not np.isfinite(patch).all():
                raise ValueError('Invalid probability tile.')
            a, c = (0 if t == 0 else 128), (0 if b == h else 128)
            d, e = (0 if l == 0 else 128), (0 if r == w else 128)
            region = np.s_[t + a:b - c, l + d:r - e]
            prob[region] = patch[a:512 - c, d:512 - e]
            coverage[region] = True
    if not coverage.all() or (prob < 0).any() or (prob > 1).any():
        raise ValueError('Incomplete or invalid calcium map.')
    return prob



def candidate_scores(im, net, xy):
    """Evaluate only final-owner tiles, exactly preserving full-map sample scores.

    Overlapping final edge tiles overwrite earlier predictions in probability_map.
    Each point is assigned to its last writer before any network call is skipped.
    No candidate, input resolution, contextual tile or decision threshold changes.
    """
    import numpy as np
    points = np.asarray(xy)
    if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
            or (points != np.floor(points)).any()):
        raise ValueError('Candidate coordinates must be finite integer XY.')
    h, w = im.shape
    if ((points[:, 0] < 0).any() or (points[:, 0] >= w).any()
            or (points[:, 1] < 0).any() or (points[:, 1] >= h).any()):
        raise ValueError('Candidate lies outside the image.')
    tiles = windows(im.shape)
    scores = np.empty(len(points), np.float32)
    stats = dict(total_tiles=len(tiles), evaluated_tiles=0, candidate_points=len(points))
    if not len(points):
        return scores, stats
    points = points.astype(np.int64)
    x, y = points[:, 0], points[:, 1]
    owner = np.full(len(points), -1, np.int32)
    for index, (t, b, l, r) in enumerate(tiles):
        a, c = (0 if t == 0 else 128), (0 if b == h else 128)
        d, e = (0 if l == 0 else 128), (0 if r == w else 128)
        owner[(y >= t+a) & (y < b-c) & (x >= l+d) & (x < r-e)] = index
    if (owner < 0).any():
        raise ValueError('A candidate has no valid contextual tile.')
    import torch
    with torch.inference_mode():
        for index in np.unique(owner):
            t, b, l, r = tiles[index]
            patch = net(torch.from_numpy(im[t:b, l:r] * 2 - 1)[None, None])[0, 0].numpy()
            if (patch.shape != (512, 512) or not np.isfinite(patch).all()
                    or (patch < 0).any() or (patch > 1).any()):
                raise ValueError('Invalid probability tile.')
            chosen = owner == index
            scores[chosen] = patch[y[chosen]-t, x[chosen]-l]
            stats['evaluated_tiles'] += 1
    return scores, stats

def run(request, assets, job, threads):
    import cv2
    import numpy as np
    import pydicom
    import segmentation_models_pytorch as smp
    import torch
    for name, expected in FROZEN.items():
        if digest(assets / name) != expected:
            raise ValueError('Frozen calcium asset mismatch.')
    sys.path.insert(0, str(assets))
    from physical_peaks_fast import extract_physical_peaks
    from morphology_stage_20261005 import silhouette_distance
    from air_context_v2_20261005 import air_context
    torch.set_num_threads(threads)
    cv2.setNumThreads(threads)
    started = time.monotonic()
    net = smp.FPN(encoder_name='inceptionv4', encoder_weights=None, in_channels=1,
                  classes=1, activation='sigmoid').cpu().eval()
    net.load_state_dict(torch.load(assets / 'hdog-original-state-only-20261003.pt',
                                   map_location='cpu', weights_only=True), strict=True)
    head = torch.load(assets / 'headonly_binary_candidate_bce-not-qualified.pt',
                      map_location='cpu', weights_only=True)
    net.decoder.load_state_dict(head['decoder'], strict=True)
    net.segmentation_head.load_state_dict(head['head'], strict=True)
    net.requires_grad_(False)
    load_seconds = time.monotonic() - started
    records = []
    for record in request['files']:
        start = time.monotonic()
        if digest(record['path']) != record['sha256']:
            raise ValueError('Source changed before calcium inference.')
        ds = pydicom.dcmread(record['path'])
        if (str(ds.SOPInstanceUID) != record['sop_uid']
                or str(ds.SeriesInstanceUID) != record['series_uid']
                or str(ds.StudyInstanceUID) != request['study_uid']):
            raise ValueError('Calcium source identity mismatch.')
        im, spacing = pixels(ds)
        peak_started = time.monotonic()
        residual = im - cv2.GaussianBlur(im, (0, 0), 3)
        peaks = extract_physical_peaks(residual, threshold=.006, spacing_yx_mm=spacing,
                                      min_distance_mm=.1, valid_mask=im > .01)
        xy = peaks[:, :2]
        peak_seconds = time.monotonic() - peak_started
        network_started = time.monotonic()
        scores, tile_stats = candidate_scores(im, net, xy)
        network_seconds = time.monotonic() - network_started
        selected = scores >= CUTOFF
        xy, scores = xy[selected], scores[selected]
        removed = np.zeros(len(xy), bool)
        if len(xy):
            removed = ((silhouette_distance(im, xy, spacing) <= 1)
                       & air_context(im, xy, spacing)['air_only_flag'])
        if digest(record['path']) != record['sha256']:
            raise ValueError('Source changed during calcium inference.')
        records.append(dict(sop_uid=record['sop_uid'], series_uid=record['series_uid'],
                            source_sha256=record['sha256'], shape_hw=list(im.shape),
                            spacing_yx_mm=spacing.tolist(), points_xy=xy[~removed].tolist(),
                            scores=scores[~removed].tolist(), edge_removed_count=int(removed.sum()),
                            elapsed_seconds=time.monotonic() - start,
                            peak_seconds=peak_seconds, network_seconds=network_seconds,
                            tile_stats=tile_stats))
    result = dict(status='success', qualification='research_only', study_id=request['study_uid'],
                  coordinate_space='native_source_pixels_xy', semantics='localization_support_points_not_individual_calcification_count',
                  morphology_status='unavailable', preprocessing_revision='b93-stored-code-polarity-v2',
                  scoring_revision='b94-exact-sparse-last-writer-v1',
                  peak_revision='b95-exact-singleton-vectorized-v1',
                  cutoff=CUTOFF, files=records,
                  load_seconds=load_seconds, elapsed_seconds=time.monotonic() - started)
    (job / 'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request', type=Path, required=True)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--deps', type=Path, required=True)
    p.add_argument('--job', type=Path, required=True)
    p.add_argument('--threads', type=int, choices=range(1, 5), default=2)
    a = p.parse_args()
    sys.path.insert(0, str(a.deps.resolve()))
    run(json.loads(a.request.read_text(encoding='utf-8')), a.assets.resolve(), a.job.resolve(), a.threads)
