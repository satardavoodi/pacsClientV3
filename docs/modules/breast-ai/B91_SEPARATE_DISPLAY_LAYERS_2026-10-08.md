# B91: Separate Breast display layers

Date: 2026-10-08. Owner decision: retain FCOS for parenchymal findings and show
the new calcium branch separately, with independent on/off controls. Remove legacy
FCOS calcium classification from presentation. Stage: source UI implementation;
authenticated end-to-end calcium publication and live GUI acceptance remain pending.

## Display contract

- The Breast AI viewport has `Parenchymal lesions: on/off` and a separate
  `Microcalcifications: on/off` button. They occupy separate rows to fit paired
  CC/MLO panes. Parenchymal boxes, labels and segmentation keep their existing
  ownership; toggling them does not change calcium visibility and vice versa.
- Calcium has its own gold point actor, using the viewer's native IJK-to-world
  transform with the existing Y flip. It is not inserted into the tissue box or
  segmentation collections. Support points are not individual-focus counts and
  do not carry morphology/BI-RADS claims.
- Until a successful dedicated calcium result is delivered, its control is disabled
  and says `Microcalcifications: unavailable`, explicitly not a normal conclusion.
  A successful empty result is different from missing inference.
- Legacy AI labels containing `calcif` are removed from the displayed FCOS item
  before both sidebar population and box creation. Raw CSVs, model weights, box
  coordinates, scores and human corrections are retained. A calcium-only legacy
  box remains an unclassified detection, not an invented Mass or normal finding.
- Existing Mass/Asymmetry/Distortion labels, when actually supplied, remain visible.
  The incumbent's four-label head does not independently predict Architectural
  Distortion; no such capability is fabricated by adding a display control. Manual
  review classification options remain available.
- Bone Age retains its previous generic box control. Lumbar keeps its existing
  no-box-control behavior. Both original source viewers and other execution domains
  remain separate.

## Implementation and lifecycle

`modules/ai_imaging/ai_module_ui/breast_display.py` owns presentation filtering,
strict image binding and the calcium actor collection. The existing AI VTK override
adds the two controls and a GUI-thread `set_microcalcification_result(result)` sink
for the complete dedicated server branch. Only `status=success` and
`coordinate_space=native_source_pixels_xy` are accepted. Study, series, single SOP,
native dimensions and finite in-bounds points must match; no resize or identity
guessing. Missing/duplicate/foreign-image results are rejected.

Series changes and AI run selection clear calcium actors and availability. Tissue
visibility is reapplied after box creation and asynchronous segmentation completion,
so new actors respect the current off state. No clinical source image or annotation
file is modified by toggling visibility.

The B90 research coordinator is still outside the clinical artifact publisher.
This change supplies the UI sink; it does not pretend the installed server already
sends calcium records. The remaining connection must use the authenticated server
job, run identity, allowlisted artifact and existing client result lifecycle. Do not
populate this layer from FCOS calcium labels or start a client-local model as a fallback.
B90 numerical portability, native CPU cost and qualification gates still apply.

## Verification

Local focused run: 30 passes (15 display contracts, four detection-only compatibility
cases, eleven dual-branch guards). It includes actual Qt button clicks offscreen and
VTK actor construction/native transform checks without opening a patient or rendering
a live clinical viewport. Label filtering preserves raw records and human corrections;
independent toggles, source switch clearing, non-Breast control behavior, mismatched
identity/geometry and unavailable results are covered.

The immediate repaint guard failed before the clear-path correction, then passed:
removing actors must repaint even if the replacement payload is rejected. Initial
Razi collection through the eager GUI package initializer failed in unrelated
PortAudio startup under SSH. Component tests now load the same leaf file directly,
without initializing the application/audio stack; this does not claim full app
startup acceptance or fix the separate audio environment.

Final focused runs: local 30 passed in 1.79 seconds; Razi Developer 30 passed in
2.96 seconds. The declared source inventory now has 8,173 matching file hashes,
with no missing/different files; active Razi remains r4. Updated source, tests and
documents are synchronized, not clinically activated.

Mirror verifier: 517 matching pairs, no drift; affected UI paths have no existing
plugin payload copies. No model or deployment flag was changed. Source parity is
recorded in the protected B91 receipt on local/Razi, separately from activation.

Live GUI: NOT PASSED. The existing `aipacs-control` CLI ping failed because the local
Test Control Server was unavailable. No relaunch, authentication automation or change
to the normal test-server flag was attempted. The next fresh source session must
check both overlay switches on an actual same-study result, empty/unavailable states,
zoom/pan, different views and switching AI runs. Unit/offscreen tests do not replace it.

Protected receipts: `C:/AI-PACS-Datasets/breast-review/point-review-20261003/b91-display-20261008`
and `D:/Eagle Eye Server/staging/breast-b91-20261008`. No new training or accuracy claim.
