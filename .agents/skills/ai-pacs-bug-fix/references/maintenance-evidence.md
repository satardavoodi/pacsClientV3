# Maintenance evidence and build handoff

Read the relevant section for recurring bugs or when establishing next-build coverage.
Repository paths below are relative to the repository root. Historical outcomes are
evidence to investigate, not a current test pass or authorization to repeat an action.

## Lessons from reviewed maintenance history

| Reviewed source | Decision that should carry forward | Current evidence to inspect |
|---|---|---|
| `fix 1`, thread `01a04ead-ae2a-7e13-abea-58be8640dc0b`, September 20 source fix | Late study growth during active sidebar construction/prefetch must not be dropped behind an old snapshot. Worker completion is not successful prefetch. Restore downloaded presentation from authoritative durable state, including events that occurred before subscription. The reported 125 focused / 259 expanded passes left a fresh source GUI gate open. | `tests/code/ui_services/test_sidebar_bounded_build.py`, `docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md`, thumbnail pipeline and current Unify ledger |
| `Fix Dental Imaging sync regression`, thread `019f19dd-98f8-78f3-a4a2-49276d75ee22` | Panoramic/cross-section agreement alone did not prove agreement with axial/coronal/sagittal geometry. Test a known physical point across each affected view and use actual reconstruction frame metadata. Keep a Dental-specific mapping repair inside Dental; do not modify working global VTK geometry. | `modules/dental_imaging/core/curved_reconstruction.py`, `tests/code/dental_imaging/test_dental_arch_pick.py`, relevant DICOM compatibility skill when coordinate transforms are involved |
| `docs/reports/THUMBNAIL_HEAP_CRASH_AND_WINDOWS_SPAWN_FLASH_2026-09-01.md` | Similar visible flashes had different causes: worker executable selection and embedded-widget retirement. A virtual-environment `pythonw.exe` substitution introduced a shared-handle download failure. Verify process/lifetime ownership and adjacent behavior rather than broadening a plausible workaround. | `PacsClient/utils/windows_multiprocessing.py`, relevant lifecycle guards and source-versus-frozen policies |
| Recovered `I want to fix several small issues inside the PACS software.`, session `local_ff5522c0-9a78-47f6-9860-201fade20b0f` | Preserve working clinical functionality and performance; inspect side effects; avoid starting with a refactor. | Current `AGENTS.md`, `CLAUDE.md` and subsystem guards |
| Recovered `Important instruction for upcoming bug reports`, session `local_b0ca4329-fd75-4067-a4a0-5b456e2d20fc` | A recurring failure mode was a source fix missing from the installed build. Trace inclusion through the actual packaging path and keep artifact acceptance open until evidenced. The historical request to run a built app does not override today's source-only live-testing rules or authorize a new build. | `BUILD.md`, `docs/release-and-build/README.md`, payload mapping, configuration writers and builder guards |

Recovered sources are indexed at
`D:/_RECOVERY/restored/projects/ai-pacs-workstation/previous-conversations`.
Read only relevant excerpts locally; do not copy transcripts, identifiers or images
into skill references, fix records or fixtures. These are selected reviewed cases,
not a claim that all historic fix conversations were reviewed.

## Per-fix coverage matrix

Use the current names and lane definitions in `BUILD.md`. If a user uses an informal
server label such as ELI, resolve it against the requested product and current
profiles; do not invent a new edition or silently switch to the separate PACS server
repository. This workstation's documented server edition is Eagle Eye Server.

| Runtime profile | PyInstaller | Nuitka | Required scope decision |
|---|---|---|---|
| Standard Client | Record applicable checks | Record applicable checks | Shared workstation behavior and Client configuration |
| ARM64-emulated Client | Record applicable checks | Record applicable checks | Shared behavior plus relevant platform/payload boundary; not native ARM64 |
| Eagle Eye Server | Record applicable checks | Record applicable checks | Shared behavior and Server-only feature/service path when affected |

For each applicable cell, record source/guard evidence, build-input evidence, and
artifact acceptance independently as passed, failed, pending, blocked, or N/A with
a reason. Shared source tests need not be run redundantly when the code/config path
is identical; explain that fact and separately check divergent profile/staging paths.
Do not claim six installer runs from one source suite.

Trace only the packaging surfaces the fix actually touches:

1. Canonical source and runtime import/override selection.
2. Plugin payload mirror and new-module registration where applicable.
3. Edition feature defaults, package definition, component/profile writers and
   configuration-family versions where applicable.
4. PyInstaller and Nuitka staging, assets and existing parity guards.
5. If external native/runtime assets changed, their assembly/source/hash provenance
   and a new immutable cache under the canonical runbook. Python/UI changes and
   native changes may have different inclusion mechanisms.
6. At the next authorized build, the candidate's source receipt, selected role,
   inventory and artifact hashes, followed by runbook-governed acceptance of the
   original scenario and adjacent workflows. Do not launch frozen apps from an
   ordinary bug-fix session; obtain the permitted acceptance evidence via the
   separately authorized build QA workflow and its human operator.

At this review (2026-09-24), `BUILD.md` documents unresolved Server qualification
and frozen-service dependency gates. Re-read their current state rather than
permanently assuming failure or treating them as cleared by an unrelated fix.

## Compact handoff fields

Append these fields to the existing owner record when delivering a fix; no separate
release plan is needed:

- User fix number plus session/date; existing incident/OPT/catalog links.
- Root cause, invariant and affected owner; relevant unchanged control scenario.
- Guard command and fail-before/pass-after result with exit codes.
- Focused/adjacent checks and attributable source GUI result.
- Changed source/payload/config paths; applicable matrix cells and evidence.
- Revision or changed-file hashes; pending build candidate/artifact receipt.
- Exact acceptance scenario, rollback, remaining gates and owner of any handoff.

Never fill pending evidence with an estimated success or a historical test count.
