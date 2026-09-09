"""Owned local processes. Call only from the Brain background worker."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from .contracts import BrainError

SYNTHSEG_REVISION = "2a2aa3bbfccb83f8253a51ca8b329b9938a2646d"


def bundle_root():
    configured = os.environ.get("AIPACS_BRAIN_BUNDLE")
    if configured:
        return Path(configured).resolve()
    from aipacs_runtime import user_data_root, modules_runtime_search_roots, is_frozen
    candidates = [user_data_root() / 'ai/eagle_eye/brain/model']
    from modules.ai_imaging.eagle_eye.assets import installed_feature_roots
    candidates.extend(root / 'model' for root in installed_feature_roots('brain'))
    candidates.extend(root / 'eagle_eye_brain/model' for root in modules_runtime_search_roots())
    for candidate in candidates:
        if (candidate / 'manifest.json').is_file():
            return candidate
    if not is_frozen():
        for parent in Path(__file__).resolve().parents:
            if (parent / ".git").exists():
                return development_bundle(parent)
    raise BrainError("The Eagle Eye Brain computation package is not installed. Contact your AI-PACS administrator.")


def development_bundle(repository):
    """Promote only the model-bound, full-inference-tested Windows candidate."""
    candidate = Path(repository) / 'generated-files/eagle-eye/brain-tf212-py310'
    if not candidate.exists():
        return Path(repository) / 'generated-files/brain-volumetry'
    try:
        probe = json.loads((candidate / 'runtime-probe.json').read_text(encoding='utf-8'))
        if (probe.get('status') != 'passed' or probe.get('inference_status') != 'passed' or
                probe.get('model_manifest_sha256') != sha256(candidate / 'model/manifest.json')):
            raise ValueError
    except (OSError, ValueError, TypeError):
        raise BrainError('The portable Brain candidate has not passed full inference or has changed.') from None
    return candidate / 'model'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_bundle(root):
    root = Path(root).resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest["revision"] != SYNTHSEG_REVISION or manifest["format_version"] not in (1, 2):
            raise ValueError
        executable = 'python/python.exe' if manifest['format_version'] == 2 else 'runtime/Scripts/python.exe'
        required = {"SynthSeg/scripts/commands/SynthSeg_predict.py", executable}
        if manifest['format_version'] == 2 and (root / 'python/pyvenv.cfg').exists():
            raise ValueError
        required.update("SynthSeg/models/" + name for name in
                        ("synthseg_2.0.h5", "synthseg_robust_2.0.h5", "synthseg_parc_2.0.h5", "synthseg_qc_2.0.h5"))
        files = manifest["sha256"]
        if not required.issubset(files):
            raise ValueError
        for relative, expected in files.items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or sha256(path) != expected:
                raise ValueError
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise BrainError("The brain model bundle is missing, incomplete or changed. Run the documented preparation step.") from None


def run_process(command, directory, cancel, *, timeout=1800, environment=None):
    """No shell, no patient paths in logs; terminate only this process tree."""
    if cancel.is_set():
        raise BrainError("Brain analysis cancelled.")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTHON", "QT_", "NEWMPR2_"))}
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="-1")
    env.update(environment or {})
    from modules.mpr.advanced_3d_slicer.owned_process import ProcessJob
    owner = ProcessJob()
    process = None
    log = None
    try:
        # Keep diagnostics with the private job, never in UI text or shared logs.
        log = (Path(directory) / 'process.log').open('ab')
        process = subprocess.Popen([str(part) for part in command], cwd=directory, env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        owner.assign(process)
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if cancel.wait(0.1):
                raise BrainError("Brain analysis cancelled.")
            if time.monotonic() > deadline:
                raise BrainError("The brain computation exceeded its time limit.")
        if cancel.is_set():
            raise BrainError("Brain analysis cancelled.")
        if process.returncode:
            raise BrainError(f"The local brain computation failed (exit code {process.returncode}). "
                             "Diagnostic details were saved with this analysis. Check model readiness and available memory.")
    finally:
        owner.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)
        if log is not None:
            log.close()


def synthseg_command(root, directory, plan):
    root, directory = Path(root).resolve(), Path(directory).resolve()
    manifest_path = root / 'manifest.json'
    version = json.loads(manifest_path.read_text(encoding='utf-8'))['format_version'] if manifest_path.is_file() else 1
    executable = root / ('python/python.exe' if version == 2 else 'runtime/Scripts/python.exe')
    command = [executable, "-E", "-s", "-B", root / "SynthSeg/scripts/commands/SynthSeg_predict.py",
               "--i", directory / "t1.nii.gz", "--o", directory / "labels.nii.gz",
               "--vol", directory / "posterior.csv", "--qc", directory / "qc.csv",
               "--resample", directory / "resampled.nii.gz", "--parc", "--cpu", "--threads", str(plan.threads)]
    if plan.profile == "robust":
        command.append("--robust")
    return command


def slicer_executable():
    from modules.mpr.advanced_3d_slicer.slicer_custom_app.launch_slicer import find_slicer_executable
    executable = find_slicer_executable()
    if not executable or not Path(executable).is_file():
        raise BrainError("The Advanced Analysis Slicer runtime is unavailable.")
    return Path(executable)


def run_slicer(directory, cancel, executable=None):
    script = Path(__file__).with_name("slicer_worker.py")
    run_process([executable or slicer_executable(), "--no-splash", "--launcher-no-splash", "--no-main-window",
                 "--disable-settings", "--ignore-slicerrc", "--launcher-ignore-user-additional-settings",
                 "--python-script", script], directory, cancel, timeout=300,
                environment={"AIPACS_BRAIN_JOB": str(directory)})
    try:
        result = json.loads((Path(directory) / "slicer_result.json").read_text(encoding="utf-8"))
        if result["status"] != "succeeded" or result["job_id"] != Path(directory).name:
            raise ValueError
        return result
    except (OSError, ValueError, KeyError):
        raise BrainError("Slicer did not confirm this analysis result.") from None
