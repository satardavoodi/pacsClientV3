"""Server-side PACS source resolution and immutable job staging; never client paths."""
import json
import os
from pathlib import Path
import shutil
import urllib.parse
import requests
import threading
import time

from .contracts import digest
from .pacs_credentials import read_pacs_credentials, pacs_address


class StorageFiles(list):
    """Server-attested atomic publication, never inferred from co-location."""
    def __init__(self, paths, *, atomic_replace=False):
        super().__init__(paths)
        self.atomic_replace = atomic_replace


class SourceLease:
    """Job-lifetime read protection for shared Windows file objects.

    Delete sharing permits PACS atomic replacement and independent alias cleanup.
    Write sharing is denied through every hardlink, including worker processes.
    Other platforms/filesystems retain isolated copies.
    """
    def __init__(self):
        self.handles = []

    def pin(self, path):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(Path(path).resolve()), 0x80000000, 5, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handles.append((kernel, handle))

    def materialize(self, path, out, *, share=False):
        if Path(out).exists():
            raise ValueError('Source destination already exists.')
        if share and os.name == 'nt' and os.environ.get('AIPACS_EAGLE_EYE_COPY_SOURCES') != '1':
            linked = False
            try:
                os.link(path, out)
                linked = True
                self.pin(out)
                return 'hardlink'
            except OSError:
                if linked:
                    Path(out).unlink()
                elif Path(out).exists():
                    raise ValueError('Source destination already exists.') from None
        shutil.copyfile(path, out)
        return 'copy'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        while self.handles:
            kernel, handle = self.handles.pop()
            kernel.CloseHandle(handle)


class StudyNotFound(ValueError):
    """The PACS explicitly reports absence, not an authentication/transport error."""


class PacsSource:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.session.trust_env = False
        self._auth_lock = threading.Lock()
        self._retry_login_after = 0
        if config.get('credential_file'):
            pacs_address(config['url'])
        if config.get('token_env'):
            import os
            token = os.environ.get(config['token_env'], '')
            if token:
                self.session.headers['Authorization'] = 'Bearer ' + token

    def get(self, url, *, stream=False):
        base = urllib.parse.urlsplit(self.config['url'])
        target = urllib.parse.urlsplit(url)
        if (target.scheme, target.netloc) != (base.scheme, base.netloc) or target.username or target.password:
            raise ValueError('PACS requests must use the configured endpoint.')
        # Metadata requests are short and serialized; analysis workers remain independent.
        # This also makes expiry renewal single-flight for concurrent jobs.
        with self._auth_lock:
            automatic = bool(self.config.get('credential_file'))
            if automatic and not self.session.headers.get('Authorization'):
                self._login()
            for attempt in range(2):
                try:
                    response = self.session.get(url, timeout=(10, 60), stream=stream, allow_redirects=False,
                                                verify=self.config.get('ca_file') or True)
                except requests.RequestException:
                    raise ValueError('PACS connection failed. Check the configured endpoint.') from None
                if response.status_code == 200:
                    return response
                expired = response.status_code == 401
                missing = response.status_code == 404
                response.close()
                if missing:
                    raise StudyNotFound('The study was not found in PACS.')
                if expired and automatic and attempt == 0:
                    self.session.headers.pop('Authorization', None)
                    self._login()
                    continue
                if expired and automatic:
                    self.session.headers.pop('Authorization', None)
                    self._retry_login_after = time.monotonic() + 30
                raise ValueError('The configured PACS could not supply the study.')

    def _login(self):
        if time.monotonic() < self._retry_login_after:
            raise ValueError('PACS authentication is waiting before retry. Check the saved service account.')
        response = None
        try:
            credentials = read_pacs_credentials(self.config['credential_file'], self.config['url'])
            response = self.session.post(self.config['url'].rstrip('/') + '/api/auth/login',
                json=credentials, timeout=(10, 30), allow_redirects=False,
                verify=self.config.get('ca_file') or True)
            if response.status_code != 200:
                raise ValueError()
            value = response.json()
            token = value.get('token')
            if value.get('success') is not True or not isinstance(token, str) or not token or len(token) > 16384:
                raise ValueError()
            self.session.headers['Authorization'] = 'Bearer ' + token
        except Exception:
            self._retry_login_after = time.monotonic() + 30
            raise ValueError('PACS sign-in failed. Check the saved service account and connection.') from None
        finally:
            if response is not None:
                response.close()

    def storage_files(self, request):
        endpoint = self.config['url'].rstrip('/') + '/api/ai-patient/by-study/' + request['study_uid']
        with self.get(endpoint) as response:
            if len(response.content) > 2 * 1024**2:
                raise ValueError('PACS source response exceeds the limit.')
            data = response.json()
        # Study ID is an administrative identifier, not the DICOM identity.
        if str(data.get('study_info', {}).get('study_instance_uid', '')) != request['study_uid']:
            raise ValueError('PACS study identity does not match the request.')
        storage = data.get('storage_info') or {}
        value = storage.get('study_path') or storage.get('dicom_file_path')
        if not value:
            raise ValueError('PACS did not supply a source location.')
        # Mapping is configured by the server administrator, never sent by a client.
        for mapping in self.config.get('path_mappings', []):
            prefix = mapping['pacs_prefix'].rstrip('/\\')
            normalized = value.replace('\\', '/')
            compare = prefix.replace('\\', '/')
            if normalized.lower().startswith(compare.lower() + '/'):
                value = str(Path(mapping['server_root']) / normalized[len(compare) + 1:])
                break
        root = Path(value).resolve()
        allowed = [Path(p).resolve() for p in self.config.get('allowed_roots', [])]
        if not any(root.is_relative_to(p) for p in allowed):
            raise ValueError('PACS source is outside configured server storage.')
        atomic = storage.get('source_write_policy') == 'atomic-replace-v1'
        if root.is_file():
            return StorageFiles([root], atomic_replace=atomic)
        if not root.is_dir():
            raise ValueError('PACS storage is not accessible on this server. Configure its storage mapping.')
        paths = []
        for index, path in enumerate(root.rglob('*')):
            if index >= 50000:
                raise ValueError('PACS study inventory exceeds the limit.')
            if path.is_file() and path.suffix.lower() in ('.dcm', '.dicom', ''):
                if not path.resolve().is_relative_to(root):
                    raise ValueError('PACS source escapes its storage directory.')
                paths.append(path)
        return StorageFiles(paths, atomic_replace=atomic)

    def stage(self, request, destination, cancel, *, lease=None):
        import pydicom
        destination = Path(destination)
        destination.mkdir(parents=True)
        selected = request['series']
        modality = {'breast': ('MG',), 'bone-age': ('DX', 'CR'),
                    'alignment': ('DX', 'CR'), 'total-spine': ('DX', 'CR')}.get(request['module'], ('MR',))
        records = []
        seen = set()
        total = 0
        inventory = self.storage_files(request)
        for path in inventory:
            if cancel.is_set():
                raise RuntimeError('Analysis cancelled.')
            ds = pydicom.dcmread(path, stop_before_pixels=True)
            study, series, sop = (str(ds.get(k, '')) for k in ('StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID'))
            if study != request['study_uid']:
                raise ValueError('PACS storage contains another study.')
            if str(ds.get('Modality', '')).upper() not in modality:
                continue
            roles = [role for role, ref in selected.items() if ref['series_uid'] == series
                     and (not ref.get('sop_uid') or ref['sop_uid'] == sop)]
            # Stitched standing radiographs are normally DERIVED. Admit only the
            # explicitly selected DX/CR SOP; model-specific pixel guards still run.
            explicit_radiograph = request['module'] in ('alignment', 'total-spine') and any(
                selected[role].get('sop_uid') == sop for role in roles)
            if 'DERIVED' in str(ds.get('ImageType', '')).upper() and not explicit_radiograph:
                continue
            if selected and not roles:
                continue
            if not sop or not series or sop in seen:
                raise ValueError('PACS source contains incomplete or duplicate identities.')
            seen.add(sop)
            size = path.stat().st_size
            total += size
            if size > 512 * 1024**2 or total > 4 * 1024**3 or len(records) >= 10000:
                raise ValueError('PACS source exceeds the analysis limits.')
            from .contracts import uid
            uid(series); uid(sop)
            out = destination / series / (sop + '.dcm')
            out.parent.mkdir(exist_ok=True)
            before = digest(path)
            storage_mode = 'copy'
            if lease is not None:
                storage_mode = lease.materialize(path, out,
                    share=getattr(inventory, 'atomic_replace', False))
            else:
                shutil.copyfile(path, out)
            if digest(out) != before or digest(path) != before:
                raise ValueError('PACS source changed while staging the analysis.')
            identity_tags = ['StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID', 'Modality', 'ImageType']
            staged_header = pydicom.dcmread(out, stop_before_pixels=True, specific_tags=identity_tags)
            if any(str(staged_header.get(tag, '')) != str(ds.get(tag, '')) for tag in identity_tags):
                raise ValueError('PACS source identity changed while staging the analysis.')
            records.append(dict(path=str(out), study_uid=study, series_uid=series,
                                sop_uid=sop, sha256=before, roles=roles, storage_mode=storage_mode))
        if not records:
            raise ValueError('PACS supplied no matching original images.')
        for role, ref in selected.items():
            if sum(role in r['roles'] for r in records) != ref['expected_count']:
                raise ValueError('PACS source inventory is incomplete for the requested analysis.')
        return records


def role_path(records, role):
    selected = [Path(r['path']) for r in records if role in r['roles']]
    if not selected:
        raise ValueError('Required input role is missing.')
    return selected[0].parent


class WorkstationCacheSource(PacsSource):
    """Read the server PC's existing completed PACS cache; never the client's DB."""
    def storage_files(self, request):
        import sqlite3
        database = Path(self.config['database']).resolve()
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=10)
        try:
            rows = connection.execute('''SELECT s.series_uid, s.series_path,
                COALESCE(NULLIF(s.expected_instance_count,0),s.image_count), s.modality
                FROM series s JOIN studies t ON s.study_fk=t.study_pk
                WHERE t.study_uid=?''', (request['study_uid'],)).fetchall()
        finally:
            connection.close()
        selected = {r['series_uid'] for r in request['series'].values()}
        modalities = ('MG',) if request['module'] == 'breast' else (
            ('DX', 'CR') if request['module'] in ('bone-age', 'alignment', 'total-spine') else ('MR',))
        allowed = [Path(p).resolve() for p in self.config.get('allowed_roots', [])]
        files = []
        for uid, folder, count, modality in rows:
            if str(modality).upper() not in modalities or (selected and uid not in selected):
                continue
            root = Path(folder or '').resolve()
            if not folder or not any(root.is_relative_to(p) for p in allowed) or not root.is_dir():
                raise ValueError('Download the selected source to the server workstation cache first.')
            candidates = []
            for index, path in enumerate(root.iterdir()):
                if index >= 20000:
                    raise ValueError('Server cache inventory exceeds the limit.')
                if path.is_file() and path.suffix.lower() in ('.dcm', '.dicom', ''):
                    if not path.resolve().is_relative_to(root):
                        raise ValueError('Server cache file escapes its source directory.')
                    candidates.append(path)
            if not count or len(candidates) != int(count):
                raise ValueError('The server workstation cache is incomplete. Finish the PACS download.')
            # Base staging additionally verifies study, SOP uniqueness and hashes.
            import pydicom
            for path in candidates:
                header = pydicom.dcmread(path, stop_before_pixels=True,
                                       specific_tags=['SeriesInstanceUID'])
                if str(header.get('SeriesInstanceUID', '')) != uid:
                    raise ValueError('Server cache series identity changed.')
            files.extend(candidates)
        if not files:
            raise ValueError('No selected PACS source is cached on the Eagle Eye server.')
        return files


class PacsWithCacheSource(PacsSource):
    """PACS first, with a server-local completed cache only after explicit absence."""
    def storage_files(self, request):
        try:
            return super().storage_files(request)
        except StudyNotFound:
            if not self.config.get('database'):
                raise StudyNotFound('Study absent from PACS; server local database is not configured.') from None
            cache = WorkstationCacheSource(self.config)
            try:
                return cache.storage_files(request)
            finally:
                cache.session.close()


def source_provider(config):
    kind = config.get('type', 'pacs-storage')
    if kind == 'workstation-cache':
        return WorkstationCacheSource(config)
    if kind == 'pacs-storage':
        return PacsWithCacheSource(config)
    raise ValueError('Unsupported server source provider.')
