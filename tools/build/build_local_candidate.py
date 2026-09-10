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
    identity = {"version": version, "source_head": git(source, "rev-parse", "HEAD"),
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


def run_builds(workspace: Path, assets: Path, version: str, reuse_python_source: Path | None = None,
               final_repo: Path = REPO, brain_source: Path | None = None) -> int:
    root = workspace / "source"
    identity = json.loads((root / "build_source_manifest.json").read_text(encoding="utf-8"))
    if not identity.get("github_freshness_verified") or not identity.get("release_sync"):
        raise ValueError(
            "Canonical release builds require a verified multi-remote Git synchronization receipt"
        )
    if identity.get("version") != version:
        raise ValueError("Candidate Git synchronization version does not match the build")
    installer_dirs = canonical_installer_dirs(final_repo, version)
    status_path = workspace / "build_status.json"
    if status_path.exists():
        raise ValueError("This build workspace already has a run; preserve it and prepare a fresh candidate")
    status = {"version": version, "status": "running", "pid": os.getpid(), "published": False,
              "production_accepted": False, "backends": {name: {"status": "queued"} for name in ("python", "nuitka")}}

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
                   "--edition", "all", "--asset-root", str(assets)],
        "nuitka": [sys.executable, "-u", "builder nuitka/build_nuitka_release.py", "--release",
                   "--compiler", "msvc", "--edition", "all", "--asset-root", str(assets)],
    }
    if reuse_python_source is not None:
        commands["python"] = [sys.executable, "-u", "tools/build/repackage_candidate.py",
                              "--previous-source", str(reuse_python_source.resolve()), "--version", version]
    for name, command in commands.items():
        try:
            identity = json.loads((root / "build_source_manifest.json").read_text(encoding="utf-8"))
            source_matches = source_fingerprint(root) == identity["source_sha256"]
        except Exception:
            source_matches = False
        if not source_matches:
            status.update(status="failed", error="Candidate source drift detected")
            save_status()
            return 1
        record = {"status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                  "log": str(workspace / (name + ".log")), "command": command}
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
                        help="Defaults to generated-files/distribution-assets")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-prepared", action="store_true")
    parser.add_argument(
        "--git-sync-receipt",
        type=Path,
        help="Fresh receipt created by tools/git/release_manager.py publish",
    )
    parser.add_argument(
        "--internal",
        action="store_true",
        help="Build a non-promotable snapshot from the latest Developer Run source",
    )
    parser.add_argument("--backend", choices=("python", "nuitka"), default="python",
                        help="Internal lane only; default: python")
    parser.add_argument("--edition", choices=("standard", "eagle-eye", "arm"), default="standard",
                        help="Internal lane only; default: standard")
    parser.add_argument("--brain-source", type=Path,
                        help="Approved Eagle Eye Brain payload; auto-discovered when omitted")
    parser.add_argument("--reuse-python-source", type=Path, help="Repackage a matching, validated previous Python stage")
    parser.add_argument("--final-repo", type=Path, default=REPO,
                        help="Repository whose existing builder output/installer folders receive final files")
    args = parser.parse_args()
    version = args.version or current_version(REPO)
    workspace = (args.workspace or default_workspace(version, internal=args.internal)).resolve()
    assets = (args.asset_root or REPO / "generated-files/distribution-assets").resolve()
    if args.prepare_only and args.run_prepared:
        parser.error("Choose prepare-only or run-prepared")
    if args.internal and args.git_sync_receipt:
        parser.error("Internal snapshots do not use a release synchronization receipt")
    if not args.internal and not args.git_sync_receipt:
        parser.error("Canonical release builds require --git-sync-receipt")
    release_sync = None
    if args.git_sync_receipt:
        release_sync = validate_sync_receipt(args.git_sync_receipt.resolve(), REPO, version)
    brain_source = None
    if not args.internal or args.edition == "eagle-eye":
        brain_source = resolve_brain_source(args.brain_source, REPO)
        preflight_brain_payload(brain_source, for_distribution=not args.internal)
    if not args.run_prepared:
        if workspace.exists():
            raise ValueError("Build workspace already exists; use a fresh directory")
        create_snapshot(REPO, workspace / "source", version, release_sync=release_sync)
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
        args.final_repo.resolve(),
        brain_source,
    )


if __name__ == "__main__":
    raise SystemExit(main())
