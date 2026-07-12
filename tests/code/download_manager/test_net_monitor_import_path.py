"""Guard: the DM network monitor must actually import.

Field log (Roshana, 2026-07-12) — the very first line of download_diagnostics.log:

    Traceback (most recent call last):
      File "modules\\download_manager\\ui\\widget\\widget.py", line 337, in __init__
        from ..network.net_monitor import NetworkReachabilityMonitor
    ModuleNotFoundError: No module named 'modules.download_manager.ui.network'

`widget.py` lives in `modules.download_manager.ui.widget`, so `..network` resolves
to `modules.download_manager.ui.network` — which does not exist. net_monitor is at
`modules/download_manager/network/`, i.e. THREE levels up. The import raised on
every startup (swallowed by the try/except), so the OPT-24 network auto-resume
feature was silently dead in every shipped build.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_net_monitor_lives_where_the_import_says():
    assert (REPO_ROOT / "modules" / "download_manager" / "network" / "net_monitor.py").is_file()
    assert not (REPO_ROOT / "modules" / "download_manager" / "ui" / "network").exists()


def test_net_monitor_is_importable():
    from modules.download_manager.network.net_monitor import (  # noqa: F401
        NetworkReachabilityMonitor,
    )


def test_widget_uses_the_correct_relative_depth():
    for rel in (
        "modules/download_manager/ui/widget/widget.py",
        "builder/plugin package/packages/download_manager/payload/python/"
        "modules/download_manager/ui/widget/widget.py",
    ):
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        assert "from ..network.net_monitor import" not in src, (
            f"{rel}: `..network` is modules.download_manager.ui.network (nonexistent)"
        )
        assert "from ...network.net_monitor import" in src, rel
