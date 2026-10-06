"""Synthetic-only realtime transport and bounded delivery guards."""
import json
import socket
import threading
import time

import pytest


def test_mailbox_coalesces_and_is_bounded():
    from modules.network.workflow_realtime import Mailbox
    box = Mailbox()
    for i in range(10000):
        box.publish([{"study_uid": str(i % 100), "patient_id": "test", "audio_count": i}])
    result = box.drain()
    assert len(result) == 100
    assert max(x["audio_count"] for x in result) == 9999
    assert box.drain() == []


def test_oversize_frame_is_rejected_before_body_read():
    from modules.network.workflow_realtime import receive
    a, b = socket.socketpair()
    try:
        b.sendall((2**31).to_bytes(4, "big"))
        with pytest.raises(ValueError):
            receive(a)
    finally:
        a.close(); b.close()


def test_fragmented_frame():
    from modules.network.workflow_realtime import receive
    a, b = socket.socketpair()
    payload = json.dumps({"status": "success"}).encode()
    def send():
        for part in [(len(payload)).to_bytes(4, "big")[:2], (len(payload)).to_bytes(4, "big")[2:], payload[:3], payload[3:]]:
            b.sendall(part)
    t = threading.Thread(target=send)
    try:
        t.start()
        assert receive(a) == {"status": "success"}
    finally:
        t.join(); a.close(); b.close()


def test_snapshot_never_accepts_unrequested_study():
    from modules.network.workflow_realtime import validated_states
    assert validated_states([{"study_uid": "other", "patient_id": "p"}], ("expected",)) == []


def test_home_owns_and_stops_realtime_service():
    from pathlib import Path
    root = Path("PacsClient/pacs/workstation_ui/home_ui")
    assert "WorkflowRealtime" in (root / "home_panel/widget.py").read_text(encoding="utf-8")
    assert "workflow_realtime.close()" in (root / "home_panel/_hp_patient_open.py").read_text(encoding="utf-8")


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    pytest.fail("Timed out waiting for synthetic workflow")


@pytest.fixture
def server(monkeypatch):
    from modules.network import workflow_realtime as m
    monkeypatch.setattr(m, "prepare_display", lambda states: states)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0)); listener.listen(); listener.settimeout(.1)
    stop = threading.Event()
    state = {"version": 1, "snapshots": 0, "subscriptions": 0, "event_socket": None, "errors": []}
    clients = []
    def reply(sock, data):
        payload = json.dumps(data).encode()
        sock.sendall(len(payload).to_bytes(4, "big") + payload)
    state["reply"] = reply
    def accept():
        while not stop.is_set():
            try:
                sock, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            clients.append(sock)
            try:
                request = m.receive(sock)
                endpoint = request["endpoint"]
                data = {"realtime_version": state["version"]}
                if endpoint == "SubscribeToEvents":
                    state["subscriptions"] += 1
                    state["event_socket"] = sock
                elif endpoint == "GetWorkflowStates":
                    assert request["params"]["study_uids"] == ["1.2.3"]
                    state["snapshots"] += 1
                    data["states"] = [dict(study_uid="1.2.3", patient_id="synthetic", report_status="pending",
                                           assignment={}, audio_count=state["snapshots"])]
                reply(sock, dict(status="success", request_id=request["request_id"], data=data))
            except Exception as exc:
                state["errors"].append(type(exc).__name__)
    thread = threading.Thread(target=accept)
    thread.start()
    state["address"] = listener.getsockname()
    yield state
    stop.set(); listener.close()
    for sock in clients:
        sock.close()
    thread.join(2)


def test_real_socket_reconnect_reconciles_and_burst_is_bounded(server):
    from modules.network.workflow_realtime import WorkflowReceiver
    receiver = WorkflowReceiver(*server["address"], "synthetic-token")
    receiver.watch(["1.2.3"])
    receiver.start()
    try:
        wait_until(lambda: server["snapshots"] >= 1)
        for _ in range(100):
            server["reply"](server["event_socket"], dict(type="broadcast", event_type="audio_uploaded", data={"study_uid": "1.2.3"}))
        wait_until(lambda: server["snapshots"] >= 2)
        assert server["snapshots"] <= 3
        server["event_socket"].shutdown(socket.SHUT_RDWR)
        server["event_socket"].close()
        wait_until(lambda: server["subscriptions"] >= 2)
        wait_until(lambda: server["snapshots"] >= 3)
        result = receiver.mailbox.drain()
        assert len(result) == 1 and result[0]["patient_id"] == "synthetic"
        assert not server["errors"]
    finally:
        receiver.stop(); receiver.join(2)
    assert not receiver.is_alive()


def test_old_server_does_not_receive_snapshot_requests(server):
    from modules.network.workflow_realtime import WorkflowReceiver
    server["version"] = 0
    receiver = WorkflowReceiver(*server["address"], "synthetic-token")
    receiver.watch(["1.2.3"]); receiver.start(); receiver.join(2)
    assert not receiver.is_alive()
    assert receiver.status == "unavailable"
    assert server["snapshots"] == 0


def test_local_completed_assignment_is_preserved(monkeypatch):
    monkeypatch.setenv("AIPACS_INO_ASSIGNMENT", "1")
    from modules.network.workflow_realtime import prepare_display
    from modules.network import ino_assignment_history
    monkeypatch.setattr(ino_assignment_history, "current_assignment_details",
                        lambda pid: {"assignment_status": "completed", "assignee_name": "Synthetic"})
    states = prepare_display([dict(patient_id="synthetic", assignment={"radiologist": {"id": "r", "name": "Synthetic"}})])
    assert states[0]["display_assignment"]["status"] == "completed"
