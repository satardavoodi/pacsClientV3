"""Local release candidates must use curated data and exact edition outputs."""
import ast
import inspect
import json
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def pipeline():
    spec = importlib.util.spec_from_file_location(
        "candidate_nuitka_pipeline", ROOT / "builder nuitka/build_nuitka_release.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_nuitka_generated_resources_are_curated():
    tree = ast.parse((ROOT / "builder nuitka/AIPacs_nuitka.spec.py").read_text())
    pairs = [tuple(item.value for item in node.elts)
             for node in ast.walk(tree) if isinstance(node, ast.Tuple)
             and all(isinstance(item, ast.Constant) for item in node.elts)]
    assert ("generated-files", "generated-files") not in pairs
    assert ("generated-files/css", "generated-files/css") in pairs
    assert ("servers.json", ".") not in pairs
    assert ("browser_bookmarks.json", ".") not in pairs


def test_nuitka_avoids_comprehensions_in_async_finally_cleanup():
    """Keep the patient-sidebar cleanup compilable by Nuitka on Python 3.13."""
    source = ROOT / "PacsClient/pacs/patient_tab/utils/thumbnail_batch_runner.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    start = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "start_sidebar_build"
    )
    run = next(
        node for node in ast.walk(start)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
    )
    comprehensions = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
    unsafe = [
        node
        for statement in ast.walk(run)
        if isinstance(statement, ast.Try)
        for final_statement in statement.finalbody
        for node in ast.walk(final_statement)
        if isinstance(node, comprehensions)
    ]
    assert not unsafe, (
        "Nuitka 4.1.3/Python 3.13 crashes while cloning a comprehension inside "
        "an async finally block (listcomp_1__.0_clone)"
    )


def test_nuitka_defaults_to_all_editions(pipeline, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["build"])
    args = pipeline.parse_args()
    assert args.edition == "all"
    assert not args.gui_smoke


def test_nuitka_resume_starts_at_recorded_failed_release_stage(pipeline):
    ctx = SimpleNamespace(state={"completed_stages": [0], "failed_stage": 6})
    assert pipeline.compute_resume_stages(ctx) == [6, 7, 8, 9, 10]


def test_nuitka_release_resume_never_enters_diagnostic_stages(pipeline):
    args = SimpleNamespace(release=True, stage=None, from_stage=None, resume=True)
    assert pipeline.parse_stage_selection(args) == ([], True)

    ctx = SimpleNamespace(
        args=args,
        state={"completed_stages": [0, 6, 7], "failed_stage": None},
    )
    assert pipeline.compute_resume_stages(ctx) == [8, 9, 10]


def test_nuitka_installer_uses_shared_fail_closed_editions(pipeline, monkeypatch, tmp_path):
    calls = []
    def compile_fixture(builder, version, selection, **kwargs):
        calls.append((builder, version, selection))
        assert builder.INSTALLER_SCRIPT == ROOT / "builder/installer/AIPacs_Setup.iss"
        assert builder.INSTALLER_SCRIPT_WOA == ROOT / "builder/installer/AIPacs_Setup_WoA.iss"
        assert builder.INSTALLER_OUTPUT_DIR == pipeline.INSTALLER_OUTPUT_DIR
        return {"outputs": [{"installer": str(tmp_path / "fresh.exe")} ]}
    monkeypatch.setattr(pipeline, "compile_editions", compile_fixture)
    ctx = SimpleNamespace(version="3.6.5", args=SimpleNamespace(edition="all"))
    result = pipeline.stage_10_inno_setup(ctx, pipeline.STAGES[10], tmp_path / "compile.log")
    assert calls[0][1:] == ("3.6.5", "all")
    assert result.artifact_paths == [str(tmp_path / "fresh.exe")]
    def failure(*args, **kwargs):
        raise RuntimeError("required edition failed")
    monkeypatch.setattr(pipeline, "compile_editions", failure)
    with pytest.raises(RuntimeError, match="required edition failed"):
        pipeline.stage_10_inno_setup(ctx, pipeline.STAGES[10], tmp_path / "compile.log")


def test_full_compile_does_not_launch_workstation(pipeline, monkeypatch, tmp_path):
    launches = []
    monkeypatch.setattr(pipeline, "run_nuitka_stage", lambda *a, **k:
                        pipeline.StageResult(artifact_paths=[str(tmp_path / "AIPacs.exe")],
                                             report_path=str(tmp_path / "report.xml")))
    monkeypatch.setattr(pipeline, "smoke_launch_exe", lambda *a, **k: launches.append(a))
    ctx = SimpleNamespace(spec=SimpleNamespace(ENTRY_POINT="main.py"),
                          args=SimpleNamespace(gui_smoke=False))
    pipeline.stage_06_full_core(ctx, pipeline.STAGES[6], tmp_path / "log.txt")
    assert not launches


def test_staged_nuitka_keeps_codec_entry_points(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "existing_modules", lambda candidates: set(candidates))
    ctx = SimpleNamespace(version="3.6.5", spec=SimpleNamespace(), args=SimpleNamespace(compiler="msvc"))
    command, _, _ = pipeline.create_nuitka_command(ctx, pipeline.STAGES[6],
                                                  profile="full_core", entrypoint="main.py")
    for dist in (
        "pylibjpeg",
        "pylibjpeg-openjpeg",
        "pylibjpeg-rle",
        "python-gdcm",
        "pyjpegls",
    ):
        assert "--include-distribution-metadata=" + dist in command
    for package in ("pylibjpeg", "openjpeg", "rle", "_gdcm", "jpeg_ls"):
        assert "--include-package=" + package in command
    for module in ("gdcm", "_gdcm.gdcmswig"):
        assert "--include-module=" + module in command


def test_nuitka_full_core_has_bounded_memory_defaults(pipeline, monkeypatch):
    monkeypatch.setattr(pipeline, "existing_modules", lambda candidates: set(candidates))
    ctx = SimpleNamespace(version="3.6.5", spec=SimpleNamespace(JOBS=0, LTO="auto"),
                          args=SimpleNamespace(compiler="msvc"))
    command, _, _ = pipeline.create_nuitka_command(ctx, pipeline.STAGES[6],
                                                  profile="full_core", entrypoint="main.py")
    for flag in ("--jobs=1", "--low-memory", "--lto=no", "--disable-cache=ccache"):
        assert flag in command


def test_nuitka_resume_preserves_only_timed_out_stage6_objects(pipeline, monkeypatch, tmp_path):
    output_root = tmp_path / "stage_06_full_core"
    build_dir = output_root / "main.build"
    dist_dir = output_root / "main.dist"
    build_dir.mkdir(parents=True)
    dist_dir.mkdir()
    (build_dir / "module.obj").write_bytes(b"compiled")
    (dist_dir / "stale.exe").write_bytes(b"stale")
    report = tmp_path / "report.xml"
    monkeypatch.setattr(
        pipeline,
        "create_nuitka_command",
        lambda *args, **kwargs: (["synthetic-nuitka", "--msvc=latest"], report, output_root),
    )

    def resumed_compile(*args, **kwargs):
        assert (build_dir / "module.obj").read_bytes() == b"compiled"
        assert not dist_dir.exists()
        assert kwargs["env"]["_CL_"].split()[-1] == "/Od"
        dist_dir.mkdir()
        (dist_dir / "AIPacs.exe").write_bytes(b"linked")
        report.write_text("<report />", encoding="utf-8")
        return 0

    monkeypatch.setattr(pipeline, "run_command_with_log", resumed_compile)
    monkeypatch.setattr(pipeline, "resolve_built_dist", lambda *args: dist_dir)
    ctx = SimpleNamespace(
        args=SimpleNamespace(resume=True),
        state={"stages": {"6": {"status": "failed", "error": "exit code 124"}}},
    )
    result = pipeline.run_nuitka_stage(
        ctx, pipeline.STAGES[6], tmp_path / "stage.log", "full_core", "main.py"
    )
    assert result.artifact_paths == [str(dist_dir / "AIPacs.exe")]


def test_build_watchdog_allows_long_silent_native_compiles():
    from builder.build_process import run_logged_build

    default = inspect.signature(run_logged_build).parameters["idle_timeout_seconds"].default
    assert default >= 4 * 3600


def test_compiler_memory_error_cannot_be_reported_as_success(pipeline, tmp_path):
    code = "print('MemoryError', flush=True)"
    rc = pipeline.run_command_with_log([sys.executable, "-c", code], cwd=tmp_path,
                                        log_path=tmp_path / "compiler.log")
    assert rc != 0


def test_edition_compiler_stages_under_a_bounded_path(tmp_path, monkeypatch):
    from builder import distribution_profiles as profiles
    from tests.code.builder.test_distribution_profiles import add_complete_slicer_runtime, source_stage
    source = source_stage(tmp_path)
    add_complete_slicer_runtime(source)
    resource = source / "core" / ("resource_" + "x" * 85 + ".txt")
    resource.write_text("synthetic build resource")
    output = tmp_path / ("nested_output_" + "y" * 60)
    monkeypatch.setenv("AIPACS_PACKAGING_STAGE_ROOT", str(tmp_path / "s"))
    def compile_fixture(command, **kwargs):
        values = dict(arg[2:].split("=", 1) for arg in command if arg.startswith("/D"))
        staged = Path(values["StageDir"])
        assert max(len(str(p)) for p in staged.rglob("*") if p.is_file()) < 260
        (Path(values["InstallerOutputDir"]) / (values["InstallerBaseName"] + ".exe")).write_bytes(b"synthetic")
    adapter = SimpleNamespace(OUTPUT_DIR=output, INSTALLER_OUTPUT_DIR=output / "installer",
                              STAGE_DIR=source, BUILDER_DIR=tmp_path,
                              INSTALLER_SCRIPT=Path("standard.iss"), find_iscc=lambda: Path("iscc.exe"),
                              run_command=compile_fixture)
    result = profiles.compile_editions(adapter, "3.6.5", "standard")
    assert result["status"] == "compiled"
    assert Path(result["outputs"][0]["installer"]).parent == output / "installer"


def test_build_watchdog_terminates_silent_child(tmp_path):
    from builder.build_process import run_logged_build
    rc = run_logged_build([sys.executable, "-c", "import time; time.sleep(30)"],
                          cwd=tmp_path, log_path=tmp_path / "timeout.log",
                          timeout_seconds=0.5, idle_timeout_seconds=0.5)
    assert rc == 124
    assert "timeout" in (tmp_path / "timeout.log").read_text()


def test_build_logging_survives_legacy_windows_stdout(tmp_path, monkeypatch):
    import io
    from builder.build_process import run_logged_build
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    rc = run_logged_build([sys.executable, "-X", "utf8", "-c", "print(chr(9731))"],
                          cwd=tmp_path, log_path=tmp_path / "unicode.log")
    assert rc == 0
    assert "\u2603" in (tmp_path / "unicode.log").read_text(encoding="utf-8")


def test_candidate_stops_before_nuitka_when_required_python_backend_fails(tmp_path, monkeypatch):
    from tools.build import build_local_candidate as candidate

    workspace = tmp_path / "candidate"
    source = workspace / "source"
    source.mkdir(parents=True)
    (source / "build_source_manifest.json").write_text(
        json.dumps({"source_sha256": "stable", "version": "3.6.5",
                    "github_freshness_verified": True,
                    "release_sync": {"commit": "0" * 40}}), encoding="utf-8"
    )
    final_repo = tmp_path / "final"
    calls = []

    monkeypatch.setattr(candidate, "source_fingerprint", lambda _root: "stable")
    monkeypatch.setattr(
        candidate,
        "canonical_installer_dirs",
        lambda _root, _version: {
            "python": final_repo / "builder/output/installer",
            "nuitka": final_repo / "builder nuitka/output/installer",
        },
    )

    def fail_python(command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["AIPACS_UPDATE_REMOTE_PUBLISH"] == "0"
        return 9

    monkeypatch.setattr(candidate, "run_logged_build", fail_python)

    assert candidate.run_builds(workspace, tmp_path / "assets", "3.6.5", final_repo=final_repo) == 1
    assert len(calls) == 1
    status = json.loads((workspace / "build_status.json").read_text(encoding="utf-8"))
    assert status["backends"]["python"]["status"] == "failed"
    assert status["backends"]["nuitka"]["status"] == "skipped"
    assert status["status"] == "failed"
    expected_stage_root = Path(workspace.resolve().anchor) / "ap-stage"
    assert Path(status["packaging_stage_root"]) == expected_stage_root
    expected_names = {
        "ai-pacs standard v3.6.5.exe",
        "ai-pacs arm64-emulated v3.6.5.exe",
    }
    for backend, installer_paths in status["expected_release_installers"].items():
        expected_parent = final_repo / (
            "builder/output/installer" if backend == "python" else "builder nuitka/output/installer"
        )
        assert {Path(path).name for path in installer_paths} == expected_names
        assert all(Path(path).parent == expected_parent for path in installer_paths)


def test_brain_release_preflight_fails_before_expensive_payload_validation(tmp_path, monkeypatch):
    from tools.build import build_local_candidate as candidate
    from builder import eagle_eye_brain_payload

    source = tmp_path / "brain"
    source.mkdir()
    calls = []
    monkeypatch.setattr(
        eagle_eye_brain_payload,
        "validate_payload",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="No compilation was started"):
        candidate.preflight_brain_payload(source, for_distribution=True)
    assert calls == []


def test_local_install_qa_builds_client_editions_to_canonical_folders(
    tmp_path, monkeypatch
):
    from tools.build import build_local_candidate as candidate

    workspace = tmp_path / "candidate"
    source = workspace / "source"
    source.mkdir(parents=True)
    (source / "build_source_manifest.json").write_text(
        json.dumps({
            "source_sha256": "stable",
            "version": "3.6.6",
            "github_freshness_verified": False,
            "release_sync": None,
        }),
        encoding="utf-8",
    )
    final_repo = tmp_path / "final"
    calls = []
    monkeypatch.setattr(candidate, "source_fingerprint", lambda _root: "stable")
    monkeypatch.setattr(
        candidate,
        "canonical_installer_dirs",
        lambda _root, _version: {
            "python": final_repo / "builder/output/installer",
            "nuitka": final_repo / "builder nuitka/output/installer",
        },
    )
    monkeypatch.setattr(
        candidate,
        "run_logged_build",
        lambda command, **kwargs: calls.append((command, kwargs)) or 0,
    )

    assert candidate.run_builds(
        workspace,
        tmp_path / "assets",
        "3.6.6",
        final_repo=final_repo,
        local_install_qa=True,
    ) == 0
    assert len(calls) == 3  # PyInstaller, Nuitka, then coherence.
    for command, invocation in calls[:2]:
        assert "--internal-build" in command
        assert command[command.index("--edition") + 1] == "client"
        assert invocation["env"]["AIPACS_PY_INSTALLER_OUTPUT_DIR"] == str(
            final_repo / "builder/output/installer"
        )
        assert invocation["env"]["AIPACS_NUITKA_INSTALLER_OUTPUT_DIR"] == str(
            final_repo / "builder nuitka/output/installer"
        )
        assert invocation["env"]["AIPACS_EAGLE_EYE_LESION_SOURCE"] == str(
            final_repo / "generated-files/eagle-eye/brain-lesions"
        )
        assert invocation["env"]["AIPACS_EAGLE_EYE_ALIGNMENT_SOURCE"] == str(
            final_repo / "generated-files/eagle-eye/alignment"
        )
        assert invocation["env"]["AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE"] == str(
            final_repo / "generated-files/eagle-eye/total-spine"
        )
    status = json.loads((workspace / "build_status.json").read_text(encoding="utf-8"))
    assert status["lane"] == "local-install-qa"
    assert status["build_target"] == "client"
    assert all(len(paths) == 2 for paths in status["expected_release_installers"].values())
    assert status["distribution_approved"] is False
    assert status["published"] is False


def test_local_qa_same_version_rebuild_archives_only_selected_backend_outputs(tmp_path):
    from tools.build import build_local_candidate as candidate

    output = tmp_path / "builder nuitka/output/installer"
    output.mkdir(parents=True)
    standard = output / "ai-pacs standard v3.6.7.exe"
    arm = output / "ai-pacs arm64-emulated v3.6.7.exe"
    server = output / "ai-pacs eagle-eye v3.6.7.exe"
    metadata = output / "distributions.json"
    for path in (standard, arm, server, metadata):
        path.write_bytes(path.name.encode("ascii"))
    status = {
        "version": "3.6.7",
        "lane": "local-install-qa",
        "expected_release_installers": {
            "nuitka": [str(standard), str(arm)],
        },
    }

    moved = candidate.archive_existing_local_qa_outputs(status, "nuitka")

    assert len(moved) == 3
    assert not standard.exists()
    assert not arm.exists()
    assert not metadata.exists()
    assert server.is_file()
    archives = {Path(row["archive"]) for row in moved}
    assert {path.name for path in archives} == {
        standard.name,
        arm.name,
        metadata.name,
    }
    assert all(path.is_file() and "_superseded" in path.parts for path in archives)
    assert candidate.archive_existing_local_qa_outputs(status, "nuitka") == []


def test_server_qa_builds_only_eagle_eye_in_both_backends(tmp_path, monkeypatch):
    from tools.build import build_local_candidate as candidate

    workspace = tmp_path / "candidate"
    source = workspace / "source"
    source.mkdir(parents=True)
    (source / "build_source_manifest.json").write_text(json.dumps({
        "source_sha256": "stable", "version": "3.6.7",
        "build_target": "server", "github_freshness_verified": False,
        "release_sync": None,
    }), encoding="utf-8")
    final_repo = tmp_path / "final"
    monkeypatch.setattr(candidate, "source_fingerprint", lambda _root: "stable")
    monkeypatch.setattr(candidate, "canonical_installer_dirs", lambda _root, _version: {
        "python": final_repo / "builder/output/installer",
        "nuitka": final_repo / "builder nuitka/output/installer",
    })
    calls = []
    monkeypatch.setattr(candidate, "run_logged_build",
                        lambda command, **_kwargs: calls.append(command) or 0)

    assert candidate.run_builds(workspace, tmp_path / "assets", "3.6.7",
                                final_repo=final_repo, local_install_qa=True,
                                target="server") == 0
    assert len(calls) == 3
    assert all(command[command.index("--edition") + 1] == "server"
               for command in calls[:2])
    status = json.loads((workspace / "build_status.json").read_text(encoding="utf-8"))
    assert status["build_target"] == "server"
    assert all(len(paths) == 1 and "eagle-eye" in paths[0]
               for paths in status["expected_release_installers"].values())


def test_server_release_is_not_misrepresented_as_qualified(tmp_path):
    from tools.build import build_local_candidate as candidate

    with pytest.raises(ValueError, match="not qualified for release"):
        candidate.run_builds(tmp_path, tmp_path / "assets", "3.6.7", target="server")


def test_python_release_materializer_stages_every_eagle_eye_external_payload():
    source = (ROOT / "builder/build_release.py").read_text(encoding="utf-8")

    for function in (
        "stage_eagle_eye_brain",
        "stage_eagle_eye_lesions",
        "stage_eagle_eye_alignment",
        "stage_eagle_eye_total_spine",
    ):
        assert function in source


def test_candidate_resume_skips_completed_python_and_resumes_nuitka(
    tmp_path, monkeypatch
):
    from tools.build import build_local_candidate as candidate

    workspace = tmp_path / "candidate"
    source = workspace / "source"
    source.mkdir(parents=True)
    (source / "build_source_manifest.json").write_text(
        json.dumps({
            "source_sha256": "stable",
            "version": "3.6.6",
            "github_freshness_verified": False,
            "release_sync": None,
        }),
        encoding="utf-8",
    )
    (source / "builder nuitka/output").mkdir(parents=True)
    (source / "builder nuitka/output/build_state.json").write_text(
        json.dumps({"completed_stages": [0, 6, 7], "failed_stage": 8}),
        encoding="utf-8",
    )
    (workspace / "build_status.json").write_text(
        json.dumps({
            "version": "3.6.6",
            "status": "failed",
            "lane": "local-install-qa",
            "published": False,
            "distribution_approved": False,
            "production_accepted": False,
            "backends": {
                "python": {
                    "status": "completed",
                    "exit_code": 0,
                    "command": [
                        sys.executable,
                        "tools/build/repackage_candidate.py",
                        "--previous-source",
                        str(tmp_path / "previous-source"),
                    ],
                },
                "nuitka": {"status": "failed", "exit_code": 1},
            },
        }),
        encoding="utf-8",
    )
    final_repo = tmp_path / "final"
    calls = []
    monkeypatch.setattr(candidate, "source_fingerprint", lambda _root: "stable")
    monkeypatch.setattr(
        candidate,
        "canonical_installer_dirs",
        lambda _root, _version: {
            "python": final_repo / "builder/output/installer",
            "nuitka": final_repo / "builder nuitka/output/installer",
        },
    )
    python_output = final_repo / "builder/output/installer"
    python_output.mkdir(parents=True)
    for edition in ("eagle-eye", "standard", "arm64-emulated"):
        (python_output / f"ai-pacs {edition} v3.6.6.exe").write_bytes(b"fixture")
    monkeypatch.setattr(
        candidate,
        "run_logged_build",
        lambda command, **kwargs: calls.append(command) or 0,
    )

    assert candidate.run_builds(
        workspace,
        tmp_path / "assets",
        "3.6.6",
        final_repo=final_repo,
        local_install_qa=True,
        resume=True,
        target="all",
    ) == 0
    assert len(calls) == 2  # Nuitka recovery, then coherence.
    assert "builder nuitka/build_nuitka_release.py" in calls[0]
    assert "--resume" in calls[0]
    assert "--release" not in calls[0]
    assert "builder/scripts/check_build_coherence.py" in calls[1]
    assert calls[1][calls[1].index("--py-stage") + 1] == str(
        tmp_path / "previous-source/builder/output/stage"
    )


def test_candidate_resume_converts_interrupted_release_stage_to_failed(
    tmp_path, monkeypatch
):
    from tools.build import build_local_candidate as candidate

    workspace = tmp_path / "candidate"
    source = workspace / "source"
    state_path = source / "builder nuitka/output/build_state.json"
    state_path.parent.mkdir(parents=True)
    (source / "build_source_manifest.json").write_text(
        json.dumps({
            "source_sha256": "stable",
            "version": "3.6.7",
            "github_freshness_verified": False,
            "release_sync": None,
        }),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps({
            "completed_stages": [0, 6, 7, 8, 9],
            "failed_stage": None,
            "current_stage": 10,
            "stages": {"10": {"status": "running"}},
        }),
        encoding="utf-8",
    )
    (workspace / "build_status.json").write_text(
        json.dumps({
            "version": "3.6.7",
            "status": "failed",
            "lane": "local-install-qa",
            "backends": {
                "python": {"status": "completed", "exit_code": 0},
                "nuitka": {"status": "running", "pid": 99999999},
            },
        }),
        encoding="utf-8",
    )
    final_repo = tmp_path / "final"
    python_output = final_repo / "builder/output/installer"
    python_output.mkdir(parents=True)
    for edition in ("eagle-eye", "standard", "arm64-emulated"):
        (python_output / f"ai-pacs {edition} v3.6.7.exe").write_bytes(b"fixture")
    calls = []
    monkeypatch.setattr(candidate, "source_fingerprint", lambda _root: "stable")
    monkeypatch.setattr(candidate, "_pid_is_alive", lambda _pid: False)
    monkeypatch.setattr(
        candidate,
        "canonical_installer_dirs",
        lambda _root, _version: {
            "python": python_output,
            "nuitka": final_repo / "builder nuitka/output/installer",
        },
    )
    monkeypatch.setattr(
        candidate,
        "run_logged_build",
        lambda command, **kwargs: calls.append(command) or 0,
    )

    assert candidate.run_builds(
        workspace,
        tmp_path / "assets",
        "3.6.7",
        final_repo=final_repo,
        local_install_qa=True,
        resume=True,
        target="all",
    ) == 0
    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    assert repaired["failed_stage"] == 10
    assert repaired["current_stage"] is None
    assert repaired["stages"]["10"]["status"] == "failed"
    assert "--resume" in calls[0]
    assert "--release" not in calls[0]


def test_internal_standard_one_command_uses_safe_defaults(tmp_path, monkeypatch):
    from tools.build import build_local_candidate as candidate

    source = tmp_path / "candidate" / "source"
    source.mkdir(parents=True)
    (source / "build_source_manifest.json").write_text(
        json.dumps({
            "version": "3.6.6",
            "github_freshness_verified": False,
            "source_sha256": "stable",
        }),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(candidate, "source_fingerprint", lambda _root: "stable")
    monkeypatch.setattr(
        candidate,
        "run_logged_build",
        lambda command, **kwargs: calls.append((command, kwargs)) or 0,
    )

    assert candidate.run_internal_build(
        tmp_path / "candidate",
        tmp_path / "assets",
        "3.6.6",
    ) == 0
    command, invocation = calls[0]
    assert "--internal-build" in command
    assert command[command.index("--edition") + 1] == "standard"
    assert "AIPACS_EAGLE_EYE_BRAIN_SOURCE" not in invocation["env"]
    status = json.loads((tmp_path / "candidate/build_status.json").read_text(encoding="utf-8"))
    assert status["lane"] == "internal"
    assert status["published"] is False
    assert status["production_accepted"] is False


def test_canonical_candidate_cli_requires_git_sync_receipt(tmp_path, monkeypatch):
    from tools.build import build_local_candidate as candidate
    monkeypatch.setattr(sys, "argv", [
        "build_local_candidate.py",
        "--workspace", str(tmp_path / "candidate"),
        "--asset-root", str(tmp_path / "assets"),
        "--version", "3.6.5",
    ])
    with pytest.raises(SystemExit) as exc:
        candidate.main()
    assert exc.value.code == 2


def test_repackage_rejects_changed_or_added_runtime_input(tmp_path):
    from tools.build.repackage_candidate import verify_matching_inputs
    from builder.source_identity import file_hash
    roots = [tmp_path / "previous", tmp_path / "candidate"]
    for root in roots:
        root.mkdir()
        (root / "main.py").write_text("SYNTHETIC = True\n")
        (root / "build_source_manifest.json").write_text(json.dumps({"version": "3.6.5",
            "files": [{"path": "main.py", "sha256": file_hash(root / "main.py")}]}))
    assert verify_matching_inputs(*roots, "3.6.5")["version"] == "3.6.5"
    (roots[1] / "main.py").write_text("SYNTHETIC = False\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_matching_inputs(*roots, "3.6.5")
    changed = {"version": "3.6.5", "files": [{"path": "main.py", "sha256": "changed"}]}
    (roots[1] / "build_source_manifest.json").write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="source inputs changed"):
        verify_matching_inputs(*roots, "3.6.5")


def test_repackage_requires_distribution_approval_only_for_published_snapshot(tmp_path):
    from tools.build.repackage_candidate import requires_distribution_approval

    manifest = {
        "github_freshness_verified": False,
        "source_published": False,
        "release_sync": None,
    }
    (tmp_path / "build_source_manifest.json").write_text(json.dumps(manifest))
    assert requires_distribution_approval(tmp_path) is False

    manifest.update(
        github_freshness_verified=True,
        source_published=True,
        release_sync={"version": "3.6.6", "commit": "a" * 40},
    )
    (tmp_path / "build_source_manifest.json").write_text(json.dumps(manifest))
    assert requires_distribution_approval(tmp_path) is True


def test_oversized_compiler_source_path_fails_before_compilation(tmp_path):
    from builder.distribution_profiles import validate_compiler_paths
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("synthetic")
    with pytest.raises(ValueError, match="safe budget"):
        validate_compiler_paths(source, tmp_path / ("long" * 60))


def test_two_equally_stale_stages_do_not_pass_coherence(tmp_path, monkeypatch):
    from builder.scripts import check_build_coherence as coherence
    monkeypatch.setattr(coherence, "load_plugin_package_definitions", lambda **k: [])
    stages = [tmp_path / "python", tmp_path / "nuitka"]
    for stage in stages:
        (stage / "core").mkdir(parents=True)
        (stage / "core/AIPacs.exe").write_bytes(b"synthetic")
        (stage / "manifest").mkdir()
        (stage / "manifest/installation_profile.json").write_text(json.dumps({
            "app_version": "0.0.1", "installer": {"current_version": "0.0.1"}, "modules": {}}))
        (stage / "plugin_packages").mkdir()
        (stage / "plugin_packages/module_package_feed.json").write_text('{"packages": []}')
    assert coherence.run_checks(*stages, tmp_path / "reports", False) == 1


@pytest.mark.parametrize("name", ["generated-files/gapgpt/private.json", "builder/output/old.exe",
                                  "builder nuitka/output/build_state.json", "data/scan.dcm",
                                  "database/dicom.db", "../outside.py", ".env"])
def test_snapshot_excludes_non_source_inputs(name):
    from builder.source_identity import is_source_input
    assert not is_source_input(name)


def test_snapshot_matches_bytes_but_not_local_config(tmp_path):
    from tools.build.build_local_candidate import create_snapshot, git
    from builder.source_identity import source_fingerprint
    source = tmp_path / "developer"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@invalid.example")
    git(source, "config", "user.name", "Synthetic Test")
    (source / "pyproject.toml").write_text('[project]\nversion="3.6.5"\n')
    (source / "main.py").write_text("CURRENT_SOURCE = True\n")
    (source / "config").mkdir()
    (source / "config/servers.json").write_text('[{"host":"synthetic.invalid"}]')
    git(source, "add", "--all")
    git(source, "commit", "-m", "Synthetic source fixture")
    (source / "new.py").write_text("UNTRACKED_SOURCE = True\n")
    destination = tmp_path / "isolated"
    result = create_snapshot(source, destination, "3.6.5")
    assert (destination / "new.py").read_bytes() == (source / "new.py").read_bytes()
    assert json.loads((destination / "config/servers.json").read_text()) == []
    assert json.loads((source / "config/servers.json").read_text()) != []
    assert result["source_sha256"] == source_fingerprint(destination)
    assert not git(destination, "status", "--porcelain")
    with pytest.raises(ValueError):
        create_snapshot(source, destination, "3.6.5")


def test_official_backend_authority_requires_receipt_bound_snapshot(tmp_path, monkeypatch):
    from builder import source_identity

    monkeypatch.setattr(source_identity, "source_fingerprint", lambda _root: "stable")
    manifest = {
        "version": "3.6.5",
        "source_head": "a" * 40,
        "source_sha256": "stable",
        "developer_run_accepted": True,
        "production_accepted": False,
        "github_freshness_verified": True,
        "source_published": True,
        "release_sync": {"version": "3.6.5", "commit": "a" * 40},
    }
    (tmp_path / "build_source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert source_identity.validate_build_authority(tmp_path, "3.6.5") == manifest

    manifest["release_sync"]["commit"] = "b" * 40
    (tmp_path / "build_source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(source_identity.BuildAuthorityError, match="source commit"):
        source_identity.validate_build_authority(tmp_path, "3.6.5")


def test_internal_backend_authority_is_non_promotable_and_snapshot_only(tmp_path, monkeypatch):
    from builder import source_identity

    monkeypatch.setattr(source_identity, "source_fingerprint", lambda _root: "stable")
    with pytest.raises(source_identity.BuildAuthorityError, match="manifest is missing"):
        source_identity.validate_build_authority(tmp_path, "3.6.5", internal=True)

    manifest = {
        "version": "3.6.5",
        "source_sha256": "stable",
        "developer_run_accepted": True,
        "production_accepted": False,
        "github_freshness_verified": False,
        "source_published": False,
        "release_sync": None,
    }
    (tmp_path / "build_source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert source_identity.validate_build_authority(tmp_path, "3.6.5", internal=True) == manifest
    with pytest.raises(source_identity.BuildAuthorityError, match="Git publication"):
        source_identity.validate_build_authority(tmp_path, "3.6.5")


def test_both_release_backends_enforce_snapshot_authority():
    pyinstaller = (ROOT / "builder/build_release.py").read_text(encoding="utf-8")
    nuitka = (ROOT / "builder nuitka/build_nuitka_release.py").read_text(encoding="utf-8")
    for source in (pyinstaller, nuitka):
        assert "validate_build_authority" in source
        assert "--internal-build" in source


def test_candidate_final_outputs_use_only_existing_repository_installer_folders(tmp_path):
    from tools.build.build_local_candidate import canonical_installer_dirs
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nversion="3.6.5"\n')
    paths = canonical_installer_dirs(repo, "3.6.5")
    assert paths == {
        "python": (repo / "builder/output/installer").resolve(),
        "nuitka": (repo / "builder nuitka/output/installer").resolve(),
    }
    with pytest.raises(ValueError, match="version"):
        canonical_installer_dirs(repo, "3.6.4")
