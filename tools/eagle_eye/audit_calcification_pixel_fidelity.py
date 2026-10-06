"""Read-only protected DICOM/PNG intensity audit; emit aggregate evidence only."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pydicom


def ranks(values):
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    return (np.cumsum(counts) - (counts + 1) / 2)[inverse]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--count', type=int, default=20)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.count <= 64:
        raise ValueError('Output exists or invalid bounded sample size.')
    records = [json.loads(line) for line in args.manifest.read_text().splitlines()]
    records = sorted([r for r in records if r['partition'] == 'train' and r['boxes']],
                     key=lambda r: hashlib.sha256(r['image_id'].encode()).digest())[:args.count]
    rng = np.random.default_rng(20261001)
    failures, polarity = Counter(), Counter()
    correlations, source_values, png_values = [], [], []
    for record in records:
        try:
            ds = pydicom.dcmread(record['full_image_path'])
            raw = ds.pixel_array
            with Image.open(record['png_full_path']) as image:
                rendered = np.asarray(image)
            if raw.ndim != 2 or raw.shape != rendered.shape:
                raise ValueError('Geometry mismatch.')
            valid = np.ones(raw.shape, dtype=bool)
            if 'PixelPaddingValue' in ds:
                padding = int(ds.PixelPaddingValue)
                end = int(ds.get('PixelPaddingRangeLimit', padding))
                valid &= (raw < min(padding, end)) | (raw > max(padding, end))
            locations = np.flatnonzero(valid)
            if len(locations) < 100:
                raise ValueError('Insufficient valid pixels.')
            locations = rng.choice(locations, min(50000, len(locations)), replace=False)
            x, y = raw.ravel()[locations], rendered.ravel()[locations]
            rx, ry = ranks(x), ranks(y)
            if np.std(rx) == 0 or np.std(ry) == 0:
                raise ValueError('Constant intensity sample.')
            correlation = float(np.corrcoef(rx, ry)[0, 1])
            correlations.append(abs(correlation))
            source_values.append(len(np.unique(x))); png_values.append(len(np.unique(y)))
            sign = 'inverted' if correlation < -.8 else 'same_order' if correlation > .8 else 'weak_relation'
            polarity[f'{ds.get("PhotometricInterpretation", "unknown")}:{sign}'] += 1
        except Exception as error:
            failures[type(error).__name__] += 1  # Never log private paths or exception text.
    report = dict(sampled_positive_training_images=len(records), decoded_pairs=len(correlations),
                  failures_by_type=dict(failures), raw_to_png_polarity_counts=dict(polarity),
                  median_absolute_rank_correlation=float(np.median(correlations)) if correlations else None,
                  median_sampled_raw_levels=float(np.median(source_values)) if source_values else None,
                  median_sampled_png_levels=float(np.median(png_values)) if png_values else None,
                  limitations=['raw stored-value comparison; no modality/VOI/presentation-LUT parity proof',
                               'global pixel sample; not evidence of individual microcalcification visibility',
                               'correlation does not establish correct diagnostic rendering'])
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps(report, allow_nan=False))


if __name__ == '__main__':
    main()
