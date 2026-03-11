from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_spec(spec_path: Path):
    loader = importlib.machinery.SourceFileLoader("echomind_nuitka_spec", str(spec_path))
    spec = importlib.util.spec_from_file_location(
        "echomind_nuitka_spec", spec_path, loader=loader,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load spec: {spec_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_args(spec_module) -> list[str]:
    entry = getattr(spec_module, "ENTRY_SCRIPT", None)
    if not entry:
        raise ValueError("ENTRY_SCRIPT is required in modules.EchoMind.nuitka.spec")

    args = [sys.executable, "-m", "nuitka", entry]

    if getattr(spec_module, "STANDALONE", True):
        args.append("--standalone")

    windows_console = getattr(spec_module, "WINDOWS_CONSOLE_MODE", None)
    if windows_console:
        args.append(f"--windows-console-mode={windows_console}")

    for plugin in getattr(spec_module, "PLUGINS", []):
        args.append(f"--enable-plugin={plugin}")

    for package in getattr(spec_module, "INCLUDE_PACKAGES", []):
        args.append(f"--include-package={package}")

    for package in getattr(spec_module, "INCLUDE_PACKAGE_DATA", []):
        args.append(f"--include-package-data={package}")

    output_dir = getattr(spec_module, "OUTPUT_DIR", None)
    if output_dir:
        args.append(f"--output-dir={output_dir}")

    args.extend(getattr(spec_module, "EXTRA_ARGS", []))
    return args


def main() -> int:
    echomind_dir = Path(__file__).resolve().parent
    repo_root = echomind_dir.parent
    spec_path = echomind_dir / "modules.EchoMind.nuitka.spec"
    if not spec_path.exists():
        print(f"modules.EchoMind.nuitka.spec not found: {spec_path}")
        return 2

    try:
        spec_module = _load_spec(spec_path)
        args = _build_args(spec_module)
    except Exception as exc:
        print(f"Failed to load spec: {exc}")
        return 2

    # Rewrite the entry script (last positional arg) to be relative to repo root
    # so that Nuitka can resolve sibling packages like PacsClient.
    entry_rel = Path("EchoMind") / args[3]  # args[3] is the entry script
    args[3] = str(entry_rel)

    # Also make output-dir relative to repo root so it lands inside EchoMind/
    for i, arg in enumerate(args):
        if arg.startswith("--output-dir="):
            output_dir = arg.split("=", 1)[1]
            args[i] = f"--output-dir={Path('EchoMind') / output_dir}"
            break

    args.extend(sys.argv[1:])
    print(f"Running from: {repo_root}")
    print(f"Command: {' '.join(args)}")
    result = subprocess.run(args, cwd=str(repo_root))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
