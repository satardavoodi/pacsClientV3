from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_canonical_runbook_defines_the_complete_release_contract():
    text = _read("BUILD.md")

    required_contract = (
        "tools\\build\\build_local_candidate.py",
        "builder/output/installer/ai-pacs eagle-eye v<version>.exe",
        "builder/output/installer/ai-pacs standard v<version>.exe",
        "builder/output/installer/ai-pacs arm64-emulated v<version>.exe",
        "builder nuitka/output/installer/ai-pacs eagle-eye v<version>.exe",
        "builder nuitka/output/installer/ai-pacs standard v<version>.exe",
        "builder nuitka/output/installer/ai-pacs arm64-emulated v<version>.exe",
        "Source validation",
        "Internal packaging validation",
        "Full release candidate",
        "setup_build_env.ps1",
        "at least 60 GiB free",
        "build_status.json",
        "coherence_exit_code",
        "RELEASE.md",
        "--git-sync-receipt",
        "Canonical role-selected command",
        "build_local_candidate.py --internal",
        "--local-install-qa",
        "not a third output hierarchy",
        "request is complete only when the selected role's versioned files",
        "Non-negotiable interpretation of a build request",
        "means the Standard Client group",
        "--target server",
        "four installers",
        "two installers",
        "The coordinator CLI intentionally has no final-output-directory override",
        "Reuse and compression decision",
        "--resume-workspace",
        "must never enter diagnostic stages 1-5",
        "Never do these",
    )
    for value in required_contract:
        assert value in text


def test_agent_and_backend_entry_documents_point_to_root_runbook():
    entry_documents = (
        "AGENTS.md",
        "README.md",
        "CLAUDE.md",
        "WORKSPACE.md",
        ".github/copilot-instructions.md",
        "docs/README.md",
        "docs/INDEX_BY_SUBSYSTEM.md",
        "docs/development/setup-and-tooling.md",
        "docs/release-and-build/README.md",
        "builder/docs/README.md",
        "builder/docs/AI_AGENT_BUILD_RUNBOOK.md",
        "builder/docs/BUILD_CHECKLIST.md",
        "builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md",
        "builder/docs/INSTALLER_QA_CHECKLIST.md",
        "builder/docs/WINDOWS_RELEASE_FLOW.md",
        "builder nuitka/README_NUITKA_BUILD.md",
        "setup_build_env.ps1",
    )

    for relative_path in entry_documents:
        text = _read(relative_path)
        assert "BUILD.md" in text, f"{relative_path} does not route to BUILD.md"

    setup_text = _read("setup_build_env.ps1")
    assert "tools\\build\\build_local_candidate.py" in setup_text


def test_source_level_entrypoints_route_to_release_and_build_documentation_hub():
    entry_documents = (
        "AGENTS.md",
        "README.md",
        "CLAUDE.md",
        "WORKSPACE.md",
        ".github/copilot-instructions.md",
        "docs/README.md",
        "docs/INDEX_BY_SUBSYSTEM.md",
        "docs/for-future-agents/README.md",
        "docs/development/setup-and-tooling.md",
        "docs/architecture/repository-layout.md",
        "builder/docs/README.md",
        "builder nuitka/README_NUITKA_BUILD.md",
        "tools/git/README.md",
        "tools/build/README.md",
        "setup_build_env.ps1",
    )
    for relative_path in entry_documents:
        assert "release-and-build/README.md" in _read(relative_path), relative_path

    hub = _read("docs/release-and-build/README.md")
    for required in (
        "RELEASE.md",
        "BUILD.md",
        "builder/docs/README.md",
        "builder%20nuitka/README_NUITKA_BUILD.md",
        "docs/releases/README.md",
        "builder/output/installer/",
        "builder nuitka/output/installer/",
        "Direct backend scripts are implementation interfaces",
        "An unqualified request to make a build means the four-file Standard Client group",
        "no supported final-output redirect",
        "Recover an interrupted role build",
    ):
        assert required in hub


def test_active_setup_doc_does_not_offer_a_direct_release_bypass():
    text = _read("docs/development/setup-and-tooling.md")
    assert ".venv_build\\Scripts\\python build.py" not in text
    assert "GitHub: Push current branch" not in text
    assert "release_manager.py" not in text  # Procedure stays owned by RELEASE.md.
    assert "../../RELEASE.md" in text
    assert "../../BUILD.md" in text


def test_backend_reference_documents_declare_current_navigation_precedence():
    references = (
        "builder/docs/ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md",
        "builder/docs/AI_AGENT_BUILD_RUNBOOK.md",
        "builder/docs/BUILD_CHECKLIST.md",
        "builder/docs/BUILD_DOCUMENT.md",
        "builder/docs/BUILD_EVALUATION_2026-08-02_v3.5.7.md",
        "builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md",
        "builder/docs/NUITKA_BUILD_AGENT_HANDOFF.md",
        "builder/docs/NUITKA_BUILD_PLAN.md",
        "builder/docs/WINDOWS_RELEASE_FLOW.md",
        "builder nuitka/NUITKA_COMPLETION_REPORT.md",
        "builder nuitka/README_NUITKA_BUILD.md",
        "builder/plugin package/README.md",
    )
    for relative_path in references:
        assert "release-and-build/README.md" in _read(relative_path), relative_path

    active_entrypoints = (
        ".github/copilot-instructions.md",
        "docs/development/setup-and-tooling.md",
        "builder/docs/README.md",
        "builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md",
    )
    for relative_path in active_entrypoints:
        text = _read(relative_path)
        assert ".venv_build\\Scripts\\python.exe build.py" not in text, relative_path
        assert "GitHub: Push current branch" not in text, relative_path


def test_runbook_rejects_known_unsafe_speed_shortcuts():
    text = _read("BUILD.md")

    for prohibited in (
        "Do not run PyInstaller and Nuitka full-core compilation concurrently",
        "Do not exclude Slicer to make Standard or ARM smaller",
        "Do not reuse or rename an older installer",
        "Do not launch an installer or the frozen workstation automatically",
    ):
        assert prohibited in text


def test_coordinator_cli_cannot_redirect_final_installer_outputs():
    source = _read("tools/build/build_local_candidate.py")

    assert '"--final-repo"' not in source
    assert "args.final_repo" not in source


def test_release_runbook_is_the_only_multi_remote_push_route():
    text = _read("RELEASE.md")
    for value in (
        "tools/git/release_targets.json",
        "Vahid-INO/ai-pacs",
        "satardavoodi/PacsClientV2",
        "satardavoodi/pacsClientV3",
        "release(v<version>):",
        "--expected-head",
        "--execute",
        "--git-sync-receipt",
        "force-push shared release branches",
    ):
        assert value in text

    legacy = _read("tools/git/Push-GitHub.ps1")
    assert "release_manager.py" in legacy

    release_entry_documents = (
        "AGENTS.md",
        "README.md",
        "CLAUDE.md",
        "docs/README.md",
        "docs/for-future-agents/README.md",
        "builder/docs/README.md",
        "builder/docs/AI_AGENT_BUILD_RUNBOOK.md",
        "builder/docs/BUILD_CHECKLIST.md",
        "builder/docs/WINDOWS_RELEASE_FLOW.md",
        "builder nuitka/README_NUITKA_BUILD.md",
        "setup_build_env.ps1",
        "BUILD.md",
        "docs/release-and-build/README.md",
        "docs/releases/README.md",
        "tools/git/README.md",
        "tools/build/README.md",
    )
    for relative_path in release_entry_documents:
        assert "RELEASE.md" in _read(relative_path), relative_path
