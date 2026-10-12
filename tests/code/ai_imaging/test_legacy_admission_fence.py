"""Synthetic guards for the legacy Eagle Eye transition admission fence."""
from http.server import ThreadingHTTPServer
import json
import threading
import time
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from modules.ai_imaging.eagle_eye_remote import server
from modules.ai_imaging.eagle_eye_remote.contracts import MODULES
from modules.ai_imaging.eagle_eye_remote.user_access import AccessStore, UserAuthority


FULL_GRANT = {
    "enabled": True,
    "echomind": True,
    "imaging": True,
    "crm": True,
    "secretary": True,
    "modules": sorted(MODULES),
}


def approved_store(tmp_path):
    store = AccessStore(tmp_path / "user-access.sqlite3", "synthetic-center")
    principals = []
    for number in range(2):
        principal = store.identify({
            "provider": "pacs",
            "subject": f"synthetic-subject-{number}",
            "username": f"synthetic-user-{number}",
        })
        store.grant(principal, {**FULL_GRANT, "crm": number == 0}, "synthetic-admin")
        principals.append(principal)
    return store, principals


def grants(store):
    keys = ("enabled", "echomind", "imaging", "crm", "secretary", "modules")
    return {row["principal"]: {key: row[key] for key in keys} for row in store.users()}


def test_fence_disables_enabled_users_atomically_and_restores_exact_grants(tmp_path):
    from tools.eagle_eye.legacy_admission_fence import LegacyGrantFence

    store, _ = approved_store(tmp_path)
    before = grants(store)
    snapshot = tmp_path / "private" / "legacy-fence.snapshot"
    fence = LegacyGrantFence(store, snapshot, actor="synthetic-transition")

    fence.disable()
    assert snapshot.is_file()
    assert all(not row["enabled"] for row in store.users())
    fence.restore()

    assert grants(store) == before
    assert not snapshot.exists()


def test_timeout_restores_grants_and_never_runs_transition(tmp_path):
    from tools.eagle_eye.legacy_admission_fence import (
        ActivitySnapshot,
        DrainTimeout,
        LegacyGrantFence,
        run_fenced_transition,
    )

    store, _ = approved_store(tmp_path)
    before = grants(store)
    fence = LegacyGrantFence(
        store, tmp_path / "private" / "legacy-fence.snapshot", actor="synthetic-transition"
    )
    transitions = []

    with pytest.raises(DrainTimeout):
        run_fenced_transition(
            fence,
            observe=lambda: ActivitySnapshot(active_handlers=1),
            transition=lambda: transitions.append(True),
            timeout=0.03,
            settle=0.01,
            poll=0.005,
        )

    assert transitions == []
    assert grants(store) == before


def test_last_verify_race_must_finish_before_transition(tmp_path):
    from tools.eagle_eye.legacy_admission_fence import (
        ActivitySnapshot,
        LegacyGrantFence,
        run_fenced_transition,
    )

    store, _ = approved_store(tmp_path)
    before = grants(store)
    active = threading.Event()
    active.set()
    transitioned = []

    def finish_already_admitted_request():
        time.sleep(0.04)
        active.clear()

    worker = threading.Thread(target=finish_already_admitted_request, daemon=True)
    worker.start()
    fence = LegacyGrantFence(
        store, tmp_path / "private" / "legacy-fence.snapshot", actor="synthetic-transition"
    )
    run_fenced_transition(
        fence,
        observe=lambda: ActivitySnapshot(
            active_handlers=int(active.is_set()), active_sockets=int(active.is_set())
        ),
        transition=lambda: transitioned.append((time.monotonic(), grants(store))),
        timeout=0.5,
        settle=0.02,
        poll=0.005,
    )
    worker.join(1)

    assert not active.is_set()
    assert len(transitioned) == 1
    assert all(not row["enabled"] for row in transitioned[0][1].values())
    assert grants(store) == before


def test_uncertain_completion_aborts_and_restores(tmp_path):
    from tools.eagle_eye.legacy_admission_fence import (
        ActivitySnapshot,
        CompletionUncertain,
        LegacyGrantFence,
        run_fenced_transition,
    )

    store, _ = approved_store(tmp_path)
    before = grants(store)
    with pytest.raises(CompletionUncertain):
        run_fenced_transition(
            LegacyGrantFence(
                store, tmp_path / "private" / "legacy-fence.snapshot",
                actor="synthetic-transition",
            ),
            observe=lambda: ActivitySnapshot(completion_uncertain=True),
            transition=lambda: pytest.fail("Uncertain work reached transition."),
            timeout=0.1,
            settle=0.01,
            poll=0.005,
        )
    assert grants(store) == before


def test_transient_uncertain_sample_resets_proof_then_allows_new_stable_idle(tmp_path):
    from tools.eagle_eye.legacy_admission_fence import (
        ActivitySnapshot,
        LegacyGrantFence,
        run_fenced_transition,
    )

    store, _ = approved_store(tmp_path)
    samples = iter([
        ActivitySnapshot(completion_uncertain=True),
        ActivitySnapshot(),
        ActivitySnapshot(),
        ActivitySnapshot(),
    ])
    transitioned = []

    result = run_fenced_transition(
        LegacyGrantFence(
            store, tmp_path / "private" / "legacy-fence.snapshot",
            actor="synthetic-transition",
        ),
        observe=lambda: next(samples),
        transition=lambda: transitioned.append(True) or "transitioned",
        timeout=0.5,
        settle=0.01,
        poll=0.005,
    )

    assert result == "transitioned"
    assert transitioned == [True]
    assert all(row["enabled"] for row in grants(store).values())


def test_concurrent_grant_enable_aborts_without_overwriting_admin_change(tmp_path):
    from tools.eagle_eye.legacy_admission_fence import (
        ActivitySnapshot,
        GrantDrift,
        LegacyGrantFence,
        run_fenced_transition,
    )

    store, _ = approved_store(tmp_path)
    new_principal = store.identify({
        "provider": "pacs",
        "subject": "synthetic-late-subject",
        "username": "synthetic-late-user",
    })
    disabled = {**FULL_GRANT, "enabled": False}
    store.grant(new_principal, disabled, "synthetic-admin")
    before = grants(store)
    changed = {**disabled, "enabled": True, "crm": False}

    def concurrent_admin_change():
        store.grant(new_principal, changed, "synthetic-other-admin")
        return ActivitySnapshot()

    with pytest.raises(GrantDrift):
        run_fenced_transition(
            LegacyGrantFence(
                store, tmp_path / "private" / "legacy-fence.snapshot",
                actor="synthetic-transition",
            ),
            observe=concurrent_admin_change,
            transition=lambda: pytest.fail("Grant drift reached transition."),
            timeout=0.1,
            settle=0.01,
            poll=0.005,
        )

    after = grants(store)
    assert {key: after[key] for key in before if key != new_principal} == {
        key: before[key] for key in before if key != new_principal
    }
    assert after[new_principal] == changed


def test_private_snapshot_recovers_after_interrupted_controller(tmp_path):
    from tools.eagle_eye.legacy_admission_fence import LegacyGrantFence, restore_from_snapshot

    store, _ = approved_store(tmp_path)
    before = grants(store)
    snapshot = tmp_path / "private" / "legacy-fence.snapshot"
    LegacyGrantFence(store, snapshot, actor="synthetic-transition").disable()

    restore_from_snapshot(store, snapshot, actor="synthetic-recovery")

    assert grants(store) == before
    assert not snapshot.exists()


class Provider:
    def verify(self, token):
        if token != "synthetic-upstream":
            raise ValueError("Rejected")
        return {"subject": "synthetic-subject", "username": "synthetic-user"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/auth/me"),
        ("GET", "/v1/usage"),
        ("GET", "/v1/jobs"),
        ("GET", "/v1/jobs/" + "a" * 32),
        ("POST", "/v1/crm/command"),
        ("POST", "/v1/cases/snapshot"),
        ("POST", "/v1/speech/transcribe"),
        ("POST", "/v1/secretary/plan"),
        ("POST", "/v1/secretary/assets"),
        ("POST", "/v1/echomind/process"),
        ("POST", "/v1/imaging/lumbar-vision"),
        ("POST", "/v1/jobs"),
    ],
)
def test_existing_sessions_recheck_disabled_grant_before_protected_routes(tmp_path, method, path):
    from tools.eagle_eye.legacy_admission_fence import LegacyGrantFence

    provider = Provider()
    authority = UserAuthority(
        AccessStore(tmp_path / "access.sqlite3", "synthetic-center"), {"pacs": provider}
    )
    principal = authority.store.identify({"provider": "pacs", **provider.verify("synthetic-upstream")})
    authority.store.grant(principal, FULL_GRANT, "synthetic-admin")
    jobs = SimpleNamespace()
    http = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        server.handler(
            jobs,
            {"synthetic-device": "synthetic-device-token"},
            user_authority=authority,
            license_guard=lambda: True,
        ),
    )
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{http.server_port}"
    try:
        login = urllib.request.Request(
            root + "/v1/auth/session",
            data=json.dumps({"provider": "pacs", "upstream_token": "synthetic-upstream"}).encode(),
            headers={"Authorization": "Bearer synthetic-device-token", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(login, timeout=3) as response:
            session = json.load(response)["user_session"]
        fence = LegacyGrantFence(
            authority.store,
            tmp_path / "private" / f"{method}-{path.replace('/', '-')}.snapshot",
            actor="synthetic-transition",
        )
        fence.disable()
        body = None if method == "GET" else json.dumps({"synthetic": True}).encode()
        request = urllib.request.Request(
            root + path,
            method=method,
            data=body,
            headers={
                "Authorization": "Bearer synthetic-device-token",
                "X-Eagle-User-Session": session,
                "Content-Type": "application/json",
                "Connection": "close",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(request, timeout=3)
        assert denied.value.code == 403
        assert json.load(denied.value)["code"] == "EAGLE_USER_DISABLED"
        fence.restore()
    finally:
        http.shutdown()
        http.server_close()
        thread.join(3)


def test_capabilities_remain_read_only_during_legacy_fence(tmp_path):
    from tools.eagle_eye.legacy_admission_fence import LegacyGrantFence

    store, _ = approved_store(tmp_path)
    fence = LegacyGrantFence(
        store, tmp_path / "private" / "legacy-fence.snapshot", actor="synthetic-transition"
    )
    fence.disable()
    jobs = SimpleNamespace()
    http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler(jobs, {}))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{http.server_port}/v1/capabilities", timeout=3
        ) as response:
            assert response.status == 200
    finally:
        fence.restore()
        http.shutdown()
        http.server_close()
        thread.join(3)
