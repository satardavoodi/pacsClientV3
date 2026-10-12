"""Developer launch must reject stale service/config before opening a GUI."""
import subprocess
from pathlib import Path
import pytest

GUARD = Path(__file__).resolve().parents[3] / "tools/eagle_eye/developer_service_target.ps1"

@pytest.mark.parametrize("command,allowed", [
    ('"C:/runtime/python.exe" "D:/review/source/tools/eagle_eye/windows_service.py" "D:/private/server.json"', True),
    ('"C:/runtime/python.exe" "D:/old/source/tools/eagle_eye/windows_service.py" "D:/private/server.json"', False),
    ('"C:/runtime/python.exe" "D:/review/source/tools/eagle_eye/windows_service.py" "D:/old/server.json"', False),
    ('"C:/runtime/python.exe" "D:/review/source/tools/eagle_eye/windows_service.py.old" "D:/private/server.json"', False),
])
def test_exact_service_target(command, allowed):
    script = ". '" + str(GUARD).replace("'", "''") + "'; try { Assert-EagleDeveloperTarget -ExpectedSource 'D:/review/source' -ExpectedConfig 'D:/private/server.json' -ServiceCommand '" + command + "'; exit 0 } catch { exit 8 }"
    run = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; " + script], capture_output=True, text=True)
    assert run.returncode == (0 if allowed else 8), run.stderr
