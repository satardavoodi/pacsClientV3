"""Explicitly consented raw log ZIP; worker-only, bounded and never recursive."""
import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
from zipfile import ZIP_DEFLATED, ZipFile

MAX_ZIP_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
_STAMP = re.compile(rb'^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:[,.]\d+)?(?:\s|\s*[-|])')
_NAME = re.compile(r'^[A-Za-z0-9_.-]{1,150}\.(?:log|txt)(?:\.\d{1,3})?$')


def build_log_archive(log_root, *, now=None, max_file_bytes=MAX_FILE_BYTES, max_total_bytes=MAX_TOTAL_BYTES):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    root = Path(log_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Log directory unavailable')
    candidates = []
    for index, path in enumerate(root.iterdir()):
        if index >= 256:
            break
        if not _NAME.fullmatch(path.name) or path.is_symlink():
            continue
        metadata = path.stat()
        if stat.S_ISREG(metadata.st_mode) and cutoff.timestamp() <= metadata.st_mtime <= now.timestamp()+5:
            candidates.append((metadata.st_mtime, path))
    candidates.sort(key=lambda item: (-item[0], item[1].name))
    files, used = [], 0
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for _, path in candidates[:32]:
            budget = min(max_file_bytes, max_total_bytes-used)
            if budget <= 0:
                break
            # Reject replacement/link races before opening; Windows reparse points
            # cannot be diagnostic inputs. Read only from the configured log root.
            metadata = path.lstat()
            if path.is_symlink() or getattr(metadata, 'st_file_attributes', 0) & 0x400:
                continue
            with path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                    continue
                size = stream.seek(0, 2)
                stream.seek(max(0, size-budget))
                data = stream.read(budget)
            if size > budget:
                data = data.partition(b'\n')[2]
            selected, active, timed = [], False, False
            for line in data.splitlines(keepends=True):
                match = _STAMP.match(line)
                if match:
                    timed = True
                    try:
                        timestamp = datetime.fromisoformat((match[1]+b' '+match[2]).decode()).astimezone(timezone.utc)
                        active = cutoff <= timestamp <= now
                    except ValueError:
                        active = False
                if active:
                    selected.append(line)
            content = b''.join(selected) if timed else data
            used += len(data)
            if not content:
                continue
            name = f'logs/log_{len(files)+1:03d}.log'
            archive.writestr(name, content)
            files.append({'entry':name, 'source':path.name, 'bytes':len(content),
                          'truncated':size > budget, 'selection':'record_timestamps' if timed else 'file_modified_time'})
        manifest = {'schema_version':1, 'window_hours':24, 'from_utc':cutoff.isoformat(), 'to_utc':now.isoformat(),
                    'timestamp_timezone':'local workstation time', 'files':files,
                    'limits':{'max_files':32, 'max_file_bytes':max_file_bytes, 'max_total_read_bytes':max_total_bytes},
                    'notice':'Raw logs may contain sensitive information. Untimed files use modification time and may contain older records.'}
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=True, indent=2))
    data = buffer.getvalue()
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError('Log archive exceeds the 2 MiB upload limit; send summaries without the archive')
    return {'window_hours':24, 'base64':base64.b64encode(data).decode('ascii'), 'sha256':sha256(data).hexdigest(), 'bytes':len(data)}
