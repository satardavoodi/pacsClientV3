"""Synthetic PACS socket to Eagle Eye to two real clients, without clinical DB.

Run with the PACS server interpreter and --server-root pointing to its checkout.
"""
import argparse
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-root', required=True)
    args = parser.parse_args()
    workstation = Path(__file__).resolve().parents[2]
    pacs_root = Path(args.server_root).resolve()
    sys.path[:0] = [str(workstation), str(pacs_root / 'tests'), str(pacs_root)]
    from socket_harness import workflow_server
    from modules.ai_imaging.eagle_eye_remote.server import Jobs, handler
    from modules.ai_imaging.eagle_eye_remote.case_realtime import CaseService
    from modules.ai_imaging.eagle_eye_remote.case_receiver import CaseReceiver
    from modules.ai_imaging.eagle_eye_remote.pacs_case_bridge import PacsCaseBridge
    from modules.ai_imaging.eagle_eye_remote.text_history import History
    from modules.ai_imaging.eagle_eye_remote.client import Client
    from modules.ai_imaging.eagle_eye_remote.contracts import digest
    from modules.ai_imaging.eagle_eye_remote.pacs_resources import PacsResources

    case = {'study_uid': '1.2.3', 'patient_id': 'synthetic'}
    pacs, namespace = workflow_server([dict(StudyInstanceUID='1.2.3', PatientID='synthetic', reportStatus='pending')])
    pacs_thread = threading.Thread(target=pacs.start, daemon=True)
    pacs_thread.start()
    def wait(predicate, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(.02)
        raise AssertionError('Three-node synthetic acceptance timed out')
    receivers, http, jobs, bridge = [], None, None, None
    try:
        wait(lambda: pacs.running)
        class Source:
            config = {'url': 'http://127.0.0.1'}
            session = SimpleNamespace(headers={'Authorization': 'Bearer synthetic-token'}, close=lambda: None)
            def case_identity(self, uid):
                row = namespace['workflow_rows'][0]
                if row['StudyInstanceUID'] != uid:
                    raise KeyError('Synthetic case missing')
                return dict(study_uid=uid, patient_id=row['PatientID'])
            def stage(self, request, destination, cancel):
                destination.mkdir()
                file = destination / 'synthetic.dcm'
                file.write_bytes(b'synthetic-source')
                return [dict(path=str(file), study_uid='1.2.3', series_uid='1.2.3.4',
                    sop_uid='1.2.3.4.5', sha256=digest(file), roles=['primary'])]
        def runner(job, cancel):
            work = job / 'work'
            work.mkdir()
            pdf = work / 'report.pdf'
            pdf.write_bytes(b'%PDF-1.4 synthetic')
            return {'artifact_directory': str(work), 'report': str(pdf), 'value': 12.5}
        with tempfile.TemporaryDirectory(prefix='aipacs-three-node-') as temporary:
            root = Path(temporary)
            jobs = Jobs(root / 'jobs', Source(), runner)
            history = History(root / 'history')
            cases = CaseService(jobs, history, {'first': 'center', 'second': 'center'}, 'center')
            jobs.case_events = cases.events
            bridge = PacsCaseBridge(cases, dict(url='http://127.0.0.1', socket_port=pacs.socket.getsockname()[1]))
            jobs.case_bridge = bridge
            bridge.start()
            tokens = {'first': 'a' * 64, 'second': 'b' * 64}
            http = ThreadingHTTPServer(('127.0.0.1', 0), handler(jobs, tokens, cases=cases))
            http.daemon_threads = True
            http_thread = threading.Thread(target=http.serve_forever, daemon=True)
            http_thread.start()
            configs = {}
            latest = [{}, {}]
            for name, token in tokens.items():
                variable = 'SYNTHETIC_CASE_' + name
                os.environ[variable] = token
                cfg = dict(url=f'http://127.0.0.1:{http.server_port}', token_env=variable)
                configs[name] = cfg
                receiver = CaseReceiver(case, settings=cfg, pacs_host='127.0.0.1')
                receiver.start()
                receivers.append(receiver)
            def observed(predicate):
                for index, receiver in enumerate(receivers):
                    value = receiver.drain()
                    if value:
                        latest[index] = value
                return all(predicate(value) for value in latest)
            wait(lambda: observed(lambda s: s.get('workflow', {}).get('report_status') == 'pending'))
            row = namespace['workflow_rows'][0]
            namespace['studies_collection'].find_one = lambda query, *args: (
                dict(row) if query.get('StudyInstanceUID') == row['StudyInstanceUID'] else None)
            row.update(NumberOfInstances=12, NumberOfSeries=3, radiologistId='synthetic-doctor',
                       radiologistName='Synthetic physician', radiologistSource='pacs')
            pacs.broadcast_study_updated('1.2.3', 'synthetic')
            wait(lambda: observed(lambda s: s.get('workflow', {}).get('image_count') == 12
                and s.get('workflow', {}).get('assignment', {}).get('radiologist', {}).get('id') == 'synthetic-doctor'))
            row['reportStatus'] = 'completed'
            pacs.broadcast_report_status_changed('1.2.3', 'synthetic', 'pending', 'completed')
            wait(lambda: observed(lambda s: s.get('workflow', {}).get('report_status') == 'completed'))
            row['attachments'] = [dict(attachment_type='voice', file_name='synthetic.wav', file_size=8)]
            voice_file = root / 'synthetic.wav'
            voice_file.write_bytes(b'fixture!')
            row['attachments'][0]['file_path'] = str(voice_file)
            pacs.broadcast_audio_uploaded('1.2.3', 'synthetic')
            wait(lambda: observed(lambda s: s.get('workflow', {}).get('audio_count') == 1))
            row['attachments'].append(dict(attachment_type='document', file_name='synthetic.pdf', file_size=10))
            report_file = root / 'synthetic.pdf'
            report_file.write_bytes(b'%PDF-1.4 x')
            row['attachments'][-1]['file_path'] = str(report_file)
            pacs.broadcast_attachment_uploaded('1.2.3', 'synthetic', {'attachment_type': 'document'})
            wait(lambda: observed(lambda s: s.get('workflow', {}).get('document_count') == 1))
            image_file = root / 'synthetic.png'
            image_file.write_bytes(b'synthetic-image')
            row['attachments'].append(dict(attachment_type='image', file_name='synthetic.png',
                file_size=15, file_path=str(image_file)))
            previous_revision = latest[1]['workflow']['attachment_revision']
            pacs.broadcast_attachment_uploaded('1.2.3', 'synthetic', {'attachment_type': 'image'})
            wait(lambda: observed(lambda s: s.get('workflow', {}).get('attachment_revision') != previous_revision))
            resources = PacsResources(case, '127.0.0.1', pacs.socket.getsockname()[1], 'synthetic-token')
            files = resources.inventory('audio')
            assert Path(resources.download(files[0], root / 'media')).read_bytes() == b'fixture!'
            files = resources.inventory('document')
            assert Path(resources.download(files[0], root / 'media')).read_bytes() == b'%PDF-1.4 x'
            images = [file for file in resources.inventory() if file['attachment_type'] == 'image']
            assert Path(resources.download(images[0], root / 'media')).read_bytes() == b'synthetic-image'
            rid = str(uuid.uuid4())
            history.begin(rid, 'first', {'study_uid': '1.2.3'}, {'workflow': 'report'})
            history.finish(rid, 'first', {'content': 'Synthetic original response'})
            cases.events.publish('1.2.3', 'echomind')
            wait(lambda: observed(lambda s: bool(s.get('echomind'))))
            assert Client(configs['second']).saved_text(case, rid)['content'] == 'Synthetic original response'
            result = Client(configs['first']).analyze('bone-age', '1.2.3', {}, {}, root / 'first')
            wait(lambda: observed(lambda s: bool(s.get('eagle_eye'))))
            job_id = latest[1]['eagle_eye'][0]['job_id']
            original_count = len(jobs.jobs)
            def reject_submission(*args, **kwargs):
                raise AssertionError('Saved retrieval submitted new inference')
            jobs.submit = reject_submission
            retrieved = Client(configs['second']).saved_analysis(case, job_id, root / 'second')
            assert retrieved['value'] == result['value'] and len(jobs.jobs) == original_count
            row['attachments'] = []
            pacs._workflow.invalidate()
            wait(lambda: observed(lambda s: s.get('workflow', {}).get('audio_count') == 0), timeout=12)
            print(json.dumps({'result': 'passed', 'clients': 2, 'checks': [
                'pacs_to_eagle_eye_to_clients', 'reporting_doctor', 'image_inventory', 'report_status', 'voice', 'document',
                'original_voice_file', 'original_report_file', 'image_attachment', 'original_image_file', 'shared_echomind',
                'shared_eagle_eye', 'no_repeat_inference', 'pacs_reconnect']}))
            for receiver in receivers:
                receiver.stop()
            cases.events.close()
            for receiver in receivers:
                receiver.join(3)
                assert not receiver.is_alive()
            bridge.stop()
            bridge.join(6)
            http.shutdown()
            http.server_close()
            http_thread.join(3)
            http = None
            jobs.close()
            jobs = None
    finally:
        for receiver in receivers:
            receiver.stop()
        if bridge:
            bridge.stop()
        if jobs:
            jobs.close()
        if http:
            http.shutdown()
            http.server_close()
        pacs.stop()
        pacs_thread.join(3)
        assert not pacs_thread.is_alive()
        for name in ('first', 'second'):
            os.environ.pop('SYNTHETIC_CASE_' + name, None)


if __name__ == '__main__':
    main()
