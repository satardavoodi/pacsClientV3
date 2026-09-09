# Eagle Eye Brain UI and maintenance

Current source contract: 2026-09-07. Read this with
[customer delivery](EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md),
[Eagle Eye ownership](EAGLE_EYE_DEVELOPMENT_CONTRACT.md) and
[reference setup](EAGLE_EYE_BRAIN_REFERENCE_SETUP.md).

## User journey and code ownership

1. The open MRI study routes through `AiMainWindow` in `brain_mri` mode.
2. `BrainVolumetryWidget` offers whole-brain analysis and explicit T1 series
   selection. Lesion detection remains unavailable. Selection must match the
   active study; the user confirms coverage and protocol.
3. A background worker calls `study_workflow.run_study_analysis` and `service`:
   DICOM preparation, SynthSeg, isolated Slicer, published references, image
   evidence and PDF. Patient/study ownership is established from DICOM.
4. Completion displays a compact result card, not the full 29-page report HTML.
   It lists measurement count and anatomical coverage. Primary action:
   **Save PDF report...**; secondary actions: **Open PDF report** and
   **Open result folder**. Opening uses the system PDF viewer. Saving runs
   atomically in the worker and preserves the original report in User Data.
5. Starting a new analysis or regeneration clears the old card and disables
   its actions. Export failure preserves the completed result for retry.

Keep expensive report rendering, file access and measurement outside the GUI
thread. The result card reads only the completed in-memory result. Do not render
`report_html` inside the widget or insert the complete report into a tiny browser.
The UI uses Qt widgets and existing application styling; no web runtime or new
third-party dependency is needed. PDF absence disables both PDF actions.

## Report contract

`organized_report.py` is the shared source for the normal service and regenerated
reports. Global volumes precede dedicated white matter, cortical summary,
hemisphere cortex, six cortical groups, CSF, basal ganglia, deep gray matter,
brainstem, cerebellum and medial temporal pages. Right and left are adjacent;
midline structures have single measurements. Headers and numeric cells are
centered; text is left aligned. The reference appendix and scientific sources
remain part of the PDF. Page count can change with coverage; never hardcode it
in the UI. Preserve unavailable references and atlas-analogue qualification.

## Verification and customer acceptance

The full local adult DICOM service run produced 101 posterior and 98 binary
measurements and a 29-page PDF. All page furniture, DICOM identity, visual layout
and atomic export were checked. Private evidence is stored under the Brain
validation directory in User Data, never copied into an installer or fixture.

The updated result card is tested with synthetic completion and visually reviewed
in a separate Qt widget harness. The actual completed DICOM result was also passed through the card and its save
button worker; exported bytes matched the original PDF and save returned to ready.
This is not a new workstation login/session.
Regression coverage lives in `test_eagle_eye_brain_study_workflow.py`;
installed lookup and payload/profile coverage live in the customer-path and
builder tests. Run pytest directly and check its exit code.

Source success is not clean-client certification. Follow `BUILD.md` for packaging,
with the exact portable model, reference hashes and external Slicer worker.
Outstanding delivery gates remain documented in customer delivery: actual asset
redistribution evidence, canonical candidate creation and clean Windows testing
without developer paths, Python, Linux or network access. Test the real chooser,
completion card, external PDF viewer, save/cancel/retry and writable User Data
under a normal user account, including display scaling. Do not mark these gates
passed based on mocked installed-path tests.
