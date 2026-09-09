# Release commits are reverting shipped code — found while preparing v3.6.5

**Date:** 2026-09-03
**Found by:** build preparation for v3.6.5 (PyInstaller + Nuitka)
**Status:** builds NOT started. Restoration decision required first.
**Branch:** `beta-version`, HEAD `4ba24be8`

---

## 1. Summary

The v3.6.5 build was gated on a fast-lane run. The lane came back **71 failed**.
Investigating the failures showed they are **not stale guards**. The guards are
correct; the code they protect has been **deleted from the repository**, and it
was deleted by our own `release(...)` commits.

Four release commits each removed large blocks of previously-shipped, guarded
code. The removed symbols now exist **nowhere in tracked source** — only inside
the test files that guard them.

This is not a v3.6.5 regression. It has been accumulating since July.

---

## 2. Evidence

`git log -S <symbol> -- <path>` for each symbol the failing guards reference.
Every one shows the same two-commit shape: added by a feature/fix commit,
removed by a later release commit.

| Symbol (feature it implements) | Added by | Removed by |
|---|---|---|
| `scan_paths`, `local_paths_from_mime` — Lite Viewer external CD drag-drop import | `beacec08` v3.4.9, 07-12 | **`79b28137` release(v3.5.4), 07-19** |
| `AIPACS_DOWNLOAD_PAGINATION_SAFE` — batch>1 silent tail-drop fix | `47dd51ae` 06-19 *"fix(download): batch>1 silent tail-drop (data completeness) + guards"* | **`7662e10e` release(v3.5.5), 07-25** |
| `_decode_socket_payload` — tolerant socket payload decode | `44a454bf` v3.3.1, 06-16 | **`7662e10e`** |
| `_first_image_prime_size` — first-image prime | `2d1f7707` v3.3.3, 06-17 | **`7662e10e`** |
| `_poor_connectivity_active` — per-server Poor Connectivity mode | `cf11ab17` 06-19 | **`7662e10e`** |
| `AIPACS_FASTFAIL_OVERSIZE` — oversize fast-fail | `d7a6051e` v3.3.6, 06-21 | **`7662e10e`** |
| `_POOR_NET_KPIS` — poor-network KPI markers | `1abd9b0f` v3.3.7, 06-26 | **`7662e10e`** |
| `--arch`, `ARM64_BUILD` — Nuitka ARM64 / WoA installers | `550d73d5` 07-11 | **`69382766` release(v3.5.3), 07-16** |
| `container.status_rank` — status-flag stash (avoids GUI recompute) | `79b28137` 07-19 | **`37a59f4d` release(v3.5.7), 08-02** |
| progressive local-search wiring (`_progressive_local_enabled() and total > _LOCAL_SEARCH_BATCH`) | — | partial; helpers survive, call site removed |

### Commit shapes

```
79b28137  release(v3.5.4)   2026-07-19
  modules/cd_burner/portable_viewer/media_scan.py | 179 +----------------
  modules/cd_burner/portable_viewer/viewer_app.py | 251 +----------------
  2 files changed, 10 insertions(+), 420 deletions(-)

7662e10e  release(v3.5.5)   2026-07-25
  modules/download_manager/network/socket_client.py | 670 +--------------
  1 file changed, 23 insertions(+), 647 deletions(-)
```

647 lines removed from `socket_client.py` by a commit whose message advertises
multi-frame DICOM geometry, Offline Service delete and viewport-load fixes.
Nothing in that message describes removing the download-reliability stack.

### Why this happens

The history is full of commits phrased *"release: publish local working state"*,
*"publish full local state"*, *"Major local-state publication"*. Releases are
being made by **publishing a whole local tree snapshot over the repo** rather
than committing a reviewed diff. Anything present in the repo but absent from
that particular machine's working tree is silently deleted. Four consecutive
releases did exactly that.

This is the source-level twin of the failure the build runbook's "prime
directive" already warns about at build level: *building from a stale checkout*.
Here the stale checkout is not merely built — it is **committed**.

---

## 3. Clinical significance

`47dd51ae` was titled *"fix(download): batch>1 silent tail-drop (data
completeness) + guards"*. It fixed series **silently losing trailing images**
during multi-image batch download. That fix, its `AIPACS_DOWNLOAD_PAGINATION_SAFE`
kill switch, its `[INCOMPLETE_SERIES]` completeness guard and its
`[BATCH_TRACE]` diagnostics were all removed by `7662e10e`.

On a diagnostic workstation an incomplete series that presents as complete is a
patient-safety concern: a radiologist can read a truncated stack believing they
have the whole acquisition. **This should be treated as the priority item**,
independent of the v3.6.5 build.

The Lite Viewer removal (`79b28137`) is lower severity but user-visible: dropping
DICOM from File Explorer / the burned disc onto the portable viewer no longer
does anything — the exact defect `docs/pipelines/cd-burner-portable-viewer.md`
records as fixed on 2026-07-12.

---

## 4. Restoration is clean

None of the affected files has been modified since the commit that truncated
them. The deleting commit is still the tip for each. That makes restoration
low-risk — there is no later work to merge against.

| File | Pre-removal | Current | Untouched since |
|---|---|---|---|
| `modules/download_manager/network/socket_client.py` | 2197 lines (`7662e10e^`) | 1632 | 2026-07-25 |
| `modules/cd_burner/portable_viewer/viewer_app.py` | 1515 lines (`79b28137^`) | 1306 | 2026-07-19 |
| `modules/cd_burner/portable_viewer/media_scan.py` | 473 lines (`79b28137^`) | 322 | 2026-07-19 |
| `builder nuitka/build_nuitka_release.py` | 1824 lines (`69382766^`) | 1748 | 2026-07-16 |

Suggested approach per file: diff the pre-removal blob against the current file,
re-apply **only the deletion hunks**, and keep the small number of genuine
insertions the release commit also made (23 lines in `7662e10e`, 10 in
`79b28137`). Then re-run the corresponding guard suite — each guard must go from
red to green, which is the proof the fix is actually back.

Restoration order, by severity:

1. `socket_client.py` — data completeness. Guards: `test_pagination_completeness`
   (8), `test_first_image_prime` (6), `test_poor_connectivity_mode` (5),
   `test_socket_payload_tolerant_decode` (5), `test_oversize_fastfail` (4),
   `test_poor_network_kpis` (1).
2. `viewer_app.py` + `media_scan.py` — Lite Viewer drop import. Guards:
   `test_lite_viewer_external_drop` (16), `test_cd_defaults_on_fresh_install` (2).
3. `build_nuitka_release.py` + `AIPacs_Nuitka_Setup.iss` — ARM64/WoA installer
   parity. Guards: `test_nuitka_arm64_parity` (6).
4. `patient_table_widget.py` `status_rank` stash (1), progressive local search (4).

After each restoration the plugin mirrors must be re-synced
(`tools/dev/sync_plugin_mirrors.py`) — `download_manager` and `cd_burner`
payloads carry mirrored copies, and the mirror currently matches the truncated
source, so `verify_plugin_mirrors.py` reports 462/462 clean while both sides are
missing the same code. **A green mirror check is not evidence the code is
present.**

---

## 5. Corrected lane baseline

Re-run with a correct environment (`WINDIR` set, `AIPACS_SKIP_GIT_FETCH=1`):

```
62 failed, 10033 passed, 69 skipped, 77 xfailed, 9 xpassed, 1 error  in 4m37s
```

Attribution of the 62:

| Count | Cluster | Root cause |
|---|---|---|
| 16 | `cd_burner/test_lite_viewer_external_drop` | deleted by `79b28137` |
| 2 | `cd_burner/test_cd_defaults_on_fresh_install` | deleted by `79b28137` |
| 8 | `download_manager/test_pagination_completeness` | deleted by `7662e10e` |
| 6 | `download_manager/test_first_image_prime` | deleted by `7662e10e` |
| 5 | `download_manager/test_poor_connectivity_mode` | deleted by `7662e10e` |
| 5 | `download_manager/test_socket_payload_tolerant_decode` | deleted by `7662e10e` |
| 4 | `download_manager/test_oversize_fastfail` | deleted by `7662e10e` |
| 1 | `download_manager/test_poor_network_kpis` | deleted by `7662e10e` |
| 1 err | `download_manager/test_instance_payload_key_variants` | `_INSTANCE_PAYLOAD_KEYS`, `_extract_instance_payload` deleted by `7662e10e` |
| 6 | `builder/test_nuitka_arm64_parity` | deleted by `69382766` |
| 1 | `ui_services/test_status_report_sorting` | `status_rank` stash deleted by `37a59f4d` |
| 4 | `system/test_local_search_progressive` | progressive call site removed |
| 1 | `builder/test_release_parity_guards` | stale stage `patient_table_sort.json` (known, see VERSION_3.6.5_BUILD.md) |
| 1 | `ui_services/test_report_assign_rendering` | login `user_id` identity — unclassified |
| 2 | `viewer/test_fast_viewer_pipeline` | did not fail in the prior run — suspected flaky, unconfirmed |

**54 of 62 are directly traceable to the four release-commit deletions.**

### Correction to the first count

9 of the originally reported 71 failures were an artifact of the environment used
to run the lane, not repository state: `WINDIR` was unset in the spawned shell, so
`qtawesome` failed with `TypeError: expected str, bytes or os.PathLike object,
not NoneType` while resolving the Windows fonts directory. With `WINDIR` set,
`tests/code/ui_services/test_field_icon_chip.py` (5) and
`test_local_incremental_and_import_date.py` (4) pass.

Two further caveats about the lane as run:

- `test_profile_switch_requires_restart` does `REPO_ROOT.rglob("*.py")` across
  the whole repo, which now includes `.venv*` and multi-GB build output trees.
  It times out rather than failing on logic. That guard needs a scoped root.
- `tests/code/builder/test_release_parity_guards.py` calls
  `release_gate.check_source_freshness`, which runs `git fetch` and **hangs on
  the GitHub credential prompt** — the same credential problem recorded in
  `VERSION_3.6.4_RELEASE.md` §10. Offline runs need `AIPACS_SKIP_GIT_FETCH=1`;
  that is a test-run workaround only and is **not** release approval.

---

## 6. Process fix — otherwise this recurs at v3.6.5

The immediate restoration does not prevent the next release from deleting it
again. Minimum guard:

1. **Never publish a release by copying a working tree over the repo.** Commit
   reviewed diffs. If a snapshot publish is unavoidable, diff it against `HEAD`
   first and require sign-off on every deletion.
2. **Fail the release on unexplained deletions.** Add a pre-commit/pre-release
   check: if a release commit deletes more than N lines from a file whose guard
   suite exists, block until acknowledged. `7662e10e` would have tripped this at
   647 lines.
3. **Run the whole fast lane before tagging, not per-domain gates.** The v3.6.4
   record gates AI Imaging, viewer, system, ui_services and fast_viewer. It does
   not gate `download_manager`, `cd_burner` or `builder` — which is precisely
   where these removals hid for six weeks.
4. **Treat a red guard as a missing fix until proven otherwise.** The guards did
   their job here; they were simply never run.

---

## 7. Build status

The v3.6.5 PyInstaller and Nuitka builds have **not** been started. Building now
would produce an installer labelled 3.6.5 that is missing the download
completeness fix, the Lite Viewer drop import, and ARM64 installer support —
all of which shipped in earlier versions. Recommend restoring first.

`pyproject.toml` already reads `3.6.5` (uncommitted); version identity flows from
there into both chains via `load_version()`, so no other version edit is needed.

---

## 8. References

- `docs/releases/VERSION_3.6.5_BUILD.md` — build preparation record
- `claude/VERSION_3.6.4_RELEASE.md` §7-8 — domain gates and open items
- `docs/pipelines/cd-burner-portable-viewer.md` — the Lite Viewer drop fix
- `builder/docs/AI_AGENT_BUILD_RUNBOOK.md` §0 — prime directive, stale source
- Lane logs: `builder/output/fastlane_v3.6.5.log`,
  `builder/output/fastlane_v3.6.5_windir.log`, `builder/output/guardfix_B.log`
