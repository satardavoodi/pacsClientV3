"""Reproduce Inno's long source path failure using synthetic data only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    from builder.build_release import find_iscc
    compiler = find_iscc()
    if compiler is None:
        raise RuntimeError("Inno Setup compiler missing")
    results = []
    with tempfile.TemporaryDirectory(prefix="ap-path-") as temporary:
        root = Path(temporary).resolve()
        source_root = root / ("nested_" + "x" * 80)
        source_root.mkdir()
        name_length = 261 - len(str(source_root)) - 1
        long_file = source_root / ("r" * (name_length - 4) + ".txt")
        long_file.write_bytes(b"synthetic build path probe")
        short_file = root / "resource.txt"
        short_file.write_bytes(long_file.read_bytes())
        for label, file in (("long", long_file), ("short", short_file)):
            script = root / (label + ".iss")
            script.write_text(f'[Setup]\nAppName=PathProbe\nAppVersion=1.0\nDefaultDirName={{tmp}}\\PathProbe\n'
                              f'OutputDir={root}\nOutputBaseFilename={label}\nUninstallable=no\n'
                              f'[Files]\nSource: "{file}"; DestDir: "{{app}}"\n', encoding="utf-8")
            result = subprocess.run([str(compiler), "/Q", str(script)], capture_output=True,
                                    text=True, timeout=60)
            results.append({"source_path_length": len(str(file)), "exists": file.exists(),
                            "variant": label, "exit_code": result.returncode,
                            "path_error": "cannot find the path" in result.stderr + result.stdout})
        print(json.dumps({"synthetic_only": True, "installer_executed": False, "results": results}))
        if results[0]["exit_code"] == 0 or results[1]["exit_code"] != 0:
            raise RuntimeError("Path-length hypothesis was not reproduced as expected")


if __name__ == "__main__":
    main()
