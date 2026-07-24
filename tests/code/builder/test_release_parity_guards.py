"""Release-parity guards — repo-level tests that make the
"works in source, missing in installed build" regression class fail a normal
pytest run instead of shipping (2026-06-11; mechanisms documented in
docs/pipelines/online-consultation-education.md §12–§13).

Layers:
  A1  installer Pascal WriteInstallationProfile() covers every MODULE_CATALOG id
      (the guard that would have caught mechanism #2).
  A2  config seeding coverage: every shippable config/ template is seed-reachable,
      every CONFIG_FAMILY_VERSIONS file exists, every feature-flag file is
      version-managed, google_oauth.json ships.
  A3  plugin payload mirrors are fresh (mechanism #3) — a forgotten
      tools/dev/sync_plugin_mirrors.py run fails the test suite, not the build.
  B   unit tests for builder/release_gate.py where pure (PYZ probe runs against
      the CURRENT stage output and skips cleanly when no stage exists).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import aipacs_runtime as runtime
from builder import release_gate

REPO_ROOT = Path(__file__).resolve().parents[3]
ISS_PATH = REPO_ROOT / "builder" / "installer" / "AIPacs_Setup.iss"
CONFIG_ROOT = REPO_ROOT / "config"

CATALOG_IDS = sorted(str(item["id"]) for item in runtime.MODULE_CATALOG)

# Feature-flag config files read by module gating code. Grep anchors:
#   modules/Identity/config.py            -> identity/identity.json
#   modules/Identity/providers/aipacs_web.py -> identity/aipacs_web.json
#   modules/cloud_consultation/feature_flags.py -> cloud_consultation/cloud_consultation.json
# Every entry MUST be a CONFIG_FAMILY_VERSIONS family so future key additions
# migrate into existing installs (mechanism #1). When adding a NEW flag file,
# add it here AND to CONFIG_FAMILY_VERSIONS.
FEATURE_FLAG_CONFIG_FILES = (
    "identity/identity.json",
    "cloud_consultation/cloud_consultation.json",
    "identity/aipacs_web.json",
    # modules/agent_gateway/feature_flags.py -> agent_gateway/agent_gateway.json
    "agent_gateway/agent_gateway.json",
)


# ---------------------------------------------------------------------------
# A1 — installer profile writer covers the runtime catalog
# ---------------------------------------------------------------------------

def _extract_iss_json_block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def test_iss_write_installation_profile_covers_module_catalog():
    """Every MODULE_CATALOG id must appear in BOTH JSON writers of the Pascal
    WriteInstallationProfile() procedure in AIPacs_Setup.iss.

    This is the guard for mechanism #2 (2026-06-11): the optional\\consultation
    component existed and copied files, but the installer-written
    installation_profile.json predated the catalog, so the module was never
    enabled in the frozen install.
    """
    iss_text = ISS_PATH.read_text(encoding="utf-8")
    proc_start = iss_text.index("procedure WriteInstallationProfile()")
    proc_text = iss_text[proc_start: iss_text.index("SaveStringToFile", proc_start)]

    modules_block = _extract_iss_json_block(proc_text, '"modules": {', '"module_packages": {')
    packages_block = _extract_iss_json_block(proc_text, '"module_packages": {', '"graphics": {')

    missing_in_modules = [
        module_id for module_id in CATALOG_IDS
        if not re.search(rf'"{re.escape(module_id)}"\s*:', modules_block)
    ]
    missing_in_packages = [
        module_id for module_id in CATALOG_IDS
        if not re.search(rf'"{re.escape(module_id)}"\s*:', packages_block)
    ]

    assert not missing_in_modules and not missing_in_packages, (
        "builder/installer/AIPacs_Setup.iss WriteInstallationProfile() lags "
        "aipacs_runtime.MODULE_CATALOG — the installer would copy the module's files "
        "but NEVER enable it on installed machines (the 2026-06-11 consultation bug).\n"
        f"  ids missing from the '\"modules\": {{' JSON writer:        {missing_in_modules}\n"
        f"  ids missing from the '\"module_packages\": {{' JSON writer: {missing_in_packages}\n"
        "Fix: in AIPacs_Setup.iss procedure WriteInstallationProfile(), add for each id\n"
        "  1) a '\"<id>\": ...' line in the modules JSON block (true for basic tier,\n"
        "     BoolToJson(OptionalModuleSelected('<id>')) for optional tier), and\n"
        "  2) a '\"<id>\": {...}' record in the module_packages JSON block (copy an\n"
        "     existing line of the same tier and adjust module_id/title/package_kind).\n"
        "Also confirm the [Components]/[Files] lines exist (covered by\n"
        "tests/code/builder/test_plugin_package_registry.py)."
    )


# ---------------------------------------------------------------------------
# A2 — config seeding coverage
# ---------------------------------------------------------------------------

def _repo_config_files() -> list[Path]:
    return [
        p.relative_to(CONFIG_ROOT)
        for p in sorted(CONFIG_ROOT.rglob("*"))
        if p.is_file()
    ]


def test_every_config_template_is_seed_reachable(tmp_path):
    """Every *.json under config/ (excluding secrets/, housekeeping files and the
    documented exclude list) must actually be delivered by the seeding pipeline —
    functionally verified, not just rule-mirrored, for subdirectory files
    (mechanism #1: subdir flag files were unreachable for every frozen install)."""
    expected = release_gate.iter_seedable_config_templates(REPO_ROOT)
    expected_set = {rel.as_posix() for rel in expected}

    # Sanity: the rules classify every real file as either seedable or
    # deliberately excluded — nothing falls through unaccounted.
    for rel in _repo_config_files():
        rel_posix = rel.as_posix()
        skipped = (
            # Mirror iter_seedable_config_templates' own backup/editor-artifact
            # rule (e.g. identity/aipacs_web.json.bak-20260613) — otherwise a
            # stray .bak in config/ fails this guard for no real reason.
            rel.name.endswith((".bak", ".orig", ".tmp"))
            or ".bak-" in rel.name
            or any(part in release_gate.CONFIG_SEED_SKIP_DIRNAMES for part in rel.parts[:-1])
            or rel.name in release_gate.CONFIG_SEED_SKIP_FILENAMES
            # Subdirectory excludes are matched by full POSIX path in
            # iter_seedable_config_templates (e.g. agent_gateway/devices.json) —
            # mirror that here so machine-generated agent_gateway state (paired
            # devices, e2e channel key, TLS cert+key) is recognised as excluded.
            or rel.as_posix() in release_gate.CONFIG_TEMPLATE_EXCLUDES
            or (len(rel.parts) == 1 and rel.name in release_gate.CONFIG_TEMPLATE_EXCLUDES)
        )
        assert (rel_posix in expected_set) != skipped, (
            f"config/{rel_posix} is neither seed-reachable nor on a documented "
            "exclude list. Either make it seedable or add it to "
            "builder/release_gate.py CONFIG_TEMPLATE_EXCLUDES with a comment."
        )

    # The flag files of mechanism #1 must be in the seedable set.
    for flag_file in FEATURE_FLAG_CONFIG_FILES:
        assert flag_file in expected_set, (
            f"feature-flag file config/{flag_file} is not seed-reachable — frozen "
            "installs would silently run with the module disabled."
        )

    # Functional check: run the REAL subdirectory seeder against a temp root and
    # assert every expected subdir file lands.
    copied = runtime._seed_config_subdirectories(CONFIG_ROOT, tmp_path)
    copied_set = set(copied)
    for rel in expected:
        if len(rel.parts) < 2:
            continue  # top-level files are seed_user_config_defaults' job
        assert rel.as_posix() in copied_set and (tmp_path / rel).exists(), (
            f"_seed_config_subdirectories did not deliver config/{rel.as_posix()} — "
            "its rules and the template layout have drifted apart."
        )
    # And nothing forbidden leaked.
    assert not (tmp_path / "identity" / "secrets").exists()
    for leaked in tmp_path.rglob(".gitignore"):
        pytest.fail(f"housekeeping file seeded into user config: {leaked}")


def test_config_family_versions_files_exist():
    """Every CONFIG_FAMILY_VERSIONS family must point at a real template in
    config/ — a typo'd or deleted family silently never migrates."""
    for rel, version in runtime.CONFIG_FAMILY_VERSIONS.items():
        template = CONFIG_ROOT / Path(rel)
        assert template.is_file(), (
            f"CONFIG_FAMILY_VERSIONS lists '{rel}' (v{version}) but "
            f"config/{rel} does not exist in the repo — migration for that "
            "family can never run. Fix the path or ship the template."
        )
        assert int(version) >= 1


def test_feature_flag_files_are_version_managed():
    """Every feature-flag config file used by gating code must be a
    CONFIG_FAMILY_VERSIONS family so NEW keys added to its template reach
    existing installs via migrate_user_config_defaults."""
    missing = [
        flag_file for flag_file in FEATURE_FLAG_CONFIG_FILES
        if flag_file not in runtime.CONFIG_FAMILY_VERSIONS
    ]
    assert not missing, (
        f"feature-flag config file(s) {missing} are missing from "
        "aipacs_runtime.CONFIG_FAMILY_VERSIONS — add each with version 1 (or bump "
        "the existing family) so existing installs receive future key additions."
    )


def test_google_oauth_template_ships():
    """identity/google_oauth.json must exist and be seed-reachable: without the
    OAuth client template, installed builds cannot connect Google Drive."""
    template = CONFIG_ROOT / "identity" / "google_oauth.json"
    assert template.is_file(), "config/identity/google_oauth.json is missing from the repo"
    seedable = {rel.as_posix() for rel in release_gate.iter_seedable_config_templates(REPO_ROOT)}
    assert "identity/google_oauth.json" in seedable


# ---------------------------------------------------------------------------
# A3 — plugin mirror freshness fails the TEST run, not just the build
# ---------------------------------------------------------------------------

def test_plugin_mirrors_are_fresh():
    check = release_gate.check_plugin_mirrors()
    assert check.ok, (
        "Plugin payload mirrors drifted from canonical sources (a build made now "
        "would ship stale module code):\n  " + "\n  ".join(check.details) +
        "\nFix: python tools/dev/sync_plugin_mirrors.py  then re-run "
        "python tools/dev/verify_plugin_mirrors.py"
    )


def test_education_mirror_file_set_matches_canonical():
    """File-SET parity for the education payload — catches a NEW canonical file
    that was never synced (invisible to the hash check, which only walks
    payload→canonical)."""
    check = release_gate.check_education_payload_set()
    assert check.ok, "\n".join(check.details)


# ---------------------------------------------------------------------------
# B — release_gate unit tests (pure parts + probe against the current stage)
# ---------------------------------------------------------------------------

def test_release_gate_template_rules_shape():
    templates = {rel.as_posix() for rel in release_gate.iter_seedable_config_templates(REPO_ROOT)}
    # The three flag files and the OAuth template are in.
    for required in (*FEATURE_FLAG_CONFIG_FILES, "identity/google_oauth.json", "servers.json"):
        assert required in templates
    # Excluded material is out.
    assert "installation_profile.json" not in templates
    assert not any(t.endswith(".gitignore") for t in templates)
    assert not any("/secrets/" in f"/{t}" or t.startswith("secrets/") for t in templates)


def test_release_gate_collect_code_symbols_walks_nested_code():
    src = "def outer():\n    def migrate_user_config_defaults():\n        return 'consultation'\n"
    code = compile(src, "<gate-test>", "exec")
    names, strings = release_gate.collect_code_symbols(code)
    assert "migrate_user_config_defaults" in names
    assert "consultation" in strings


_STAGE_EXE = release_gate.STAGE_CORE_DIR / "AIPacs.exe"


@pytest.mark.skipif(not _STAGE_EXE.exists(), reason="no staged build at builder/output/stage/core — run builder/build_release.py first")
def test_release_gate_pyz_probe_against_current_stage():
    """The staged AIPacs.exe's frozen aipacs_runtime must carry the current
    MODULE_CATALOG ids and the config-migration sentinels. Skips when no stage
    output exists (e.g. fresh clones / CI without a build)."""
    check = release_gate.check_frozen_runtime()
    assert check.ok, "\n".join([check.status] + check.details)


@pytest.mark.skipif(not _STAGE_EXE.exists(), reason="no staged build at builder/output/stage/core — run builder/build_release.py first")
def test_release_gate_stage_config_parity_against_current_stage():
    check = release_gate.check_stage_config_parity()
    assert check.ok, "\n".join([check.status] + check.details)


# ---------------------------------------------------------------------------
# C — source-freshness gate (2026-06-16): the "built from a stale checkout"
# guard. A secondary build PC parked on an OLD branch (the p2 remote's default
# 'DR.vahid', v2.2.x) froze pre-v3.2.0 MPR bytecode while all dev lands on
# beta-version/main. release_gate.check_source_freshness() now fails the build
# FAST (pre-build) when the working tree is not current release source.
# ---------------------------------------------------------------------------

_IS_GIT_WORKTREE = (REPO_ROOT / ".git").exists()


def test_source_freshness_skip_flag_is_non_blocking(monkeypatch):
    """AIPACS_SKIP_SOURCE_FRESHNESS opts out without failing the build (WARN)."""
    monkeypatch.setenv("AIPACS_SKIP_SOURCE_FRESHNESS", "1")
    check = release_gate.check_source_freshness()
    assert check.status == "WARN"
    assert check.ok  # WARN never blocks a build


def test_release_branches_env_parsing(monkeypatch):
    """_release_branches(): default set, comma/semicolon override, empty disables."""
    monkeypatch.delenv("AIPACS_RELEASE_BRANCHES", raising=False)
    assert release_gate._release_branches() == set(release_gate._DEFAULT_RELEASE_BRANCHES)

    monkeypatch.setenv("AIPACS_RELEASE_BRANCHES", "main, release/x ; hotfix")
    assert release_gate._release_branches() == {"main", "release/x", "hotfix"}

    monkeypatch.setenv("AIPACS_RELEASE_BRANCHES", "")
    assert release_gate._release_branches() == set()  # branch check disabled


@pytest.mark.skipif(not _IS_GIT_WORKTREE, reason="not a git work tree")
def test_source_freshness_offbranch_fails_then_override(monkeypatch):
    """An off-release branch FAILS the gate; AIPACS_ALLOW_OFFBRANCH_BUILD clears it.

    Offline (AIPACS_SKIP_GIT_FETCH) so the 'behind upstream' signal can't add a
    second, network-dependent failure and make the assertion flaky.
    """
    monkeypatch.setenv("AIPACS_SKIP_GIT_FETCH", "1")
    monkeypatch.delenv("AIPACS_SKIP_SOURCE_FRESHNESS", raising=False)
    monkeypatch.delenv("AIPACS_ALLOW_OFFBRANCH_BUILD", raising=False)
    # No real branch is named this, so the current branch is never allow-listed.
    monkeypatch.setenv("AIPACS_RELEASE_BRANCHES", "__no_such_release_branch__")

    failed = release_gate.check_source_freshness()
    # If the probe could not evaluate git it returns WARN — only assert the FAIL
    # contract when it actually reached the branch check.
    if failed.status == "FAIL":
        assert any("not a release branch" in d for d in failed.details)
        monkeypatch.setenv("AIPACS_ALLOW_OFFBRANCH_BUILD", "1")
        assert release_gate.check_source_freshness().ok
