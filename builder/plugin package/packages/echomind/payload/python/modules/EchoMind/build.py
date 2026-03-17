from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    spec_path = root / "modules.EchoMind.spec"
    if not spec_path.exists():
        print(f"modules.EchoMind.spec not found: {spec_path}")
        return 2

    args = ["--noconfirm", "--clean", str(spec_path)]
    args.extend(sys.argv[1:])

    from PyInstaller.__main__ import run

    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
