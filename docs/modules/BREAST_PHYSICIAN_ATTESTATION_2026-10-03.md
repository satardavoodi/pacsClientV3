# Physician crop assessability and negative-label attestation

The owner explicitly confirmed that all previously reviewed mammographic crops were assessable after display-window adjustment, all green rectangles denote real calcifications, and crops without green rectangles contain no calcifications. Repeat quality review is unnecessary. The protected feedback revision records direct-message provenance and scope; the original feedback file remains unchanged.

Aggregate inventory: 46 mammographic crops, 25 positive crops, 59 positive region rectangles, 21 attested calcification-free crops, and two excluded non-mammographic crops. No dense masks or full-image negative labels were created.

Before negative sampling, source-coordinate windows were checked against positive rectangles from other crops of the same image. Twenty negative crops had no positive-region intersection. One negative crop intersects a broad positive region in another crop and is held out of negative training pending geometry/annotation reconciliation. Intersection alone does not prove the physician missed a punctum, because region rectangles can include normal tissue.

The protected same-domain supervision manifest groups by existing source person keys before patch extraction. Current development partition counts are 20 positive and 17 safe negative training crops, plus five positive and three safe negative validation crops. This small, previously inspected development material is not an independent qualification cohort. Overlapping derived crops remain in the same group. Positive rectangles provide region supervision, not all-positive pixel masks.

Protected artifacts remain outside the repository: `physician-feedback-attested-20261002.json` and `same-domain-supervision-20261002.json` under the local authorized breast-review storage. The date in these filenames denotes the existing research version; this attestation clarification continued into 2026-10-03. The aggregate receipt is `generated-files/eagle-eye/calcification-candidate-20261001/physician-attestation-receipt-20261002.json`.

The follow-up page now shows completion rather than requesting another review. Actual same-domain retraining and clinical qualification have not been completed by this label reconciliation step.
