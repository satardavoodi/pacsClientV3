"""Run two real workstation receivers against the PACS synthetic socket harness.

Usage: server-venv/python workflow_wire_acceptance.py --server-root <checkout>
No clinical configuration, database, records, authentication or services are used.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-root", required=True)
    args = parser.parse_args()
    root = Path(args.server_root).resolve()
    sys.path[:0] = [str(root / "tests"), str(root)]
    from socket_harness import workflow_server
    source = Path(__file__).resolve().parents[2] / "modules/network/workflow_realtime.py"
    spec = importlib.util.spec_from_file_location("workstation_workflow", source)
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    # Local overlay IO has independent unit coverage; keep this wire harness pure.
    client.prepare_display = lambda states: states
    server, namespace = workflow_server([dict(StudyInstanceUID="1.2.3", PatientID="synthetic", reportStatus="pending")])
    listener = threading.Thread(target=server.start, daemon=True)
    listener.start()
    receivers = []
    latest = [{}, {}]
    def wait_for(predicate, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            for index, receiver in enumerate(receivers):
                for row in receiver.mailbox.drain():
                    latest[index] = row
            if predicate():
                return
            time.sleep(.02)
        raise AssertionError("Synthetic workflow acceptance timed out")
    try:
        wait_for(lambda: server.running)
        address = server.socket.getsockname()
        for _ in range(2):
            receiver = client.WorkflowReceiver(*address, "synthetic-token")
            receiver.watch(["1.2.3"]); receiver.start(); receivers.append(receiver)
        wait_for(lambda: all(row.get("report_status") == "pending" for row in latest))
        row = namespace["workflow_rows"][0]
        row.update(radiologistId="synthetic-user", radiologistName="Synthetic Reader", radiologistSource="pacs")
        server.broadcast_patient_list_updated({"study_uid": "1.2.3", "patient_id": "synthetic"})
        wait_for(lambda: all(x.get("assignment", {}).get("radiologist", {}).get("id") == "synthetic-user" for x in latest))
        row["reportStatus"] = "completed"
        server.broadcast_report_status_changed("1.2.3", "synthetic", "pending", "completed")
        wait_for(lambda: all(x.get("report_status") == "completed" for x in latest))
        row["attachments"] = [{"attachment_type": "voice"}]
        for _ in range(200):
            server.broadcast_audio_uploaded("1.2.3", "synthetic")
        wait_for(lambda: all(x.get("audio_count") == 1 for x in latest), timeout=12)
        row["attachments"] = []
        server._workflow.invalidate()
        wait_for(lambda: all(x.get("audio_count") == 0 for x in latest), timeout=12)
        # No event: periodic reconciliation must still discover a missed update.
        row["reportStatus"] = "archived"
        wait_for(lambda: all(x.get("report_status") == "archived" for x in latest), timeout=36)
        print(json.dumps({"result": "passed", "receivers": 2, "checks": [
            "assignment", "report", "voice", "burst", "reconnect", "missed_event_reconciliation"]}))
    finally:
        for receiver in receivers:
            receiver.stop(); receiver.join(3)
            assert not receiver.is_alive()
        server.stop(); listener.join(3)
        assert not listener.is_alive()


if __name__ == "__main__":
    main()
