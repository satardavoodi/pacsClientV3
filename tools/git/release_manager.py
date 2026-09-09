"""Fail-closed AI-PACS Git release audit, publication, and synchronization receipt.

The release unit is one immutable commit. The same commit and annotated version
tag are pushed explicitly to every branch in ``release_targets.json``. There is
no force-push path and no implicit use of Git's default push configuration.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from urllib.parse import urlparse


REPO = Path(__file__).resolve().parents[2]
POLICY_PATH = Path(__file__).with_name("release_targets.json")
RECEIPT_DIR = REPO / "generated-files" / "release-git"
FULL_SHA = re.compile(r"[0-9a-f]{40}")


class ReleaseError(RuntimeError):
    """A release invariant was not satisfied."""


def _redacted_message(value: str) -> str:
    value = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", value)
    value = re.sub("s" + r"k-(?:proj-)?[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
    value = re.sub("g" + r"h[pousr]_[A-Za-z0-9]{12,}", "[REDACTED]", value)
    return value


def _git(repo: Path, *args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Release commands must never hang behind an invisible credential prompt.
    env["GCM_INTERACTIVE"] = "Never"
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "credential.interactive=never", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )
    if check and result.returncode:
        message = (result.stderr or result.stdout or "Git command failed").strip()
        raise ReleaseError(_redacted_message(message.splitlines()[-1]))
    return result


def load_policy(path: Path = POLICY_PATH) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1:
        raise ReleaseError("Unsupported release target policy schema")
    targets = policy.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ReleaseError("Release target policy has no targets")
    remotes = [target.get("remote") for target in targets]
    if len(remotes) != len(set(remotes)):
        raise ReleaseError("Release target policy contains duplicate remotes")
    for target in targets:
        if not target.get("url") or not target.get("branches"):
            raise ReleaseError("Every release target requires a URL and branches")
        if len(target["branches"]) != len(set(target["branches"])):
            raise ReleaseError(f"Duplicate branch in target {target['remote']}")
    return policy


def policy_digest(path: Path = POLICY_PATH) -> str:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_github_url(value: str) -> str:
    value = value.strip().replace("\\", "/")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.split(":", 1)[1]
    parsed = urlparse(value)
    if parsed.hostname and parsed.hostname.lower() == "github.com":
        path = parsed.path.rstrip("/")
        if path.lower().endswith(".git"):
            path = path[:-4]
        return "github.com/" + path.strip("/").lower()
    return value.rstrip("/").removesuffix(".git").lower()


def _display_remote_url(value: str) -> str:
    if not value:
        return "missing"
    normalized = _normalized_github_url(value)
    return "https://" + normalized if normalized.startswith("github.com/") else "configured (redacted)"


def _version_values(repo: Path) -> dict[str, str | None]:
    project = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    sources = {
        "pyproject.toml": str(project["project"]["version"]),
        "main.py": None,
        "Information panel": None,
    }
    main_text = (repo / "main.py").read_text(encoding="utf-8")
    match = re.search(r'app\.setApplicationVersion\("([^"\r\n]+)"\)', main_text)
    if match:
        sources["main.py"] = match.group(1)
    info_text = (repo / "PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r'"version"\s*:\s*"([^"\r\n]+)"', info_text)
    if match:
        sources["Information panel"] = match.group(1)
    return sources


def _secret_findings(repo: Path) -> list[dict[str, object]]:
    """Return high-confidence tracked-tree findings without returning secret values."""
    # Tokens are split so the scanner does not match its own source definitions.
    patterns = {
        "private-key": re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "google-api-key": re.compile("AI" + r"za[0-9A-Za-z_-]{35}"),
        "openai-api-key": re.compile("s" + r"k-(?:proj-)?[A-Za-z0-9_-]{20,}"),
        "github-token": re.compile("g" + r"h[pousr]_[A-Za-z0-9]{30,}"),
        "github-pat": re.compile("github_" + r"pat_[A-Za-z0-9_]{20,}"),
        "aws-access-key": re.compile("AK" + r"IA[0-9A-Z]{16}"),
    }
    names = _git(repo, "ls-files", "-z").stdout.split("\0")
    findings: list[dict[str, object]] = []
    for name in names:
        if not name:
            continue
        path = repo / name
        try:
            if not path.is_file() or path.stat().st_size > 5_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for kind, pattern in patterns.items():
                if pattern.search(line):
                    findings.append({"path": name.replace("\\", "/"), "line": line_number, "kind": kind})
    return findings


def _remote_refs(repo: Path, remote: str, policy: dict, *, refresh: bool) -> dict[str, str]:
    target = next(item for item in policy["targets"] if item["remote"] == remote)
    if refresh:
        refspecs = [
            f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}"
            for branch in target["branches"]
        ]
        _git(repo, "fetch", "--no-tags", remote, *refspecs, timeout=300)
    refs: dict[str, str] = {}
    for branch in target["branches"]:
        result = _git(repo, "rev-parse", "--verify", f"refs/remotes/{remote}/{branch}", check=False)
        if result.returncode == 0:
            refs[branch] = result.stdout.strip()
    return refs


def audit_release(repo: Path, version: str, *, refresh: bool = True) -> dict:
    repo = repo.resolve()
    policy = load_policy()
    checks: list[dict[str, object]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    branch = _git(repo, "branch", "--show-current").stdout.strip()
    add("source_branch", branch == policy["source_branch"], f"branch={branch or '(detached)'}")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
    dirty_count = len(status.splitlines()) if status else 0
    add("clean_worktree", dirty_count == 0, f"dirty_paths={dirty_count}")
    operation_names = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
    active = []
    for name in operation_names:
        git_path = _git(repo, "rev-parse", "--git-path", name).stdout.strip()
        if (repo / git_path).exists() if not Path(git_path).is_absolute() else Path(git_path).exists():
            active.append(name)
    add("no_git_operation", not active, "active=" + (",".join(active) if active else "none"))

    versions = _version_values(repo)
    add("version_parity", all(value == version for value in versions.values()),
        ", ".join(f"{key}={value or 'missing'}" for key, value in versions.items()))
    release_notes = (repo / "docs/releases/RELEASE_NOTES.md").read_text(encoding="utf-8")
    add("release_notes", f"## v{version} " in release_notes, f"v{version} heading")
    release_doc = repo / "docs" / "releases" / f"VERSION_{version}_RELEASE.md"
    release_record_ready = False
    if release_doc.is_file():
        record_text = release_doc.read_text(encoding="utf-8")
        release_record_ready = bool(
            re.search(r"(?m)^Source publication status: READY\s*$", record_text)
        )
    add("release_record", release_record_ready,
        release_doc.relative_to(repo).as_posix() +
        (" (READY)" if release_record_ready else " (missing or BLOCKED)"))
    subject = _git(repo, "show", "-s", "--format=%s", "HEAD").stdout.strip()
    subject_ok = subject.startswith(f"release(v{version}): ")
    add("release_commit", subject_ok,
        f"expected_prefix=release(v{version}): actual_match={'yes' if subject_ok else 'no'}")

    findings = _secret_findings(repo)
    finding_locations = ", ".join(
        f"{item['path']}:{item['line']} ({item['kind']})" for item in findings[:12]
    )
    if len(findings) > 12:
        finding_locations += f", and {len(findings) - 12} more"
    add("tracked_secret_scan", not findings, finding_locations or "no high-confidence token patterns")

    for target in policy["targets"]:
        name = target["remote"]
        configured = _git(repo, "remote", "get-url", "--push", name, check=False)
        actual_url = configured.stdout.strip() if configured.returncode == 0 else ""
        url_ok = bool(actual_url) and _normalized_github_url(actual_url) == _normalized_github_url(target["url"])
        add(f"remote_url:{name}", url_ok, _display_remote_url(actual_url))

    # Avoid credential prompts and misleading partial network results until all
    # local release preparation is complete.
    local_ok = all(item["status"] == "PASS" for item in checks)
    if local_ok:
        tag = policy["tag_prefix"] + version
        local_tag_ref = _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}", check=False)
        local_tag_object = local_tag_ref.stdout.strip() if local_tag_ref.returncode == 0 else None
        local_tag_type = (
            _git(repo, "cat-file", "-t", f"refs/tags/{tag}", check=False).stdout.strip()
            if local_tag_object else None
        )
        for target in policy["targets"]:
            remote = target["remote"]
            try:
                refs = _remote_refs(repo, remote, policy, refresh=refresh)
            except (ReleaseError, subprocess.TimeoutExpired) as exc:
                add(f"remote_access:{remote}", False, type(exc).__name__ + ": authentication or network unavailable")
                continue
            for target_branch in target["branches"]:
                remote_head = refs.get(target_branch)
                if not remote_head:
                    add(f"fast_forward:{remote}/{target_branch}", False, "remote branch missing")
                    continue
                ancestor = _git(repo, "merge-base", "--is-ancestor", remote_head, head, check=False).returncode == 0
                add(f"fast_forward:{remote}/{target_branch}", ancestor,
                    f"remote={remote_head[:12]} local={head[:12]}")

            if refresh:
                try:
                    published = _ls_remote_release(repo, remote, target["branches"], tag)
                    remote_tag_object = published.get(f"refs/tags/{tag}")
                    remote_tag_commit = published.get(f"refs/tags/{tag}^{{}}") or remote_tag_object
                    if remote_tag_object:
                        tag_ok = (
                            local_tag_object is not None
                            and remote_tag_object == local_tag_object
                            and remote_tag_commit == head
                        )
                        add(f"remote_tag:{remote}", tag_ok,
                            f"{tag} object={remote_tag_object[:12]} commit={remote_tag_commit[:12]}")
                    else:
                        checks.append({"name": f"remote_tag:{remote}", "status": "READY",
                                       "detail": f"{tag} will be created"})
                except (ReleaseError, subprocess.TimeoutExpired) as exc:
                    add(f"remote_tag:{remote}", False,
                        type(exc).__name__ + ": authentication or network unavailable")

        tag_result = _git(repo, "rev-list", "-n", "1", tag, check=False)
        if tag_result.returncode == 0:
            add("local_tag", tag_result.stdout.strip() == head and local_tag_type == "tag",
                f"{tag}={tag_result.stdout.strip()[:12]} type={local_tag_type or 'missing'} local={head[:12]}")
        else:
            checks.append({"name": "local_tag", "status": "READY", "detail": f"{tag} will be created"})
    else:
        checks.append({"name": "remote_freshness", "status": "BLOCKED",
                       "detail": "local release checks must pass before network access"})

    return {
        "schema_version": 1,
        "version": version,
        "head": head,
        "branch": branch,
        "policy_sha256": policy_digest(),
        "checks": checks,
        "ok": all(item["status"] in {"PASS", "READY"} for item in checks),
    }


def _ls_remote_release(repo: Path, remote: str, branches: list[str], tag: str) -> dict:
    patterns = [*(f"refs/heads/{branch}" for branch in branches), f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"]
    result = _git(repo, "ls-remote", remote, *patterns, timeout=180)
    return {ref: sha for sha, ref in (line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line)}


def publish_release(repo: Path, version: str, expected_head: str, *, execute: bool) -> Path:
    if not execute:
        raise ReleaseError("Publication requires the literal --execute flag")
    if not FULL_SHA.fullmatch(expected_head):
        raise ReleaseError("--expected-head must be the complete 40-character commit SHA")
    repo = repo.resolve()
    actual_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if actual_head != expected_head:
        raise ReleaseError(f"HEAD changed: expected {expected_head}, found {actual_head}")
    report = audit_release(repo, version, refresh=True)
    if not report["ok"]:
        raise ReleaseError("Release audit failed; nothing was pushed")
    policy = load_policy()
    tag = policy["tag_prefix"] + version
    tag_commit = _git(repo, "rev-list", "-n", "1", tag, check=False)
    if tag_commit.returncode != 0:
        _git(repo, "tag", "-a", tag, "-m", f"AI-PACS {tag} release", expected_head)
    elif tag_commit.stdout.strip() != expected_head:
        raise ReleaseError(f"Existing tag {tag} points to another commit")
    tag_object = _git(repo, "rev-parse", f"refs/tags/{tag}").stdout.strip()

    for target in policy["targets"]:
        refspecs = [f"{expected_head}:refs/heads/{branch}" for branch in target["branches"]]
        refspecs.append(f"refs/tags/{tag}:refs/tags/{tag}")
        _git(repo, "push", "--atomic", "--porcelain", target["remote"], *refspecs, timeout=900)

    verified_targets = []
    for target in policy["targets"]:
        refs = _ls_remote_release(repo, target["remote"], target["branches"], tag)
        branch_refs = {branch: refs.get(f"refs/heads/{branch}") for branch in target["branches"]}
        remote_tag_object = refs.get(f"refs/tags/{tag}")
        peeled_tag = refs.get(f"refs/tags/{tag}^{{}}") or remote_tag_object
        if (any(value != expected_head for value in branch_refs.values())
                or peeled_tag != expected_head or remote_tag_object != tag_object):
            raise ReleaseError(f"Post-push verification failed for remote {target['remote']}")
        verified_targets.append({
            "remote": target["remote"],
            "url": target["url"],
            "branches": branch_refs,
            "tag_object": remote_tag_object,
            "tag_commit": peeled_tag,
        })

    receipt = {
        "schema_version": 1,
        "version": version,
        "tag": tag,
        "tag_object": tag_object,
        "commit": expected_head,
        "policy_sha256": policy_digest(),
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "targets": verified_targets,
    }
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = RECEIPT_DIR / f"{tag}-{expected_head[:12]}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def validate_sync_receipt(receipt_path: Path, repo: Path, version: str) -> dict:
    policy = load_policy()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    head = _git(repo.resolve(), "rev-parse", "HEAD").stdout.strip()
    if receipt.get("schema_version") != 1:
        raise ReleaseError("Unsupported Git synchronization receipt schema")
    if receipt.get("version") != version or receipt.get("tag") != policy["tag_prefix"] + version:
        raise ReleaseError("Git synchronization receipt version does not match the build")
    if receipt.get("commit") != head:
        raise ReleaseError("Git synchronization receipt does not match current HEAD")
    if receipt.get("policy_sha256") != policy_digest():
        raise ReleaseError("Git synchronization target policy changed after publication")
    verified_at = datetime.fromisoformat(str(receipt.get("verified_at_utc", "")).replace("Z", "+00:00"))
    if verified_at.tzinfo is None:
        raise ReleaseError("Git synchronization receipt timestamp has no timezone")
    max_age = timedelta(hours=float(policy["receipt_max_age_hours"]))
    age = datetime.now(timezone.utc) - verified_at.astimezone(timezone.utc)
    if age < timedelta(minutes=-5):
        raise ReleaseError("Git synchronization receipt timestamp is in the future")
    if age > max_age:
        raise ReleaseError("Git synchronization receipt is stale; verify and publish again")
    expected_targets = {
        (item["remote"], item["url"], frozenset(item["branches"]))
        for item in policy["targets"]
    }
    actual_targets = set()
    tag_object = receipt.get("tag_object")
    if not isinstance(tag_object, str) or not FULL_SHA.fullmatch(tag_object):
        raise ReleaseError("Git synchronization receipt has no valid annotated tag object")
    local_tag_object = _git(
        repo.resolve(), "rev-parse", "--verify", f"refs/tags/{receipt['tag']}", check=False
    )
    local_tag_commit = _git(repo.resolve(), "rev-list", "-n", "1", receipt["tag"], check=False)
    local_tag_type = _git(repo.resolve(), "cat-file", "-t", f"refs/tags/{receipt['tag']}", check=False)
    if (local_tag_object.returncode != 0 or local_tag_object.stdout.strip() != tag_object
            or local_tag_commit.returncode != 0 or local_tag_commit.stdout.strip() != head
            or local_tag_type.returncode != 0 or local_tag_type.stdout.strip() != "tag"):
        raise ReleaseError("Local annotated release tag does not match the synchronization receipt")
    for item in receipt.get("targets", []):
        branches = item.get("branches", {})
        if (any(value != head for value in branches.values()) or item.get("tag_commit") != head
                or item.get("tag_object") != tag_object):
            raise ReleaseError("Git synchronization receipt contains inconsistent refs")
        actual_targets.add((item.get("remote"), item.get("url"), frozenset(branches)))
    if actual_targets != expected_targets:
        raise ReleaseError("Git synchronization receipt does not cover every required target")
    status = _git(repo.resolve(), "status", "--porcelain=v1", "--untracked-files=all").stdout
    if status:
        raise ReleaseError("Working tree changed after Git synchronization")
    return receipt


def _print_report(report: dict) -> None:
    for check in report["checks"]:
        print(f"[{check['status']}] {check['name']}: {check['detail']}")
    print(f"VERDICT: {'READY' if report['ok'] else 'BLOCKED'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "publish"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--offline", action="store_true", help="Use cached remote refs during audit only")
    parser.add_argument("--expected-head")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            report = audit_release(args.repo, args.version, refresh=not args.offline)
            _print_report(report)
            return 0 if report["ok"] else 1
        if not args.expected_head:
            parser.error("publish requires --expected-head")
        path = publish_release(args.repo, args.version, args.expected_head, execute=args.execute)
        print(f"Release synchronized and verified. Receipt: {path}")
        return 0
    except (ReleaseError, subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
