# Slicer extensions: installation and programmatic control

Verified: 2026-08-31. Companion: [core control runbook](ADVANCED_ANALYSIS_SLICER_CONTROL_RUNBOOK.md).

**Third-party extension calculations can be exposed through the same local bridge and a future MCP adapter. This was demonstrated with one downloaded extension on our existing custom runtime. It does not mean every extension installs or runs unchanged, or that its GUI will load.**

The practical recommendation is to use a separate adapter for each selected extension, preinstall and pin its dependencies outside inference requests, and qualify its computation and GUI separately. There is no automatic rule that every installed extension becomes a safe MCP tool.

## 1. Evidence and scope

Five public extension repositories were inspected at pinned commits. Selected source files were downloaded, with SHA-256 recorded in the [source manifest](../reports/SLICER_EXTENSION_SOURCE_MANIFEST_2026-08-31.json). Downloaded source is research material, not part of the shipped application.

| Extension / project | Useful function | Control surface found | Status on our runtime |
|---|---|---|---|
| SlicerSandbox: SegmentCrossSectionArea | Area measurements from existing segmentations | Independent Python logic with axis/input/output arguments | Computation and table roundtrip tested; GUI setup failed |
| SlicerTotalSegmentator | Task-specific automatic anatomy segmentation, including MR vertebrae | TotalSegmentatorLogic.process | Source reviewed; AI engine/dependencies not installed |
| SlicerMONAIAuto3DSeg | Model catalog, including multi-sequence brain tumor segmentation | MONAIAuto3DSegLogic.process and cancelProcessing | Source reviewed; one weight endpoint partially downloaded; no inference |
| MedSAMSlicer / MedSAM Lite | ROI-guided medical image segmentation | Logic methods plus MedSAM_Interface backend; significant widget state dependencies | Source reviewed; not installed or executed |
| Raidionics-Slicer | Brain tumor segmentation and structured quantitative reporting workflows | RaidionicsLogic plus Docker backend and structured model parameters | Source reviewed; Docker/model execution not tested |
| MONAI Label | Slicer client for model-specific annotation/inference services | Client/server architecture | Upstream documentation reviewed only; not part of the pinned five-project source audit |

The remembered name “Segment Everything” is ambiguous. **TotalSegmentator** performs predefined anatomy tasks; **Segment Anything / MedSAM** uses prompts such as a bounding box to segment a chosen region. Neither name implies that all pathologies are automatically detected or diagnosed.

## 2. Download, install, and run are three different checks

### What was actually downloaded

- Pinned README/license/source files for the five projects above, including the lightweight extension's Python module and UI resource.
- GitHub release metadata for MONAI Auto3DSeg models, MedSAM Lite, and Raidionics.
- A 32-byte range from the BraTS GLI model archive, using a bounded HTTP request. Response: **206**, Content-Range **bytes 0-31/322685643**, ZIP magic valid. The approximately 322.7 MB file was **not** downloaded in full.

The [BraTS GLI release asset](https://github.com/lassoan/SlicerMONAIAuto3DSeg/releases/download/Models/brats-gli-v1.0.0.zip) was therefore reachable from this machine at inspection time. This is not a checksum verification, completed weight installation, or a guarantee of future access to all model/package hosts. The MedSAM module's raw URL returned HTTP 400; downloading the same pinned public file through the GitHub Contents API succeeded.

Raw local evidence is under `generated-files/slicer-extension-research/2026-08-31/`. The durable manifest records source commits, hashes, release metadata, and the bounded model-download result. No patient images or identifiers were used.

### Installation in a normal full Slicer distribution

The usual path is Extensions Manager: select the extension, install its declared dependencies, restart when requested, then complete any separately required Python-package and model-weight installation. Offline extension packages can be installed from a local package where supported.

For pure Python modules, a source checkout can instead be added through Additional module paths or Extension Wizard, retaining its resource/helper directories. A source ZIP is not necessarily an installable binary extension package. Compiled modules require an appropriately matching Slicer build. See [official extension development/loading instructions](https://slicer.readthedocs.io/en/latest/developer_guide/extensions.html).

### Installation in our custom Advanced Viewer

Our application configuration defaults `Slicer_BUILD_EXTENSIONMANAGER_SUPPORT` to OFF. Do not assume that the stock extension browser or `installExtensionFromServer` workflow exists here. Enabling a production extension manager is a separate build/packaging change.

Available integration strategies:

1. **Pure Python extension with existing dependencies:** stage reviewed source and resources outside the runtime, then pass its module directory with `--additional-module-path`. This was tested successfully for computation and does not persist settings.
2. **Pure Python extension with AI dependencies:** provision a versioned disposable analysis runtime or an isolated inference service first. The current embedded Python lacks torch, MONAI, TotalSegmentator, and SimpleITK. The workstation's .venv is a different interpreter and does not fill those gaps.
3. **Compiled extension:** build against the matching custom Slicer inner build/ABI and required Qt/VTK/Python configuration; deploy its libraries and launcher paths deliberately. A package for a nearby stock Slicer release is not automatically compatible.
4. **External inference backend:** keep heavy model dependencies in a separate local process/container/server, exchange validated image/result artifacts, and use Slicer for scene management, visualization, editing, and measurement.

The fourth strategy is attractive for AI-PACS dependency isolation, but no new inference server was installed or contacted here. A remote backend would require separate authorization for patient-data transfer, authentication, encryption, and data retention controls.

Do not modify the generated build tree or installed payload directly to add dependencies. A future shipped extension must follow the runtime catalog, package definition, config-family, mirror synchronization, and release validation rules in CLAUDE.md.

## 3. Executed third-party extension experiment

Project: [PerkLab/SlicerSandbox](https://github.com/PerkLab/SlicerSandbox/tree/7211da97bf65edc26fc67f1c69668be584409786/SegmentCrossSectionArea), commit `7211da97bf65edc26fc67f1c69668be584409786`.

The inspected Apply handler calls:

```python
SegmentCrossSectionAreaLogic().run(
    segmentationNode, volumeNode, axis, tableNode, plotChartNode
)
```

The implementation explicitly accepts `slice`, `row`, or `column`. It calculates areas from visible segments, exports temporary labelmaps in the reference-volume geometry, and writes MRML table/chart nodes. The upstream README describes it as a basic tool and points to more advanced alternatives; this audit selected it to test extension control, not to recommend a final clinical measurement engine.

The probe loaded only this module directory. It created one synthetic cuboid mask, changed the Axis parameter, read it back, called the extension logic, retrieved the table, saved TSV, and reloaded/compared the numbers.

| Axis string | Axis in this extension | Table rows | Nonempty sections | Area of each nonempty section |
|---|---|---:|---:|---:|
| slice | K | 12 | 4 | 23.04 mm2 |
| row | I | 32 | 8 | 36.00 mm2 |
| column | J | 24 | 4 | 64.00 mm2 |

Integrating the areas with the corresponding spacing produced **230.4 mm3** on all axes within floating-point tolerance. An invalid axis was rejected by the bridge. The full run also repeated the core DICOM/threshold/export checks and exited normally with code 0.

Successful evidence: [result.json](../../generated-files/slicer-control-probe/ce29efba6e7f466eb9aef604f9d0fa51/result.json).

### Separate GUI compatibility finding

The extension's `.ui` form did **not** initialize successfully in this isolated custom-runtime launch. QUiLoader reported that `qMRMLWidget` and `qMRMLNodeComboBox` could not be created, fell back to QWidget, and then `setMRMLScene` failed. The inspected runtime tree contains CTK designer plugins, but no matching MRML widget designer plugin file was found. The exact packaging/loading fix has not been established.

The successful JSON result explicitly contains `gui.initialized: false` and `gui_parameter_readback_equal: false`. Its overall `passed: true` means the bounded computational contract passed; it does **not** certify GUI compatibility.

Earlier attempts `5e74d08808444b68b3b5fe327cf4df96` and `b04cf4f1dd08409387cdf293f1ae716a` retained their failed results. They required GUI initialization. The final probe reports GUI readiness separately and successfully calls the same upstream computation without a widget. No upstream code or packaged runtime was patched.

This observation directly answers the UI question: **a plugin's calculation can remain callable even when its GUI cannot load**. Conversely, a plugin that embeds essential logic in widgets may require a larger adapter or a qualified runtime with working UI resources.

### Reproduce the temporary loading experiment

The following downloads only the reviewed module, UI, and license into the research directory. Existing files are not overwritten; the probe subsequently verifies the exact Python/UI SHA-256 values before loading them.

```powershell
$taskRepo = (Get-Location).Path
$taskRoot = Join-Path $taskRepo 'generated-files/slicer-extension-research/2026-08-31/SlicerSandbox'
$taskCommit = '7211da97bf65edc26fc67f1c69668be584409786'
$taskFiles = @(
    'LICENSE',
    'SegmentCrossSectionArea/SegmentCrossSectionArea.py',
    'SegmentCrossSectionArea/Resources/UI/SegmentCrossSectionArea.ui'
)
foreach ($taskFile in $taskFiles) {
    $taskDestination = Join-Path $taskRoot $taskFile
    New-Item -ItemType Directory -Force -Path (Split-Path $taskDestination) | Out-Null
    if (-not (Test-Path -LiteralPath $taskDestination)) {
        $taskUrl = "https://raw.githubusercontent.com/PerkLab/SlicerSandbox/$taskCommit/$taskFile"
        Invoke-WebRequest -Uri $taskUrl -OutFile $taskDestination
    }
}
.\.venv\Scripts\python.exe tools/dev/run_slicer_control_probe.py --with-reviewed-extension
if ($LASTEXITCODE -ne 0) { throw "Slicer extension control probe failed" }
```

Run from the repository root with no Advanced Viewer process already open. The flag is optional; the ordinary core probe remains independent of the downloaded extension. No model weights, persistent module paths, or runtime package installations are involved. After process exit, no extension remains installed in the application.

## 4. Extension-specific APIs and limitations

### TotalSegmentator: relatively direct adapter

Inspected source: [TotalSegmentator.py at 270cac20](https://github.com/lassoan/SlicerTotalSegmentator/blob/270cac20b78a282505e4f6a25d268666e4056019/TotalSegmentator/TotalSegmentator.py).

Its computational signature is:

```python
process(inputVolume, outputSegmentation, quality=None, cpu=False,
        task=None, subset=None, interactive=False, sequenceBrowserNode=None)
```

The GUI calls this method after dependency setup and copying advanced options onto the logic object. There is no need to simulate mouse clicks to request the calculation.

Parameters include task, supported quality mode, CPU selection, optional structure subset, and properties such as robustCrop, removeSmallBlobs, higherOrderResampling, bodyCrop, and useStandardSegmentNames. These are not all universally applicable: inspect the selected task's metadata and engine support before exposing them.

The inspected task catalog includes **total_mr** and **vertebrae_mr**. The latter explicitly includes sacrum and cervical/thoracic/lumbar vertebrae. That makes it a relevant candidate for lumbar localization experiments, not evidence that it detects disc disease or neural compression accurately.

This version expects the **PyTorch** and **SlicerNNUNet** extensions plus the TotalSegmentator engine; the source pins an engine download associated with v2.14.0. Its installer protects selected Slicer packages and assumes some standard dependencies already exist. Our missing SimpleITK is therefore a compatibility gap, not something to solve by blindly running that installer.

For an unattended adapter, use `interactive=False`, provision dependencies beforehand, reject unsupported task/quality combinations, and isolate blocking execution. This flag suppresses processing popups; it is not permission to bypass installation or license requirements. Software, model weights, and restricted tasks must each have their licensing checked before commercial distribution.

### MONAI Auto3DSeg: explicit jobs, models, and cancellation

Inspected source: [MONAIAuto3DSeg.py at 9cdf2df4](https://github.com/lassoan/SlicerMONAIAuto3DSeg/blob/9cdf2df4e8b3a5351ad11a3f934b0c13ffb15cca/MONAIAuto3DSeg/MONAIAuto3DSeg.py).

```python
process(inputNodes, outputSegmentation, model=None, cpu=False,
        waitForCompletion=True, sequenceBrowserNode=None,
        eventCallback=None, customEventCallbackData=None)
cancelProcessing(segmentationTaskListInfo)
```

The GUI already requests `waitForCompletion=False` and supplies an event callback. This is a useful basis for a job-based adapter, but input serialization and setup still need profiling; asynchronous inference does not make every call nonblocking.

The [pinned model catalog](https://github.com/lassoan/SlicerMONAIAuto3DSeg/blob/9cdf2df4e8b3a5351ad11a3f934b0c13ffb15cca/MONAIAuto3DSeg/Resources/Models.json) lists BraTS GLI, MEN, MET, PED, and SSA models. Their declared input order is **T2-FLAIR, contrast-enhanced T1, noncontrast T1, T2-weighted**. An adapter must validate sequence identity and spatial compatibility, not guess order from four arbitrary loaded volumes. Use the exact model ID returned by the catalog; do not invent it from the display title.

Weights are downloaded/cached separately. Upstream documents a manual cache under the user's `.MONAIAuto3DSeg/models/` folder. The inspected local dependency handler uses PyTorchUtils and installs MONAI with imaging extras. The process path may invoke dependency setup automatically on first use; deployment must resolve this before clinical tool requests.

The source also includes **RemoteMONAIAuto3DSegLogic**, model/metadata endpoints, and an inference server path. This is an existing architectural option, not a server already configured for AI-PACS. Never send patient data to a URL supplied by an LLM.

The extension's permissive software license does not replace review of each model/dataset's terms or clinical validation.

### MedSAM Lite: controllable, but not a clean stateless process call

Inspected source: [MedSAMLite.py at 14c756fd](https://github.com/bowang-lab/MedSAMSlicer/blob/14c756fdd8ec49af17b083f07deae482c1013f6b/MedSAMLite/MedSAMLite.py), identifying itself as v0.13.

Relevant methods are `sendImage(partial=False)`, `inferSegmentation()`, `showSegmentation(mask)`, `applySegmentation()`, and `get_bounding_box()`. The interface backend provides `set_image(...)` and `infer(slice_idx, bbox, zrange)` calls.

However, the logic reads widget controls, model-path widgets, progress dialogs, timers, and selected engine/speed. The bounding-box method looks up a scene node named **R**. It also imports SimpleITK at module load, which fails in our current inventory. Therefore `MedSAMLiteLogic()` alone is not a complete independent MCP tool.

The adapter should accept explicit source and ROI handles, validated physical coordinates, model identity, preprocessing profile, and output destination. It should remove reliance on a globally named ROI or implicit current selection. Either drive a fully initialized qualified module with explicit state, or integrate the backend separately and import its result into Slicer.

Upstream installation requires module source/resources, PyTorch support, additional inference dependencies, and separately downloaded model files. Reviewed preprocessing can update source voxel arrays in place; use a derived job-owned volume and preserve original data. Do not map “increase sensitivity” to an invented universal MedSAM threshold. ROI size, preprocessing, propagation range, and engine choice have different effects.

This review covers the pinned **MedSAM Lite** plugin, not every MedSAM2/SAM2 project or newer fork.

### Raidionics: backend control with integration work

Inspected source: [RaidionicsLogic.py at 2b551daf](https://github.com/raidionics/Raidionics-Slicer/blob/2b551daf4fc1d5a581be23ec2af5b2e41eec1328/Raidionics/src/RaidionicsLogic.py).

The singleton logic accepts `run(model_parameters)`; the processing code reads inputs, outputs, params, and iodict fields and uses shared resources. Its documented setup requires Docker and a separately obtained RADS image/models. Downloading the Slicer source alone is insufficient.

It is a candidate for brain tumor analysis and reporting research, but not a ready drop-in lumbar tool. The inspected threading construction calls `thread_doit(...)` while constructing the Thread target; do not assume background execution from the method name. Worker ownership, progress/cancellation, file mappings, and output geometry require dedicated testing before an MCP wrapper can be described as reliable.

### MONAI Label: service architecture, not one universal model

[MONAI Label's Slicer client](https://github.com/Project-MONAI/MONAILabel/tree/main/plugins/slicer) connects annotation/inference workflows to a model-serving application. It is another possible way to separate Slicer UI from heavy inference dependencies. The selected server application defines available models and parameters. This task did not install or source-audit that client/server stack, so its compatibility remains unverified.

## 5. How to expose an extension through the same MCP

A single MCP server can contain several named tools, each implemented by its own adapter:

| Proposed tool | Internal target | Required inputs / guard |
|---|---|---|
| measure_cross_section | SegmentCrossSectionAreaLogic.run | Authorized segmentation/reference volume, explicit axis and segment selection |
| segment_anatomy | TotalSegmentatorLogic.process | Modality-compatible task, allowed quality/subset, pinned engine |
| segment_brain_tumor | MONAIAuto3DSegLogic.process | Exact model and required ordered/aligned sequences |
| segment_prompted_roi | MedSAM backend or controlled module adapter | Explicit ROI geometry, source handle, engine and preprocessing |
| get_analysis_job / cancel_analysis_job | Adapter-owned task state / supported cancellation | Job ownership, timeout and cancellation validation |

These are proposed tool names, not tools installed in the current application. The tested `extension_cross_section` command is a research-only HTTP operation with a fixed synthetic input. **The experiment proves the extension API behind the transport; it does not prove a complete MCP or dual-LLM integration.**

Changing a MRML parameter node can synchronize an extension GUI only when that extension implements observers and the GUI initializes successfully. Setting a parameter does not necessarily execute the algorithm: call the documented logic/effect method and check completion and output. If an extension has no independent API, add a narrow adapter or separate backend; fragile screen clicking should not be the clinical computation contract.

Do not expose install/update/uninstall, arbitrary Python, free-form Docker arguments, arbitrary URLs, or unrestricted paths to the diagnostic LLMs. A tool must fail with a clear capability/dependency error when its extension is absent or incompatible.

## 6. Suggested qualification order

1. Retain the proven core bridge and synthetic probe as the baseline.
2. Qualify an MRI anatomy task such as TotalSegmentator's vertebrae_mr in an isolated analysis environment. Confirm lumbar levels and geometry before using derived evidence in Eagle Eye.
3. Test a prompted ROI backend if lesion boundary refinement is needed. Do not assume a vertebral anatomy model detects disc lesions.
4. Qualify a brain tumor model separately, using the model's required sequences and an appropriate validation dataset.
5. Resolve GUI plugin packaging if users need the upstream extension panels. Computational success does not close that issue.
6. Only then expose the approved adapters to the two LLMs and compare fixed versus adaptive use against the unchanged baseline.

For every candidate record: source/package/model hashes; license terms; supported modality/sequences; dependencies and GPU/CPU requirements; parameter schema; patient-data destinations; import and geometry tests; synthetic/reference-case results; performance; cancellation; saved-output roundtrip; and rollback.

Rollback should restore a versioned analysis environment and remove only its owned module-path configuration. Do not rely on pip uninstall to reconstruct a modified shipped runtime. No production installation, model inference, GUI repair, or clinical accuracy claim is part of this completed documentation task.
