"""Worker-only, UUID-scoped Secretary source folders and bounded snapshots."""
import base64
import hashlib
from pathlib import Path
import stat
from uuid import UUID

from modules.ai_imaging.eagle_eye_remote.secretary.session_sources import EXTENSIONS, MAX_FILES, MAX_TOTAL, Source


def worker_only():
    from PySide6.QtCore import QCoreApplication, QThread
    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() == app.thread():
        raise RuntimeError('Session file operations must run on a background worker')


class SessionFiles:
    def __init__(self, root=None):
        if root is None:
            from PacsClient.utils.data_paths import ECHOMIND_DIR
            root = ECHOMIND_DIR / 'secretary_sessions'
        self.root = Path(root)

    def folder(self, session_id, create=True):
        worker_only()
        if str(UUID(session_id)) != session_id:
            raise ValueError('Invalid session identity')
        path = self.root / session_id / 'files'
        # Refuse junctions/symlinks anywhere below the trusted User Data root.
        for component in (self.root, self.root/session_id, path):
            if component.is_symlink() or (hasattr(component,'is_junction') and component.is_junction()):
                raise ValueError('Session folders cannot be links')
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def snapshot(self, session_id):
        folder = self.folder(session_id, create=False)
        if not folder.exists():
            return []
        result, total = [], 0
        for path in sorted(folder.iterdir()):
            if path.name.startswith('.') or path.name.lower() in {'desktop.ini','thumbs.db'}:
                continue
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or path.is_symlink():
                raise ValueError('Put files directly in the session folder; subfolders and links are unsupported')
            if path.suffix.lower() not in EXTENSIONS:
                raise ValueError('Session files support JPEG, PNG, PDF, PPTX, DOCX and UTF-8 TXT')
            total += before.st_size
            if len(result) >= MAX_FILES or total > MAX_TOTAL or before.st_size == 0:
                raise ValueError('Use at most 12 nonempty session files, 8 MiB in total')
            with path.open('rb') as stream:
                raw = stream.read(MAX_TOTAL+1)
            after = path.lstat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or len(raw)!=before.st_size:
                raise ValueError('Session file changed while reading; finish copying and retry')
            result.append(Source(name=path.name,sha256=hashlib.sha256(raw).hexdigest(),data=base64.b64encode(raw).decode('ascii')).model_dump())
        return result
