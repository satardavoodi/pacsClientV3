# AI-PACS canonical Git release workflow

Status: authoritative for versioned source publication and the Git prerequisite
for a full installer build. Audience: human maintainers and AI agents.

Documentation map: [`docs/release-and-build/README.md`](docs/release-and-build/README.md).

`BUILD.md` remains authoritative for compilation and installer QA. This file is
the only source of truth for deciding what is committed, tagged, and pushed
before that build begins.

## 1. Immutable release unit and destinations

A release is one reviewed commit SHA plus one annotated `v<version>` tag. The
same SHA must be present on both `beta-version` and `main` in all three configured
repositories:

| Remote | Repository | Required branches |
|---|---|---|
| `origin` | `Vahid-INO/ai-pacs` | `beta-version`, `main` |
| `p2` | `satardavoodi/PacsClientV2` | `beta-version`, `main` |
| `satar` | `satardavoodi/pacsClientV3` | `beta-version`, `main` |

The machine-readable authority is `tools/git/release_targets.json`. Do not add a
new destination only to a command line or local Git configuration. Review and
commit the policy change first.

The release manager names every remote, branch, commit, and tag explicitly. It
never relies on `push.default`, never uses a wildcard refspec, and has no force-
push option. Per-remote pushes are atomic. Git cannot make three different
servers atomic as one transaction; if a later remote is unavailable, rerun the
same command with the same SHA after restoring access. Already synchronized refs
remain idempotent.

## 2. Required order

### Step A — freeze and review the source

1. Start on local `beta-version`. Inspect `git status --short --branch`, the full
   diff, untracked files, and staged diff. Do not reset, clean, pull, or switch a
   dirty checkout automatically.
2. Select the intended release scope deliberately. Generated output, installers,
   clinical data, local configuration, credentials, logs, caches, and recovered
   files must not enter the commit. Do not use an unreviewed `git add -A`.
3. Update all version authorities: `pyproject.toml`, `main.py`, the Information
   panel fallback, installer metadata, `docs/releases/RELEASE_NOTES.md`, and the
   version-specific release record.
4. Create `docs/releases/VERSION_<version>_RELEASE.md` from
   `docs/releases/RELEASE_TEMPLATE.md`. Record scope, evidence, exclusions,
   known risks, rollback, and approval state. Test counts must come from direct
   process exit codes, not an ambiguous wrapper.
5. Synchronize packaged mirrors when required, run their parity guard, run the
   version and subsystem regression guards, and review `git diff --check`.
6. Resolve every high-confidence secret finding. Never paste a detected value
   into a report. Historical credential exposure still requires rotation and
   history remediation; a clean current-tree scan does not undo prior exposure.

### Step B — create one release commit

Use this subject format:

```text
release(v<version>): <short outcome-oriented summary>
```

The body must summarize user-visible changes, compatibility or migration impact,
tests and manual acceptance, explicit exclusions, known blockers, and rollback.
Do not create different commits for different accounts. After committing, review:

```powershell
git show --stat --oneline HEAD
git diff HEAD^ HEAD --check
git status --short --branch
```

The worktree must now be clean. If another edit is required, make and review a
new commit before publication; do not amend a commit that has reached any remote.

### Step C — fail-closed audit

Run from the repository root with the supported development interpreter:

```powershell
$version = "3.6.5"
& .\.venv\Scripts\python.exe tools\git\release_manager.py audit --version $version
```

The audit checks the source branch, clean worktree, absence of an in-progress Git
operation, version parity, release notes, version-specific release record,
release commit subject, high-confidence tracked-tree secrets, exact remote URLs,
and fast-forward safety for every destination branch. Private repositories must
be accessible through the authenticated Git credential manager. Missing or
ambiguous authentication is a blocker, not an offline success.

`--offline` is diagnostic only. It uses cached remote refs and cannot authorize a
push or create a build receipt.

### Step D — publish only after explicit owner authorization

Copy the complete SHA printed by `git rev-parse HEAD`; do not use a short SHA:

```powershell
$version = "3.6.5"
$releaseHead = git rev-parse HEAD
& .\.venv\Scripts\python.exe tools\git\release_manager.py publish `
  --version $version `
  --expected-head $releaseHead `
  --execute
```

The literal `--execute` and exact 40-character SHA are required. The command
reruns the online audit, creates the annotated version tag if it does not exist,
pushes explicit refs atomically to each remote, reads every remote back, and only
then writes an ignored synchronization receipt under
`generated-files/release-git/`.

Do not manually move an existing version tag. If a published release is wrong,
revert it with a reviewed commit and issue the next patch version. Never reset or
force-push shared release branches.

## 3. Build handoff

A full PyInstaller + Nuitka candidate requires the fresh synchronization receipt
for the exact current HEAD and version:

```powershell
$version = "3.6.5"
$releaseHead = git rev-parse HEAD
$receipt = "generated-files\release-git\v$version-$($releaseHead.Substring(0, 12)).json"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$candidateRoot = "C:\b\aipacs-$version-$stamp"
$assetRoot = Join-Path (Get-Location).Path "generated-files\distribution-assets"
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --workspace $candidateRoot `
  --version $version `
  --asset-root $assetRoot `
  --git-sync-receipt $receipt
```

The receipt expires after four hours, is bound to the policy hash, version, tag,
current commit, all six remote branch refs, and all three tag refs. The candidate
runner also requires a clean checkout. This prevents a full release build from
silently using local work that was not committed and synchronized.

For disposable single-edition packaging work before source freeze, use the
documented `--internal --prepare-only` path in `BUILD.md`. Internal snapshots are
marked non-promotable and cannot run the canonical six-installer coordinator.

## 4. Failure and recovery rules

- Authentication or network failure: stop, restore account access, then rerun the
  audit. Do not substitute stale tracking refs as publication evidence.
- Remote branch is ahead or diverged: fetch and review its changes. Merge through
  the normal source workflow, retest, and create a new release commit. Do not
  overwrite it.
- One remote succeeded and a later remote failed: preserve the same commit and
  tag, fix access, and rerun publication. The receipt is not created until every
  remote verifies.
- Receipt expired or the worktree changed: audit and publish the reviewed current
  release commit again. A changed source requires a new commit; never edit around
  the receipt check.
- Build failure after successful publication: keep the Git release immutable,
  preserve build evidence, fix through a new commit/version when source changes,
  and use the build recovery rules in `BUILD.md` only for identical inputs.

## 5. Legacy command boundary

`tools/git/Push-GitHub.ps1` remains a connectivity helper for non-release feature
branches and dry runs. It is not a release tool and refuses a live single-remote
push to `main` or `beta-version`. A versioned release must use this workflow.
