# Deployment Safety Record - Eagle Eye 2D development pilot - 2026-09-26

Change: explicit native 2D MindGlide lesion route in the existing development service.
Gate result: PASSED for scoped development activation; NOT a customer/clinical release.

## Evidence before activation
- User authorization: implement 2D/3D in the same UI and on Eagle Eye Server; user launched/logged into the requested source test app and replied ready.
- Source GUI: real series selection, explicit 2D mode, DICOM age/sex, progress, responsive PACS during computation, completed result and native PDF Save verified. Export checksum matches returned PDF; all 9 pages visually inspected.
- Tests: initial 7 fail-before guards, then 142 related tests passed before the final long-path export guard; final aggregate is recorded below. No live database tests.
- Isolated Razi candidate completed full DICOM-to-PDF inference in 152.29 seconds, matching local output counts and sampled volume. Initial Windows long-path failure was corrected and retested.
- Scope: 10 hash-listed Python files in validation/brain-2d-20260926/candidate/receipt.json. Existing files receive only 2D routing/reporting/acquisition/export additions. The earlier remote 3D topography/correction implementation is preserved; no broad dirty-tree sync.
- Backup: exact before bytes and hashes under validation/brain-2d-20260926/before; artifact publisher backed up immediately before activation. Every existing source hash must match receipt.before; new files must be absent.
- Model: separate optional MindGlide engine with verified model/private-code/shared-runtime hashes. Existing sealed LST runtime was not modified. No customer rights acceptance receipt was invented.
- API/data: documented in docs/modules/eagle-eye-server-development/docs/LESIONS_2D_2026-09-26.md. Existing authenticated PACS references and artifact transport; no source DICOM exported, no credentials or patient identifiers in this record.
- Viewer/FAST/overlays/measurements/sidebars: no code changes in those domains. Actual native study scrolling rendered new pixels during the worker run.
- Metadata: preserved original DICOM identity; same-examination guards and explicit 2D geometry checks. No clinical DB changes.
- Service: only AIPacsEagleEye may restart, after all jobs are terminal. Other PACS/CRM services remain untouched. Recheck queue immediately before stop and activation.
- Performance: selected needed runtime files remain hashed; no clinical functionality removed for speed. New 2D regional/criteria limitations are explicit unavailable values.

## Verification and rollback

After activation: authenticate through the paired Python Client; check 2D/3D capabilities, submit the same test study as a new job, download/verify PDF and native mask, compare mask arrays with local output, check LocalService Running and listener health. Do not equate capabilities with completed inference.

Rollback: drain Eagle Eye jobs, stop AIPacsEagleEye, compare active hashes to receipt.after, restore every receipt.before file from before/, remove only the two new source modules listed with before=null, then start AIPacsEagleEye and verify authenticated capabilities. Optional engine can stay inert; never remove source DICOM, jobs or original LST models. Do not roll back over another developer's changes.

Customer deployment remains unqualified: model-weights redistribution rights, clinical validation, clean installer/reboot and live remote brain manual-correction acceptance are separate gates. No production build/tag/push was performed.


## Live Razi service acceptance

Scoped 10-file activation completed after queue drain, before-hash verification and
backup. Only AIPacsEagleEye restarted; it returned Running under LocalService.
Authenticated capabilities advertise 3d and 2d. A fresh request through the paired
Client retrieved the selected PACS series, ran the actual service worker, returned
four checksum-verified artifacts and completed in 160.85 seconds. Native mask arrays
were exactly equal to the earlier local source-GUI output. This is reproducibility
on one input, not sensitivity/specificity or clinical diagnostic validation.

Final automated gate: 143 passed, 6 dependency deprecation warnings, exit 0.
Mirror verification: 472 matching pairs; dry-run sync reports zero drift/new files.
Scoped diff whitespace check passed. No full build or customer installer acceptance.
The server's older brain-correction capability was deliberately not broadened here.
