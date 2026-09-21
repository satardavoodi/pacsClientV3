"""Window-owned verification cache for immutable, hash-sealed runtime files.

Full content verification runs on first use or any observed file metadata change.
Subsequent prompts inspect every sealed file's identity/size/write/change times.
No image, patient state or live interpreter object is retained here.
"""
import json
from pathlib import Path


class RuntimeSeal:
    def __init__(self):
        self._verified = None

    @staticmethod
    def _snapshot(root, cancel):
        manifest_path = root/'manifest.json'
        content = manifest_path.read_bytes()
        manifest = json.loads(content)
        names = sorted(manifest['sha256'])
        if not names or len(names) > 50_000:
            raise ValueError('Unexpected runtime manifest size.')
        signatures = []
        for name in names:
            if cancel.is_set():
                raise ValueError('Analysis cancelled.')
            path = (root/name).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Invalid runtime manifest path.')
            stat = path.stat()
            signatures.append((name, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        return str(root), content, tuple(signatures)

    def verify(self, root, cancel):
        from ..eagle_eye_alignment.service import validate_bundle
        root = Path(root).resolve()
        before = self._snapshot(root, cancel)
        if before == self._verified:
            return
        self._verified = None
        validate_bundle(root, cancel)
        after = self._snapshot(root, cancel)
        if before != after:
            raise ValueError('Runtime files changed during verification. Retry after preparation completes.')
        self._verified = after
