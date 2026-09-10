"""Recover installation packaging without recompiling an unchanged verified core."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from builder.source_identity import file_hash


def core_input(name):
    first = name.split("/", 1)[0]
    return (first in {"PacsClient", "modules", "database", "config", "Qss", "Fonts",
                      "graphics_runtime", "json-styles", "hooks", "diagnostic_hooks"}
            or name.startswith(("builder/spec/", "generated-files/css/"))
            or ("/" not in name and (name.endswith((".py", ".toml", ".spec"))
                                    or name.startswith("requirements"))))


def verify_matching_inputs(previous, candidate, version):
    manifests = [json.loads((root / "build_source_manifest.json").read_text(encoding="utf-8"))
                 for root in (previous, candidate)]
    if any(m["version"] != version for m in manifests):
        raise ValueError("Candidate and previous source versions must match")
    maps = [{item["path"]: item["sha256"] for item in m["files"] if core_input(item["path"])}
            for m in manifests]
    if not maps[0] or not maps[1]:
        raise ValueError("Core source inventory is empty")
    if maps[0] != maps[1]:
        raise ValueError("Frozen-core source inputs changed; a fresh Python compile is required")
    for root, entries in zip((previous, candidate), maps):
        if any(not (root / name).resolve().is_relative_to(root.resolve()) for name in entries):
            raise ValueError("Core input escapes its source root")
        if any(file_hash(root / name) != digest for name, digest in entries.items()):
            raise ValueError("Recorded core input hash mismatch")
    return manifests[0]


def requires_distribution_approval(candidate):
    """Return true only for a receipt-backed, published release snapshot."""
    manifest = json.loads(
        (Path(candidate) / "build_source_manifest.json").read_text(encoding="utf-8")
    )
    return bool(
        manifest.get("github_freshness_verified")
        and manifest.get("source_published")
        and manifest.get("release_sync")
    )


def main():
    from builder import build_release, release_gate
    from builder.distribution_profiles import compile_editions
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-source", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    previous = args.previous_source.resolve()
    if previous == ROOT.resolve():
        raise ValueError("Recovery must use a separate candidate workspace")
    provenance = verify_matching_inputs(previous, ROOT, args.version)
    for_distribution = requires_distribution_approval(ROOT)
    stage = previous / "builder/output/stage"
    release = json.loads((stage / "manifest/release_manifest.json").read_text(encoding="utf-8"))
    if release.get("version") != args.version:
        raise ValueError("Previous staged release version mismatch")
    if not release_gate.report(release_gate.run_pre_build_gate(), label="repackage pre-build"):
        return 1
    if not release_gate.report(release_gate.run_post_stage_gate(stage), label="repackage existing stage"):
        return 1
    build_release.verify_frozen_mpr_geometry(stage / "core")
    exe = stage / "core/AIPacs.exe"
    core_hash = file_hash(exe)
    output = build_release.INSTALLER_OUTPUT_DIR.parent
    output.mkdir(parents=True, exist_ok=True)
    identity = {"version": args.version, "previous_source": str(previous),
                "previous_candidate_commit": provenance["candidate_commit"],
                "core_sha256": core_hash, "source_inputs_match": True,
                "distribution_approved": for_distribution, "published": False}
    (output / "repackage_provenance.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    def run(command, *, cwd):
        subprocess.run(command, cwd=cwd, check=True)
    adapter = SimpleNamespace(OUTPUT_DIR=output, INSTALLER_OUTPUT_DIR=build_release.INSTALLER_OUTPUT_DIR,
                              STAGE_DIR=stage, BUILDER_DIR=ROOT / "builder",
                              INSTALLER_SCRIPT=build_release.INSTALLER_SCRIPT,
                              INSTALLER_SCRIPT_WOA=build_release.INSTALLER_SCRIPT_WOA,
                              find_iscc=build_release.find_iscc, run_command=run, BACKEND="python")
    compile_editions(
        adapter,
        args.version,
        "all",
        for_distribution=for_distribution,
    )
    if file_hash(exe) != core_hash:
        raise RuntimeError("Previous core changed during repackaging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
