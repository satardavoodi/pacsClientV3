"""Local full-service acceptance probe; keep its output inside private User Data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--t1', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True, help='Feature payload root containing model and references')
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--age', type=float)
    parser.add_argument('--sex', choices=('male', 'female', 'unknown'), default='unknown')
    args = parser.parse_args()
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.service import run_analysis
    from modules.ai_imaging.eagle_eye_brain.normative import BrainDemographics
    from modules.ai_imaging.eagle_eye_brain.runtime import sha256
    app = QApplication.instance() or QApplication([])
    model = args.bundle.resolve() / 'model'
    probe_file = args.bundle.resolve() / 'runtime-probe.json'
    probe = json.loads(probe_file.read_text(encoding='utf-8'))
    digest = sha256(model / 'manifest.json')
    if probe.get('model_manifest_sha256') != digest or probe.get('status') != 'passed':
        raise RuntimeError('A current interpreter/import probe is required first')
    output = args.output_root.resolve()
    from aipacs_runtime import user_data_root
    if not output.is_relative_to(user_data_root().resolve()):
        raise ValueError('Patient validation outputs must remain inside private User Data')
    output.mkdir(parents=True, exist_ok=True)
    record = {'status': 'failed', 'model_manifest_sha256': digest,
              'scope': 'Local service pipeline; not clean-machine or clinical acceptance'}
    try:
        result = run_analysis(args.t1, None, output, bundle=model,
            demographics=BrainDemographics(args.age, args.sex), reference_id='volbrain',
            progress=lambda text: print(text, flush=True))
        if not result.get('pdf_available'):
            raise RuntimeError('The service did not produce a PDF')
        record.update(status='passed', posterior_row_count=len(result['posterior_rows']),
            binary_row_count=len(result['binary_rows']), pdf_available=True,
            reference_status=result['normative']['status'], artifact_directory=result['artifact_directory'])
        probe.update(inference_status='passed')
        probe.pop('inference_exit_code', None)
    except Exception:
        probe.update(inference_status='failed')
        raise
    finally:
        (output / 'acceptance.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        # No patient identity, image digest or output path enters the distributable probe.
        temporary = probe_file.with_suffix('.partial')
        temporary.write_text(json.dumps(probe, indent=2), encoding='utf-8')
        temporary.replace(probe_file)
    print('Full local portable Windows service probe passed; distribution is not approved.')
    return app


if __name__ == '__main__':
    main()
