"""Run one hidden, source-linked, synthetic Slicer extension qualification."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inference", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    flags = subprocess.CREATE_NO_WINDOW
    processes = subprocess.check_output(
        ["tasklist", "/FI", "IMAGENAME eq AIPacsAdvancedViewer.exe", "/FO", "CSV", "/NH"],
        text=True, creationflags=flags)
    if '"aipacsadvancedviewer.exe"' in processes.lower():
        raise RuntimeError("An Advanced Viewer is running; no probe was launched")
    result_dir = repo / "generated-files/offline-lumbar/probes" / uuid.uuid4().hex
    result_dir.mkdir(parents=True)
    runtime = repo / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build"
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("NEWMPR2_", "PYTHON"))}
    env.update(AIPACS_LUMBAR_PROBE_DIR=str(result_dir),
               AIPACS_LUMBAR_PROBE_INFERENCE="1" if args.inference else "0",
               AIPACS_OFFLINE_LUMBAR_ROOT=str(repo / "generated-files/offline-lumbar/bundle"))
    command = [str(runtime / "AIPacsAdvancedViewer.exe"), "--no-splash", "--no-main-window",
               "--disable-settings", "--ignore-slicerrc", "--launcher-ignore-user-additional-settings",
               "--additional-module-path", str(repo / "modules/mpr/advanced_3d_slicer/slicer_modules"),
               "--python-script", str(repo / "tools/dev/slicer_offline_lumbar_probe.py")]
    with (result_dir / "runtime.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, env=env, cwd=result_dir, stdout=log, stderr=log, creationflags=flags)
        try:
            code = process.wait(timeout=940 if args.inference else 90)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           check=False, creationflags=flags, stdout=subprocess.DEVNULL)
            process.wait(timeout=15)
            raise
    result = json.loads((result_dir / "result.json").read_text(encoding="utf-8"))
    print(json.dumps({"passed": result["passed"], "process_exit_code": code,
                      "result": str(result_dir / "result.json"), "error": result.get("error")}))
    return 0 if result["passed"] and code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
