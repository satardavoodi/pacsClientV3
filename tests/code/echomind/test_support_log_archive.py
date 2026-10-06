import base64
import io
import json
import os
from datetime import datetime, timezone
from zipfile import ZipFile

from PacsClient.utils.support_log_archive import build_log_archive


def test_archive_filters_old_records_and_keeps_tracebacks_and_manifest(tmp_path):
    now = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    (tmp_path/'app.log').write_text('2026-09-29 12:00:00 OLD\nold traceback\n2026-10-02 11:00:00 RECENT\nrecent traceback\n')
    os.utime(tmp_path/'app.log', (now.timestamp(), now.timestamp()))
    (tmp_path/'passwords.json').write_text('excluded')
    result = build_log_archive(tmp_path, now=now)
    with ZipFile(io.BytesIO(base64.b64decode(result['base64']))) as archive:
        body = archive.read('logs/log_001.log')
        assert b'RECENT' in body and b'recent traceback' in body and b'OLD' not in body
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['window_hours'] == 24
        assert manifest['files'][0]['selection'] == 'record_timestamps'
        assert len(archive.namelist()) == 2


def test_untimed_recent_logs_are_marked_as_mtime_selection_and_old_files_excluded(tmp_path):
    now = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
    (tmp_path/'native_fault.log').write_text('Untimed native traceback')
    os.utime(tmp_path/'native_fault.log', (now.timestamp(), now.timestamp()))
    (tmp_path/'old.log').write_text('old')
    os.utime(tmp_path/'old.log', (now.timestamp()-90000, now.timestamp()-90000))
    result = build_log_archive(tmp_path, now=now)
    with ZipFile(io.BytesIO(base64.b64decode(result['base64']))) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert len(manifest['files']) == 1
        assert manifest['files'][0]['selection'] == 'file_modified_time'


def test_archive_is_bounded_and_does_not_follow_links(tmp_path):
    from PacsClient.utils import support_log_archive as module
    (tmp_path/'app.log').write_bytes(b'raw diagnostic\n'*200)
    result = build_log_archive(tmp_path, max_file_bytes=200, max_total_bytes=300)
    with ZipFile(io.BytesIO(base64.b64decode(result['base64']))) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['files'][0]['truncated'] is True
        assert len(archive.read('logs/log_001.log')) <= 200
    assert result['bytes'] <= module.MAX_ZIP_BYTES


def test_raw_archive_is_opt_in_and_retry_keeps_original_zip(tmp_path):
    from tests.code.echomind.test_support_issue_reporting import Client, Store
    from PacsClient.utils.support_issue_reporting import IssueReporter
    (tmp_path/'app.log').write_text('Synthetic raw traceback')
    client, store = Client(), Store()
    client.fail = True
    reporter = IssueReporter('synthetic-user', client, store, tmp_path, archive_root=tmp_path/'tickets')
    context = {'pacs_user':'synthetic-user', 'app_version':'3.7.0'}
    reporter.submit('Synthetic problem', 'hang', False, context, include_log_archive=True)
    original = client.calls[-1]['log_archive']
    assert client.calls[-1]['consent_version'] == 'support-package-v3'
    package = client.calls[-1]['ticket_package']
    with ZipFile(io.BytesIO(base64.b64decode(package['base64']))) as archive:
        assert archive.testzip() is None
        assert 'logs.zip' in archive.namelist()
    (tmp_path/'app.log').write_text('Changed diagnostic')
    reporter.retry()
    assert client.calls[-1]['log_archive'] == original
    assert client.calls[-1]['ticket_package'] == package
    store.clear()
    reporter.submit('Synthetic problem', 'hang', False, context)
    assert 'log_archive' not in client.calls[-1]
