# AI Agent Build Runbook — AI‑PACS Installer

**Audience:** an AI coding agent (or engineer) that builds the AI‑PACS Windows
installer on the build PC.
**Goal:** produce `builder/output/installer/ai-pacs installer v<version>.exe`
that contains **exactly the current release source** — no stale code.
**Last updated:** 2026‑06‑16.

> This runbook is the *driver*. For deeper detail it points to the canonical
> docs already in `builder/docs/`: `BUILD_CHECKLIST.md` (dependency audits +
> the dual‑location rule), `WINDOWS_RELEASE_FLOW.md` (commands, EULA contract,
> resumable flow), `ADVANCED_MPR_BUILD_RUNTIME_INTEGRATION.md`,
> `INSTALLER_QA_CHECKLIST.md`, and the regression record
> `docs/reports/MPR_GEOMETRY_BUILD_REGRESSION_2026-06-11.md`.

---

## 0. Prime directive — build only from CURRENT release source

The single most common failure on this project is **"I changed the code but the
installer still has the old behaviour."** It is almost never a build bug. It is
the build running against a **stale checkout**.

What happened on 2026‑06‑16: a clean build on the build PC failed the MPR
geometry gate (`PYZ_MPR_STALE`) because the clone was parked on an **old branch**
(the `p2` remote's default `DR.vahid`, v2.2.x) while all development lands on
`beta-version`/`main`. PyInstaller faithfully froze the old source; the gate
correctly refused to ship it.

**Therefore, before anything else, prove the working tree is the release source
(Step 1). The build also has a new pre‑build gate that enforces this — but you
should still verify it yourself.**

The build freezes Python **bytecode into a PYZ** and strips `.py` source from the
bundle (see `AIPacs.spec`). The running app executes that frozen bytecode, *not*
the on‑disk `.py`. So "the file on disk looks right" is **not** proof the
installer is right — only a clean rebuild from current source + passing gates is.

---

## 1. Source freshness (do this first, every time)

Run on the build PC, inside the repo:

```powershell
# 1a. Where am I, and on what?
git remote -v
git rev-parse --abbrev-ref HEAD        # branch — must be a RELEASE branch
git log --oneline -1                   # current commit

# 1b. Get the latest release source
git fetch --all --prune
git checkout main                      # or: beta-version (both are release branches)
git pull

# 1c. Prove you are at the release tip (no output = you ARE current)
git rev-list --count HEAD..@{u}        # MUST print 0  (0 commits behind upstream)
git status -s                          # review any uncommitted changes — they WILL be built
```

Pass criteria for this step:

- Branch is `main` or `beta-version` (the release branches). **Never build
  `DR.vahid`, `32bit`, `sadra`, or any `v2.2.x`/old branch.**
- `git rev-list --count HEAD..@{u}` prints **0** (you are not behind).
- The current commit is the intended release commit. If a version was just
  cut, `pyproject.toml` `version` should match it.

If you cannot satisfy these, **stop and fix the checkout** — do not build.

> The build now self‑checks this: `builder/release_gate.py::check_source_freshness`
> runs as the first pre‑build gate and **fails the build fast** (before the long
> PyInstaller run) if the tree is behind upstream or on a non‑release branch. You
> will see `[FAIL] source_freshness` with the remedy. Do not bypass it to "make
> the build go" — fix the source instead.

---

## 2. Environment prerequisites (one‑time per machine)

See `BUILD_CHECKLIST.md` for the authoritative list. Essentials:

- **Virtual env `.venv_build`** activated (`(.venv_build)` in the prompt). All
  commands below assume `python` = `.venv_build\Scripts\python.exe`.
- Dependencies installed: `builder/requirements/build_requirements.txt` **and**
  the project runtime deps (`requirements-core.txt`).
- **Inno Setup 6** installed (`ISCC.exe` at `C:\Program Files (x86)\Inno Setup 6\`
  or `C:\Program Files\Inno Setup 6\`). Needed to compile the installer.
- **`graphics_runtime/`** contains `opengl32sw.dll`, `osmesa.dll`,
  `pipe_swrast.dll` (software‑OpenGL fallback). The build fails without them.
- Quick dependency sanity (from `BUILD_CHECKLIST.md`):

  ```powershell
  python -c "import cv2; print('cv2 OK', cv2.__version__)"
  python -c "from modules.printing.data import get_series_for_study; print('main data OK')"
  ```

---

## 3. Pre‑build sanity (mirrors + version)

Plugin payloads under `builder/plugin package/packages/<name>/payload/python/...`
are the **production runtime** copies of `modules/<name>/...` (Dual‑Location Rule,
`BUILD_CHECKLIST.md`). If a module changed but its mirror did not, the installed
app runs old code.

```powershell
# Refresh + verify the plugin mirrors (must be clean before building)
python tools/dev/sync_plugin_mirrors.py
python tools/dev/verify_plugin_mirrors.py        # expect: all mirror pairs match

# Confirm the version you are about to build
python -c "import tomllib,pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])"
```

> The build also enforces mirror freshness in the pre‑build gate
> (`plugin_mirrors`) and an education file‑set check in the post‑stage gate.

---

## 4. Run the build (clean, logged)

For a **release**, use a clean build so a stale PyInstaller cache cannot leak old
bytecode. Tee the output to a log so it can be inspected.

```powershell
python build.py --clean-build 2>&1 | Tee-Object -FilePath "builder\output\build_v<version>_clean.log"
```

Notes:

- `build.py` forwards to `builder/build_release.py`. `--clean-build` wipes the
  PyInstaller cache + work dir and passes `--clean` to PyInstaller.
- A full clean build takes ~20–40 min (PyInstaller scan + ~1.4 GB bundle + ISCC).
- The build reads the **working tree**, so anything uncommitted is included
  (the `source_freshness` gate reports how many uncommitted changes there are).
- If a long compile is interrupted, resume with
  `python builder/run_resumable_build.py --status` then `... run_resumable_build.py`
  (see `WINDOWS_RELEASE_FLOW.md`).
- Incremental builds (`python build.py`, no `--clean-build`) are fine for
  iteration — the gates still verify the frozen PYZ — but prefer `--clean-build`
  for the artifact you actually ship.

---

## 5. Read the gates (this is the proof your code shipped)

The release gate runs in two phases and **must end with PASS**. Watch the log for:

**Pre‑build**

```
[PASS] source_freshness        HEAD=<sha> branch=main      ← you are on current release source
[PASS] plugin_mirrors          NNN mirror pair(s) match
RELEASE_GATE: PASS (pre-build) [...]
```

**Post‑stage (after PyInstaller, before ISCC)**

```
[OK] [MPR_GEOMETRY_GATE] frozen MPR geometry verified.      ← frozen bytecode has the current MPR fixes
RELEASE_GATE: PASS (post-stage) [frozen_runtime_pyz=PASS, stage_config_parity=PASS, stage_plugin_packages=PASS, education_payload_set=PASS]
Compiling Inno Setup installer ...
```

`frozen_runtime_pyz=PASS` and the `MPR_GEOMETRY_GATE` line are the direct proof
that the **bytecode inside `AIPacs.exe`** matches current source — not just the
files on disk.

---

## 6. On failure — decision tree (fix the cause, never bypass)

| Gate / message | Meaning | Fix |
|---|---|---|
| `[FAIL] source_freshness … not a release branch` | Building an old/wrong branch (e.g. `DR.vahid`) | `git checkout main && git pull`, then rebuild (Step 1). |
| `[FAIL] source_freshness … N commits BEHIND` | Forgot to pull | `git pull`, then rebuild. |
| `PYZ_MPR_STALE … MISSING marker …` | Frozen MPR bytecode predates the geometry fixes — **stale source or stale cache** | First re‑verify Step 1 (you are almost certainly on old source). If source is current, the cache is stale → rebuild with `--clean-build`. |
| `[FAIL] plugin_mirrors … DRIFTED` | A `modules/<name>` edit was not mirrored | `python tools/dev/sync_plugin_mirrors.py`, re‑verify, rebuild. |
| `[FAIL] education_payload_set` | New `modules/education` file never synced | `python tools/dev/sync_plugin_mirrors.py`, rebuild. |
| `[FAIL] stage_config_parity` | Staged `config/` differs from repo, or a `secrets/` file leaked | Rebuild clean; ensure no secret was added under `config/secrets/`. |
| `[FAIL] frozen_runtime_pyz … catalog ids do not match` | Frozen `aipacs_runtime` is stale (cache) | Rebuild with `--clean-build`. |
| PyInstaller missing graphics DLLs | `graphics_runtime/` incomplete | Restore the three Mesa DLLs (Step 2), rebuild. |
| Advanced MPR payload unavailable | Slicer runtime not assembled | `python tools/slicer/assemble_slicer_runtime.py`, or set `AIPACS_ALLOW_MISSING_ADVANCED_MPR=1` only if intentionally shipping without it. |

After any one targeted fix, **re‑run the build once** and re‑read the gates.

---

## 7. Verify the produced installer

```powershell
# Fresh artifact?
Get-Item "builder\output\installer\ai-pacs installer v<version>.exe" | Select-Object Name, Length, LastWriteTime
Get-FileHash "builder\output\installer\ai-pacs installer v<version>.exe" -Algorithm SHA256
```

- Confirm `LastWriteTime` is *this* build (not an older artifact of the same
  version number — same name can hide a stale file).
- The log must show `RELEASE_GATE: PASS (post-stage ...)` **and** the installer
  compile succeeding.
- Follow `INSTALLER_QA_CHECKLIST.md` for install‑time QA.
- After test‑installing, you can run the read‑only field diagnosis:
  `python tools/maintenance/install_doctor.py` (see its `--help`).

---

## 8. Hard rules — NEVER do these for a customer release

- **Never** set `AIPACS_ALLOW_STALE_MPR_PYZ=1`. It bypasses the MPR gate and
  ships stale MPR geometry — the exact failure this whole runbook prevents.
- **Never** pass `--skip-release-gate`. It is an emergencies‑only escape hatch;
  it disables the freshness, mirror, frozen‑PYZ, and config‑parity checks.
- **Never** build `DR.vahid` / `32bit` / `sadra` / any old `v2.x` branch.
- **Never** "make the build pass" by disabling a gate. A red gate means the
  artifact would be wrong — fix the source/cache, not the gate.

---

## 9. Override flags (legitimate, deliberate use only)

| Env var | Effect | When |
|---|---|---|
| `AIPACS_RELEASE_BRANCHES` | Comma/semicolon list of allowed release branches (default `beta-version,main`) | Your release branch has a different name. |
| `AIPACS_ALLOW_OFFBRANCH_BUILD=1` | Skip the release‑branch check in `source_freshness` | A deliberate test build off a feature branch. |
| `AIPACS_SKIP_GIT_FETCH=1` | `source_freshness` does not hit the network | Offline build; "behind" is then judged from the last fetch. |
| `AIPACS_SKIP_SOURCE_FRESHNESS=1` | Skip the source‑freshness check entirely | Non‑git/exported tree where git checks are meaningless. |
| `AIPACS_ALLOW_MISSING_ADVANCED_MPR=1` | Build without the Advanced‑MPR Slicer payload | Intentionally shipping the variant without it. |

These downgrade safety. Do not set them by default; record it when you do.

---

## 10. Happy‑path quick sequence (copy/paste)

```powershell
# 0. In the repo, in the .venv_build environment.
git fetch --all --prune
git checkout main
git pull
git rev-list --count HEAD..@{u}                 # must be 0

# 1. Mirrors + sanity
python tools/dev/sync_plugin_mirrors.py
python tools/dev/verify_plugin_mirrors.py

# 2. Clean, logged release build (gates ON)
python build.py --clean-build 2>&1 | Tee-Object -FilePath "builder\output\build_release.log"

# 3. Confirm both gate phases PASS in the log:
#      RELEASE_GATE: PASS (pre-build) ...
#      [OK] [MPR_GEOMETRY_GATE] frozen MPR geometry verified.
#      RELEASE_GATE: PASS (post-stage) ...

# 4. Verify the artifact
Get-ChildItem "builder\output\installer\ai-pacs installer v*.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
```

If every gate is green and the installer is freshly written, the build contains
the current code. If any gate is red, **go to §6 and fix the cause — do not
bypass.**

---

## 11. Optional: validate the gate logic itself

```powershell
python -m pytest tests/code/builder/test_release_parity_guards.py -q -p no:debugging
```

This includes the `source_freshness` tests (section C) added 2026‑06‑16.
