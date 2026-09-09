"""Fail-before guards for the canonical multi-remote Git release workflow."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tools.git import release_manager as manager


VERSION = "9.9.9"


def run_git(repo: Path, *args: str) -> str:
    return manager._git(repo, *args).stdout.strip()


@pytest.fixture()
def release_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "--initial-branch=beta-version")
    run_git(repo, "config", "user.email", "release-test@invalid.example")
    run_git(repo, "config", "user.name", "Release Test")
    (repo / "PacsClient/pacs/workstation_ui/home_ui").mkdir(parents=True)
    (repo / "docs/releases").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(f'[project]\nversion = "{VERSION}"\n', encoding="utf-8")
    (repo / "main.py").write_text(f'app.setApplicationVersion("{VERSION}")\n', encoding="utf-8")
    (repo / "PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py").write_text(
        f'RELEASE_INFO = {{"version": "{VERSION}"}}\n', encoding="utf-8"
    )
    (repo / "docs/releases/RELEASE_NOTES.md").write_text(
        f"## v{VERSION} (unreleased) - Synthetic release\n", encoding="utf-8"
    )
    (repo / f"docs/releases/VERSION_{VERSION}_RELEASE.md").write_text(
        "# Synthetic release record\n\nSource publication status: READY\n", encoding="utf-8"
    )
    run_git(repo, "add", "--all")
    run_git(repo, "commit", "-m", f"release(v{VERSION}): verify synthetic workflow")
    head = run_git(repo, "rev-parse", "HEAD")
    for target in manager.load_policy()["targets"]:
        run_git(repo, "remote", "add", target["remote"], target["url"])
        for branch in target["branches"]:
            run_git(repo, "update-ref", f"refs/remotes/{target['remote']}/{branch}", head)
    return repo


def test_release_policy_covers_every_required_repository_and_branch():
    policy = manager.load_policy()
    assert {
        (target["remote"], target["url"], tuple(target["branches"]))
        for target in policy["targets"]
    } == {
        ("origin", "https://github.com/Vahid-INO/ai-pacs.git", ("beta-version", "main")),
        ("p2", "https://github.com/satardavoodi/PacsClientV2.git", ("beta-version", "main")),
        ("satar", "https://github.com/satardavoodi/pacsClientV3.git", ("beta-version", "main")),
    }


def test_clean_release_commit_passes_offline_audit(release_repo: Path):
    report = manager.audit_release(release_repo, VERSION, refresh=False)
    assert report["ok"]
    statuses = {item["name"]: item["status"] for item in report["checks"]}
    assert statuses["clean_worktree"] == "PASS"
    assert statuses["release_commit"] == "PASS"
    assert statuses["fast_forward:origin/main"] == "PASS"
    assert statuses["fast_forward:p2/beta-version"] == "PASS"
    assert statuses["fast_forward:satar/main"] == "PASS"
    assert statuses["local_tag"] == "READY"


def test_dirty_tree_blocks_before_remote_access(release_repo: Path):
    (release_repo / "unreviewed.py").write_text("UNREVIEWED = True\n", encoding="utf-8")
    report = manager.audit_release(release_repo, VERSION, refresh=True)
    assert not report["ok"]
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["clean_worktree"]["status"] == "FAIL"
    assert checks["remote_freshness"]["status"] == "BLOCKED"
    assert not any(item["name"].startswith("fast_forward:") for item in report["checks"])


def test_secret_scan_reports_location_but_never_value(release_repo: Path):
    token = "sk-" + "A" * 40
    (release_repo / "credential.py").write_text(f'TOKEN = "{token}"\n', encoding="utf-8")
    run_git(release_repo, "add", "credential.py")
    run_git(release_repo, "commit", "-m", f"release(v{VERSION}): add unsafe fixture")
    report = manager.audit_release(release_repo, VERSION, refresh=True)
    finding = next(item for item in report["checks"] if item["name"] == "tracked_secret_scan")
    assert finding["status"] == "FAIL"
    assert "credential.py:1" in finding["detail"]
    assert token not in json.dumps(report)


def test_sync_receipt_is_bound_to_head_version_policy_and_all_targets(release_repo: Path, tmp_path: Path):
    head = run_git(release_repo, "rev-parse", "HEAD")
    run_git(release_repo, "tag", "-a", "v" + VERSION, "-m", "Synthetic annotated release tag", head)
    tag_object = run_git(release_repo, "rev-parse", "refs/tags/v" + VERSION)
    policy = manager.load_policy()
    receipt = {
        "schema_version": 1,
        "version": VERSION,
        "tag": "v" + VERSION,
        "tag_object": tag_object,
        "commit": head,
        "policy_sha256": manager.policy_digest(),
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "targets": [
            {
                "remote": target["remote"],
                "url": target["url"],
                "branches": {branch: head for branch in target["branches"]},
                "tag_object": tag_object,
                "tag_commit": head,
            }
            for target in policy["targets"]
        ],
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert manager.validate_sync_receipt(path, release_repo, VERSION)["commit"] == head
    receipt["targets"].pop()
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(manager.ReleaseError, match="every required target"):
        manager.validate_sync_receipt(path, release_repo, VERSION)


def test_publish_requires_literal_execute_and_complete_sha(release_repo: Path):
    head = run_git(release_repo, "rev-parse", "HEAD")
    with pytest.raises(manager.ReleaseError, match="--execute"):
        manager.publish_release(release_repo, VERSION, head, execute=False)
    with pytest.raises(manager.ReleaseError, match="40-character"):
        manager.publish_release(release_repo, VERSION, head[:12], execute=True)


def test_remote_url_and_git_errors_never_expose_embedded_credentials():
    secret = "sensitive-user-token"
    configured = f"https://{secret}@github.com/Vahid-INO/ai-pacs.git"
    displayed = manager._display_remote_url(configured)
    assert displayed == "https://github.com/vahid-ino/ai-pacs"
    assert secret not in displayed
    assert secret not in manager._redacted_message(f"fatal: https://{secret}@github.com failed")
