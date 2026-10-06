"""Stage protected development-only digital transfer inputs; no training or test tuning."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.manifest.read_text().splitlines()]
    rows = [row for row in rows if row['partition'] == 'validation']
    selected, seen = [], set()
    for positive in (True, False):
        count = 0
        for row in sorted(rows, key=lambda r: hashlib.sha256(r['image_id'].encode()).digest()):
            eligible = bool(row['boxes']) if positive else row['all_finding_labels'] == ['No Finding']
            if not eligible or row['study_id'] in seen:
                continue
            seen.add(row['study_id']); selected.append(row); count += 1
            if count == 12:
                break
        if count != 12:
            raise ValueError('Insufficient disjoint development studies.')
    staged = []
    with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_STORED) as archive:
        for index, row in enumerate(selected):
            path = Path(row['png_full_path'])
            with Image.open(path) as image:
                image.load()
                if image.size != (row['width'], row['height']):
                    raise ValueError('Digital source geometry mismatch.')
            name = f'images/{index:03d}.png'
            archive.write(path, name)
            staged.append(dict(image=name, partition='validation', boxes=row['boxes'],
                               person_key=hashlib.sha256(row['study_id'].encode()).hexdigest(),
                               source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                               control_label='Suspicious Calcification' if row['boxes'] else 'No Finding',
                               grouping='study proxy; not verified patient grouping'))
        archive.writestr('manifest.json', json.dumps(staged))
    report = dict(images=len(staged), positive_images=12, no_finding_controls=12,
                  targets=sum(len(row['boxes']) for row in staged),
                  sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                  protocol='development transfer; suspicious boxes; No Finding does not exclude benign calcification')
    args.output.with_suffix('.aggregate.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
