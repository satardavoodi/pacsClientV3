from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> int:
    script = PROJECT_ROOT / "builder" / "build_release.py"
    args = [sys.executable, str(script), *sys.argv[1:]]
    return subprocess.call(args, cwd=str(PROJECT_ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
