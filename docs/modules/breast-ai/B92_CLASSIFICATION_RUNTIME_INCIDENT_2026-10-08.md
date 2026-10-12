# B92: Detection-only dialog on the active Razi service

## Symptom and verified evidence (2026-10-08)
The owner supplied the detection-available / classification-unavailable dialog.
Its client handler checks absence of csv_classification, not lesion absence.
A read-only audit found the newest retained server engine result had four images,
status success, classification_status unavailable, and no classification-stage CSVs.
Exact linkage to the screenshot request has not been independently verified.
No patient identities, image data or coordinates are recorded here.

The running AIPacsEagleEye service remains on 20261008-lumbar-marrow-r4.
Loading that revision's actual Breast weights and calling its own schema validator
reproduced ValueError: Breast classifier weights and inference feature schema do
not match. There are four base model kinds and four stackers, each requiring nine
features. The active validator accepts only four. This deterministically blocks
classification before ROI processing, consistent with the retained result.

The selected reconciled Developer bundle loads its weights and passes its own
schema validator. Its existing correction reconstructs the additional five stack
features with the saved imputer, rather than bypassing validation. B90 already
records successful synthetic end-to-end classification on both hosts. Neither
finding establishes classification accuracy on this owner's clinical examination.

## Decision and next action
No threshold, weights, UI warning or active service was changed. Hiding the dialog
would conceal incomplete inference. This is a deployment/version gap, not evidence
of poor lesion typing accuracy and not a negative mammography result.

The next runtime action is qualification and controlled activation of the corrected
sealed Breast bundle through the existing deployment workflow, with rollback and
an actual affected-workflow GUI check. Do not overwrite the executing revision.
Do not imply the research calcium branch is clinically connected: B90/B91 integration
and GUI gates remain pending independently. No new training or clinical metric.

This session adds documentation only. Local and Razi Developer document parity is
tracked in the protected b92-classification-incident-20261008 receipt. Active clinical
source remains unchanged; documentation synchronization is not deployment acceptance.
