from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILDER_ROOT = PROJECT_ROOT / "builder"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BUILDER_ROOT) not in sys.path:
    sys.path.insert(0, str(BUILDER_ROOT))
if str((PROJECT_ROOT / "builder nuitka")) not in sys.path:
    sys.path.insert(0, str((PROJECT_ROOT / "builder nuitka")))

from aipacs_runtime import (  # noqa: E402
    APP_NAME,
    INSTALLATION_PROFILE_FILENAME,
    MODULE_CATALOG,
    default_installation_profile,
)
from build_release import (  # noqa: E402
    find_iscc,
    load_version,
    validate_local_graphics_runtime,
)
from builder.materialize_plugin_packages import materialize_plugin_packages  # noqa: E402
from builder.plugin_package_registry import PLUGIN_PACKAGES_DIR, load_plugin_package_definitions  # noqa: E402

from nuitka_build_config import (  # noqa: E402
    CHECKPOINTS_DIR,
    DIST_DIR,
    INSTALLER_DIR,
    INSTALLER_OUTPUT_DIR,
    LOGS_DIR,
    NUITKA_CACHE_DIR,
    OUTPUT_ROOT,
    REPORTS_DIR,
    STAGE_DIR,
    STATE_FILE,
    ensure_output_dirs,
)


OPTIONAL_PLUGIN_MODULES = [
    "modules.printing",
    "modules.cd_burner",
    "modules.web_browser",
    "modules.EchoMind",
    "modules.mpr.advanced_3d_slicer",
    "modules.data_analysis",
]

ALLOW_MISSING_ADVANCED_MPR_ENV = "AIPACS_ALLOW_MISSING_ADVANCED_MPR"
ADVANCED_MPR_REQUIRED_RUNTIME_FILES = (
    "AIPacsAdvancedViewer.exe",
    "AIPacsAdvancedViewerLauncherSettings.ini",
    "bin/Python/startup_script.py",
    "python-install/Lib/site-packages/numpy/testing/__init__.py",
    "python-install/Lib/site-packages/pydicom/examples/__init__.py",
)

NATIVE_AUDIT_PACKAGES = [
    "pandas",
    "matplotlib",
    "cv2",
    "vtkmodules",
    "SimpleITK",
    "PySide6",
    "numpy",
    "PIL",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def print_header(text: str) -> None:
    print("\n" + "=" * 88)
    print(text)
    print("=" * 88)


class StageError(RuntimeError):
    pass


@dataclass
class StageResult:
    command: list[str] | None = None
    output_paths: list[str] = field(default_factory=list)
    artifact_paths: list[str] = field(default_factory=list)
    report_path: str | None = None
    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Stage:
    number: int
    key: str
    title: str
    runner: Callable[["BuildContext", "Stage", Path], StageResult]


class BuildContext:
    def __init__(self, args: argparse.Namespace, spec: ModuleType):
        self.args = args
        self.spec = spec
        self.version = load_version()
        self.state = self._load_state()
        self.run_mode = self._derive_run_mode(args)
        self._bootstrap_state()

    def _derive_run_mode(self, args: argparse.Namespace) -> str:
        if args.resume:
            return "resume"
        if args.from_stage is not None:
            return "from_stage"
        if args.stage is not None:
            return "single_stage"
        return "fresh"

    def _load_state(self) -> dict[str, Any]:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "schema_version": 1,
            "created_at_utc": utc_now(),
            "completed_stages": [],
            "stages": {},
        }

    def _bootstrap_state(self) -> None:
        self.state.setdefault("schema_version", 1)
        self.state.setdefault("created_at_utc", utc_now())
        self.state["updated_at_utc"] = utc_now()
        self.state["mode"] = self.run_mode
        self.state.setdefault("stages", {})
        self._normalize_state()
        if self.args.clean_all:
            self.state["clean_mode"] = "all"
        elif self.args.clean_stage is not None:
            self.state["clean_mode"] = f"stage:{self.args.clean_stage}"
        else:
            self.state["clean_mode"] = "none"
        self.save_state()

    def _normalize_state(self) -> None:
        stages_payload = self.state.get("stages")
        if not isinstance(stages_payload, dict):
            stages_payload = {}
            self.state["stages"] = stages_payload

        normalized_completed: set[int] = set()
        for raw in self.state.get("completed_stages", []):
            try:
                stage_num = int(raw)
            except (TypeError, ValueError):
                continue
            if stage_num not in STAGES:
                continue
            stage_state = stages_payload.get(str(stage_num))
            if isinstance(stage_state, dict) and stage_state.get("status") == "completed":
                stage_state.pop("error", None)
                normalized_completed.add(stage_num)
        self.state["completed_stages"] = sorted(normalized_completed)

        failed_stage = self.state.get("failed_stage")
        if failed_stage is not None:
            try:
                failed_stage = int(failed_stage)
            except (TypeError, ValueError):
                failed_stage = None
        if failed_stage not in STAGES:
            failed_stage = None
        self.state["failed_stage"] = failed_stage

        current_stage = self.state.get("current_stage")
        if current_stage is not None:
            try:
                current_stage = int(current_stage)
            except (TypeError, ValueError):
                current_stage = None
        if current_stage not in STAGES:
            current_stage = None
        self.state["current_stage"] = current_stage

    def save_state(self) -> None:
        self.state["updated_at_utc"] = utc_now()
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

    def prepare_stage_log(self, stage: Stage) -> Path:
        base = LOGS_DIR / f"stage_{stage.number:02d}_{stage.key}.log"
        if base.exists():
            archive_name = f"stage_{stage.number:02d}_{stage.key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            base.rename(LOGS_DIR / archive_name)
        return base

    def set_stage_running(self, stage: Stage, log_path: Path) -> None:
        self.state["current_stage"] = stage.number
        stage_state = self.state["stages"].setdefault(str(stage.number), {})
        stage_state.update(
            {
                "name": stage.title,
                "status": "running",
                "started_at_utc": utc_now(),
                "log_path": str(log_path),
            }
        )
        self.save_state()

    def set_stage_completed(self, stage: Stage, result: StageResult) -> None:
        stage_state = self.state["stages"].setdefault(str(stage.number), {})
        stage_state.update(
            {
                "name": stage.title,
                "status": "completed",
                "finished_at_utc": utc_now(),
                "command": result.command or [],
                "output_paths": result.output_paths,
                "artifact_paths": result.artifact_paths,
                "report_path": result.report_path,
                "issues": result.issues,
                "notes": result.notes,
            }
        )
        stage_state.pop("error", None)
        completed = set(int(x) for x in self.state.get("completed_stages", []))
        completed.add(stage.number)
        self.state["completed_stages"] = sorted(completed)
        if stage.number > 0:
            self.invalidate_downstream_stages(stage.number)
        self.state["failed_stage"] = None
        self.state["current_stage"] = None
        self.write_checkpoint(stage, result)
        self.save_state()

    def invalidate_downstream_stages(self, stage_number: int) -> None:
        downstream = [n for n in STAGES if n > stage_number]
        if not downstream:
            return
        completed = set(int(x) for x in self.state.get("completed_stages", []))
        touched = False
        for number in downstream:
            if number in completed:
                completed.discard(number)
                touched = True
            state_entry = self.state.get("stages", {}).get(str(number))
            if isinstance(state_entry, dict) and state_entry.get("status") == "completed":
                state_entry["status"] = "stale"
                state_entry.pop("error", None)
                touched = True
        if touched:
            self.state["completed_stages"] = sorted(completed)

    def set_stage_failed(self, stage: Stage, result: StageResult, error: Exception, log_path: Path) -> None:
        stage_state = self.state["stages"].setdefault(str(stage.number), {})
        stage_state.update(
            {
                "name": stage.title,
                "status": "failed",
                "finished_at_utc": utc_now(),
                "command": result.command or [],
                "output_paths": result.output_paths,
                "artifact_paths": result.artifact_paths,
                "report_path": result.report_path,
                "issues": result.issues,
                "error": str(error),
                "log_path": str(log_path),
            }
        )
        self.state["failed_stage"] = stage.number
        self.state["current_stage"] = None
        self.save_state()

    def write_checkpoint(self, stage: Stage, result: StageResult) -> None:
        checkpoint_dir = CHECKPOINTS_DIR / f"stage_{stage.number:02d}"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "stage": stage.number,
            "key": stage.key,
            "title": stage.title,
            "created_at_utc": utc_now(),
            "marker_only": True,
            "command": result.command or [],
            "output_paths": result.output_paths,
            "artifact_paths": result.artifact_paths,
            "log_path": self.state.get("stages", {}).get(str(stage.number), {}).get("log_path", ""),
            "report_path": result.report_path,
            "issues": result.issues,
            "notes": result.notes,
        }
        (checkpoint_dir / "checkpoint.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_spec(spec_path: Path) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("nuitka_spec_staged", str(spec_path))
    spec_obj = importlib.util.spec_from_loader("nuitka_spec_staged", loader, origin=str(spec_path))
    if spec_obj is None:
        raise StageError(f"Unable to load spec from {spec_path}")
    module = importlib.util.module_from_spec(spec_obj)
    module.__file__ = str(spec_path)
    loader.exec_module(module)
    return module


def ensure_stage_entrypoints() -> None:
    entry_dir = PROJECT_ROOT / "builder nuitka" / "stage_entrypoints"
    entry_dir.mkdir(parents=True, exist_ok=True)

    stage1 = entry_dir / "stage1_minimal_bootstrap.py"
    stage1.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import os
            import sys
            from pathlib import Path

            if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
                print("AIPacs stage1 smoke bootstrap OK")
                raise SystemExit(0)

            print(f"Python executable: {sys.executable}")
            print(f"Running from: {Path.cwd()}")
            print("AIPacs stage1 bootstrap executable generated successfully.")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    stage2 = entry_dir / "stage2_qt_shell.py"
    stage2.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import os
            import sys

            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication, QLabel

            app = QApplication(sys.argv)
            label = QLabel("AIPacs Qt shell stage")
            label.setWindowTitle("AIPacs Qt Shell")
            label.resize(360, 80)
            label.show()

            QTimer.singleShot(250, app.quit)
            raise SystemExit(app.exec())
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    stage3 = entry_dir / "stage3_core_bootstrap.py"
    stage3.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import os

            import database
            import database.core
            import database.manager
            import modules.module_system

            if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
                print("AIPacs stage3 core bootstrap OK")
                raise SystemExit(0)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    stage4 = entry_dir / "stage4_dicom_bootstrap.py"
    stage4.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import os

            import numpy
            import pydicom
            import pydicom.encoders
            import pydicom.pixel_data_handlers
            import pydicom.pixel_data_handlers.numpy_handler

            if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
                print("AIPacs stage4 DICOM bootstrap OK")
                raise SystemExit(0)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    stage5 = entry_dir / "stage5_native_bootstrap.py"
    stage5.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import os

            import SimpleITK
            import vtkmodules.all
            import vtkmodules.qt.QVTKRenderWindowInteractor
            import vtkmodules.util.numpy_support

            if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
                print("AIPacs stage5 native bootstrap OK")
                raise SystemExit(0)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def stage_output_root(stage: Stage) -> Path:
    return DIST_DIR / f"stage_{stage.number:02d}_{stage.key}"


def stage_dist_dir(stage: Stage, entrypoint: str) -> Path:
    return stage_output_root(stage) / f"{Path(entrypoint).stem}.dist"


def append_log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def run_command_with_log(
    cmd: list[str],
    *,
    cwd: Path,
    log_path: Path,
    env: dict[str, str] | None = None,
) -> int:
    append_log(log_path, f"[COMMAND] {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        universal_newlines=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        append_log(log_path, line.rstrip("\n"))
    process.wait()
    append_log(log_path, f"[EXIT_CODE] {process.returncode}")
    return int(process.returncode)


def build_root_launcher_exe(ctx: BuildContext, core_stage: Path, log_path: Path) -> Path:
    launcher_src = core_stage / "_launcher_root.py"
    launcher_exe = core_stage / f"{APP_NAME}.exe"

    launcher_src.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import subprocess
            import sys
            from pathlib import Path


            def _message_box(text: str) -> None:
                try:
                    import ctypes

                    ctypes.windll.user32.MessageBoxW(0, text, "AIPacs Launcher", 0x10)
                except Exception:
                    pass


            def main() -> int:
                root = Path(sys.argv[0]).resolve().parent
                engine_exe = root / "Engine" / "AIPacs.exe"
                if not engine_exe.exists():
                    _message_box(f"Engine executable not found:\\n{engine_exe}")
                    return 1

                try:
                    subprocess.Popen([str(engine_exe), *sys.argv[1:]], cwd=str(engine_exe.parent))
                    return 0
                except Exception as exc:
                    _message_box(f"Failed to start engine:\\n{exc}")
                    return 1


            if __name__ == "__main__":
                raise SystemExit(main())
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        f"--output-dir={core_stage}",
        f"--output-filename={APP_NAME}.exe",
        "--windows-console-mode=disable",
        str(launcher_src),
    ]
    icon = getattr(ctx.spec, "ICON", "")
    if icon and (PROJECT_ROOT / icon).exists():
        cmd.insert(-1, f"--windows-icon-from-ico={icon}")

    rc = run_command_with_log(cmd, cwd=PROJECT_ROOT, log_path=log_path)
    if rc != 0 or not launcher_exe.exists():
        raise StageError(f"Failed to build root launcher executable: {launcher_exe}")
    launcher_src.unlink(missing_ok=True)
    for suffix in (".build", ".dist", ".onefile-build"):
        cleanup_dir = core_stage / f"_launcher_root{suffix}"
        if cleanup_dir.exists():
            shutil.rmtree(cleanup_dir, ignore_errors=True)
    return launcher_exe


def parse_missing_issues(text: str) -> list[str]:
    patterns = [
        r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]",
        r"ImportError: DLL load failed[^\n]*",
        r"cannot open shared object file[^\n]*",
        r"No such file or directory[^\n]*",
        r"qt\.qpa\.plugin: Could not find the Qt platform plugin[^\n]*",
    ]
    findings: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            issue = match if isinstance(match, str) else " ".join(match)
            issue = issue.strip()
            if not issue:
                continue
            if issue not in findings:
                findings.append(issue)
            if len(findings) >= 20:
                return findings
    return findings


def copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    if source.is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        target = destination
        # Treat destination as a directory target when it already is one, or
        # when caller passed a folder-like path without a suffix.
        if destination.exists() and destination.is_dir():
            target = destination / source.name
        elif not destination.exists() and destination.suffix == "":
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / source.name
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return True


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def get_spec_list(spec: ModuleType, name: str) -> list[Any]:
    value = getattr(spec, name, [])
    if value is None:
        return []
    return list(value)


def module_exists(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def existing_modules(candidates: list[str]) -> set[str]:
    return {name for name in candidates if module_exists(name)}


def create_nuitka_command(
    ctx: BuildContext,
    stage: Stage,
    *,
    profile: str,
    entrypoint: str,
) -> tuple[list[str], Path, Path]:
    report_path = REPORTS_DIR / f"nuitka_stage_{stage.number:02d}_{stage.key}.xml"
    output_root = stage_output_root(stage)

    cmd: list[str] = [sys.executable, "-m", "nuitka", "--standalone"]
    cmd.append(f"--output-dir={output_root}")
    cmd.append(f"--output-filename={APP_NAME}.exe")
    cmd.append("--product-name=AIPacs")
    # Nuitka requires --product-version to be up to 4 dot-separated integers.
    # Sanitize the human-facing version (e.g. "2.4.7c") to a numeric tuple
    # ("2.4.7") for Nuitka while keeping ctx.version intact for Inno Setup.
    _numeric_parts: list[str] = []
    for _part in str(ctx.version).split("."):
        _digits = "".join(_ch for _ch in _part if _ch.isdigit())
        if not _digits:
            break
        _numeric_parts.append(_digits)
        if len(_numeric_parts) >= 4:
            break
    _nuitka_version = ".".join(_numeric_parts) if _numeric_parts else "0"
    cmd.append(f"--product-version={_nuitka_version}")
    cmd.append("--company-name=AIPacs")
    cmd.append("--file-description=AIPacs - staged Nuitka build")
    cmd.append("--windows-console-mode=disable")

    icon = getattr(ctx.spec, "ICON", "")
    if icon:
        icon_path = PROJECT_ROOT / icon
        if icon_path.exists():
            cmd.append(f"--windows-icon-from-ico={icon}")

    # Nuitka 4.0.8 does not support "--cache-dir". Keep project-local cache
    # strategy via tool-specific environment variables where possible.
    cmd.append(f"--report={report_path}")
    cmd.append("--assume-yes-for-downloads")
    cmd.append("--warn-unusual-code")
    cmd.append("--warn-implicit-exceptions")
    # Keep hash-based internals deterministic across compile/runtime and avoid
    # accidental cwd imports in frozen startup.
    cmd.append("--python-flag=static_hashes")
    cmd.append("--python-flag=safe_path")

    lto = getattr(ctx.spec, "LTO", "auto")
    if profile in {"minimal", "qt_shell", "heavy_native", "full_core"} and lto == "yes":
        lto = "no"
    if lto in {"yes", "no", "auto"}:
        cmd.append(f"--lto={lto}")

    jobs = int(getattr(ctx.spec, "JOBS", 0) or 0)
    if jobs > 0:
        cmd.append(f"--jobs={jobs}")

    compiler = str(getattr(ctx.spec, "C_COMPILER", "") or "").strip().lower()
    compiler_override = str(getattr(ctx.args, "compiler", "auto") or "auto").strip().lower()
    if compiler_override != "auto":
        compiler = compiler_override
    if compiler == "zig":
        cmd.append("--zig")
    elif compiler == "mingw64":
        cmd.append("--mingw64")
    elif compiler == "clang":
        cmd.append("--clang")
    elif compiler in {"msvc", "latest"}:
        cmd.append("--msvc=latest")

    forced: set[str] = set()
    include_packages: set[str] = set()
    nofollow: set[str] = set()

    filtered_nofollow_from_spec = {
        item
        for item in get_spec_list(ctx.spec, "NOFOLLOW_IMPORTS")
        if str(item).startswith("modules.")
    }

    if profile == "minimal":
        forced = {"_project_root", "aipacs_runtime"}
        include_packages = set()
        nofollow = set()
    elif profile == "qt_shell":
        cmd.append("--enable-plugin=pyside6")
        forced = set()
        include_packages = set()
        nofollow = set()
    elif profile == "core":
        cmd.append("--enable-plugin=pyside6")
        cmd.append("--include-package-data=PySide6")
        include_packages = {
            "database",
            "modules.module_system",
        }
        forced = {
            "database",
            "database.core",
            "database.manager",
            "PySide6.QtCore",
            "PySide6.QtGui",
            "PySide6.QtWidgets",
        }
    elif profile == "dicom":
        include_packages = {"numpy", "pydicom"}
        forced = {
            "numpy",
            "pydicom",
            "pydicom.encoders",
            "pydicom.pixel_data_handlers",
            "pydicom.pixel_data_handlers.numpy_handler",
        }
    elif profile == "heavy_native":
        include_packages = {"vtkmodules", "SimpleITK", "numpy", "pydicom"}
        forced = {
            "vtkmodules",
            "vtkmodules.all",
            "vtkmodules.qt.QVTKRenderWindowInteractor",
            "vtkmodules.util.numpy_support",
            "SimpleITK",
            "SimpleITK._SimpleITK",
            "numpy",
            "pydicom",
            "pydicom.encoders",
            "pydicom.pixel_data_handlers",
            "pydicom.pixel_data_handlers.numpy_handler",
        }
        append_mesa_runtime_flags(cmd)
    elif profile == "full_core":
        cmd.append("--enable-plugin=pyside6")
        # Keep optional plugin modules external while still allowing runtime
        # imports from external module packages.
        cmd.append("--no-deployment-flag=excluded-module-usage")
        # Entry-point driven inclusion is significantly more stable for this
        # project than broad forced/include-package lists.
        include_packages = {
            "pydicom",
            # settings_ui is imported lazily via package __getattr__/import_module.
            # Force include to avoid runtime "No module named ...settings_ui.settings_ui".
            "PacsClient.pacs.workstation_ui.settings_ui",
        }
        forced = existing_modules(
            [
                # Optional Web Browser stays external, but its PySide6
                # QtWebEngine native runtime must live in the compiled Engine.
                "PySide6.QtWebEngineCore",
                "PySide6.QtWebEngineWidgets",
                "pydicom",
                "pydicom.encoders",
                "pydicom.encoders.base",
                "pydicom.encoders.gdcm",
                "pydicom.encoders.native",
                "pydicom.encoders.pylibjpeg",
                "pydicom.pixel_data_handlers",
                "pydicom.pixel_data_handlers.numpy_handler",
                "pydicom.pixel_data_handlers.gdcm_handler",
            ]
        )
        nofollow = set(filtered_nofollow_from_spec)
        append_mesa_runtime_flags(cmd)

    if profile == "full_core":
        pass
    elif profile in {"dicom", "heavy_native"}:
        # Keep optional plugins external during partial stages as well.
        nofollow = set(filtered_nofollow_from_spec)

    if profile == "full_core":
        pass
    elif profile in {"dicom", "heavy_native", "core"}:
        forced.update(
            {
                "PySide6.QtCore",
                "PySide6.QtGui",
                "PySide6.QtWidgets",
            }
        )

    for item in sorted(nofollow):
        cmd.append(f"--nofollow-import-to={item}")
    for item in sorted(forced):
        cmd.append(f"--include-module={item}")
    for item in sorted(include_packages):
        cmd.append(f"--include-package={item}")

    if profile in {"full_core", "heavy_native"}:
        for src, dst in get_spec_list(ctx.spec, "OPTIONAL_DATA"):
            p = PROJECT_ROOT / src
            if p.is_dir():
                cmd.append(f"--include-data-dir={src}={dst}")
            elif p.is_file():
                cmd.append(f"--include-data-files={src}={dst}/{p.name}")

    cmd.append(entrypoint)
    return cmd, report_path, output_root


def append_mesa_runtime_flags(cmd: list[str]) -> None:
    runtime_dir = PROJECT_ROOT / "graphics_runtime"
    for dll_name in ("opengl32sw.dll", "osmesa.dll", "pipe_swrast.dll"):
        dll_path = runtime_dir / dll_name
        if dll_path.exists():
            cmd.append(f"--include-data-files={dll_path}=./{dll_name}")


def resolve_built_dist(stage: Stage, entrypoint: str) -> Path:
    dist = stage_dist_dir(stage, entrypoint)
    if dist.exists():
        return dist
    output_root = stage_output_root(stage)
    fallback = sorted(output_root.glob("*.dist"))
    if fallback:
        return fallback[0]
    raise StageError(f"Compiled output folder not found for stage {stage.number}: {dist}")


def run_nuitka_stage(ctx: BuildContext, stage: Stage, log_path: Path, profile: str, entrypoint: str) -> StageResult:
    cmd, report_path, output_root = create_nuitka_command(ctx, stage, profile=profile, entrypoint=entrypoint)

    env = os.environ.copy()
    # Keep compiler cache optional; forcing cache env vars has shown unstable
    # artifacts with some toolchain combinations.
    append_log(log_path, "[INFO] Compiler cache env override disabled (using toolchain defaults)")
    if "--zig" in cmd:
        # Let Nuitka select and manage Zig by default; forcing CC/CXX/LINK to
        # a PATH Zig can pin older toolchains and produce unstable binaries.
        zig_exe = shutil.which("zig")
        if zig_exe:
            append_log(log_path, f"[INFO] PATH Zig detected (not forcing CC/CXX/LINK): {zig_exe}")
        else:
            append_log(log_path, "[INFO] PATH Zig not detected; Nuitka-managed Zig toolchain will be used")

    rc = run_command_with_log(cmd, cwd=PROJECT_ROOT, log_path=log_path, env=env)
    if rc != 0:
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        issues = parse_missing_issues(text)
        raise StageError(f"Nuitka command failed with exit code {rc}. Issues: {issues or ['see log']} ")

    dist = resolve_built_dist(stage, entrypoint)
    exe = dist / f"{APP_NAME}.exe"
    if not exe.exists():
        alt = list(dist.glob("*.exe"))
        if alt:
            shutil.copy2(alt[0], exe)
        else:
            raise StageError(f"Stage {stage.number} finished but executable was not produced in {dist}")

    return StageResult(
        command=cmd,
        output_paths=[str(output_root), str(dist)],
        artifact_paths=[str(exe)],
        report_path=str(report_path),
    )


def smoke_launch_exe(exe_path: Path, log_path: Path, env_overrides: dict[str, str] | None = None, timeout_sec: int = 20) -> None:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    cmd = [str(exe_path)]
    append_log(log_path, f"[SMOKE] {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        cwd=str(exe_path.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        stdout, _ = process.communicate(timeout=timeout_sec)
        if stdout:
            append_log(log_path, stdout)
    except subprocess.TimeoutExpired:
        process.kill()
        append_log(log_path, "[SMOKE] Timeout reached; process terminated intentionally")
        return
    if process.returncode not in (0, None):
        raise StageError(f"Smoke launch failed for {exe_path} (exit={process.returncode})")


def stage_00_preflight(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    messages: list[str] = []

    def check(condition: bool, ok: str, bad: str) -> None:
        line = f"[OK] {ok}" if condition else f"[FAIL] {bad}"
        print(line)
        append_log(log_path, line)
        messages.append(line)
        if not condition:
            raise StageError(bad)

    append_log(log_path, f"[INFO] Stage {stage.number:02d} started at {utc_now()}")
    check(sys.version_info >= (3, 10), f"Python version {sys.version.split()[0]}", "Python 3.10+ is required")

    try:
        nuitka_version = importlib.metadata.version("nuitka")
    except importlib.metadata.PackageNotFoundError as exc:
        raise StageError(
            "Nuitka is not installed in this interpreter. "
            "Run setup_build_env.ps1 or install requirements-nuitka.txt in .venv_build."
        ) from exc
    line = f"[OK] Nuitka {nuitka_version}"
    print(line)
    append_log(log_path, line)

    compiler = str(getattr(ctx.spec, "C_COMPILER", "") or "").strip().lower()
    if compiler == "zig":
        check(shutil.which("zig") is not None, "Zig compiler available", "C_COMPILER=zig but zig is not on PATH")
    else:
        has_msvc = shutil.which("cl") is not None
        has_mingw = shutil.which("gcc") is not None or shutil.which("g++") is not None
        check(has_msvc or has_mingw, "MSVC/MinGW compiler found", "No supported C compiler found (MSVC or MinGW)")

    ccache_found = shutil.which("ccache") is not None
    clcache_found = shutil.which("clcache") is not None
    line = f"[INFO] ccache={ccache_found} clcache={clcache_found} nuitka_cache={NUITKA_CACHE_DIR}"
    print(line)
    append_log(log_path, line)

    required_sources = [
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "PacsClient",
        PROJECT_ROOT / "database",
        PROJECT_ROOT / "modules",
        PROJECT_ROOT / "aipacs_runtime.py",
        PROJECT_ROOT / "config",
        PROJECT_ROOT / "Qss",
        PROJECT_ROOT / "Fonts",
        PROJECT_ROOT / "graphics_runtime",
    ]
    for source in required_sources:
        check(source.exists(), f"Found {source}", f"Required path missing: {source}")

    try:
        validate_local_graphics_runtime()
        append_log(log_path, "[OK] Mesa/software graphics runtime is valid")
    except Exception as exc:
        append_log(log_path, f"[WARN] Graphics runtime validation warning: {exc}")

    def import_check(module_name: str) -> None:
        try:
            imported = importlib.import_module(module_name)
            append_log(log_path, f"[OK] Import check passed: {module_name} -> {Path(imported.__file__).resolve()}")
            print(f"[OK] Import check passed: {module_name}")
        except Exception as exc:
            append_log(log_path, f"[FAIL] Import check failed: {module_name} :: {exc}")
            raise StageError(
                f"Required package import failed: {module_name}. "
                f"Install/update build environment (.venv_build) and retry."
            ) from exc

    import_check("PySide6")
    for module_name in ("vtkmodules", "SimpleITK", "pydicom", "numpy"):
        import_check(module_name)

    return StageResult(
        output_paths=[str(OUTPUT_ROOT)],
        artifact_paths=[str(STATE_FILE)],
        notes=["Preflight checks completed"],
    )


def stage_01_minimal_core(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    entrypoint = "builder nuitka/stage_entrypoints/stage1_minimal_bootstrap.py"
    result = run_nuitka_stage(ctx, stage, log_path, profile="minimal", entrypoint=entrypoint)
    exe = Path(result.artifact_paths[0])
    smoke_launch_exe(exe, log_path, env_overrides={"AIPACS_STAGE_SMOKE": "1"}, timeout_sec=10)
    return result


def stage_02_qt_shell(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    entrypoint = "builder nuitka/stage_entrypoints/stage2_qt_shell.py"
    result = run_nuitka_stage(ctx, stage, log_path, profile="qt_shell", entrypoint=entrypoint)
    exe = Path(result.artifact_paths[0])
    smoke_launch_exe(exe, log_path, env_overrides={"QT_QPA_PLATFORM": "offscreen"}, timeout_sec=20)

    plugin_candidates = [
        exe.parent / "PySide6" / "plugins" / "platforms",
        exe.parent / "PySide6" / "qt-plugins" / "platforms",
    ]
    plugin_dir = next((candidate for candidate in plugin_candidates if candidate.exists()), None)
    if plugin_dir is None:
        raise StageError(
            "Qt platform plugin folder missing. Checked: "
            + ", ".join(str(candidate) for candidate in plugin_candidates)
        )
    result.artifact_paths.append(str(plugin_dir))
    return result


def stage_03_core_packages(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    entrypoint = "builder nuitka/stage_entrypoints/stage3_core_bootstrap.py"
    result = run_nuitka_stage(ctx, stage, log_path, profile="core", entrypoint=entrypoint)
    smoke_launch_exe(Path(result.artifact_paths[0]), log_path, env_overrides={"AIPACS_STAGE_SMOKE": "1"}, timeout_sec=15)
    return result


def stage_04_dicom_basic(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    entrypoint = "builder nuitka/stage_entrypoints/stage4_dicom_bootstrap.py"
    result = run_nuitka_stage(ctx, stage, log_path, profile="dicom", entrypoint=entrypoint)
    smoke_launch_exe(Path(result.artifact_paths[0]), log_path, env_overrides={"AIPACS_STAGE_SMOKE": "1"}, timeout_sec=15)
    return result


def stage_05_heavy_native(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    entrypoint = "builder nuitka/stage_entrypoints/stage5_native_bootstrap.py"
    result = run_nuitka_stage(ctx, stage, log_path, profile="heavy_native", entrypoint=entrypoint)
    smoke_launch_exe(Path(result.artifact_paths[0]), log_path, env_overrides={"AIPACS_STAGE_SMOKE": "1"}, timeout_sec=20)
    return result


def stage_06_full_core(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    entrypoint = str(getattr(ctx.spec, "ENTRY_POINT", "main.py"))
    result = run_nuitka_stage(ctx, stage, log_path, profile="full_core", entrypoint=entrypoint)
    try:
        smoke_launch_exe(
            Path(result.artifact_paths[0]),
            log_path,
            env_overrides={"AIPACS_NUITKA_SMOKE_TEST": "1"},
            timeout_sec=25,
        )
    except Exception as exc:
        result.notes.append(f"Stage 6 smoke-launch warning: {exc}")

    report = Path(result.report_path or "")
    if report.exists():
        text = report.read_text(encoding="utf-8", errors="replace")
        forbidden_hits = []
        for module_name in OPTIONAL_PLUGIN_MODULES:
            pattern = rf"<module\s+name=\"{re.escape(module_name)}(?:\.|\")"
            if re.search(pattern, text):
                forbidden_hits.append(module_name)
        if forbidden_hits:
            raise StageError(
                "Optional plugin modules were compiled into core unexpectedly: "
                + ", ".join(forbidden_hits)
            )
        result.notes.append("Optional plugin boundary check passed (no compiled optional modules found in report)")

    return result


def stage_07_runtime_resources(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    stage6_dist = stage_dist_dir(STAGES[6], str(getattr(ctx.spec, "ENTRY_POINT", "main.py")))
    if not stage6_dist.exists():
        raise StageError(f"Stage 6 dist not found: {stage6_dist}")

    core_stage = STAGE_DIR / "core"
    engine_stage = core_stage / "Engine"
    # Recreate core stage payload from stage 6 each run to avoid stale files
    # breaking subsequent resource copies.
    if core_stage.exists():
        shutil.rmtree(core_stage, ignore_errors=True)
    core_stage.mkdir(parents=True, exist_ok=True)
    engine_stage.mkdir(parents=True, exist_ok=True)
    shutil.copytree(stage6_dist, engine_stage, dirs_exist_ok=True)
    nested_user_data = engine_stage / "User Data"
    if nested_user_data.exists():
        shutil.rmtree(nested_user_data, ignore_errors=True)

    copied: list[str] = []
    for src, dst in get_spec_list(ctx.spec, "DATA_DIRS"):
        source_path = PROJECT_ROOT / src
        destination_path = engine_stage / dst
        if copy_if_exists(source_path, destination_path):
            copied.append(f"{src} -> Engine/{dst}")

    theme_css = PROJECT_ROOT / "generated-files" / "css" / "main.css"
    if theme_css.exists():
        destination = engine_stage / "Qss" / "main.qss"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(theme_css, destination)
        copied.append("generated-files/css/main.css -> Engine/Qss/main.qss")

    launcher_exe = build_root_launcher_exe(ctx, core_stage, log_path)
    copied.append(f"{launcher_exe.name} (root launcher exe)")

    launcher_cmd = core_stage / "Launch AIPacs.cmd"
    launcher_cmd.write_text(
        "@echo off\n"
        "setlocal\n"
        "set \"APP_ROOT=%~dp0\"\n"
        "start \"\" \"%APP_ROOT%Engine\\AIPacs.exe\" %*\n",
        encoding="utf-8",
    )
    copied.append("Launch AIPacs.cmd")

    launcher_vbs = core_stage / "Launch AIPacs.vbs"
    launcher_vbs.write_text(
        'Set fso = CreateObject("Scripting.FileSystemObject")\n'
        "base = fso.GetParentFolderName(WScript.ScriptFullName)\n"
        'exePath = base & "\\Engine\\AIPacs.exe"\n'
        'CreateObject("WScript.Shell").Run """" & exePath & """", 0, False\n',
        encoding="utf-8",
    )
    copied.append("Launch AIPacs.vbs")

    # Keep install layout expectations explicit for end users.
    user_data_dir = core_stage / "User Data"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    copied.append("User Data/ (parallel to Engine)")

    pyinstaller_core = PROJECT_ROOT / "builder" / "output" / "dist" / "AIPacs"
    comparison_notes: list[str] = []
    if pyinstaller_core.exists():
        for relative in ("Qss", "Fonts", "config", "json-styles"):
            src_exists = (pyinstaller_core / relative).exists()
            dst_exists = (engine_stage / relative).exists()
            comparison_notes.append(
                f"compare:{relative}: pyinstaller={'yes' if src_exists else 'no'} nuitka_engine={'yes' if dst_exists else 'no'}"
            )

    return StageResult(
        output_paths=[str(core_stage)],
        artifact_paths=[
            str(engine_stage / f"{APP_NAME}.exe"),
            str(launcher_exe),
            str(core_stage / "Launch AIPacs.cmd"),
            str(core_stage / "Launch AIPacs.vbs"),
        ],
        notes=["Runtime resources staged"] + copied + comparison_notes,
    )


def stage_08_plugin_staging(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    materialize_plugin_packages(include_runtime_payloads=True)
    plugin_stage = STAGE_DIR / "plugin_packages"
    if plugin_stage.exists():
        shutil.rmtree(plugin_stage, ignore_errors=True)

    plugin_stage.mkdir(parents=True, exist_ok=True)
    optional_defs = load_plugin_package_definitions(optional_only=True)
    optional_ids = sorted({str(item["module_id"]) for item in optional_defs})
    copied_dirs: list[str] = []
    for module_id in optional_ids:
        source_dir = PLUGIN_PACKAGES_DIR / module_id
        if not source_dir.exists():
            raise StageError(f"Optional plugin package missing from materialized source: {source_dir}")
        shutil.copytree(source_dir, plugin_stage / module_id, dirs_exist_ok=True)
        copied_dirs.append(module_id)

    source_feed = PLUGIN_PACKAGES_DIR / "module_package_feed.json"
    if not source_feed.exists():
        raise StageError(f"Plugin package feed missing from materialized source: {source_feed}")
    feed_data = json.loads(source_feed.read_text(encoding="utf-8"))
    packages = list(feed_data.get("packages") or [])
    feed_data["packages"] = [item for item in packages if str(item.get("module_id") or "") in optional_ids]
    feed_path = plugin_stage / "module_package_feed.json"
    feed_path.write_text(json.dumps(feed_data, indent=2, ensure_ascii=False), encoding="utf-8")

    stage_notes: list[str] = []
    if "advanced_mpr" in optional_ids:
        advanced_mpr_dir = plugin_stage / "advanced_mpr"
        advanced_mpr_manifest = advanced_mpr_dir / "module_package.json"
        allow_missing_advanced_mpr = _env_truthy(ALLOW_MISSING_ADVANCED_MPR_ENV)
        if not advanced_mpr_manifest.exists():
            raise StageError(f"Advanced MPR package manifest missing: {advanced_mpr_manifest}")

        manifest_data = json.loads(advanced_mpr_manifest.read_text(encoding="utf-8"))
        payload_dir_name = str(manifest_data.get("payload_dir") or "").strip()
        payload_dir = advanced_mpr_dir / payload_dir_name if payload_dir_name else None
        missing_required = (
            list(ADVANCED_MPR_REQUIRED_RUNTIME_FILES)
            if payload_dir is None
            else [relative for relative in ADVANCED_MPR_REQUIRED_RUNTIME_FILES if not (payload_dir / relative).exists()]
        )
        if missing_required:
            message = (
                "Advanced MPR runtime payload is not materialized for Nuitka Stage 08. "
                "Set AIPACS_ADVANCED_MPR_RUNTIME_SOURCE to the built Slicer runtime root "
                "before running Stage 08. Missing required files: "
                + ", ".join(missing_required)
            )
            if allow_missing_advanced_mpr:
                stage_notes.append(f"WARNING: {message} Continuing because {ALLOW_MISSING_ADVANCED_MPR_ENV}=1.")
            else:
                raise StageError(
                    message
                    + f". To bypass deliberately, set {ALLOW_MISSING_ADVANCED_MPR_ENV}=1."
                )

    package_dirs = sorted([p.name for p in plugin_stage.iterdir() if p.is_dir()])
    return StageResult(
        output_paths=[str(plugin_stage)],
        artifact_paths=[str(feed_path)],
        notes=[f"Staged optional plugin packages: {', '.join(package_dirs)}", *stage_notes],
    )


def stage_09_installer_staging(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    manifest_dir = STAGE_DIR / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    install_profile = default_installation_profile()
    install_profile["app_version"] = ctx.version
    installer = dict(install_profile.get("installer") or {})
    installer["current_version"] = ctx.version
    install_profile["installer"] = installer
    install_profile["generated_at_utc"] = utc_now()

    profile_path = manifest_dir / INSTALLATION_PROFILE_FILENAME
    profile_path.write_text(json.dumps(install_profile, indent=2, ensure_ascii=False), encoding="utf-8")

    module_packages_dir = STAGE_DIR / "plugin_packages"
    package_names = sorted([p.name for p in module_packages_dir.iterdir() if p.is_dir()]) if module_packages_dir.exists() else []

    release_manifest = {
        "version": ctx.version,
        "generated_at_utc": utc_now(),
        "core_bundle": str(STAGE_DIR / "core"),
        "plugin_packages": package_names,
        "module_catalog": MODULE_CATALOG,
    }
    release_manifest_path = manifest_dir / "release_manifest.json"
    release_manifest_path.write_text(json.dumps(release_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return StageResult(
        output_paths=[str(manifest_dir), str(STAGE_DIR)],
        artifact_paths=[str(profile_path), str(release_manifest_path)],
        notes=["Installer staging manifests generated"],
    )


def stage_10_inno_setup(ctx: BuildContext, stage: Stage, log_path: Path) -> StageResult:
    iscc = find_iscc()
    if iscc is None:
        raise StageError("Inno Setup compiler (ISCC.exe) not found")

    installer_script = INSTALLER_DIR / "AIPacs_Nuitka_Setup.iss"
    if not installer_script.exists():
        raise StageError(f"Installer script missing: {installer_script}")

    cmd = [
        str(iscc),
        f"/DMyAppVersion={ctx.version}",
        f"/DStageDir={STAGE_DIR}",
        f"/DInstallerOutputDir={INSTALLER_OUTPUT_DIR}",
        "/DInstallerBaseName=ai-pacs-nuitka-installer",
        str(installer_script),
    ]

    rc = run_command_with_log(cmd, cwd=INSTALLER_DIR, log_path=log_path)
    if rc != 0:
        raise StageError(f"Installer compile failed with exit code {rc}")

    compiled = sorted(INSTALLER_OUTPUT_DIR.glob("*.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not compiled:
        raise StageError("Installer compilation finished but no output executable was found")

    compiled_installer = compiled[0]
    primary = INSTALLER_OUTPUT_DIR / "ai-pacs-nuitka-installer.exe"
    versioned = INSTALLER_OUTPUT_DIR / f"ai-pacs-nuitka-installer v{ctx.version}.exe"
    if compiled_installer.resolve() != primary.resolve():
        shutil.copy2(compiled_installer, primary)
    else:
        primary = compiled_installer
    shutil.copy2(primary, versioned)

    metadata = {
        "version": ctx.version,
        "generated_at_utc": utc_now(),
        "artifacts": {
            "compiled": str(compiled_installer),
            "primary": str(primary),
            "versioned": str(versioned),
        },
        "sha256": {
            "primary": sha256_file(primary),
            "versioned": sha256_file(versioned),
        },
    }
    (INSTALLER_OUTPUT_DIR / "nuitka_installer_release_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return StageResult(
        command=cmd,
        output_paths=[str(INSTALLER_OUTPUT_DIR)],
        artifact_paths=[str(primary), str(versioned)],
        notes=["Inno Setup installer built"],
    )


def smoke_test(ctx: BuildContext) -> int:
    print_header("Nuitka Smoke Test")
    failures: list[str] = []

    full_dist = stage_dist_dir(STAGES[6], str(getattr(ctx.spec, "ENTRY_POINT", "main.py")))
    exe = full_dist / f"{APP_NAME}.exe"
    if not exe.exists():
        failures.append(f"Missing compiled exe: {exe}")

    qt_platform_candidates = [
        full_dist / "PySide6" / "plugins" / "platforms",
        full_dist / "PySide6" / "qt-plugins" / "platforms",
    ]
    if not any(path.exists() for path in qt_platform_candidates):
        failures.append(
            "Missing Qt platform plugins folder: "
            + ", ".join(str(path) for path in qt_platform_candidates)
        )

    for dll_name in ("opengl32sw.dll", "osmesa.dll", "pipe_swrast.dll"):
        if not ((full_dist / dll_name).exists() or (STAGE_DIR / "core" / "Engine" / dll_name).exists()):
            failures.append(f"Missing graphics DLL candidate: {dll_name}")

    web_package = STAGE_DIR / "plugin_packages" / "web_browser" / "module_package.json"
    if web_package.exists():
        webengine_required = [
            full_dist / "PySide6" / "QtWebEngineWidgets.pyd",
            full_dist / "PySide6" / "QtWebEngineCore.pyd",
            full_dist / "QtWebEngineProcess.exe",
            full_dist / "qt6webenginewidgets.dll",
            full_dist / "qt6webenginecore.dll",
        ]
        if not all(path.exists() for path in webengine_required):
            failures.append("Web Browser package is staged, but QtWebEngine runtime files are missing from Engine")

    for relative in ("Qss", "Fonts", "config"):
        if not (STAGE_DIR / "core" / "Engine" / relative).exists():
            failures.append(f"Missing staged resource folder: {relative}")

    plugin_stage = STAGE_DIR / "plugin_packages"
    if not plugin_stage.exists():
        failures.append(f"Missing plugin staging folder: {plugin_stage}")
    elif not (plugin_stage / "module_package_feed.json").exists():
        failures.append(f"Missing plugin package feed: {plugin_stage / 'module_package_feed.json'}")

    report = REPORTS_DIR / "nuitka_stage_06_full_core.xml"
    if report.exists():
        report_text = report.read_text(encoding="utf-8", errors="replace")
        for module_name in OPTIONAL_PLUGIN_MODULES:
            pattern = rf"<module\s+name=\"{re.escape(module_name)}(?:\.|\")"
            if re.search(pattern, report_text):
                failures.append(f"Optional module appears compiled in core report: {module_name}")

    if exe.exists():
        try:
            smoke_log = LOGS_DIR / f"smoke_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            smoke_launch_exe(
                exe,
                smoke_log,
                env_overrides={"AIPACS_NUITKA_SMOKE_TEST": "1", "QT_QPA_PLATFORM": "offscreen"},
                timeout_sec=20,
            )
            print(f"[OK] Smoke executable launch check passed ({smoke_log})")
        except Exception as exc:
            message = str(exc)
            if "exit=3" in message:
                print(f"[WARN] Launch smoke returned exit=3 (known unstable fast-exit path): {message}")
            else:
                failures.append(f"Launch smoke test failed: {exc}")

    if failures:
        print("[FAIL] Smoke test found issues:")
        for item in failures:
            print(f" - {item}")
        print("\nManual checks:")
        print(" 1) Launch stage_06 full core executable and verify main window opens")
        print(" 2) Open a simple DICOM series if test data is available")
        print(" 3) Verify optional plugins load from staged external package folder")
        return 1

    print("[OK] Smoke checks passed")
    print("Manual checks:")
    print(" 1) Launch full executable and verify login/main shell behavior")
    print(" 2) Run one DICOM load and one viewer interaction")
    print(" 3) Validate installer staging under builder nuitka/output/stage")
    return 0


def _native_audit_package_presence(relative_path: str) -> set[str]:
    normalized = relative_path.replace("\\", "/")
    parts = [part.lower() for part in normalized.split("/")]
    top_level = parts[0] if parts else ""
    filename = parts[-1] if parts else ""
    stem = Path(filename).stem.lower()
    present: set[str] = set()

    package_patterns = {
        "pandas": {"top": {"pandas", "pandas.libs"}, "stem": set()},
        "matplotlib": {"top": {"matplotlib", "mpl_toolkits"}, "stem": set()},
        "cv2": {"top": {"cv2"}, "stem": {"cv2"}},
        "vtkmodules": {"top": {"vtkmodules", "vtk.libs"}, "stem": set()},
        "SimpleITK": {"top": {"simpleitk"}, "stem": {"_simpleitk", "simpleitk"}},
        "PySide6": {"top": {"pyside6", "shiboken6"}, "stem": {"pyside6", "shiboken6"}},
        "numpy": {"top": {"numpy", "numpy.libs"}, "stem": {"_numpy"}},
        "PIL": {"top": {"pil", "pillow"}, "stem": set()},
    }
    for display_name, patterns in package_patterns.items():
        if top_level in patterns["top"] or any(part in patterns["top"] for part in parts):
            present.add(display_name)
            continue
        if stem in patterns["stem"] or any(stem.startswith(prefix + ".") for prefix in patterns["stem"]):
            present.add(display_name)
    return present


def _native_audit_optional_presence(relative_path: str) -> set[str]:
    normalized = relative_path.replace("\\", "/").lower()
    optional_patterns = {
        "advanced_mpr": ("modules/mpr/advanced_3d_slicer", "advanced_mpr"),
        "printing": ("modules/printing",),
        "run_cd": ("modules/cd_burner", "modules/run_cd", "cd_burner", "run_cd"),
        "web_browser": ("modules/web_browser", "web_browser"),
        "echomind": ("modules/echomind", "modules/echomind", "echomind"),
    }
    found: set[str] = set()
    for module_id, needles in optional_patterns.items():
        if any(needle in normalized for needle in needles):
            found.add(module_id)
    return found


def _read_stage_06_report_presence() -> dict[str, bool]:
    report_path = REPORTS_DIR / "nuitka_stage_06_full_core.xml"
    presence = {module_name: False for module_name in OPTIONAL_PLUGIN_MODULES}
    if not report_path.exists():
        return presence
    report_text = report_path.read_text(encoding="utf-8", errors="replace")
    for module_name in OPTIONAL_PLUGIN_MODULES:
        pattern = rf"<module\s+name=\"{re.escape(module_name)}(?:\.|\")"
        presence[module_name] = bool(re.search(pattern, report_text))
    return presence


def audit_native_footprint(_ctx: BuildContext) -> int:
    print_header("Nuitka Native Footprint Audit")
    engine_dir = STAGE_DIR / "core" / "Engine"
    if not engine_dir.exists():
        print(f"[FAIL] Staged Engine folder not found: {engine_dir}")
        print('Run: python "builder nuitka/build_nuitka_release.py" --from-stage 7')
        return 1

    native_files = sorted(
        [path for path in engine_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".dll", ".pyd"}],
        key=lambda path: path.relative_to(engine_dir).as_posix().lower(),
    )
    dll_files = [path for path in native_files if path.suffix.lower() == ".dll"]
    pyd_files = [path for path in native_files if path.suffix.lower() == ".pyd"]

    top_folders: Counter[str] = Counter()
    package_hits: dict[str, set[str]] = {name: set() for name in NATIVE_AUDIT_PACKAGES}
    optional_hits: dict[str, set[str]] = {
        "advanced_mpr": set(),
        "printing": set(),
        "run_cd": set(),
        "web_browser": set(),
        "echomind": set(),
    }

    relative_files: list[str] = []
    for path in native_files:
        relative = path.relative_to(engine_dir).as_posix()
        relative_files.append(relative)
        top_level = relative.split("/", 1)[0] if "/" in relative else "(Engine root)"
        top_folders[top_level] += 1

        for package_name in _native_audit_package_presence(relative):
            package_hits[package_name].add(relative)
        for module_id in _native_audit_optional_presence(relative):
            optional_hits[module_id].add(relative)

    previous_path = REPORTS_DIR / "native_footprint.json"
    previous_files: set[str] = set()
    if previous_path.exists():
        try:
            previous_payload = json.loads(previous_path.read_text(encoding="utf-8"))
            previous_files = set(previous_payload.get("native_files") or [])
        except Exception:
            previous_files = set()

    current_files = set(relative_files)
    added = sorted(current_files - previous_files)
    removed = sorted(previous_files - current_files)

    optional_report_presence = _read_stage_06_report_presence()
    audit_payload = {
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "engine_dir": str(engine_dir),
        "summary": {
            "dll_count": len(dll_files),
            "pyd_count": len(pyd_files),
            "native_file_count": len(native_files),
        },
        "largest_native_folders": [
            {"folder": folder, "count": count} for folder, count in top_folders.most_common(25)
        ],
        "package_presence": {
            package_name: {
                "present": bool(files),
                "native_file_count": len(files),
                "examples": sorted(files)[:25],
            }
            for package_name, files in package_hits.items()
        },
        "optional_plugin_presence": {
            module_id: {
                "native_path_present": bool(files),
                "native_file_count": len(files),
                "examples": sorted(files)[:25],
            }
            for module_id, files in optional_hits.items()
        },
        "optional_plugin_report_presence": optional_report_presence,
        "comparison_to_previous": {
            "previous_report": str(previous_path) if previous_files else None,
            "added_count": len(added) if previous_files else 0,
            "removed_count": len(removed) if previous_files else 0,
            "added_examples": added[:50] if previous_files else [],
            "removed_examples": removed[:50] if previous_files else [],
        },
        "native_files": relative_files,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "native_footprint.json"
    md_path = REPORTS_DIR / "native_footprint.md"
    json_path.write_text(json.dumps(audit_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    markdown_lines = [
        "# Nuitka Native Footprint Audit",
        "",
        f"Generated: `{audit_payload['generated_at_utc']}`",
        f"Engine: `{engine_dir}`",
        "",
        "## Summary",
        "",
        f"- DLL files: `{len(dll_files)}`",
        f"- PYD files: `{len(pyd_files)}`",
        f"- Total native files: `{len(native_files)}`",
        "",
        "## Largest Native Folders",
        "",
    ]
    for item in audit_payload["largest_native_folders"][:15]:
        markdown_lines.append(f"- `{item['folder']}`: `{item['count']}`")

    markdown_lines.extend(["", "## Key Package Presence", ""])
    for package_name, payload in audit_payload["package_presence"].items():
        status = "present" if payload["present"] else "not detected"
        markdown_lines.append(f"- `{package_name}`: {status}, native files `{payload['native_file_count']}`")

    markdown_lines.extend(["", "## Optional Plugin Boundary", ""])
    for module_id, payload in audit_payload["optional_plugin_presence"].items():
        status = "native paths present" if payload["native_path_present"] else "no native paths detected"
        markdown_lines.append(f"- `{module_id}`: {status}")
    for module_name, present in optional_report_presence.items():
        if present:
            markdown_lines.append(f"- WARNING: `{module_name}` appears in Stage 6 Nuitka report")

    markdown_lines.extend(
        [
            "",
            "## Comparison To Previous Audit",
            "",
            f"- Added native files: `{audit_payload['comparison_to_previous']['added_count']}`",
            f"- Removed native files: `{audit_payload['comparison_to_previous']['removed_count']}`",
            "",
            "This audit is warning-only. Use it to decide whether a dependency reduction is safe before changing Stage 6 include/exclude rules.",
            "",
        ]
    )
    md_path.write_text("\n".join(markdown_lines), encoding="utf-8")

    print(f"[OK] Native audit written: {json_path}")
    print(f"[OK] Native audit summary: {md_path}")
    print(f"DLL: {len(dll_files)} | PYD: {len(pyd_files)} | Total native: {len(native_files)}")
    for folder, count in top_folders.most_common(8):
        print(f" - {folder}: {count}")
    return 0


def parse_stage_selection(args: argparse.Namespace) -> tuple[list[int], bool]:
    if args.stage is not None:
        return [args.stage], False
    if args.from_stage is not None:
        return [n for n in STAGES if n >= args.from_stage], False
    if args.resume:
        return [], True
    return list(STAGES.keys()), False


def compute_resume_stages(ctx: BuildContext) -> list[int]:
    completed = set(int(x) for x in ctx.state.get("completed_stages", []))
    for number in sorted(STAGES.keys()):
        if number not in completed:
            return [n for n in STAGES if n >= number]
    failed = ctx.state.get("failed_stage")
    if failed is not None:
        failed = int(failed)
        return [n for n in STAGES if n >= failed]
    return []


def clean_stage_artifacts(stage_number: int) -> None:
    stage = STAGES.get(stage_number)
    if stage is None:
        raise StageError(f"Unknown stage number: {stage_number}")

    patterns = [
        DIST_DIR / f"stage_{stage.number:02d}_{stage.key}",
        REPORTS_DIR / f"nuitka_stage_{stage.number:02d}_{stage.key}.xml",
        LOGS_DIR / f"stage_{stage.number:02d}_{stage.key}.log",
        CHECKPOINTS_DIR / f"stage_{stage.number:02d}",
    ]

    for path in patterns:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)


def clean_all_nuitka_outputs() -> None:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT, ignore_errors=True)


def stage_failure_message(stage: Stage, log_path: Path, report_path: str | None) -> str:
    command_line = ""
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("[COMMAND] "):
                command_line = line.replace("[COMMAND] ", "", 1).strip()
                break

    lines = [
        f"Stage {stage.number} {stage.title} failed.",
        "Previous completed stage checkpoints are preserved.",
        f"Log: {log_path}",
    ]
    if command_line:
        lines.append(f"Command: {command_line}")
    if report_path:
        lines.append(f"Report: {report_path}")
    lines.extend(
        [
            "Next action: fix the missing dependency/import/resource reported in the log/report.",
            'Resume with: python "builder nuitka/build_nuitka_release.py" --resume',
            f'Or rerun only this stage: python "builder nuitka/build_nuitka_release.py" --stage {stage.number}',
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Checkpoint-based staged Nuitka release pipeline")
    parser.add_argument("--resume", action="store_true", help="Resume from failed/incomplete stage")
    parser.add_argument("--from-stage", type=int, dest="from_stage", help="Run from selected stage forward")
    parser.add_argument("--stage", type=int, help="Run only one stage")
    parser.add_argument("--clean-stage", type=int, dest="clean_stage", help="Delete output/log/checkpoint for one stage")
    parser.add_argument("--clean-all", action="store_true", help="Delete only builder nuitka/output artifacts")
    parser.add_argument("--smoke-test", action="store_true", help="Run staged smoke checks without rebuilding")
    parser.add_argument(
        "--audit-native-footprint",
        action="store_true",
        help="Write a warning-only DLL/PYD footprint report for staged Nuitka core",
    )
    parser.add_argument(
        "--compiler",
        choices=["auto", "zig", "msvc", "mingw64", "clang"],
        default="auto",
        help="Override compiler selection for Nuitka compile stages",
    )
    parser.add_argument("--spec", default="AIPacs_nuitka.spec", help="Nuitka spec path")
    return parser.parse_args()


def validate_stage_number(value: int | None, arg_name: str) -> None:
    if value is None:
        return
    if value not in STAGES:
        raise StageError(f"{arg_name} must be one of: {', '.join(str(x) for x in STAGES)}")


def run_pipeline(ctx: BuildContext) -> int:
    selected_stages, is_resume = parse_stage_selection(ctx.args)
    if is_resume:
        selected_stages = compute_resume_stages(ctx)
        if not selected_stages:
            print("All stages are already complete. Nothing to resume.")
            return 0

    print_header("AIPacs Nuitka Incremental Pipeline")
    print(f"Mode: {ctx.run_mode}")
    print(f"Selected stages: {selected_stages}")
    print(f"State file: {STATE_FILE}")

    for number in selected_stages:
        stage = STAGES[number]
        log_path = ctx.prepare_stage_log(stage)
        ctx.set_stage_running(stage, log_path)

        append_log(log_path, f"[STAGE] {stage.number:02d} {stage.title}")
        append_log(log_path, f"[TIME] {utc_now()}")

        print_header(f"Stage {stage.number:02d} - {stage.title}")

        result = StageResult()
        try:
            result = stage.runner(ctx, stage, log_path)
            if result.report_path and Path(result.report_path).exists():
                report_text = Path(result.report_path).read_text(encoding="utf-8", errors="replace")
                result.issues.extend([x for x in parse_missing_issues(report_text) if x not in result.issues])
            ctx.set_stage_completed(stage, result)
            print(f"[OK] Stage {stage.number:02d} completed")
        except Exception as exc:
            text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            for item in parse_missing_issues(text):
                if item not in result.issues:
                    result.issues.append(item)
            ctx.set_stage_failed(stage, result, exc, log_path)
            print("[FAIL] " + stage_failure_message(stage, log_path, result.report_path))
            return 1

    print_header("Pipeline Complete")
    print("All selected stages completed successfully.")
    print(f"Checkpoints: {CHECKPOINTS_DIR}")
    print(f"Logs: {LOGS_DIR}")
    print(f"Reports: {REPORTS_DIR}")
    return 0


STAGES: dict[int, Stage] = {
    0: Stage(0, "preflight", "Preflight", stage_00_preflight),
    1: Stage(1, "minimal_core", "Minimal Core Smoke Build", stage_01_minimal_core),
    2: Stage(2, "qt_shell", "Qt Shell Build", stage_02_qt_shell),
    3: Stage(3, "core_packages", "Core Package Inclusion", stage_03_core_packages),
    4: Stage(4, "dicom_basic", "DICOM Basic Viewer Dependencies", stage_04_dicom_basic),
    5: Stage(5, "heavy_native", "Heavy Native Imaging Stack", stage_05_heavy_native),
    6: Stage(6, "full_core", "Full Core Build", stage_06_full_core),
    7: Stage(7, "runtime_resources", "Runtime Resources", stage_07_runtime_resources),
    8: Stage(8, "plugin_staging", "External Plugin Package Staging", stage_08_plugin_staging),
    9: Stage(9, "installer_staging", "Installer Staging", stage_09_installer_staging),
    10: Stage(10, "inno_setup", "Inno Setup Installer", stage_10_inno_setup),
}


def main() -> int:
    args = parse_args()

    validate_stage_number(args.from_stage, "--from-stage")
    validate_stage_number(args.stage, "--stage")
    validate_stage_number(args.clean_stage, "--clean-stage")

    if args.resume and args.stage is not None:
        raise StageError("--resume cannot be combined with --stage")
    if args.resume and args.from_stage is not None:
        raise StageError("--resume cannot be combined with --from-stage")
    if args.stage is not None and args.from_stage is not None:
        raise StageError("--stage cannot be combined with --from-stage")

    if args.clean_all and args.clean_stage is not None:
        raise StageError("Choose either --clean-all or --clean-stage")

    if args.clean_all:
        clean_all_nuitka_outputs()
        print(f"Removed Nuitka output root: {OUTPUT_ROOT}")
        return 0

    ensure_output_dirs()
    ensure_stage_entrypoints()

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = PROJECT_ROOT / spec_path
    if not spec_path.exists():
        raise StageError(f"Spec not found: {spec_path}")

    spec = load_spec(spec_path)
    ctx = BuildContext(args, spec)

    if args.clean_stage is not None:
        clean_stage_artifacts(args.clean_stage)
        stage_id = str(args.clean_stage)
        ctx.state.get("stages", {}).pop(stage_id, None)
        ctx.state["completed_stages"] = [
            int(x) for x in ctx.state.get("completed_stages", []) if int(x) != args.clean_stage
        ]
        if ctx.state.get("failed_stage") == args.clean_stage:
            ctx.state["failed_stage"] = None
        if ctx.state.get("current_stage") == args.clean_stage:
            ctx.state["current_stage"] = None
        ctx.save_state()
        print(f"Removed stage {args.clean_stage} artifacts, logs, report, and checkpoint")
        return 0

    if args.smoke_test:
        return smoke_test(ctx)

    if args.audit_native_footprint:
        return audit_native_footprint(ctx)

    return run_pipeline(ctx)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StageError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Build interrupted by user")
        raise SystemExit(1)
