"""Actual stdio handshake; never calls an application or patient tool."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest


@pytest.mark.parametrize("interpreter", [sys.executable] + (
    [os.environ["AIPACS_MCP_COMPAT_PYTHON"]] if os.environ.get("AIPACS_MCP_COMPAT_PYTHON") else []))
def test_mcp_sdk_stdio_inventory(interpreter):
    root = Path(__file__).resolve().parents[3]
    process = subprocess.Popen([interpreter, str(root / "tools/testing/aipacs_control_mcp/server.py")],
        cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    received = queue.Queue()
    def read():
        for line in process.stdout:
            received.put(line)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
    def response(request_id):
        while True:
            message = json.loads(received.get(timeout=15))
            if message.get("id") == request_id:
                return message
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "synthetic-check", "version": "1"}}})
        assert "result" in response(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {tool["name"] for tool in response(2)["result"]["tools"]}
        assert {"ping", "list_actions", "raw_command", "open_patient"} <= names
    finally:
        process.terminate()
        process.wait(timeout=5)
        reader.join(timeout=2)
