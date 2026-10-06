"""Explicit worker-only voice/report reads with exact case and safe publication."""
import base64
import hashlib
from pathlib import Path
import socket
import uuid

from modules.network.workflow_realtime import send, receive
from .contracts import case_reference, digest

FORMATS = {'.wav', '.mp3', '.m4a', '.ogg', '.webm', '.pdf', '.txt', '.png', '.jpg', '.jpeg'}
MAX_FILE = 32 * 1024**2


class PacsResources:
    def __init__(self, reference, host, port, token):
        self.reference = case_reference(reference)
        self.address, self.token = (host, int(port)), token

    def request(self, endpoint, params, *, limit=1024**2):
        with socket.create_connection(self.address, timeout=5) as sock:
            rid = send(sock, endpoint, params, self.token)
            reply = receive(sock, timeout=30, max_frame=limit)
        if reply.get('request_id') != rid or reply.get('status') != 'success':
            raise ValueError('PACS resource read rejected.')
        return reply.get('data') or {}

    def verify(self):
        data = self.request('GetWorkflowStates', {'study_uids': [self.reference['study_uid']]})
        states = data.get('states') or []
        if (data.get('realtime_version') != 1 or len(states) != 1
                or any(states[0].get(k) != v for k, v in self.reference.items())):
            raise ValueError('PACS resource case changed or access denied.')
        return states[0]

    def inventory(self, kind=''):
        state = self.verify()
        data = self.request('GetStudyAttachments', {'study_uid': self.reference['study_uid'], 'include_data': False})
        self.validate_case(data)
        rows = data.get('attachments')
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError('PACS resource inventory exceeds the limit.')
        selected = [dict(file_name=r['file_name'], file_size=r.get('file_size', 0),
                     attachment_type=r.get('attachment_type', '')) for r in rows
                if self.safe_row(r) and (not kind or r.get('attachment_type') in
                    ({'audio', 'voice', 'sound'} if kind == 'audio' else {'document', 'report'}))]
        if state.get('legacy_audio') and kind in ('', 'audio'):
            selected.append(dict(file_name='Saved study recording', legacy=True,
                                 attachment_type='audio', file_size=0))
        return selected

    def validate_case(self, data):
        if any(data.get(k) != v for k, v in self.reference.items()):
            raise ValueError('PACS resource response belongs to another case.')

    @staticmethod
    def safe_row(row):
        if not isinstance(row, dict):
            return False
        name = row.get('file_name')
        return (isinstance(name, str) and 0 < len(name) <= 240 and '/' not in name
            and '\\' not in name and ':' not in name and not any(ord(c) < 32 for c in name)
            and Path(name).suffix.lower() in FORMATS and type(row.get('file_size')) is int
            and 0 <= row['file_size'] <= MAX_FILE)

    def download(self, row, destination):
        if row.get('legacy') is True:
            self.verify()
            data = self.request('GetStudyAudio', {'study_uid': self.reference['study_uid']}, limit=48 * 1024**2)
            self.verify()
            suffix = '.' + str(data.get('audio_format', '')).lower()
            raw = base64.b64decode(data.get('audio_data', ''), validate=True)
            if suffix not in FORMATS or len(raw) != data.get('audio_file_size') or len(raw) > MAX_FILE:
                raise ValueError('Saved study recording is incomplete or unsupported.')
            return self.publish(raw, suffix, destination)
        if not self.safe_row(row):
            raise ValueError('Invalid PACS resource.')
        self.verify()
        data = self.request('GetStudyAttachments', {'study_uid': self.reference['study_uid'],
            'include_data': True, 'names': [row['file_name']]}, limit=48 * 1024**2)
        self.validate_case(data)
        rows = data.get('attachments') or []
        if len(rows) != 1 or rows[0].get('file_name') != row['file_name']:
            raise ValueError('PACS resource selection changed.')
        raw = base64.b64decode(rows[0].get('attachment_data', ''), validate=True)
        if len(raw) != row['file_size'] or len(raw) > MAX_FILE:
            raise ValueError('PACS resource changed or is incomplete.')
        return self.publish(raw, Path(row['file_name']).suffix.lower(), destination)

    @staticmethod
    def publish(raw, suffix, destination):
        root = Path(destination).resolve()
        root.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(raw).hexdigest()
        target = root / ('server-' + sha + suffix)
        if target.is_symlink():
            raise ValueError('Invalid resource cache target.')
        if target.exists():
            if digest(target) != sha:
                raise ValueError('Resource cache identity changed.')
            return str(target)
        temporary = root / (uuid.uuid4().hex + '.partial')
        try:
            temporary.write_bytes(raw)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return str(target)
