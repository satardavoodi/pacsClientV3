"""Three explicit installer outputs from one frozen core; never publish automatically."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid


@dataclass(frozen=True)
class Edition:
    name: str
    include_slicer: bool
    include_offline_lumbar: bool
    install_package: str
    filename: str


EDITIONS = {
    "eagle-eye": Edition("eagle-eye", True, True, "x64", "ai-pacs eagle-eye"),
    "standard": Edition("standard", True, False, "x64", "ai-pacs standard"),
    "arm": Edition("arm", True, False, "x64_on_arm64", "ai-pacs arm64-emulated"),
}
DEFAULT_COMPACT_MAX_BYTES = 700_000_000
MAX_COMPILER_PATH = 240


def short_stage_root(output):
    configured = os.environ.get("AIPACS_PACKAGING_STAGE_ROOT")
    if configured:
        root = Path(configured).resolve()
    elif os.name == "nt":
        root = Path(Path(output).resolve().anchor) / "ap-stage"
    else:
        root = Path(tempfile.gettempdir()) / "ap-stage"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="r-", dir=root))


def validate_compiler_paths(source, destination):
    # Inno can fail while opening an existing file at MAX_PATH even when
    # Windows long-path support and Python's long-path support are enabled.
    for path in Path(source).rglob("*"):
        if len(str(destination / path.relative_to(source))) >= MAX_COMPILER_PATH:
            raise ValueError("Installer source path exceeds safe budget; choose a shorter AIPACS_PACKAGING_STAGE_ROOT")


def _sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _atomic_write(path, content):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_release_metadata(output, inventory):
    """Refresh the established installer-folder notes and checksum files."""
    output = Path(output)
    rows = inventory["outputs"]
    notes = [
        f"AIPacs {inventory['version']} Installation Notes",
        "=" * (len(inventory["version"]) + 27),
        "",
        f"Build backend: {inventory['backend']}",
        "Installers in this folder:",
    ]
    checksums = [
        f"AIPacs {inventory['version']} Installer SHA256 Checksums",
        "=" * (len(inventory["version"]) + 34),
        "",
    ]
    descriptions = {
        "eagle-eye": "Includes Slicer and the Eagle Eye Brain and Lumbar offline payloads.",
        "standard": "Includes the standard Advanced MPR/Slicer runtime without the Eagle Eye offline lumbar model.",
        "arm": "Includes the standard Advanced MPR/Slicer runtime for Windows on ARM64 emulation; not native ARM64.",
    }
    for index, row in enumerate(rows, start=1):
        filename = Path(row["installer"]).name
        notes.extend([f"{index}) {filename}", f"   {descriptions[row['edition']]}"])
        checksums.extend([filename, f"SHA256: {row['sha256'].upper()}", ""])
    notes.extend([
        "",
        "Installation:",
        '- Right-click the selected installer and choose "Run as administrator".',
        "- Complete the setup wizard, then verify the selected edition and optional modules.",
        "- Verify the file against SHA256.txt before transferring or installing it.",
        "",
        "Release safety:",
        "- All installers listed above were produced by one completed backend run.",
        "- Legacy installers still present in this folder are not part of this version manifest.",
        "- No installer was uploaded or published automatically.",
        "",
    ])
    note_text = "\n".join(notes)
    checksum_text = "\n".join(checksums + [f"Version: {inventory['version']}",
                                             f"Backend: {inventory['backend']}", ""])
    # Retain the established four filenames. Repository policy requires newly
    # generated release artifacts to remain English, including compatibility files.
    for name in ("INSTALL_NOTES.txt", "INSTALL_NOTES_FA.txt"):
        _atomic_write(output / name, note_text)
    for name in ("SHA256.txt", "SHA256_FA.txt"):
        _atomic_write(output / name, checksum_text)
    serialized = json.dumps(inventory, indent=2)
    _atomic_write(output / "distributions.json", serialized)
    metadata_name = ("nuitka_installer_release_metadata.json"
                     if inventory["backend"] == "nuitka" else "installer_release_metadata.json")
    _atomic_write(output / metadata_name, serialized)


def editions_for(name):
    if name == "all":
        return tuple(EDITIONS.values())
    return (EDITIONS[name],)


def _link_or_copy(source, destination):
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def _edition_copy_ignore(package_root, edition):
    """Skip edition-excluded large payloads before copytree starts reading them."""
    package_root = Path(package_root).resolve()
    advanced_payload = package_root / "payload"
    slicer_modules = (
        advanced_payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules"
    )

    def ignore(directory, names):
        if edition.include_offline_lumbar:
            return ()
        current = Path(directory).resolve()
        excluded = []
        if current == advanced_payload and "offline_lumbar" in names:
            excluded.append("offline_lumbar")
        if current == advanced_payload and "eagle_eye" in names:
            excluded.append("eagle_eye")
        if current == slicer_modules and "AIPacsOfflineLumbar.py" in names:
            excluded.append("AIPacsOfflineLumbar.py")
        return tuple(excluded)

    return ignore


def stage_edition(source, destination, edition, *, for_distribution=True):
    """Create a new isolated view; never write through linked core or package files."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("Edition staging must be separate from the input tree")
    if destination.exists():
        raise FileExistsError("Edition stage exists; use a new build run directory")
    destination.mkdir(parents=True)
    shutil.copytree(source / "core", destination / "core", copy_function=_link_or_copy)
    packages = destination / "plugin_packages"
    packages.mkdir()
    for path in (source / "plugin_packages").iterdir():
        if path.is_dir() and (edition.include_slicer or path.name != "advanced_mpr"):
            copy_options = {"copy_function": _link_or_copy}
            if path.name == "advanced_mpr":
                copy_options["ignore"] = _edition_copy_ignore(path, edition)
            shutil.copytree(path, packages / path.name, **copy_options)
    if edition.include_slicer and not edition.include_offline_lumbar:
        advanced_payload = packages / "advanced_mpr/payload"
        shutil.rmtree(advanced_payload / "offline_lumbar", ignore_errors=True)
        (advanced_payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsOfflineLumbar.py").unlink(
            missing_ok=True
        )
    feed_path = source / "plugin_packages/module_package_feed.json"
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    for entry in feed.get("packages", []):
        if entry.get("module_id") == "advanced_mpr" and not edition.include_slicer:
            entry.update(available=False, has_payload=False, archive_name="", archive_path="",
                         staged_package_path="", sha256="")
    (packages / feed_path.name).write_text(json.dumps(feed, indent=2), encoding="utf-8")
    manifest_dir = destination / "manifest"
    if (source / "manifest").exists():
        shutil.copytree(source / "manifest", manifest_dir)
    manifest_dir.mkdir(exist_ok=True)
    identity = {
        "edition": edition.name,
        "install_package": edition.install_package,
        "slicer_included": edition.include_slicer,
        "offline_lumbar_included": edition.include_offline_lumbar,
        "eagle_eye_features": ['brain', 'lumbar'] if edition.include_offline_lumbar else [],
        "model_task": "vertebrae_mr" if edition.include_offline_lumbar else None,
    }
    (manifest_dir / "distribution.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    release_manifest = manifest_dir / "release_manifest.json"
    if release_manifest.exists():
        release = json.loads(release_manifest.read_text(encoding="utf-8"))
        release["distribution"] = identity
        release["core_dir"] = str(destination / "core")
        release["module_packages"] = feed.get("packages", [])
        advanced_payload = release.setdefault("payloads", {}).setdefault("advanced_mpr", {})
        if isinstance(advanced_payload, dict):
            advanced_payload["staged"] = edition.include_slicer
            advanced_payload["offline_lumbar_staged"] = edition.include_offline_lumbar
            if edition.include_slicer and not edition.include_offline_lumbar:
                advanced_payload["reason"] = "Standard Slicer runtime included; Eagle Eye offline lumbar model excluded"
        release_manifest.write_text(json.dumps(release, indent=2), encoding="utf-8")
    profile = manifest_dir / "installation_profile.json"
    if profile.exists():
        data = json.loads(profile.read_text(encoding="utf-8"))
        data["distribution_edition"] = edition.name
        data["install_package"] = edition.install_package
        data.setdefault("modules", {})["advanced_mpr"] = edition.include_slicer
        profile.write_text(json.dumps(data, indent=2), encoding="utf-8")
    validate_edition(destination, edition, for_distribution=for_distribution)
    return destination


def validate_edition(stage, edition, *, for_distribution=True):
    core = stage / "core"
    if not (core / "AIPacs.exe").is_file():
        raise RuntimeError("Frozen core is missing")
    # The common core must never contain the separately packaged model/runtime.
    for path in core.rglob("*"):
        if path.is_file() and (path.name.lower() == "aipacsadvancedviewer.exe" or
                (path.suffix.lower() in {".pt", ".pth"} and path.stat().st_size > 1024**2)):
            raise RuntimeError("Heavy Slicer/model payload leaked into the shared core")
    payload = stage / "plugin_packages/advanced_mpr/payload"
    if edition.include_slicer:
        from builder.build_release import ADVANCED_MPR_REQUIRED_RUNTIME_FILES
        for name in ADVANCED_MPR_REQUIRED_RUNTIME_FILES:
            if not (payload / name).is_file():
                raise RuntimeError("Edition requires the complete Slicer runtime: " + name)
        modules = payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules"
        if not (modules / "AIPacsBackgroundRuntime.py").is_file():
            raise RuntimeError("Slicer resident integration is missing: AIPacsBackgroundRuntime.py")
        if edition.include_offline_lumbar:
            from builder.eagle_eye_brain_payload import validate_payload as validate_brain
            validate_brain(payload / 'eagle_eye/brain', for_distribution=for_distribution)
            from modules.ai_imaging.offline_lumbar.bundle import validate_bundle
            if not (modules / "AIPacsOfflineLumbar.py").is_file():
                raise RuntimeError("Eagle Eye Slicer integration is missing: AIPacsOfflineLumbar.py")
            validate_bundle(payload / "offline_lumbar")
        else:
            if (payload / 'eagle_eye').exists():
                raise RuntimeError('Standard editions must exclude Eagle Eye Brain assets')
            if (payload / "offline_lumbar").exists() or (modules / "AIPacsOfflineLumbar.py").exists():
                raise RuntimeError("Standard Slicer edition must exclude the Eagle Eye offline lumbar payload")
    elif payload.parent.exists():
        raise RuntimeError("Compact edition must not contain Advanced MPR or model payloads")


def compile_editions(builder, version, selection="all", *, stage_only=False,
                     compact_max_bytes=DEFAULT_COMPACT_MAX_BYTES,
                     for_distribution=True):
    """Require every selected output and place final files in the existing installer folder."""
    if compact_max_bytes <= 0:
        raise ValueError("Compact installer size budget must be positive")
    editions = editions_for(selection)
    output = Path(builder.INSTALLER_OUTPUT_DIR).resolve()
    expected = Path(
        getattr(builder, "EXPECTED_INSTALLER_OUTPUT_DIR", Path(builder.OUTPUT_DIR) / "installer")
    ).resolve()
    if output != expected:
        raise ValueError("Installer output must be the backend's existing output/installer folder")
    output.mkdir(parents=True, exist_ok=True)
    compiler = None if stage_only else builder.find_iscc()
    if not stage_only and compiler is None:
        raise RuntimeError("Inno Setup is required for all requested distribution outputs")
    artifacts = []
    stage_root = short_stage_root(output)
    compiler_output = stage_root / "compiled"
    compiler_output.mkdir()
    for edition in editions:
        destination = stage_root / edition.name
        stage = stage_edition(
            builder.STAGE_DIR,
            destination,
            edition,
            for_distribution=for_distribution,
        )
        if not stage_only:
            validate_compiler_paths(stage, destination)
        record = {"edition": edition.name, "stage": str(stage), "status": "staged"}
        if not stage_only:
            backend = getattr(builder, "BACKEND", "python")
            name = f"{edition.filename} v{version}"
            installer = (builder.INSTALLER_SCRIPT_WOA if edition.name == "arm" else builder.INSTALLER_SCRIPT)
            builder.run_command([str(compiler), f"/DMyAppVersion={version}", f"/DStageDir={stage}",
                                 f"/DInstallerOutputDir={compiler_output}", f"/DInstallerBaseName={name}",
                                 f"/DDistributionEdition={edition.name}",
                                 f"/DIncludeAdvancedMpr={int(edition.include_slicer)}",
                                 f"/DIncludeOfflineLumbar={int(edition.include_offline_lumbar)}", str(installer)],
                                cwd=builder.BUILDER_DIR / "installer")
            file = compiler_output / (name + ".exe")
            if not file.is_file() or file.stat().st_size == 0:
                raise RuntimeError("Compiler did not produce the required output: " + edition.name)
            size = file.stat().st_size
            if not edition.include_offline_lumbar and size > compact_max_bytes:
                raise RuntimeError(f"{edition.name} installer exceeds its {compact_max_bytes}-byte size budget ({size})")
            record.update(status="compiled", temporary_installer=str(file), bytes=size, sha256=_sha256(file))
        artifacts.append(record)
    if not stage_only:
        targets = [output / Path(row["temporary_installer"]).name for row in artifacts]
        existing = [path for path in targets if path.exists()]
        if existing:
            raise FileExistsError("Refusing to overwrite an existing versioned installer: " + existing[0].name)
        for row, target in zip(artifacts, targets):
            temporary_target = output / f".{target.name}.{uuid.uuid4().hex}.partial"
            shutil.copy2(row.pop("temporary_installer"), temporary_target)
            if _sha256(temporary_target) != row["sha256"]:
                temporary_target.unlink(missing_ok=True)
                raise RuntimeError("Installer changed while copying to the canonical output folder")
            temporary_target.replace(target)
            row["installer"] = str(target)
    inventory = {"version": version, "backend": getattr(builder, "BACKEND", "python"),
                 "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                 "status": "staged" if stage_only else "compiled",
                 "published": False, "compact_size_budget_bytes": compact_max_bytes, "outputs": artifacts}
    if stage_only:
        _atomic_write(stage_root / "distributions.json", json.dumps(inventory, indent=2))
        print("Temporary distribution stages: " + str(stage_root))
    else:
        _write_release_metadata(output, inventory)
        print("Installer outputs: " + str(output))
    return inventory
