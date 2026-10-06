"""Private clinical transcript storage, separate from diagnostic logs.

An authenticated owner is supplied by the host, never by the request body.
Case context is a client-origin study/session reference, not a PACS identity claim.
"""
from contextlib import closing
from pathlib import Path
import json
import re
import sqlite3
import time
from uuid import UUID


def validate_context(value):
    if not isinstance(value, dict) or set(value) - {'study_uid', 'session_id'}:
        raise ValueError('Invalid history context')
    result = {}
    for key, text in value.items():
        if not isinstance(text, str) or not text or len(text) > 128 or any(ord(c) < 32 for c in text):
            raise ValueError('Invalid history context')
        if key == 'study_uid' and not re.fullmatch(r'[0-9.]{1,64}', text):
            raise ValueError('Invalid study reference')
        result[key] = text
    return result


def request_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Invalid request identifier')
    return value


class History:
    def __init__(self, directory):
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise ValueError('History directory must be absolute')

    def _open(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.directory / 'history.sqlite3', timeout=10)
        db.execute('''CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY, owner TEXT NOT NULL, context_json TEXT NOT NULL,
            workflow TEXT NOT NULL, state TEXT NOT NULL, request_json TEXT NOT NULL,
            response_json TEXT, started_at REAL NOT NULL, completed_at REAL)''')
        db.execute('''CREATE INDEX IF NOT EXISTS case_history_read ON requests
            (owner, json_extract(context_json, '$.study_uid'), state, completed_at)''')
        db.commit()
        return db

    def begin(self, rid, owner, context, body):
        with closing(self._open()) as db, db:
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,NULL,?,NULL)',
                (request_id(rid), owner, json.dumps(validate_context(context)),
                 body.get('workflow', 'report'), 'running', json.dumps(body, ensure_ascii=False), time.time()))

    def finish(self, rid, owner, result=None, *, failed=False):
        with closing(self._open()) as db, db:
            db.execute('UPDATE requests SET state=?, response_json=?, completed_at=? WHERE request_id=? AND owner=?',
                ('failed' if failed else 'succeeded',
                 None if failed else json.dumps(result, ensure_ascii=False), time.time(), rid, owner))

    def case_list(self, owners, study_uid, *, offset=0):
        if not owners:
            return []
        validate_context({'study_uid': study_uid})
        with closing(self._open()) as db:
            rows = db.execute(f'''SELECT request_id, workflow, completed_at FROM requests
                WHERE owner IN ({','.join('?' for _ in owners)})
                AND json_extract(context_json, '$.study_uid')=? AND state='succeeded'
                ORDER BY completed_at DESC, request_id DESC LIMIT 51 OFFSET ?''',
                (*owners, study_uid, offset)).fetchall()
        return [dict(request_id=rid, workflow=workflow, completed_at=stamp)
                for rid, workflow, stamp in rows]

    def case_result(self, owners, study_uid, rid):
        request_id(rid)
        validate_context({'study_uid': study_uid})
        if not owners:
            raise KeyError('Saved response unavailable.')
        with closing(self._open()) as db:
            row = db.execute(f'''SELECT response_json FROM requests
                WHERE request_id=? AND owner IN ({','.join('?' for _ in owners)})
                AND json_extract(context_json, '$.study_uid')=? AND state='succeeded' ''',
                (rid, *owners, study_uid)).fetchone()
        if not row or not row[0]:
            raise KeyError('Saved response unavailable.')
        return dict(json.loads(row[0]), request_id=rid)
