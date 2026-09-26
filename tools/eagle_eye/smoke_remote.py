"""Loopback-only synthetic PACS -> server model -> client acceptance probe.

Starts neither the workstation UI nor a clinical server. Uses only generated data.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def smoke(engine, output, hosted=False):
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, DigitalXRayImageStorageForPresentation, generate_uid
    from modules.ai_imaging.eagle_eye_remote.source import PacsSource
    from modules.ai_imaging.eagle_eye_remote.server import Jobs, handler
    from modules.ai_imaging.eagle_eye_remote.client import Client
    root = Path(output).resolve() / ('smoke-' + uuid.uuid4().hex)
    pacs_root = root / 'pacs'
    pacs_root.mkdir(parents=True)
    study, series, sop = generate_uid(), generate_uid(), generate_uid()
    meta = FileMetaDataset()
    meta.TransferSyntaxUID, meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID = ExplicitVRLittleEndian, DigitalXRayImageStorageForPresentation, sop
    path = pacs_root / 'synthetic.dcm'
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.SOPInstanceUID = study, series, sop
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.Modality, ds.BodyPartExamined, ds.PatientSex = ('MG' if engine == 'breast' else 'DX'), 'HAND', 'M'
    ds.Rows = ds.Columns = 512
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit, ds.PixelRepresentation = 15, 0
    ds.PixelSpacing, ds.ImageLaterality, ds.ViewPosition = [.1, .1], 'L', 'CC'
    yy, xx = np.mgrid[:512, :512]
    ds.PixelData = (500 + xx * 3 + yy * 2 + 1000 * np.exp(-((xx - 250)**2 + (yy - 230)**2) / 4000)).astype('<u2').tobytes()
    ds.save_as(path, write_like_original=False)
    calls = []
    class PacsHandler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path != '/api/ai-patient/by-study/' + study:
                self.send_error(404)
                return
            calls.append('metadata')
            raw = json.dumps({'study_info': {'study_id': study}, 'storage_info': {'study_path': str(pacs_root)}}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    pacs = ThreadingHTTPServer(('127.0.0.1', 0), PacsHandler)
    token = secrets.token_hex(32)
    token_file = root / 'access.token'
    token_file.write_text(token, encoding='utf-8')
    jobs = Jobs(root / 'server', PacsSource({'url': f'http://127.0.0.1:{pacs.server_port}', 'allowed_roots': [str(pacs_root)]}))
    api = ThreadingHTTPServer(('127.0.0.1', 0), handler(jobs, {'synthetic': token}))
    hosted_service = None
    if hosted:
        # Exercise the same launch-role and cache adapter used by the desktop.
        import sqlite3
        from modules.ai_imaging.eagle_eye_remote.launch import configure
        database = root / 'synthetic.db'
        with sqlite3.connect(database) as connection:
            connection.executescript('CREATE TABLE studies(study_pk,study_uid); CREATE TABLE series(series_uid,series_path,expected_instance_count,image_count,modality,study_fk);')
            connection.execute('INSERT INTO studies VALUES(1,?)', (study,))
            connection.execute('INSERT INTO series VALUES(?,?,?,?,?,1)', (series, str(pacs_root), 1, 1, ds.Modality))
        configuration = root / 'hosted.json'
        configuration.write_text(json.dumps({'host': '127.0.0.1', 'port': 0,
            'job_root': str(root / 'hosted-jobs'), 'clients': {'synthetic': str(token_file)},
            'pacs': {'type': 'workstation-cache', 'database': str(database), 'allowed_roots': [str(pacs_root)]}}))
        hosted_service = configure(['main.py', '--eagle-eye-mode', 'server', '--eagle-eye-config', str(configuration)])
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (pacs, api)]
    for thread in threads: thread.start()
    try:
        params = {'sex': 'M'} if engine == 'bone-age' else {'threshold': .45}
        port = hosted_service.server.server_port if hosted_service else api.server_port
        result = Client({'url': f'http://127.0.0.1:{port}', 'token_file': str(token_file)}).analyze(
            engine, study, {}, params, root / 'client', timeout=900)
        assert calls == ([] if hosted else ['metadata'])
        assert not list((root / 'client').rglob('*.dcm'))
        receipt = {'synthetic': True, 'engine': engine, 'transport': 'real-loopback-http',
                   'model_execution': 'real-cpu', 'server_pacs_metadata_requests': len(calls),
                   'launch_mode': 'hosted-server' if hosted else 'standalone-test',
                   'source_dicom_uploaded_by_client': False, 'source_dicom_downloaded_by_client': False,
                   'image_count': result['image_count'], 'classification_status': result.get('classification_status'),
                   'status': 'passed'}
        (root / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt))
    finally:
        if hosted_service:
            hosted_service.close()
        for s in (api, pacs): s.shutdown(); s.server_close()
        jobs.close()
        for thread in threads: thread.join(timeout=3)
        token_file.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', choices=('breast', 'bone-age'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hosted', action='store_true')
    args = parser.parse_args()
    smoke(args.engine, args.output, hosted=args.hosted)
