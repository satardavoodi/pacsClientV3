# Eagle Eye Lumbar Bone Marrow pilot

Status (2026-10-08): canonical client and server implementation exists. The isolated
Razi candidate `20261008-lumbar-marrow-r3` is tested and running in **Development**
after explicit owner authorization. It is not promoted to the shared SCM service,
which remains on `20261007-echo-reference-r2`. Source GUI acceptance
and actual patient inference are pending. No installer or clinical qualification.

## Client to server contract

Choose Function exposes `Lumbar Bone Marrow | Experimental T1` for lumbar MR,
outside the brain-specific menu. Opening it loads the current study's available
MR series in a worker; it never starts inference automatically. The reader chooses
a downloaded native precontrast non-fat-suppressed lumbar T1 series and confirms
the acquisition. Known incompatible sequence headers are rejected on the server.
Ambiguous headers still require reader confirmation; sequence identity is not
inferred reliably from a series name.

The existing authenticated protocol-1 job route receives module `lumbar-marrow`,
one `primary` reference containing series UID and counted inventory, and parameters
`t1_confirmed: true` plus optional bounded `clinical` fields. Paths and pixel arrays
are not uploaded by the client. It verifies exact study/series identity in a worker
and checks server capability before submission. No local inference/provider fallback.
The server retrieves the exact PACS series and owns decoding, model execution,
signal calculations and report generation. DICOM rescaling is applied by SimpleITK.
The lumbar CPU model budget is inherited for previously complete seven-route
resource configurations; other missing resource profiles remain errors.

## What the first test measures

The existing `vertebrae_mr` TotalSegmentator bundle supplies whole-vertebra labels.
Only L1-L5 labels are sampled. A 2 mm physical-radius erosion excludes boundary
voxels; KJI/XYZ conversion respects native voxel spacing and orthogonal obliquity.
At least 20 sample voxels are required. Each level reports sample count/volume,
mean, median, standard deviation, and 10th/90th percentile of T1 arbitrary-unit
signal. Insufficient samples remain null and missing labels are listed explicitly.

This is **not** a validated marrow/body ROI. Posterior elements can remain, and
sample volume is not marrow volume. T1 signal depends on acquisition/scaling;
there is no interpatient normalization, muscle ratio or longitudinal equivalence
claim. Red marrow fraction, fat fraction and iron concentration are explicitly
null. There are no diagnostic thresholds or treatment recommendations.

Artifacts: labels/segmentation from the existing model, `marrow-roi.npy`,
`marrow.csv`, a native-orientation `preview.png` sampling overlay, `report.html`,
and the standard authenticated result envelope with model/source provenance.
The client displays the server draft and overlay. The report is marked
`unreviewed_research_draft` and is not approved for patient delivery. This pilot
does not yet provide full-volume mask editing, physician sign-off or PDF export.

## Optional physician-entered context

| Key | Unit / meaning |
|---|---|
| ferritin_ng_ml | ng/mL |
| transferrin_saturation_percent | Percent; not soluble transferrin receptor |
| hemoglobin_g_dl | g/dL |
| transfusions_per_year | Number of transfusion episodes per year |
| dxa_z_score | Z score |
| liver_iron_mg_g_dry | mg/g dry tissue |
| cardiac_t2star_ms | ms |
| emh | unknown / absent / present, reader-entered |

Blank values are unknown, not zero. Inputs are range-bounded and finite, including
signed DXA scores. EMH is not automatically detected or quantified. All clinical
context and image-derived artifacts remain private in the existing authenticated
server job/client artifact stores. Do not copy real patient artifacts into Git,
documentation, screenshots or external AI services.

## Verification and deployment

- Canonical new guards: 24 passed, including source staging; prior menu assertion
  failed against the Git baseline and passes after implementation.
- Adjacent workspace/remote/lumbar guards: 219 passed, plus five scheduler guards.
  Builder/runtime checks:
  56 passed, two frozen-stage checks skipped because no build was prepared.
- 515 existing mirror pairs match. Scoped `sync_plugin_mirrors.add_paths` found
  no affected plugin mirrors. This is a feature inside the existing full-core
  `ai_imaging` package, not a new installer module or feature flag.
- Razi candidate server/transport guards: 48 passed, one client-menu test
  deliberately deselected because that server snapshot retains its old client UI;
  one test reran. Client menu is tested in canonical workstation source.
  Candidate `pip check` passed. Segmentation is stubbed in synthetic adapter tests;
  this is not evidence of real model execution on the selected patient.
- Actual portable-model preflight on Razi passed full manifest/file/weight hashing
  and imports: `vertebrae-mr-cpu-2.14.0`, PyTorch `2.6.0+cpu`, status `ready`.
  The Python audit guard blocked one network attempt. Inference was explicitly
  not executed. Private receipt: `validation/marrow-preflight-20261008/result.json`.
- Candidate staging uses bounded contextual patches and checks transferred hashes.
  It retains newer baseline server work, excludes user_data/database, and reuses
  immutable runtime/model trees through local junctions. It changes no service,
  shared configuration or running source. Historical r1/r2 candidates are retained;
  r2's combined test initially failed on the absent server-side client menu.
- Receipts: server revision `marrow-stage.json` and `marrow-tests-server.json`;
  transferred source-only bundle under server `staging/marrow-20261008`.

Before promotion to the shared service: source GUI menu/form acceptance, human deployment sign-off,
authenticated queue/ownership checks, protected exact SCM/config backup and
rollback command. Activate only the named Eagle Eye service after queue drain;
preserve PACS/DICOM/CRM listeners. Rollback restores the exact prior SCM command
with the unchanged prior revision and shared config. Do not terminate processes
by name/port or silently rewrite deployment receipts.

First patient test: select the confirmed native T1, run on the approved server,
inspect L1-L5 anatomy and sampling overlays, verify source identity and results,
then review draft limitations. A report-producing technical test is not clinical
validation. Next development: reviewed vertebral-body ROIs and same-image muscle
reference, then a separately validated Dixon acquisition/quantification contract.
Two-echo signal differences must not silently be labeled PDFF or red marrow volume.

## Authorized Development connection

The owner explicitly selected a separate Razi Development route for this test.
The candidate runs under the manual-only scheduled task
`AI-PACS Lumbar Marrow Development 20261008`, using the existing `Supervisor`
and Windows Job Object ownership. It has no automatic trigger. Listener:
`https://127.0.0.1:8042` on Razi (`192.168.2.222`); private isolated job root:
`D:/Eagle Eye Server/jobs-marrow-development-20261008`. EchoMind/Secretary
provider workflows are disabled in this MRI-only Development configuration.

The workstation connects at `https://127.0.0.1:18042` through the existing
authenticated SSH route. Server CA verification, paired client certificate and
token checks remain enabled. The tunnel config derives authentication/path
settings from the central SSH configuration, quotes its space-containing paths,
requires the existing known host key and omits unrelated local forwards.
No key contents were copied. The original shared SCM path was checked unchanged
and Running. No firewall rule was created or changed.

An attempted direct LAN listener/firewall command was rejected by automatic
approval review with `blocked by policy` and no further reason; it did not run.
The narrower loopback/SSH alternative succeeded. The first detached Development
process ended with its SSH session; the manually started owned task resolved this.
Authenticated client capabilities now advertise eight routes including
`lumbar-marrow`. This proves connectivity, not model execution or GUI acceptance.

Human source launch from the canonical repository:

```powershell
& '.\tools\eagle_eye\open_marrow_development.ps1'
```

This selects Standard client role, the private prepared Development configuration
and the explicitly authorized Test Control Server. Human sign-in, one source
instance and study/T1 confirmation remain required. Do not launch it automatically
or open the installed executable. Use normal launch settings for clinical work.
The prepared client config and tunnel PID receipts are private generated files
under `generated-files/marrow-stage-20261008`; they contain credential references,
not copied key/token contents. They are not distribution artifacts.

Development shutdown: require its queue idle, verify the named task and listener
source/config ownership, then stop only the named Development task and its owned
supervisor/process tree. Verify port 8042 closed; stop only the verified local
tunnel PID from its receipt. Preserve the shared SCM service/listeners. This
shutdown/rollback procedure is written, not claimed as a completed drill.

## Shared Razi activation 2026-10-08
Owner explicitly requested the existing server update. The shared AIPacsEagleEye
service now uses the hash-verified 20261008-lumbar-marrow-r3 candidate and unchanged
paired HTTPS8002 configuration. All durable client jobs were terminal before restart.
Authenticated normal workstation capabilities advertise lumbar-marrow and eight routes;
jobs API succeeded. Exact SCM/config backup: server backups/marrow-service-20261008.
Initial sc.exe update failed and restored baseline; structured CIM Change succeeded.
Real patient inference and GUI acceptance remain pending; experimental measurements
are not clinically qualified. Normal clients require no tunnel/config change.

## Result review tab correction 2026-10-08
The returned report was embedded under input fields in the popup. Completion now
emits resultsReady and the study/session workspace adds and activates a reusable
Lumbar Bone Marrow review tab. The popup owns input/progress only and is hidden on
completion. The report browser expands in the tab; duplicate completion/reopening
reuses the same page. Failure/cancellation creates no review tab. Teardown is
idempotent and rejects late completion. Server inference and protocol are unchanged.
Guard test_lumbar_marrow_workspace.py failed before correction (tab count remained1).
66 focused tests passed, then two cancellation/failure guards added and all three
UI guards passed. 515 mirror pairs match; no affected packaged mirror exists.
Source live acceptance pending: current Test Control Server ping is unavailable.
Human must launch fresh source with normal Razi config and optional TestServer,
sign in, then verify report completion/tab layout. No installer build performed.
Client PyInstaller/Nuitka include full ai_imaging; no server runtime update needed
for this client-only presentation correction. Rollback reverts the completion signal
and workspace tab hook, preserving returned private artifacts.

## Review UX, PDF and Slicer revisions 2026-10-08
The report-only browser caused cramped numeric cells and poor image navigation.
MarrowReview now separates Image and measurements, Structured report and Physician
notes. The scrollable/pannable preview has Fit, Zoom and 100% controls. Measurement
cells use two decimals, volume in cm3, fixed readable header spacing and level colors
matching the existing overlay palette. Colors identify anatomy, not severity.
Definitions explain arbitrary SI, ROI, mean/median/SD and QC. Physician notes are
included in the exported draft but do not overwrite server measurements.
PDF uses the existing Eagle Eye paged A4 renderer with marrow title/footer; synthetic
PDF was rendered with bundled Poppler and visually checked. No patient artifact
was copied into documentation. Source identity unavailable is explicit, not invented.
Slicer uses existing isolated prepare_review/manual_slicer controls. Server now
exports owned reference image, full labelmap and label names. Saved edits use the
bounded label correction protocol: same source/owner/parent, mask hash, geometry,
allowed labels, size/decompression limits and revision-conflict checks. Signal
remeasurement occurs only on the server without rerunning inference; original job
is retained. Interrupted submissions retain a resumable client handle. Earlier
results without review assets require a new analysis. Corrected labels are whole
vertebrae followed by the same 2 mm erosion, not a validated marrow-body segmentation.
Razi scoped R4 candidate is active on the existing paired HTTPS8002 service. The
all-client durable queue was idle; exact prior SCM/config backup is on server at
backups/marrow-review-20261008. Normal client capabilities confirm marrow analysis
and correction. Candidate synthetic guards:22 passed,1 old client-menu deselected.
Canonical tests and UI/PDF synthetic checks pass; fresh source GUI/Slicer/native
patient correction acceptance pending. No installed Client or full build was created.
515 mirrors match; no affected plugin mirror. Client PyInstaller/Nuitka package
whole ai_imaging; server correction source is included in existing full-core tree.
Rollback: after queue drain restore prior SCM binpath from activation receipt and
start only AIPacsEagleEye; revert client review changes separately if necessary.

## Automatic saved module result tabs 2026-10-08
Opening an Eagle Eye workspace now discovers locally retained server result.json
records in the Eagle Eye artifact root and exact-study attachment root off-thread.
Latest complete result per server module is restored as a named tab without any
inference submission or source-series loading. Discovery requires exact study
identity, owned artifact directory, bounded JSON/report and existing report/PDF;
foreign studies, escaped artifacts and incomplete results are skipped. Existing
tabs are reused and the current imaging viewport remains selected. Marrow restores
its full review/PDF/Slicer page; other server modules restore read-only saved report
and PDF tabs. Existing native module review/edit workflows remain available through
their functions; generic saved report tabs do not reconstruct their editor state.
Scope is locally retained results, not remote-only jobs or another study's history.
Synthetic missing-discovery guard failed before implementation. 44 focused guards
passed, including workspace reopening without loading inputs, duplicate suppression,
exact-study and missing-report exclusion. 515 mirror pairs match; no mirrored source.
Fresh source live GUI remains pending. This client-only change needs no server restart.
Both Client build backends include the ai_imaging core; no installer was produced.
