"""Fail-closed aggregate observation for the pre-counter Eagle Eye service."""
import hashlib
import json
import os
import threading
import time

import pytest

from modules.ai_imaging.eagle_eye_remote.user_access import AccessStore


EXPECTED_COLUMNS = frozenset({
    "principal", "provider", "subject", "username", "enabled", "echomind",
    "imaging", "crm", "secretary", "modules",
})


def raw_sample(**changes):
    from tools.eagle_eye.legacy_activity_observer import RawLegacySample

    values = dict(
        release_id="synthetic-active-release",
        manifest_sha256="a" * 64,
        source_matches=True,
        access_columns=EXPECTED_COLUMNS,
        nonterminal_jobs=0,
        echomind_admitted=0,
        secretary_admitted=0,
        crm_admitted=0,
        speech_admitted=0,
        imaging_admitted=0,
        process_tree_digest="b" * 64,
        unknown_children=0,
        service_nonlisten_sockets=0,
        owned_nonlisten_sockets=0,
        open_job_handles=0,
        open_source_handles=0,
        access_denied=False,
        probe_failed=False,
    )
    values.update(changes)
    return RawLegacySample(**values)


class Adapter:
    def __init__(self, samples):
        self.samples = iter(samples)

    def sample(self):
        return next(self.samples)


def observer(samples):
    from tools.eagle_eye.legacy_activity_observer import LegacyActivityObserver

    return LegacyActivityObserver(
        Adapter(samples),
        expected_release_id="synthetic-active-release",
        expected_manifest_sha256="a" * 64,
        required_access_columns=EXPECTED_COLUMNS,
        stable_process_samples=2,
    )


def test_idle_requires_stable_owned_process_tree_and_complete_identity():
    watch = observer([raw_sample(), raw_sample()])

    first = watch.observe()
    second = watch.observe()

    assert first.completion_uncertain is False
    assert not first.idle
    assert watch.previous_reason_codes == ("process_tree_unstable",)
    assert second.idle is True
    assert watch.reason_codes == ()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"release_id": "wrong"}, "release_mismatch"),
        ({"manifest_sha256": "c" * 64}, "manifest_mismatch"),
        ({"source_matches": False}, "source_mismatch"),
        ({"access_columns": frozenset()}, "access_schema_mismatch"),
        ({"unknown_children": 1}, "unknown_child"),
        ({"access_denied": True}, "access_denied"),
        ({"probe_failed": True}, "probe_failed"),
    ],
)
def test_identity_schema_and_probe_failures_are_uncertain(changes, reason):
    watch = observer([raw_sample(**changes)])

    result = watch.observe()

    assert result.completion_uncertain is True
    assert reason in watch.reason_codes


def test_jobs_audit_handles_and_all_owned_nonlisten_sockets_remain_active():
    sample = raw_sample(
        nonterminal_jobs=1,
        echomind_admitted=1,
        secretary_admitted=1,
        crm_admitted=1,
        speech_admitted=1,
        imaging_admitted=1,
        service_nonlisten_sockets=2,
        owned_nonlisten_sockets=4,
        open_job_handles=1,
        open_source_handles=1,
    )
    watch = observer([sample, sample])
    watch.observe()

    result = watch.observe()

    assert result.active_jobs == 1
    assert result.active_handlers == 9
    assert result.active_sockets == 4
    assert result.completion_uncertain is False
    assert not result.idle


def test_process_tree_change_restarts_stability_proof():
    watch = observer([
        raw_sample(process_tree_digest="1" * 64),
        raw_sample(process_tree_digest="1" * 64),
        raw_sample(process_tree_digest="2" * 64),
        raw_sample(process_tree_digest="2" * 64),
    ])

    assert not watch.observe().idle
    assert watch.observe().idle
    assert not watch.observe().idle
    assert watch.observe().idle


def test_adapter_exception_fails_closed_without_exposing_details():
    class Broken:
        def sample(self):
            raise PermissionError("private path and identity must not escape")

    from tools.eagle_eye.legacy_activity_observer import LegacyActivityObserver

    watch = LegacyActivityObserver(
        Broken(),
        expected_release_id="synthetic-active-release",
        expected_manifest_sha256="a" * 64,
        required_access_columns=EXPECTED_COLUMNS,
    )
    result = watch.observe()

    assert result.completion_uncertain is True
    assert watch.reason_codes == ("observer_exception",)


def test_outer_transition_times_out_while_child_socket_remains(tmp_path):
    from tools.eagle_eye.legacy_activity_observer import LegacyActivityObserver
    from tools.eagle_eye.legacy_admission_fence import (
        DrainTimeout,
        LegacyGrantFence,
        run_fenced_transition,
    )

    store = AccessStore(tmp_path / "access.sqlite3", "synthetic-center")
    principal = store.identify({
        "provider": "pacs", "subject": "synthetic-subject", "username": "synthetic-user"
    })
    grant = dict(
        enabled=True, echomind=True, imaging=True, crm=True, secretary=True, modules=["lumbar"]
    )
    store.grant(principal, grant, "synthetic-admin")
    busy = raw_sample(owned_nonlisten_sockets=1)
    watch = LegacyActivityObserver(
        type("Busy", (), {"sample": lambda self: busy})(),
        expected_release_id="synthetic-active-release",
        expected_manifest_sha256="a" * 64,
        required_access_columns=EXPECTED_COLUMNS,
        stable_process_samples=2,
    )
    with pytest.raises(DrainTimeout):
        run_fenced_transition(
            LegacyGrantFence(
                store, tmp_path / "private" / "fence.snapshot", actor="synthetic-transition"
            ),
            observe=watch.observe,
            transition=lambda: pytest.fail("Child socket reached transition."),
            timeout=0.04,
            settle=0.01,
            poll=0.005,
        )

    assert store.user(principal)["enabled"] == 1


def test_filesystem_adapter_reads_only_aggregate_state(tmp_path, monkeypatch):
    from tools.eagle_eye.legacy_activity_observer import FilesystemProcessAdapter, ProcessAggregate

    manifest = tmp_path / "deployment.json"
    manifest.write_text(json.dumps({"release_id": "synthetic-active-release"}), encoding="utf-8")
    job_root = tmp_path / "jobs"
    (job_root / "job-a").mkdir(parents=True)
    (job_root / "job-a" / "state.json").write_text(
        json.dumps({"status": "succeeded", "private": "must-not-be-returned"}), encoding="utf-8"
    )
    store = AccessStore(tmp_path / "access.sqlite3", "synthetic-center")
    principal = store.identify({
        "provider": "pacs", "subject": "synthetic-subject", "username": "synthetic-user"
    })
    store.event(principal, "synthetic-device", "echomind", "admitted", "synthetic-request")
    adapter = FilesystemProcessAdapter(
        manifest_path=manifest,
        source_root=tmp_path,
        job_root=job_root,
        access_database=store.path,
        service_pid=os.getpid(),
        allowed_child_sha256=set(),
    )
    monkeypatch.setattr(
        adapter,
        "_process_aggregate",
        lambda: ProcessAggregate(
            source_matches=True,
            tree_digest="d" * 64,
            unknown_children=0,
            service_nonlisten_sockets=0,
            owned_nonlisten_sockets=0,
            open_job_handles=0,
            open_source_handles=0,
        ),
    )

    sample = adapter.sample()

    assert sample.release_id == "synthetic-active-release"
    assert sample.manifest_sha256 == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert sample.nonterminal_jobs == 0
    assert sample.echomind_admitted == 1
    assert sample.secretary_admitted == sample.crm_admitted == sample.speech_admitted == 0
    assert sample.imaging_admitted == 0
    assert not hasattr(sample, "private")


def test_manifest_accepts_candidate_revision_and_rejects_conflicting_identity(tmp_path):
    from tools.eagle_eye.legacy_activity_observer import FilesystemProcessAdapter

    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(
        json.dumps({"candidate_revision": "synthetic-active-release", "files": {}}),
        encoding="utf-8",
    )
    job_root = tmp_path / "jobs"
    job_root.mkdir()
    store = AccessStore(tmp_path / "access.sqlite3", "synthetic-center")
    adapter = FilesystemProcessAdapter(
        manifest_path=manifest,
        source_root=tmp_path,
        job_root=job_root,
        access_database=store.path,
        service_pid=os.getpid(),
        allowed_child_sha256=set(),
    )

    release_id, digest = adapter._manifest()

    assert release_id == "synthetic-active-release"
    assert digest == hashlib.sha256(manifest.read_bytes()).hexdigest()
    manifest.write_text(
        json.dumps({
            "release_id": "synthetic-active-release",
            "candidate_revision": "different-release",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicting"):
        adapter._manifest()


@pytest.mark.skipif(os.name != "nt", reason="Windows raw-handle guard")
def test_windows_inspector_detects_sourcelease_createfile_handle(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.ownership import DirectoryLease
    from modules.ai_imaging.eagle_eye_remote.source import SourceLease
    from tools.eagle_eye.legacy_activity_observer import WindowsHandleInspector

    source = tmp_path / "job-a" / "sources" / "synthetic.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic")
    inspector = WindowsHandleInspector()
    directory_lease = DirectoryLease(tmp_path)
    lease = SourceLease()
    try:
        lease.pin(source)
        try:
            open_jobs, open_sources = inspector.inspect([os.getpid()], tmp_path)
            assert open_jobs >= 0
            assert open_sources >= 1
        finally:
            lease.close()

        _open_jobs, open_sources = inspector.inspect([os.getpid()], tmp_path)
        assert open_sources == 0
    finally:
        directory_lease.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows raw-handle guard")
def test_windows_inspector_rejects_nested_or_duplicate_directory_lease(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.ownership import DirectoryLease
    from tools.eagle_eye.legacy_activity_observer import WindowsHandleInspector

    nested = tmp_path / "job-a"
    nested.mkdir()
    root_lease = DirectoryLease(tmp_path)
    nested_lease = DirectoryLease(nested)
    try:
        inspector = WindowsHandleInspector()
        open_jobs, open_sources = inspector.inspect([os.getpid()], tmp_path)
        assert open_jobs >= 1
        assert open_sources == 0
        with (tmp_path / ".server.lock").open("rb"):
            with pytest.raises(OSError, match="one verified ownership lease"):
                inspector.inspect([os.getpid()], tmp_path)
    finally:
        nested_lease.close()
        root_lease.close()


def test_handle_inspection_failure_makes_complete_observation_uncertain(tmp_path, monkeypatch):
    from tools.eagle_eye.legacy_activity_observer import FilesystemProcessAdapter

    class DeniedInspector:
        def inspect(self, process_ids, job_root):
            raise PermissionError("Synthetic inspection denial")

    manifest = tmp_path / "deployment.json"
    manifest.write_text(json.dumps({"release_id": "synthetic-active-release"}), encoding="utf-8")
    job_root = tmp_path / "jobs"
    job_root.mkdir()
    store = AccessStore(tmp_path / "access.sqlite3", "synthetic-center")
    adapter = FilesystemProcessAdapter(
        manifest_path=manifest,
        source_root=tmp_path,
        job_root=job_root,
        access_database=store.path,
        service_pid=os.getpid(),
        allowed_child_sha256=set(),
        handle_inspector=DeniedInspector(),
    )
    watch = observer([raw_sample()])
    watch.adapter = adapter
    monkeypatch.setattr(adapter, "_manifest", lambda: ("synthetic-active-release", "a" * 64))
    monkeypatch.setattr(adapter, "_access", lambda: (EXPECTED_COLUMNS, {
        "echomind": 0, "secretary": 0, "crm": 0, "speech": 0, "imaging": 0,
    }))

    result = watch.observe()

    assert result.completion_uncertain is True
    assert watch.reason_codes == ("observer_exception",)


def test_only_explicit_bounded_established_pacs_pool_peer_is_idle(tmp_path):
    from collections import namedtuple
    from tools.eagle_eye.legacy_activity_observer import FilesystemProcessAdapter

    manifest = tmp_path / "deployment.json"
    manifest.write_text(json.dumps({"release_id": "synthetic-active-release"}), encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    store = AccessStore(tmp_path / "access.sqlite3", "synthetic-center")
    now = [100.0]
    owner = (os.getpid(), 1.0)
    adapter = FilesystemProcessAdapter(
        manifest_path=manifest,
        source_root=tmp_path,
        job_root=jobs,
        access_database=store.path,
        service_pid=os.getpid(),
        allowed_child_sha256=set(),
        permitted_idle_tcp_peers={("127.0.0.1", 8000): 1},
        idle_tcp_owner_pid=os.getpid(),
        idle_tcp_owner_create_time=1.0,
        clock=lambda: now[0],
    )
    Address = namedtuple("Address", "ip port")
    Connection = namedtuple("ConnectionWithLocal", "status laddr raddr")
    pooled = [Connection("ESTABLISHED", Address("127.0.0.1", 53744), Address("127.0.0.1", 8000))]
    assert adapter._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=owner
    ) == 1
    now[0] += 74
    assert adapter._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=owner
    ) == 1
    now[0] += 1
    assert adapter._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=owner
    ) == 0
    assert adapter._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=(os.getpid() + 1, 1.0)
    ) == 1
    assert adapter._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=(os.getpid(), 2.0)
    ) == 1
    assert adapter._active_tcp_count([
        Connection("ESTABLISHED", Address("127.0.0.1", 53744), Address("127.0.0.1", 8000)),
        Connection("ESTABLISHED", Address("127.0.0.1", 53745), Address("127.0.0.1", 8000)),
        Connection("ESTABLISHED", Address("127.0.0.1", 53746), Address("127.0.0.1", 8002)),
        Connection("CLOSE_WAIT", Address("127.0.0.1", 53747), Address("127.0.0.1", 8000)),
        Connection("LISTEN", Address("127.0.0.1", 8002), ()),
    ], "LISTEN", "ESTABLISHED", owner=owner) == 3

    permitted_counts = {("127.0.0.1", 8000): 0}
    assert adapter._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=owner,
        permitted_counts=permitted_counts,
    ) == 0
    assert adapter._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=owner,
        permitted_counts=permitted_counts,
    ) == 1


@pytest.mark.parametrize("peers", [
    {("not-an-ip", 8000): 1},
    {("127.0.0.1", 0): 1},
    {("127.0.0.1", 8000): 0},
    {("127.0.0.1", 8000): 5},
])
def test_idle_tcp_peer_configuration_is_strictly_bounded(tmp_path, peers):
    from tools.eagle_eye.legacy_activity_observer import FilesystemProcessAdapter

    manifest = tmp_path / "deployment.json"
    manifest.write_text(json.dumps({"release_id": "synthetic-active-release"}), encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    store = AccessStore(tmp_path / "access.sqlite3", "synthetic-center")
    with pytest.raises(ValueError):
        FilesystemProcessAdapter(
            manifest_path=manifest,
            source_root=tmp_path,
            job_root=jobs,
            access_database=store.path,
            service_pid=os.getpid(),
            allowed_child_sha256=set(),
            permitted_idle_tcp_peers=peers,
            idle_tcp_owner_pid=os.getpid(),
            idle_tcp_owner_create_time=1.0,
        )


def test_idle_tcp_pool_identity_change_restarts_minimum_age(tmp_path):
    from collections import namedtuple
    from tools.eagle_eye.legacy_activity_observer import FilesystemProcessAdapter

    manifest = tmp_path / "deployment.json"
    manifest.write_text(json.dumps({"release_id": "synthetic-active-release"}), encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    store = AccessStore(tmp_path / "access.sqlite3", "synthetic-center")
    now = [0.0]
    adapter = FilesystemProcessAdapter(
        manifest_path=manifest, source_root=tmp_path, job_root=jobs,
        access_database=store.path, service_pid=os.getpid(), allowed_child_sha256=set(),
        permitted_idle_tcp_peers={("127.0.0.1", 8000): 1},
        idle_tcp_owner_pid=os.getpid(), idle_tcp_owner_create_time=1.0,
        clock=lambda: now[0],
    )
    Address = namedtuple("Address", "ip port")
    Connection = namedtuple("Connection", "status laddr raddr")
    first = Connection("ESTABLISHED", Address("127.0.0.1", 53000), Address("127.0.0.1", 8000))
    changed = Connection("ESTABLISHED", Address("127.0.0.1", 53001), Address("127.0.0.1", 8000))

    assert adapter._active_tcp_count(
        [first], "LISTEN", "ESTABLISHED", owner=(os.getpid(), 1.0)
    ) == 1
    now[0] = 75
    assert adapter._active_tcp_count(
        [changed], "LISTEN", "ESTABLISHED", owner=(os.getpid(), 1.0)
    ) == 1


def test_opaque_idle_tcp_age_state_survives_isolated_probe_without_exposing_tuple(tmp_path):
    from collections import namedtuple
    from tools.eagle_eye.legacy_activity_observer import FilesystemProcessAdapter

    manifest = tmp_path / "deployment.json"
    manifest.write_text(json.dumps({"release_id": "synthetic-active-release"}), encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    store = AccessStore(tmp_path / "access.sqlite3", "synthetic-center")
    now = [10.0]
    options = dict(
        manifest_path=manifest, source_root=tmp_path, job_root=jobs,
        access_database=store.path, service_pid=os.getpid(), allowed_child_sha256=set(),
        permitted_idle_tcp_peers={("127.0.0.1", 8000): 1},
        idle_tcp_owner_pid=os.getpid(), idle_tcp_owner_create_time=1.0,
        clock=lambda: now[0],
    )
    Address = namedtuple("Address", "ip port")
    Connection = namedtuple("Connection", "status laddr raddr")
    pooled = [Connection(
        "ESTABLISHED", Address("127.0.0.1", 53000), Address("127.0.0.1", 8000)
    )]
    first = FilesystemProcessAdapter(**options)
    assert first._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=(os.getpid(), 1.0)
    ) == 1
    state = first.idle_tcp_state()
    assert list(state) and all(len(key) == 64 and "127.0.0.1" not in key for key in state)

    now[0] = 85.0
    second = FilesystemProcessAdapter(**options, idle_tcp_first_seen=state)
    assert second._active_tcp_count(
        pooled, "LISTEN", "ESTABLISHED", owner=(os.getpid(), 1.0)
    ) == 0
