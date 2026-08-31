"""Run a bounded synthetic control experiment against the source-linked runtime.

Creates a unique artifact directory; does not load patient data, start AI-PACS,
modify the packaged runtime, install extensions, or change user settings.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-reviewed-extension", action="store_true",
                        help="Load the pinned SegmentCrossSectionArea research download for this process only")
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    runtime = repository / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build"
    executable = runtime / "AIPacsAdvancedViewer.exe"
    if not executable.is_file():
        raise RuntimeError("Source-linked Advanced Viewer runtime is not present")
    extension = repository / "generated-files/slicer-extension-research/2026-08-31/SlicerSandbox/SegmentCrossSectionArea"
    if arguments.with_reviewed_extension:
        reviewed_files = {
            "SegmentCrossSectionArea.py": "6147e0153543f5a5c5542573e5f62b6153d2c996ec5c5d82d699cb6d2c270637",
            "Resources/UI/SegmentCrossSectionArea.ui": "1ce6d5524e908d719e654b71299bca99ea9b169d88cf206c8b38c0adce11574c",
        }
        for relative, expected in reviewed_files.items():
            path = extension / relative
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Missing or changed reviewed extension file: {relative}; see extension guide")
    processes = subprocess.run(["tasklist", "/FI", "IMAGENAME eq AIPacsAdvancedViewer.exe", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if '"aipacsadvancedviewer.exe"' in processes.stdout.lower():
        raise RuntimeError("An Advanced Viewer instance is already running; no probe launched")
    output = repository / "generated-files/slicer-control-probe" / uuid.uuid4().hex
    output.mkdir(parents=True)
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("NEWMPR2_") or name in ("PYTHONHOME", "PYTHONPATH"):
            environment.pop(name)
    environment["AIPACS_SLICER_PROBE_DIR"] = str(output)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["AIPACS_SLICER_PROBE_EXTENSION"] = "1" if arguments.with_reviewed_extension else "0"
    command = [str(executable), "--no-splash", "--no-main-window", "--disable-settings", "--ignore-slicerrc",
               "--launcher-ignore-user-additional-settings", "--launcher-timeout", "180",
               "--python-script", str(repository / "tools/dev/slicer_control_probe.py")]
    if arguments.with_reviewed_extension:
        command.extend(["--additional-module-path", str(extension)])
    results = {"scope": "synthetic-only isolated runtime", "calls": [], "passed": False}
    connection = None
    # Avoid proxies even if the workstation configures one for external requests.
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(operation, parameters=None, token=None):
        body = json.dumps({"operation": operation, "parameters": parameters or {},
                           "token": connection["token"] if token is None else token}).encode()
        request = urllib.request.Request(f'http://127.0.0.1:{connection["port"]}/probe', data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
        start = time.monotonic()
        with http.open(request, timeout=35) as response:
            result = json.load(response)
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        results["calls"].append(result)
        return result

    with (output / "runtime.stdout.txt").open("w", encoding="utf-8") as stdout, (output / "runtime.stderr.txt").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=output, env=environment, stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        started = time.monotonic()
        try:
            connection_file = output / "connection.json"
            while not connection_file.exists():
                if (output / "startup_error.json").exists():
                    raise RuntimeError("Probe adapter startup failed; see startup_error.json")
                if process.poll() is not None:
                    raise RuntimeError(f"Runtime exited before readiness: {process.returncode}")
                if time.monotonic() - started > 85:
                    raise TimeoutError("Runtime did not become ready within 85 seconds")
                time.sleep(0.2)
            connection = json.loads(connection_file.read_text(encoding="utf-8"))
            results["startup_seconds"] = round(time.monotonic() - started, 3)
            for operation, parameters in [("capabilities", {}), ("open_fixture", {}),
                                          ("open_dicom_fixture", {}),
                                          ("threshold", {"lower": 30, "upper": 100}),
                                          ("threshold", {"lower": 60, "upper": 100}), ("save_reload", {})]:
                result = call(operation, parameters)
                if not result.get("ok"):
                    raise RuntimeError(f"{operation}: {result.get('message')}")
                print(json.dumps({"operation": operation, "ok": True, "seconds": result["elapsed_seconds"]}), flush=True)
            if arguments.with_reviewed_extension:
                for axis in ("slice", "row", "column"):
                    result = call("extension_cross_section", {"axis": axis})
                    if not result.get("ok"):
                        raise RuntimeError(f"extension_cross_section: {result.get('message')}")
                    print(json.dumps({"operation": "extension_cross_section", "axis": axis,
                                      "ok": True, "seconds": result["elapsed_seconds"]}), flush=True)
                if call("extension_cross_section", {"axis": "invalid"}).get("ok"):
                    raise RuntimeError("Invalid extension axis was accepted")
            if call("threshold", {"lower": 60, "upper": 100}, token="invalid").get("ok"):
                raise RuntimeError("Unauthorized request was accepted")
            if call("execute_python").get("ok"):
                raise RuntimeError("Unknown operation was accepted")
            if call("threshold", {"lower": 100, "upper": 20}).get("ok"):
                raise RuntimeError("Invalid parameter range was accepted")
            results["passed"] = True
        except Exception as exc:
            results["error"] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            if connection is not None and process.poll() is None:
                try:
                    call("shutdown")
                except (OSError, urllib.error.URLError) as exc:
                    results["shutdown_warning"] = type(exc).__name__
            try:
                results["process_exit_code"] = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                # Popen still owns this live process handle, so its PID cannot
                # refer to a reused process. Stop only this probe's process tree.
                stopped = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                         capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                results["owned_tree_stop_exit_code"] = stopped.returncode
                results["shutdown_warning"] = "Isolated probe required forced cleanup"
                try:
                    results["process_exit_code"] = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    results["process_exit_code"] = None
                results["passed"] = False
            results["passed"] = results["passed"] and results["process_exit_code"] == 0
            (output / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            (output / "connection.json").unlink(missing_ok=True)
    print(json.dumps({"passed": results["passed"], "result": str(output / "result.json"),
                      "error": results.get("error"), "process_exit_code": results.get("process_exit_code")}), flush=True)
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
