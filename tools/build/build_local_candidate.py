"""Build AI-PACS installers from one isolated, content-addressed snapshot.

Never publishes, modifies the development checkout, or launches a workstation.
Status and logs live beside the snapshot, not inside its source tree.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from builder.config_sanitizer import build_clean_config_tree, scan_for_center_values
from builder.source_identity import file_hash, input_paths, source_fingerprint
from builder.build_process import run_logged_build
from tools.git.release_manager import validate_sync_receipt
from tools.build.prepare_distribution_assets import DEFAULT_ROOT as DEFAULT_ASSET_ROOT


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def current_version(root: Path = REPO) -> str:
    return str(
        tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    )


def default_workspace(version: str, *, internal: bool) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    lane = "internal" if internal else "release"
    return Path("C:/b") / f"aipacs-{lane}-{version}-{stamp}"


def resolve_brain_source(configured: Path | None, root: Path = REPO) -> Path:
    if configured is not None:
        return configured.resolve()
    environment = os.environ.get("AIPACS_EAGLE_EYE_BRAIN_SOURCE", "").strip()
    if environment:
        return Path(environment).resolve()
    return (root / "generated-files/eagle-eye/brain-tf212-py310").resolve()


def resolve_lesion_source(root: Path = REPO) -> Path:
    configured = os.environ.get('AIPACS_EAGLE_EYE_LESION_SOURCE', '').strip()
    return Path(configured).resolve() if configured else (root / 'generated-files/eagle-eye/brain-lesions').resolve()


def resolve_alignment_source(root: Path = REPO) -> Path:
    configured = os.environ.get("AIPACS_EAGLE_EYE_ALIGNMENT_SOURCE", "").strip()
    return (
        Path(configured).resolve()
        if configured
        else (root / "generated-files/eagle-eye/alignment").resolve()
    )


def resolve_total_spine_source(root: Path = REPO) -> Path:
    configured = os.environ.get("AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE", "").strip()
    return (
        Path(configured).resolve()
        if configured
        else (root / "generated-files/eagle-eye/total-spine").resolve()
    )


def preflight_lesion_payload(*, for_distribution: bool) -> None:
    from builder.eagle_eye_lesion_payload import validate_payload
    validate_payload(resolve_lesion_source(), for_distribution=for_distribution)


def preflight_alignment_payload(*, for_distribution: bool) -> None:
    from builder.eagle_eye_alignment_payload import validate_payload

    validate_payload(resolve_alignment_source(), for_distribution=for_distribution)


def preflight_total_spine_payload(*, for_distribution: bool) -> None:
    from builder.eagle_eye_total_spine_payload import validate_payload

    validate_payload(resolve_total_spine_source(), for_distribution=for_distribution)


def preflight_server_service_dependencies(asset_root: Path) -> None:
    """Reject a Server freeze without real pywin32 build and offline inputs.

    This is a build-input gate, not installed Session 0 service qualification.
    """
    from importlib import metadata, util

    required_version = "311"
    manifest = json.loads((asset_root / "manifest.json").read_text(encoding="utf-8"))
    files = {item.get("path") for item in manifest.get("files", [])}
    wheel_prefix = f"build-wheels/pywin32-{required_version}-"
    if not any(isinstance(name, str) and name.startswith(wheel_prefix)
               and name.endswith("-win_amd64.whl") for name in files):
        raise RuntimeError(
            "Eagle Eye Server build cache needs a pywin32 311 wheel; "
            "pywin32-ctypes is not a substitute. Prepare a new immutable dependency cache."
        )
    lock = (asset_root / "build-environment.lock").read_text(encoding="utf-8")
    hashed = (asset_root / "build-wheels-hashed.lock").read_text(encoding="utf-8")
    if f"pywin32=={required_version}" not in lock.splitlines() or not any(
        line.startswith(f"pywin32=={required_version} --hash=sha256:")
        for line in hashed.splitlines()
    ):
        raise RuntimeError(
            "Eagle Eye Server cache must pin pywin32 311 in its environment and hashed wheel locks."
        )
    try:
        installed = metadata.version("pywin32")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "Eagle Eye Server build environment needs pywin32 311; "
            "pywin32-ctypes is not a substitute."
        ) from exc
    if installed != required_version:
        raise RuntimeError(f"Eagle Eye Server needs pywin32 {required_version}, found {installed}.")
    required_imports = (
        "servicemanager", "win32service", "win32serviceutil", "win32crypt",
        "win32security", "pywintypes",
    )
    missing = [name for name in required_imports if util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            "Eagle Eye Server build environment lacks pywin32 service/DPAPI modules: "
            + ", ".join(missing)
        )


def preflight_brain_payload(source: Path, *, for_distribution: bool) -> None:
    """Fail before any core compilation when the requested Brain payload cannot ship."""
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"Eagle Eye Brain payload is missing: {source}")
    approval = source / "distribution-approval.json"
    if for_distribution and not approval.is_file():
        raise ValueError(
            "Eagle Eye Brain release approval is missing. No compilation was started. "
            f"Expected: {approval}. Complete the evidence described in "
            "docs/modules/EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md; do not bypass this gate."
        )
    from builder.eagle_eye_brain_payload import validate_payload

    validate_payload(source, for_distribution=for_distribution)


def create_snapshot(
    source: Path,
    destination: Path,
    version: str,
    release_sync: dict | None = None,
    build_target: str = "client",
) -> dict:
    source, destination = source.resolve(), destination.absolute()
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Snapshot destination must be new and separate from the source")
    actual = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if actual != version:
        raise ValueError("Requested version does not match the current source")
    names = input_paths(source)
    original = {}
    destination.mkdir(parents=True)
    for name in names:
        path = source / name
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents) if p != source.parent):
            raise ValueError("Snapshot input traverses a filesystem link")
        if not path.resolve().is_relative_to(source):
            raise ValueError("Snapshot input escapes the source")
        original[name] = file_hash(path)
        if name.startswith("config/"):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if file_hash(target) != original[name]:
            raise RuntimeError("Source changed during snapshot copy; retry after edits finish")
    # Config is transformed only in the isolated candidate, never in Developer Run.
    config_source = source / "config"
    for path in config_source.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Configuration contains a filesystem link")
    build_clean_config_tree(config_source, destination / "config")
    if scan_for_center_values(destination / "config"):
        raise RuntimeError("Sanitized candidate configuration failed the privacy gate")
    if input_paths(source) != names or any(file_hash(source / n) != h for n, h in original.items()):
        raise RuntimeError("Source changed while copying; snapshot was not approved for building")
    # Local audit commit only: deliberately no remote, push, tag, or copied history.
    git(destination, "init", "--initial-branch=beta-version")
    git(destination, "config", "core.autocrlf", "false")
    git(destination, "config", "user.name", "AI-PACS Local Build")
    git(destination, "config", "user.email", "local-build@invalid.example")
    git(destination, "add", "--all")
    git(destination, "commit", "-m", f"Local source snapshot for {version} installer verification")
    identity = {"version": version, "build_target": build_target,
                "source_head": git(source, "rev-parse", "HEAD"),
                "source_branch": git(source, "branch", "--show-current"),
                "candidate_commit": git(destination, "rev-parse", "HEAD"),
                "source_sha256": source_fingerprint(destination),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "developer_run_accepted": True, "production_accepted": False,
                "github_freshness_verified": release_sync is not None,
                "source_published": release_sync is not None,
                "published": False,
                "release_sync": release_sync,
                "configuration": "sanitized defaults; developer configuration unchanged",
                "files": [{"path": n, "sha256": file_hash(destination / n)}
                          for n in input_paths(destination)]}
    (destination / "build_source_manifest.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    git(destination, "add", "build_source_manifest.json")
    git(destination, "commit", "-m", "Record local candidate source provenance and exclusions")
    return identity


def canonical_installer_dirs(final_repo: Path, version: str) -> dict[str, Path]:
    """Return only the two established repository installer destinations."""
    final_repo = final_repo.resolve()
    project_file = final_repo / "pyproject.toml"
    if not project_file.is_file():
        raise ValueError("Final repository does not contain pyproject.toml")
    actual = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]["version"]
    if actual != version:
        raise ValueError("Final repository version does not match the requested build")
    result = {
        "python": (final_repo / "builder/output/installer").resolve(),
        "nuitka": (final_repo / "builder nuitka/output/installer").resolve(),
    }
    expected = {
        "python": Path("builder/output/installer"),
        "nuitka": Path("builder nuitka/output/installer"),
    }
    for name, path in result.items():
        if path.relative_to(final_repo) != expected[name]:
            raise ValueError("Installer destination escaped the established repository layout")
    return result


def expected_release_installers(final_repo: Path, version: str,
                                target: str = "client") -> dict[str, list[str]]:
    """Return only the selected role's canonical deliverables."""
    directories = canonical_installer_dirs(final_repo, version)
    filenames_by_target = {
        "client": (f"ai-pacs standard v{version}.exe",
                   f"ai-pacs arm64-emulated v{version}.exe"),
        "server": (f"ai-pacs eagle-eye v{version}.exe",),
        # Historical six-output candidates can still be resumed, not newly selected.
        "all": (f"ai-pacs eagle-eye v{version}.exe",
                f"ai-pacs standard v{version}.exe",
                f"ai-pacs arm64-emulated v{version}.exe"),
    }
    filenames = filenames_by_target[target]
    return {
        backend: [str(directory / filename) for filename in filenames]
        for backend, directory in directories.items()
    }


def _pid_is_alive(pid: object) -> bool:
    try:
        value = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except OSError:
        return False
    return True


def _recorded_python_reuse_source(status: dict) -> Path | None:
    configured = status.get("reuse_python_source")
    if configured:
        return Path(str(configured)).resolve()
    command = status.get("backends", {}).get("python", {}).get("command", [])
    if isinstance(command, list) and "--previous-source" in command:
        index = command.index("--previous-source") + 1
        if index < len(command):
            return Path(str(command[index])).resolve()
    return None


def _completed_backend_outputs_exist(status: dict, backend: str) -> bool:
    paths = status.get("expected_release_installers", {}).get(backend, [])
    expected_count = {"client": 2, "server": 1, "all": 3}[
        status.get("build_target", "all")
    ]
    return len(paths) == expected_count and all(Path(path).is_file() for path in paths)


_BACKEND_INSTALLER_METADATA = {
    "python": (
        "distributions-client.json",
        "distributions.json",
        "INSTALL_NOTES_FA.txt",
        "INSTALL_NOTES-client.txt",
        "INSTALL_NOTES.txt",
        "installer_release_metadata.json",
        "SHA256_FA.txt",
        "SHA256-client.txt",
        "SHA256.txt",
    ),
    "nuitka": (
        "distributions.json",
        "INSTALL_NOTES_FA.txt",
        "INSTALL_NOTES.txt",
        "nuitka_installer_release_metadata.json",
        "SHA256_FA.txt",
        "SHA256.txt",
    ),
}


def archive_existing_local_qa_outputs(status: dict, backend: str) -> list[dict[str, str]]:
    """Preserve an earlier same-version QA candidate before rebuilding it.

    Production candidates remain immutable. This recovery is limited to the
    explicitly non-promotable local install-QA lane and moves only the selected
    role's exact installer names plus that backend's top-level metadata.
    """
    if status.get("lane") != "local-install-qa":
        return []
    expected = [Path(path).resolve() for path in
                status.get("expected_release_installers", {}).get(backend, [])]
    if not expected:
        return []
    output_dir = expected[0].parent
    if any(path.parent != output_dir for path in expected):
        raise ValueError("Recorded installer outputs do not share one canonical folder")
    candidates = [path for path in expected if path.is_file()]
    candidates.extend(
        path for name in _BACKEND_INSTALLER_METADATA[backend]
        if (path := output_dir / name).is_file()
    )
    if not candidates:
        return []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = output_dir / "_superseded" / f"local-qa-{status['version']}-{stamp}-{backend}"
    suffix = 1
    while archive.exists():
        suffix += 1
        archive = output_dir / "_superseded" / (
            f"local-qa-{status['version']}-{stamp}-{backend}-{suffix}"
        )
    archive.mkdir(parents=True)
    moved = []
    for source in candidates:
        destination = archive / source.name
        source.replace(destination)
        moved.append({"source": str(source), "archive": str(destination)})
    return moved


def run_builds(workspace: Path, assets: Path, version: str, reuse_python_source: Path | None = None,
               final_repo: Path = REPO, brain_source: Path | None = None,
               local_install_qa: bool = False, resume: bool = False,
               target: str = "client") -> int:
    if target not in {"client", "server", "all"}:
        raise ValueError("Build target must be client or server")
    if target == "server" and not local_install_qa:
        raise ValueError(
            "Eagle Eye Server is not qualified for release: portable Breast/Bone bundles, "
            "service installation and clean-host acceptance are pending. "
            "Use --local-install-qa --target server for a non-promotable installer candidate."
        )
    if target == "server" and reuse_python_source is not None:
        raise ValueError("Server model payloads cannot reuse an older Python stage")
    root = workspace / "source"
    identity = json.loads((root / "build_source_manifest.json").read_text(encoding="utf-8"))
    if local_install_qa:
        if identity.get("github_freshness_verified") or identity.get("release_sync"):
            raise ValueError("Local install-QA builds require a non-promotable internal snapshot")
    elif not identity.get("github_freshness_verified") or not identity.get("release_sync"):
        raise ValueError(
            "Canonical release builds require a verified multi-remote Git synchronization receipt"
        )
    if identity.get("version") != version:
        raise ValueError("Candidate Git synchronization version does not match the build")
    if identity.get("build_target") and identity["build_target"] != target:
        raise ValueError("Candidate snapshot build target does not match the requested role")
    installer_dirs = canonical_installer_dirs(final_repo, version)
    status_path = workspace / "build_status.json"
    if status_path.exists() and not resume:
        raise ValueError("This build workspace already has a run; preserve it and prepare a fresh candidate")
    if resume:
        if not status_path.is_file():
            raise ValueError("Resume workspace has no build_status.json")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        expected_lane = "local-install-qa" if local_install_qa else "release-candidate"
        if (status.get("version") != version or status.get("lane") != expected_lane
                or status.get("build_target", "all") != target):
            raise ValueError("Resume workspace version, lane or build target does not match")
        for backend, record in status.get("backends", {}).items():
            if record.get("status") == "running" and _pid_is_alive(record.get("pid")):
                raise ValueError(f"Cannot resume while the recorded {backend} build process is still active")
        status["status"] = "recovering"
        status["pid"] = os.getpid()
        status["recovery_started_at_utc"] = datetime.now(timezone.utc).isoformat()
    else:
        status = {"version": version, "status": "running", "pid": os.getpid(),
                  "build_target": target,
                  "lane": "local-install-qa" if local_install_qa else "release-candidate",
                  "published": False, "distribution_approved": not local_install_qa,
                  "production_accepted": False,
                  "asset_root": str(assets.resolve()),
                  "brain_source": str(brain_source.resolve()) if brain_source else None,
                  "reuse_python_source": str(reuse_python_source.resolve()) if reuse_python_source else None,
                  "expected_release_installers": expected_release_installers(final_repo, version, target),
                  "backends": {name: {"status": "queued"} for name in ("python", "nuitka")}}
    if resume and reuse_python_source is None:
        reuse_python_source = _recorded_python_reuse_source(status)
    status["expected_release_installers"] = expected_release_installers(final_repo, version, target)

    def save_status():
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(status, indent=2), encoding="utf-8")
        temporary.replace(status_path)
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONPATH=str(root),
               GCM_INTERACTIVE="Never", GIT_TERMINAL_PROMPT="0", QT_QPA_PLATFORM="offscreen")
    env["AIPACS_PY_INSTALLER_OUTPUT_DIR"] = str(installer_dirs["python"])
    env["AIPACS_NUITKA_INSTALLER_OUTPUT_DIR"] = str(installer_dirs["nuitka"])
    env["AIPACS_PY_EXPECTED_INSTALLER_OUTPUT_DIR"] = str(installer_dirs["python"])
    env["AIPACS_NUITKA_EXPECTED_INSTALLER_OUTPUT_DIR"] = str(installer_dirs["nuitka"])
    # Candidate compilation never uploads application updates. Publication is a
    # separate, explicitly authorized operation after signing and install QA.
    env["AIPACS_UPDATE_REMOTE_PUBLISH"] = "0"
    if brain_source is not None:
        env["AIPACS_EAGLE_EYE_BRAIN_SOURCE"] = str(brain_source.resolve())
    env['AIPACS_EAGLE_EYE_LESION_SOURCE'] = str(resolve_lesion_source(final_repo))
    env["AIPACS_EAGLE_EYE_ALIGNMENT_SOURCE"] = str(resolve_alignment_source(final_repo))
    env["AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE"] = str(resolve_total_spine_source(final_repo))
    status["eagle_eye_external_sources"] = {
        "brain": env.get("AIPACS_EAGLE_EYE_BRAIN_SOURCE"),
        "brain_lesions": env["AIPACS_EAGLE_EYE_LESION_SOURCE"],
        "alignment": env["AIPACS_EAGLE_EYE_ALIGNMENT_SOURCE"],
        "total_spine": env["AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE"],
    }
    workspace_anchor = Path(workspace.resolve().anchor)
    packaging_stage_root = (workspace_anchor / "ap-stage" if workspace_anchor
                            else workspace.resolve().parent / "ap-stage")
    env["AIPACS_PACKAGING_STAGE_ROOT"] = str(packaging_stage_root)
    status["installer_output_dirs"] = {name: str(path) for name, path in installer_dirs.items()}
    status["packaging_stage_root"] = str(packaging_stage_root)
    # Do not inherit a developer's old release bypass or debug override.
    for name in list(env):
        if name.startswith("AIPACS_SKIP_") or name.startswith("AIPACS_ALLOW_"):
            env.pop(name)
    commands = {
        "python": [sys.executable, "-u", "builder/build_release.py", "--clean-build",
                   "--edition", target, "--asset-root", str(assets)],
        "nuitka": [sys.executable, "-u", "builder nuitka/build_nuitka_release.py", "--release",
                   "--compiler", "msvc", "--edition", target, "--asset-root", str(assets)],
    }
    if local_install_qa:
        commands["python"].insert(3, "--internal-build")
        commands["nuitka"].insert(3, "--internal-build")
    if reuse_python_source is not None:
        commands["python"] = [sys.executable, "-u", "tools/build/repackage_candidate.py",
                              "--previous-source", str(reuse_python_source.resolve()), "--version", version,
                              "--edition", target]
    try:
        identity = json.loads((root / "build_source_manifest.json").read_text(encoding="utf-8"))
        source_matches = source_fingerprint(root) == identity["source_sha256"]
    except Exception:
        source_matches = False
    if not source_matches:
        status.update(status="failed", error="Candidate source drift detected")
        save_status()
        return 1
    for name, command in commands.items():
        previous_record = dict(status.get("backends", {}).get(name, {}) or {})
        if (
            previous_record.get("status") == "completed"
            and previous_record.get("exit_code") == 0
            and _completed_backend_outputs_exist(status, name)
        ):
            print(f"Reusing completed {name} backend from this immutable candidate.", flush=True)
            continue
        superseded_outputs = archive_existing_local_qa_outputs(status, name)
        if resume and name == "nuitka" and (root / "builder nuitka/output/build_state.json").is_file():
            nuitka_state_path = root / "builder nuitka/output/build_state.json"
            nuitka_state = json.loads(nuitka_state_path.read_text(encoding="utf-8"))
            release_stages = {0, 6, 7, 8, 9, 10}
            interrupted_stage = nuitka_state.get("current_stage")
            if interrupted_stage is not None:
                interrupted_stage = int(interrupted_stage)
                if interrupted_stage not in release_stages:
                    raise ValueError("Interrupted Nuitka stage is outside the release pipeline")
                stage_record = nuitka_state.setdefault("stages", {}).setdefault(
                    str(interrupted_stage), {}
                )
                stage_record.update(
                    status="failed",
                    error="Recorded build process ended before the stage completed",
                    finished_at_utc=datetime.now(timezone.utc).isoformat(),
                )
                nuitka_state["failed_stage"] = interrupted_stage
                nuitka_state["current_stage"] = None
                temporary_state = nuitka_state_path.with_suffix(".tmp")
                temporary_state.write_text(json.dumps(nuitka_state, indent=2), encoding="utf-8")
                temporary_state.replace(nuitka_state_path)
            failed_stage = nuitka_state.get("failed_stage")
            if failed_stage is None or int(failed_stage) not in release_stages:
                raise ValueError("Nuitka resume has no failed release-pipeline stage")
            # The backend's --release switch means "fresh complete run" and is
            # intentionally incompatible with --resume. The validated failed
            # stage above keeps this recovery inside the release-stage set.
            command = [item for item in command if item != "--release"]
            command.append("--resume")
        attempts = list(previous_record.get("attempts", []))
        if previous_record.get("started_at_utc"):
            attempts.append({key: value for key, value in previous_record.items() if key != "attempts"})
        record = {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                  "log": str(workspace / (name + ".log")), "command": command,
                  "attempts": attempts}
        if superseded_outputs:
            record["superseded_outputs"] = superseded_outputs
        status["backends"][name] = record
        save_status()
        print(f"Starting {name} {version}: {record['log']}", flush=True)
        def started(pid):
            record["pid"] = pid
            save_status()
        try:
            rc = run_logged_build(command, cwd=root, env=env, log_path=Path(record["log"]), on_start=started)
        except Exception as exc:
            rc = 1
            record["supervisor_error"] = type(exc).__name__
        record.update(status="completed" if rc == 0 else "failed", exit_code=rc,
                      finished_at_utc=datetime.now(timezone.utc).isoformat())
        save_status()
        if rc != 0:
            for queued_name, queued_record in status["backends"].items():
                if queued_record.get("status") == "queued":
                    status["backends"][queued_name] = {
                        "status": "skipped",
                        "reason": f"required {name} backend failed",
                    }
            status["status"] = "failed"
            save_status()
            return 1
    status["status"] = "completed" if all(r["exit_code"] == 0 for r in status["backends"].values()) else "failed"
    if status["status"] == "completed":
        status["status"] = "verifying_coherence"
        save_status()
        py_stage = ((reuse_python_source / "builder/output/stage") if reuse_python_source else
                    (root / "builder/output/stage"))
        try:
            rc = run_logged_build([sys.executable, "builder/scripts/check_build_coherence.py",
                                   "--py-stage", str(py_stage), "--require-stage6-report"],
                                  cwd=root, env=env, log_path=workspace / "coherence.log", timeout_seconds=300)
        except Exception as exc:
            rc = 1
            status["coherence_error"] = type(exc).__name__
        status["coherence_exit_code"] = rc
        status["status"] = "failed" if rc else "completed"
    save_status()
    return 0 if status["status"] == "completed" else 1


def run_internal_build(
    workspace: Path,
    assets: Path,
    version: str,
    *,
    backend: str = "python",
    edition: str = "standard",
    brain_source: Path | None = None,
) -> int:
    """Run one non-promotable packaging check entirely inside its snapshot."""
    print(
        "DIAGNOSTIC ONLY: this run does not satisfy a full build request and will not "
        "update the repository installer folders.",
        flush=True,
    )
    root = workspace / "source"
    status_path = workspace / "build_status.json"
    if status_path.exists():
        raise ValueError("This build workspace already has a run; preserve it and prepare a fresh candidate")
    identity = json.loads((root / "build_source_manifest.json").read_text(encoding="utf-8"))
    if identity.get("version") != version or identity.get("github_freshness_verified"):
        raise ValueError("Internal build requires a matching non-release snapshot")
    if source_fingerprint(root) != identity.get("source_sha256"):
        raise ValueError("Candidate source drift detected")

    env = dict(
        os.environ,
        PYTHONUNBUFFERED="1",
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        PYTHONPATH=str(root),
        GCM_INTERACTIVE="Never",
        GIT_TERMINAL_PROMPT="0",
        QT_QPA_PLATFORM="offscreen",
        AIPACS_UPDATE_REMOTE_PUBLISH="0",
    )
    for name in list(env):
        if name.startswith("AIPACS_SKIP_") or name.startswith("AIPACS_ALLOW_"):
            env.pop(name)
    if brain_source is not None:
        env["AIPACS_EAGLE_EYE_BRAIN_SOURCE"] = str(brain_source.resolve())
        env['AIPACS_EAGLE_EYE_LESION_SOURCE'] = str(resolve_lesion_source(REPO))
        env["AIPACS_EAGLE_EYE_ALIGNMENT_SOURCE"] = str(resolve_alignment_source(REPO))
        env["AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE"] = str(resolve_total_spine_source(REPO))

    commands = {
        "python": [
            sys.executable,
            "-u",
            "builder/build_release.py",
            "--internal-build",
            "--clean-build",
            "--edition",
            edition,
            "--asset-root",
            str(assets),
        ],
        "nuitka": [
            sys.executable,
            "-u",
            "builder nuitka/build_nuitka_release.py",
            "--internal-build",
            "--release",
            "--compiler",
            "msvc",
            "--edition",
            edition,
            "--asset-root",
            str(assets),
        ],
    }
    command = commands[backend]
    log_path = workspace / f"{backend}.log"
    status = {
        "version": version,
        "lane": "internal",
        "backend": backend,
        "edition": edition,
        "status": "running",
        "published": False,
        "production_accepted": False,
        "source": str(root),
        "installer_output": str(
            root / ("builder/output/installer" if backend == "python" else "builder nuitka/output/installer")
        ),
        "log": str(log_path),
        "command": command,
    }

    def save_status() -> None:
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(status, indent=2), encoding="utf-8")
        temporary.replace(status_path)

    save_status()
    try:
        rc = run_logged_build(command, cwd=root, env=env, log_path=log_path)
    except Exception as exc:
        rc = 1
        status["supervisor_error"] = type(exc).__name__
    status["exit_code"] = rc
    status["status"] = "completed" if rc == 0 else "failed"
    status["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_status()
    return rc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, help="Defaults to a new timestamped C:\\b workspace")
    parser.add_argument("--version", help="Defaults to the version in pyproject.toml")
    parser.add_argument("--asset-root", type=Path,
                        help="Defaults to the current native-Slicer shared distribution asset cache")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-prepared", action="store_true")
    parser.add_argument(
        "--resume-workspace",
        type=Path,
        help="Resume the recorded failed full candidate in this existing C:\\b workspace",
    )
    parser.add_argument(
        "--target", choices=("client", "server"),
        help="Full build role: client makes Standard and ARM; server makes Eagle Eye. Default: client.",
    )
    parser.add_argument(
        "--git-sync-receipt",
        type=Path,
        help="Fresh receipt created by tools/git/release_manager.py publish",
    )
    parser.add_argument(
        "--internal",
        action="store_true",
        help=(
            "Explicit single-package diagnostic only; does not satisfy a full build request "
            "or update canonical installer folders"
        ),
    )
    parser.add_argument(
        "--local-install-qa",
        action="store_true",
        help=(
            "Build the selected role in both backends into the two canonical repository folders "
            "for local QA without asserting Git publication or redistribution approval"
        ),
    )
    parser.add_argument("--backend", choices=("python", "nuitka"), default="python",
                        help="Internal lane only; default: python")
    parser.add_argument("--edition", choices=("standard", "eagle-eye", "arm"), default="standard",
                        help="Internal lane only; default: standard")
    parser.add_argument("--brain-source", type=Path,
                        help="Approved Eagle Eye Brain payload; auto-discovered when omitted")
    parser.add_argument("--reuse-python-source", type=Path, help="Repackage a matching, validated previous Python stage")
    args = parser.parse_args()
    if args.resume_workspace:
        if any((args.workspace, args.prepare_only, args.run_prepared, args.internal,
                args.local_install_qa, args.git_sync_receipt, args.reuse_python_source)):
            parser.error("--resume-workspace cannot be combined with a new-build or lane option")
        if args.target:
            parser.error("Resume uses the build target recorded in its workspace")
        workspace = args.resume_workspace.resolve()
        status_path = workspace / "build_status.json"
        manifest_path = workspace / "source/build_source_manifest.json"
        if not status_path.is_file() or not manifest_path.is_file():
            parser.error("Resume workspace must contain build_status.json and source/build_source_manifest.json")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        identity = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = args.version or str(identity.get("version") or "")
        if not version or version != current_version(REPO):
            parser.error("Resume candidate version must match the current repository version")
        local_install_qa = status.get("lane") == "local-install-qa"
        if status.get("lane") not in {"local-install-qa", "release-candidate"}:
            parser.error("Only a recorded role-selected candidate can be resumed")
        target = status.get("build_target", "all")
        if target not in {"client", "server", "all"}:
            parser.error("Resume workspace has an invalid build target")
        recorded_assets = Path(status.get("asset_root") or DEFAULT_ASSET_ROOT).resolve()
        assets = (args.asset_root or recorded_assets).resolve()
        if assets != recorded_assets:
            parser.error("Resume asset root must match the original candidate")
        recorded_brain = status.get("brain_source")
        brain_source = (resolve_brain_source(
            Path(recorded_brain) if recorded_brain else args.brain_source, REPO,
        ) if target in {"server", "all"} else None)
        if recorded_brain and args.brain_source and brain_source != Path(recorded_brain).resolve():
            parser.error("Resume Brain source must match the original candidate")
        if target in {"server", "all"}:
            preflight_server_service_dependencies(assets)
            preflight_brain_payload(brain_source, for_distribution=not local_install_qa)
            preflight_lesion_payload(for_distribution=not local_install_qa)
            preflight_alignment_payload(for_distribution=not local_install_qa)
            preflight_total_spine_payload(for_distribution=not local_install_qa)
        recorded_reuse = _recorded_python_reuse_source(status)
        return run_builds(
            workspace,
            assets,
            version,
            recorded_reuse,
            REPO,
            brain_source,
            local_install_qa=local_install_qa,
            resume=True,
            target=target,
        )
    version = args.version or current_version(REPO)
    workspace = (
        args.workspace
        or default_workspace(version, internal=args.internal or args.local_install_qa)
    ).resolve()
    assets = (args.asset_root or DEFAULT_ASSET_ROOT).resolve()
    if args.prepare_only and args.run_prepared:
        parser.error("Choose prepare-only or run-prepared")
    target = args.target or "client"
    if args.run_prepared:
        prepared = workspace / "source/build_source_manifest.json"
        if not prepared.is_file():
            parser.error("Prepared workspace has no source manifest")
        recorded_target = json.loads(prepared.read_text(encoding="utf-8")).get("build_target", "all")
        if args.target and args.target != recorded_target:
            parser.error("Prepared workspace build target cannot be changed")
        target = recorded_target
    if args.internal and args.target:
        parser.error("--target selects a two-backend build; use --edition for a diagnostic")
    if args.internal and args.local_install_qa:
        parser.error("Choose --internal or --local-install-qa")
    if args.internal and args.git_sync_receipt:
        parser.error("Internal snapshots do not use a release synchronization receipt")
    if args.local_install_qa and args.git_sync_receipt:
        parser.error("Local install-QA builds do not use a release synchronization receipt")
    if not args.internal and not args.local_install_qa and not args.git_sync_receipt:
        parser.error("Canonical release builds require --git-sync-receipt")
    if not args.internal and target == "server" and not args.local_install_qa:
        parser.error("Eagle Eye Server is not release-qualified; use --local-install-qa --target server")
    release_sync = None
    if args.git_sync_receipt:
        release_sync = validate_sync_receipt(args.git_sync_receipt.resolve(), REPO, version)
    brain_source = None
    if (not args.internal and target == "server") or (args.internal and args.edition == "eagle-eye"):
        preflight_server_service_dependencies(assets)
        brain_source = resolve_brain_source(args.brain_source, REPO)
        preflight_brain_payload(
            brain_source,
            for_distribution=not (args.internal or args.local_install_qa),
        )
        preflight_lesion_payload(for_distribution=not (args.internal or args.local_install_qa))
        preflight_alignment_payload(for_distribution=not (args.internal or args.local_install_qa))
        preflight_total_spine_payload(for_distribution=not (args.internal or args.local_install_qa))
    if not args.run_prepared:
        from builder.slicer_runtime_payload import verify_cache_matches_developer_runtime

        verify_cache_matches_developer_runtime(REPO, assets)
        if workspace.exists():
            raise ValueError("Build workspace already exists; use a fresh directory")
        create_snapshot(REPO, workspace / "source", version, release_sync=release_sync,
                        build_target=target)
        print(f"Prepared isolated candidate: {workspace}")
    if args.prepare_only:
        return 0
    if args.internal:
        return run_internal_build(
            workspace,
            assets,
            version,
            backend=args.backend,
            edition=args.edition,
            brain_source=brain_source,
        )
    return run_builds(
        workspace,
        assets,
        version,
        args.reuse_python_source,
        REPO,
        brain_source,
        local_install_qa=args.local_install_qa,
        target=target,
    )


if __name__ == "__main__":
    raise SystemExit(main())
