"""Fail-closed aggregate observer for a pre-counter Eagle Eye service.

The observer returns only aggregate counts and fixed reason codes. It never emits
paths, process command lines, identities, request IDs, job payloads or clinical
content. A caller must still apply the reviewed legacy grant fence before using
an idle result for a controlled service transition.
"""
from contextlib import closing
import ctypes
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import time

from tools.eagle_eye.legacy_admission_fence import ActivitySnapshot


TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
AUDIT_OPERATIONS = ("echomind", "secretary", "crm", "speech", "imaging")


@dataclass(frozen=True)
class RawLegacySample:
    release_id: str
    manifest_sha256: str
    source_matches: bool
    access_columns: frozenset
    nonterminal_jobs: int
    echomind_admitted: int
    secretary_admitted: int
    crm_admitted: int
    speech_admitted: int
    imaging_admitted: int
    process_tree_digest: str
    unknown_children: int
    service_nonlisten_sockets: int
    owned_nonlisten_sockets: int
    open_job_handles: int
    open_source_handles: int
    access_denied: bool
    probe_failed: bool

    def __post_init__(self):
        counts = (
            self.nonterminal_jobs,
            self.echomind_admitted,
            self.secretary_admitted,
            self.crm_admitted,
            self.speech_admitted,
            self.imaging_admitted,
            self.unknown_children,
            self.service_nonlisten_sockets,
            self.owned_nonlisten_sockets,
            self.open_job_handles,
            self.open_source_handles,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("Legacy activity counts must be non-negative integers.")
        if type(self.source_matches) is not bool or type(self.access_denied) is not bool or type(self.probe_failed) is not bool:
            raise ValueError("Legacy observation flags must be boolean.")
        if not isinstance(self.access_columns, frozenset):
            raise ValueError("Access columns must be an immutable set.")
        if not isinstance(self.release_id, str) or not self.release_id:
            raise ValueError("A bounded active release identity is required.")
        for value in (self.manifest_sha256, self.process_tree_digest):
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError("Observation digests must be SHA-256 values.")


@dataclass(frozen=True)
class ProcessAggregate:
    source_matches: bool
    tree_digest: str
    unknown_children: int
    service_nonlisten_sockets: int
    owned_nonlisten_sockets: int
    open_job_handles: int
    open_source_handles: int


class WindowsHandleInspector:
    """Count service-owned job files, including raw Win32 ``CreateFile`` handles."""

    SYSTEM_EXTENDED_HANDLE_INFORMATION = 64
    STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
    PROCESS_DUP_HANDLE = 0x0040
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    DUPLICATE_SAME_ACCESS = 0x00000002
    FILE_READ_ATTRIBUTES = 0x0080
    FILE_SHARE_ALL = 0x00000007
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_TYPE_DISK = 1
    MAX_HANDLE_TABLE_BYTES = 128 * 1024 * 1024

    def __init__(self):
        if os.name != "nt":
            raise OSError("Native Windows handle inspection is unavailable.")
        from ctypes import wintypes

        self.wintypes = wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.DuplicateHandle.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
            ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
        ]
        self.kernel.DuplicateHandle.restype = wintypes.BOOL
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel.GetFileType.argtypes = [wintypes.HANDLE]
        self.kernel.GetFileType.restype = wintypes.DWORD
        self.kernel.GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ]
        self.kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.ntdll.NtQuerySystemInformation.argtypes = [
            wintypes.ULONG, wintypes.LPVOID, wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        self.ntdll.NtQuerySystemInformation.restype = wintypes.LONG

        pointer = ctypes.c_size_t

        class HandleEntry(ctypes.Structure):
            _fields_ = [
                ("object", wintypes.LPVOID),
                ("process_id", pointer),
                ("handle_value", pointer),
                ("granted_access", wintypes.ULONG),
                ("creator_backtrace_index", wintypes.USHORT),
                ("object_type_index", wintypes.USHORT),
                ("handle_attributes", wintypes.ULONG),
                ("reserved", wintypes.ULONG),
            ]

        self.HandleEntry = HandleEntry
        self.invalid_handle = ctypes.c_void_p(-1).value

    def _system_handles(self):
        size = 1024 * 1024
        while size <= self.MAX_HANDLE_TABLE_BYTES:
            buffer = ctypes.create_string_buffer(size)
            required = self.wintypes.ULONG()
            status = self.ntdll.NtQuerySystemInformation(
                self.SYSTEM_EXTENDED_HANDLE_INFORMATION,
                buffer,
                size,
                ctypes.byref(required),
            )
            if status == 0:
                pointer_size = ctypes.sizeof(ctypes.c_size_t)
                count = ctypes.c_size_t.from_buffer(buffer).value
                offset = pointer_size * 2
                capacity = (size - offset) // ctypes.sizeof(self.HandleEntry)
                if count > capacity:
                    raise OSError("The Windows handle table snapshot is incomplete.")
                return [
                    self.HandleEntry.from_buffer_copy(
                        buffer,
                        offset + index * ctypes.sizeof(self.HandleEntry),
                    )
                    for index in range(count)
                ]
            if ctypes.c_ulong(status).value != self.STATUS_INFO_LENGTH_MISMATCH:
                raise OSError("Windows handle enumeration failed.")
            requested = int(required.value) if required.value else size * 2
            size = max(size * 2, requested + 64 * 1024)
        raise OSError("Windows handle enumeration exceeded its safety bound.")

    def _classified_handle_snapshot(self, job_root):
        handle = self.kernel.CreateFileW(
            str(job_root), self.FILE_READ_ATTRIBUTES, self.FILE_SHARE_ALL, None,
            self.OPEN_EXISTING, self.FILE_FLAG_BACKUP_SEMANTICS, None,
        )
        if not handle or handle == self.invalid_handle:
            raise PermissionError("The job root cannot be opened for handle classification.")
        entries = self._system_handles()
        current_pid = os.getpid()
        handle_value = ctypes.cast(handle, ctypes.c_void_p).value
        for entry in entries:
            if entry.process_id == current_pid and entry.handle_value == handle_value:
                return entries, entry.object_type_index, handle, handle_value
        self.kernel.CloseHandle(handle)
        raise OSError("The handle-table snapshot did not contain its classification handle.")

    def _resolved_path(self, handle):
        capacity = 512
        while capacity <= 32768:
            buffer = ctypes.create_unicode_buffer(capacity)
            length = self.kernel.GetFinalPathNameByHandleW(handle, buffer, capacity, 0)
            if length == 0:
                raise OSError("A service-owned disk handle could not be resolved.")
            if length < capacity:
                value = buffer.value
                if value.startswith("\\\\?\\UNC\\"):
                    return "\\\\" + value[8:]
                if value.startswith("\\\\?\\"):
                    return value[4:]
                return value
            capacity = length + 1
        raise OSError("A service-owned disk path exceeded its safety bound.")

    def inspect(self, process_ids, job_root):
        process_ids = frozenset(process_ids)
        if not process_ids or any(type(value) is not int or value <= 0 for value in process_ids):
            raise ValueError("Explicit service process identities are required.")
        job_root = Path(job_root).resolve()
        entries, file_type_index, classification_handle, classification_value = (
            self._classified_handle_snapshot(job_root)
        )
        current_process = self.kernel.GetCurrentProcess()
        process_handles = {}
        open_jobs = 0
        open_sources = 0
        directory_leases = 0
        expected_root = os.path.normcase(str(job_root))
        try:
            for process_id in process_ids:
                process = self.kernel.OpenProcess(
                    self.PROCESS_DUP_HANDLE | self.PROCESS_QUERY_LIMITED_INFORMATION,
                    False,
                    process_id,
                )
                if not process:
                    raise PermissionError("A service process cannot be inspected.")
                process_handles[process_id] = process
            for entry in entries:
                process_id = int(entry.process_id)
                if process_id not in process_handles or entry.object_type_index != file_type_index:
                    continue
                if process_id == os.getpid() and entry.handle_value == classification_value:
                    continue
                duplicate = self.wintypes.HANDLE()
                if not self.kernel.DuplicateHandle(
                    process_handles[process_id], self.wintypes.HANDLE(entry.handle_value),
                    current_process, ctypes.byref(duplicate), 0, False,
                    self.DUPLICATE_SAME_ACCESS,
                ):
                    raise OSError("A service-owned file handle changed during observation.")
                try:
                    if self.kernel.GetFileType(duplicate) != self.FILE_TYPE_DISK:
                        continue
                    path = os.path.normcase(os.path.abspath(self._resolved_path(duplicate)))
                finally:
                    self.kernel.CloseHandle(duplicate)
                try:
                    inside = os.path.commonpath((expected_root, path)) == expected_root
                except ValueError:
                    inside = False
                if not inside:
                    continue
                relative = os.path.relpath(path, expected_root).split(os.sep)
                if relative == [".server.lock"]:
                    directory_leases += 1
                    continue
                if "sources" in relative:
                    open_sources += 1
                else:
                    open_jobs += 1
        finally:
            for process in process_handles.values():
                self.kernel.CloseHandle(process)
            self.kernel.CloseHandle(classification_handle)
        if directory_leases != 1:
            raise OSError("The durable job root does not have one verified ownership lease.")
        return open_jobs, open_sources


class LegacyActivityObserver:
    """Convert complete host samples into conservative transition activity."""

    def __init__(self, adapter, *, expected_release_id, expected_manifest_sha256,
                 required_access_columns, stable_process_samples=2):
        if not callable(getattr(adapter, "sample", None)):
            raise TypeError("A complete legacy activity adapter is required.")
        if not isinstance(expected_release_id, str) or not expected_release_id:
            raise ValueError("The expected active release is required.")
        if not isinstance(expected_manifest_sha256, str) or len(expected_manifest_sha256) != 64:
            raise ValueError("The expected manifest SHA-256 is required.")
        if not isinstance(required_access_columns, frozenset) or not required_access_columns:
            raise ValueError("The required access-store schema is required.")
        if type(stable_process_samples) is not int or stable_process_samples < 2:
            raise ValueError("At least two stable process-tree samples are required.")
        self.adapter = adapter
        self.expected_release_id = expected_release_id
        self.expected_manifest_sha256 = expected_manifest_sha256.lower()
        self.required_access_columns = required_access_columns
        self.stable_process_samples = stable_process_samples
        self._tree_digest = None
        self._tree_samples = 0
        self.reason_codes = ()
        self.previous_reason_codes = ()

    def observe(self):
        self.previous_reason_codes = self.reason_codes
        try:
            sample = self.adapter.sample()
            if not isinstance(sample, RawLegacySample):
                raise TypeError("Incomplete legacy activity sample.")
        except Exception:
            self.reason_codes = ("observer_exception",)
            self._tree_digest = None
            self._tree_samples = 0
            return ActivitySnapshot(completion_uncertain=True)

        reasons = []
        if sample.release_id != self.expected_release_id:
            reasons.append("release_mismatch")
        if sample.manifest_sha256.lower() != self.expected_manifest_sha256:
            reasons.append("manifest_mismatch")
        if not sample.source_matches:
            reasons.append("source_mismatch")
        if not self.required_access_columns.issubset(sample.access_columns):
            reasons.append("access_schema_mismatch")
        if sample.unknown_children:
            reasons.append("unknown_child")
        if sample.access_denied:
            reasons.append("access_denied")
        if sample.probe_failed:
            reasons.append("probe_failed")

        if sample.process_tree_digest == self._tree_digest:
            self._tree_samples += 1
        else:
            self._tree_digest = sample.process_tree_digest
            self._tree_samples = 1
        if self._tree_samples < self.stable_process_samples:
            reasons.append("process_tree_unstable")

        self.reason_codes = tuple(sorted(set(reasons)))
        uncertain_reasons = tuple(
            reason for reason in self.reason_codes if reason != "process_tree_unstable"
        )
        admitted = (
            sample.echomind_admitted
            + sample.secretary_admitted
            + sample.crm_admitted
            + sample.speech_admitted
            + sample.imaging_admitted
        )
        return ActivitySnapshot(
            active_handlers=(sample.service_nonlisten_sockets + admitted
                             + sample.open_job_handles + sample.open_source_handles
                             + int("process_tree_unstable" in self.reason_codes)),
            active_jobs=sample.nonterminal_jobs,
            active_sockets=sample.owned_nonlisten_sockets,
            completion_uncertain=bool(uncertain_reasons),
        )


class FilesystemProcessAdapter:
    """Read aggregate state from one explicitly selected source-service process."""

    REQUIRED_ACCESS_COLUMNS = frozenset({
        "principal", "provider", "subject", "username", "enabled", "echomind",
        "imaging", "crm", "secretary", "modules",
    })

    def __init__(self, *, manifest_path, source_root, job_root, access_database,
                 service_pid, allowed_child_sha256, handle_inspector=None,
                 permitted_idle_tcp_peers=None, idle_tcp_owner_pid=None,
                 idle_tcp_owner_create_time=None, idle_tcp_min_age=75,
                 idle_tcp_first_seen=None, clock=None):
        self.manifest_path = self._absolute_file(manifest_path)
        self.source_root = self._absolute_directory(source_root)
        self.job_root = self._absolute_directory(job_root)
        self.access_database = self._absolute_file(access_database)
        if type(service_pid) is not int or service_pid <= 0:
            raise ValueError("An explicit service process ID is required.")
        if not isinstance(allowed_child_sha256, set) or any(
                not isinstance(value, str) or len(value) != 64 for value in allowed_child_sha256):
            raise ValueError("Allowed child images require explicit SHA-256 values.")
        self.service_pid = service_pid
        self.allowed_child_sha256 = {value.lower() for value in allowed_child_sha256}
        self.handle_inspector = handle_inspector
        peers = permitted_idle_tcp_peers or {}
        if not isinstance(peers, dict):
            raise ValueError("Idle TCP peers require an explicit bounded mapping.")
        self.permitted_idle_tcp_peers = {}
        for peer, maximum in peers.items():
            if (not isinstance(peer, tuple) or len(peer) != 2
                    or type(peer[1]) is not int or not 1 <= peer[1] <= 65535
                    or type(maximum) is not int or not 1 <= maximum <= 4):
                raise ValueError("Idle TCP peers require an IP, port and bounded count.")
            address = str(ipaddress.ip_address(peer[0]))
            if (not ipaddress.ip_address(address).is_loopback or peer[1] != 8000
                    or maximum != 1 or len(peers) != 1):
                raise ValueError("Only the one reviewed loopback PACS HTTP pool is eligible.")
            self.permitted_idle_tcp_peers[(address, peer[1])] = maximum
        if (peers and (type(idle_tcp_owner_pid) is not int or idle_tcp_owner_pid <= 0
                       or type(idle_tcp_owner_create_time) not in (int, float)
                       or idle_tcp_owner_create_time <= 0)):
            raise ValueError("Idle TCP peers require the exact API service child process.")
        if not peers and (idle_tcp_owner_pid is not None or idle_tcp_owner_create_time is not None):
            raise ValueError("An idle TCP owner is invalid without an allowed peer.")
        self.idle_tcp_owner_pid = idle_tcp_owner_pid
        self.idle_tcp_owner = ((idle_tcp_owner_pid, float(idle_tcp_owner_create_time))
                               if peers else None)
        if (type(idle_tcp_min_age) not in (int, float)
                or not 65 <= idle_tcp_min_age <= 300):
            raise ValueError("Idle TCP qualification must exceed the legacy PACS read timeout.")
        self.idle_tcp_min_age = float(idle_tcp_min_age)
        self.clock = clock or time.monotonic
        prior = idle_tcp_first_seen or {}
        now = self.clock()
        if (not isinstance(prior, dict) or len(prior) > 8
                or any(not isinstance(key, str) or len(key) != 64
                       or any(character not in "0123456789abcdef" for character in key)
                       or type(value) not in (int, float) or not now - 600 <= value <= now
                       for key, value in prior.items())):
            raise ValueError("Idle TCP age state is invalid.")
        self._idle_peer_first_seen = dict(prior)
        self._idle_peer_seen = set()

    @staticmethod
    def _absolute_file(path):
        value = Path(path)
        if not value.is_absolute() or not value.is_file():
            raise ValueError("A private existing absolute file is required.")
        return value.resolve()

    @staticmethod
    def _absolute_directory(path):
        value = Path(path)
        if not value.is_absolute() or not value.is_dir():
            raise ValueError("A private existing absolute directory is required.")
        return value.resolve()

    def _manifest(self):
        raw = self.manifest_path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
        identities = [value.get("release_id"), value.get("candidate_revision")]
        if isinstance(value.get("deployment"), dict):
            identities.append(value["deployment"].get("release_id"))
        identities = [identity for identity in identities if identity is not None]
        if len(set(identities)) > 1:
            raise ValueError("The active manifest contains conflicting release identities.")
        release_id = identities[0] if identities else None
        if not isinstance(release_id, str) or not release_id:
            raise ValueError("The active manifest has no release identity.")
        return release_id, hashlib.sha256(raw).hexdigest()

    def _access(self):
        uri = self.access_database.as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            columns = frozenset(row[1] for row in db.execute("PRAGMA table_info(users)"))
            if not self.REQUIRED_ACCESS_COLUMNS.issubset(columns):
                raise ValueError("The active access-store schema is incompatible.")
            counts = {}
            for operation in AUDIT_OPERATIONS:
                counts[operation] = db.execute(
                    """SELECT COUNT(*) FROM events
                       WHERE outcome='admitted' AND (operation=? OR operation LIKE ?)""",
                    (operation, operation + ".%"),
                ).fetchone()[0]
        return columns, counts

    def _jobs(self):
        count = 0
        for state_path in self.job_root.glob("*/state.json"):
            value = json.loads(state_path.read_text(encoding="utf-8-sig"))
            status = value.get("status")
            if not isinstance(status, str) or status not in TERMINAL_JOB_STATES:
                count += 1
        return count

    @staticmethod
    def _digest_file(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _command_uses_source(self, command):
        expected = os.path.normcase(str(self.source_root))
        for item in command:
            if not isinstance(item, str):
                continue
            candidate = item.strip('"')
            if not os.path.isabs(candidate):
                continue
            normalized = os.path.normcase(os.path.abspath(candidate))
            try:
                if os.path.commonpath((expected, normalized)) == expected:
                    return True
            except ValueError:
                continue
        return False

    def _process_uses_source(self, process):
        if self._command_uses_source(process.cmdline()):
            return True
        expected = os.path.normcase(str(self.source_root))
        current = os.path.normcase(os.path.abspath(process.cwd()))
        try:
            return os.path.commonpath((expected, current)) == expected
        except ValueError:
            return False

    @staticmethod
    def _tcp_address(value):
        if hasattr(value, "ip"):
            address, port = value.ip, value.port
        else:
            address, port = value[0], value[1]
        return str(ipaddress.ip_address(address)), port

    def _active_tcp_count(self, connections, listen_status, established_status, *, owner=0,
                          permitted_counts=None):
        permitted = (permitted_counts if permitted_counts is not None
                     else {peer: 0 for peer in self.permitted_idle_tcp_peers})
        active = 0
        now = self.clock()
        for connection in connections:
            if connection.status == listen_status:
                continue
            peer = None
            if connection.status == established_status and connection.raddr:
                try:
                    peer = self._tcp_address(connection.raddr)
                except (AttributeError, IndexError, TypeError, ValueError):
                    peer = None
            if (owner == self.idle_tcp_owner and peer in permitted
                    and permitted[peer] < self.permitted_idle_tcp_peers[peer]):
                permitted[peer] += 1
                try:
                    local = self._tcp_address(connection.laddr)
                except (AttributeError, IndexError, TypeError, ValueError):
                    local = None
                identity = hashlib.sha256(
                    json.dumps([owner, local, peer], separators=(",", ":")).encode()
                ).hexdigest()
                self._idle_peer_seen.add(identity)
                first_seen = self._idle_peer_first_seen.setdefault(identity, now)
                if now - first_seen >= self.idle_tcp_min_age:
                    continue
            active += 1
        return active

    def idle_tcp_state(self):
        """Return opaque bounded age evidence for an isolated next probe."""
        return dict(self._idle_peer_first_seen)

    def _process_aggregate(self):
        import psutil

        service = psutil.Process(self.service_pid)
        children = service.children(recursive=True)
        service_executable = self._digest_file(service.exe())
        source_matches = self._process_uses_source(service)
        unknown_children = 0
        identities = []
        owned = [service, *children]
        idle_owner = None
        for process in owned:
            executable = self._digest_file(process.exe())
            command_matches = self._process_uses_source(process)
            if process is not service and not (
                    executable in self.allowed_child_sha256
                    or (executable == service_executable and command_matches)):
                unknown_children += 1
            identities.append((process.pid, process.create_time(), executable))
            if (process.pid == self.idle_tcp_owner_pid
                    and process.create_time() == self.idle_tcp_owner[1]):
                command = process.cmdline()
                idle_owner = process if (
                    self._process_uses_source(process)
                    and any(
                        command[index:index + 2] == [
                            "-m", "modules.ai_imaging.eagle_eye_remote.service_host"
                        ]
                        for index in range(max(0, len(command) - 1))
                    )
                ) else False
        if self.permitted_idle_tcp_peers and idle_owner is None:
            raise OSError("The configured idle TCP owner is not in the service process tree.")
        if idle_owner is False:
            raise OSError("The configured idle TCP owner is not the reviewed API service child.")
        tree_digest = hashlib.sha256(
            json.dumps(sorted(identities), separators=(",", ":")).encode()
        ).hexdigest()

        service_nonlisten = 0
        owned_nonlisten = 0
        open_jobs = 0
        open_sources = 0
        self._idle_peer_seen = set()
        permitted_counts = {peer: 0 for peer in self.permitted_idle_tcp_peers}
        for process in owned:
            connections = process.net_connections(kind="tcp")
            count = self._active_tcp_count(
                connections, psutil.CONN_LISTEN, psutil.CONN_ESTABLISHED,
                owner=(process.pid, process.create_time()), permitted_counts=permitted_counts,
            )
            owned_nonlisten += count
            if process is service:
                service_nonlisten = count
        self._idle_peer_first_seen = {
            identity: first_seen for identity, first_seen in self._idle_peer_first_seen.items()
            if identity in self._idle_peer_seen
        }
        if os.name == "nt":
            inspector = self.handle_inspector or WindowsHandleInspector()
            open_jobs, open_sources = inspector.inspect(
                [process.pid for process in owned], self.job_root
            )
        else:
            job_root = os.path.normcase(str(self.job_root))
            for process in owned:
                for opened in process.open_files():
                    path = os.path.normcase(os.path.abspath(opened.path))
                    try:
                        inside = os.path.commonpath((job_root, path)) == job_root
                    except ValueError:
                        inside = False
                    if not inside:
                        continue
                    relative = os.path.relpath(path, job_root).split(os.sep)
                    if "sources" in relative:
                        open_sources += 1
                    else:
                        open_jobs += 1
        return ProcessAggregate(
            source_matches=source_matches,
            tree_digest=tree_digest,
            unknown_children=unknown_children,
            service_nonlisten_sockets=service_nonlisten,
            owned_nonlisten_sockets=owned_nonlisten,
            open_job_handles=open_jobs,
            open_source_handles=open_sources,
        )

    def sample(self):
        release_id, manifest_sha256 = self._manifest()
        columns, admitted = self._access()
        nonterminal = self._jobs()
        process = self._process_aggregate()
        return RawLegacySample(
            release_id=release_id,
            manifest_sha256=manifest_sha256,
            source_matches=process.source_matches,
            access_columns=columns,
            nonterminal_jobs=nonterminal,
            echomind_admitted=admitted["echomind"],
            secretary_admitted=admitted["secretary"],
            crm_admitted=admitted["crm"],
            speech_admitted=admitted["speech"],
            imaging_admitted=admitted["imaging"],
            process_tree_digest=process.tree_digest,
            unknown_children=process.unknown_children,
            service_nonlisten_sockets=process.service_nonlisten_sockets,
            owned_nonlisten_sockets=process.owned_nonlisten_sockets,
            open_job_handles=process.open_job_handles,
            open_source_handles=process.open_source_handles,
            access_denied=False,
            probe_failed=False,
        )
