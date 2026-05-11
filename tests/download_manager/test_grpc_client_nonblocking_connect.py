"""Non-blocking connect contract for DownloadManager gRPC client.

Regression guard:
- ``GrpcMetadataClient._connect`` must not call ``time.sleep`` while building
  the channel/subscription path, because this method is reachable from UI
  thread during DM widget construction.
"""

from __future__ import annotations

from pathlib import Path
import re


def _method_body(src: str, method: str) -> str:
    m = re.search(
        rf"def {method}\(self.*?\):.*?(?=\n    def |\nclass |\Z)",
        src,
        re.DOTALL,
    )
    assert m is not None, f"method {method!r} not found"
    return m.group(0)


def test_grpc_connect_has_no_sleep_calls_canonical() -> None:
    src = Path("modules/download_manager/network/grpc_client.py").read_text(encoding="utf-8")
    body = _method_body(src, "_connect")
    assert "time.sleep(" not in body, (
        "Found time.sleep() inside GrpcMetadataClient._connect in canonical file. "
        "_connect must remain non-blocking for UI-thread safety."
    )


def test_grpc_connect_has_no_sleep_calls_plugin() -> None:
    plugin = Path(
        "builder/plugin package/packages/download_manager/payload/python/"
        "modules/download_manager/network/grpc_client.py"
    )
    if not plugin.exists():
        return
    src = plugin.read_text(encoding="utf-8")
    body = _method_body(src, "_connect")
    assert "time.sleep(" not in body, (
        "Found time.sleep() inside plugin GrpcMetadataClient._connect. Keep canonical/plugin parity."
    )
