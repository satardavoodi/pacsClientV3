# cvi42 Flow Export — Same-Study VM Collapse Diagnosis and Guarded Fix

**Date:** 2026-09-01

**Status:** Root cause proven; source fix implemented and automatically verified; cvi42 live re-import pending

**Privacy:** No patient identifiers, clinical paths, raw study/series/instance UIDs, images, or private-tag values are recorded here.

## Outcome

AI-PACS did not lose the flow pixels, Siemens CSA velocity metadata, instance identities, cardiac phases, or magnitude/phase series. The socket-served DICOM objects had already collapsed standard multi-valued text elements into one Python-list representation before the workstation stored them.

The decisive defect is `(0008,0008) Image Type`:

| Same flow instance | Value model |
|---|---|
| Reference export | Five real DICOM values; VM=5; pydicom `MultiValue` |
| AI-PACS export before correction | One string containing the textual representation of a Python list; VM=1 |

Flow software uses the Image Type components to distinguish base, magnitude, and phase images. Once the phase marker is no longer an individual component, cvi42 can import/display the study while withholding flow quantification.

The malformed representation is also non-conformant for VR `CS`: list punctuation is not part of the CS character repertoire, and the string can exceed the per-value length limit.

The governing references are DICOM PS3.5 Table 6.2-1 for VR encoding and value multiplicity, PS3.6 for the standard data-element dictionary, and PS3.3 C.8.3 for the MR Image Module:

- https://dicom.nema.org/medical/dicom/current/output/html/part05.html#table_6.2-1
- https://dicom.nema.org/medical/dicom/current/output/chtml/part06/chapter_6.html
- https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.8.3.html

## Same-study evidence

The two supplied local exports were compared only in memory. Identity values were compared for equality and were not printed or persisted.

### Whole-study alignment

- 1,700 DICOM instances in the reference export and 1,700 in the AI-PACS export.
- 1,700/1,700 SOP Instance identities intersect exactly.
- 80/80 Series Instance identities intersect exactly.
- The Study and Frame of Reference identities match.
- Every flow series in the inspected 43–54 range contains the same 30 instances in both exports.

### Flow payload integrity

Across 360 paired flow instances:

- Pixel Data bytes are identical: 360/360.
- Siemens CSA Image Header bytes are identical: 360/360.
- Siemens CSA Series Header bytes are identical: 360/360.
- Study, Series, SOP, and Frame of Reference identities are equal: 360/360.
- The reference uses Explicit VR Little Endian; the server-served copy uses Implicit VR Little Endian. The correction preserves the received transfer syntax rather than transcoding it.

### Metadata divergence

Before correction, all 1,700 AI-PACS instances had Image Type collapsed to VM=1. Other standard VM>1 elements were affected where present, including Scanning Sequence, Sequence Variant, and Scan Options. Private elements were present; their values are not included in this report.

This falsifies the competing hypotheses of missing flow frames, UID regeneration, lost velocity pixels, stripped CSA/VENC blocks, or DICOMDIR series-record insufficiency.

## Earliest failing boundary

The active workstation download path base64-decodes and optionally gunzips the server payload, then writes those bytes atomically through `.part` and `os.replace`. It did not create the malformed Image Type. The CD export in Original mode is intentionally passthrough, so it faithfully exported the malformed locally stored objects.

The root defect is therefore the upstream socket/PACS-server DICOM serialization that converted a pydicom multi-value to `str(value)`. The workstation fix is a compatibility defense; the server serializer still requires its own correction so it emits the original DICOM bytes or real multi-value lists.

## Implemented correction

`PacsClient/utils/dicom_vm_normalization.py` is the single normalization authority.

It repairs an element only when all of these are true:

1. the element is standard, not private;
2. its DICOM dictionary VM permits more than one value;
3. its VR is textual;
4. its current value is one strict Python-list literal;
5. every parsed item is a string.

The helper does not infer or fabricate values. VM=1 elements and all private elements remain untouched.

The authority is used at two boundaries:

- socket ingestion, before the atomic final write, protecting newly downloaded studies;
- DICOMDIR/media copy creation, repairing exports from previously downloaded local studies without mutating the local source files.

Clean DICOM payloads return as the exact original bytes. Parse/write/validation failure fails open to the exact received bytes and records only a non-sensitive exception type. Normalized payloads are re-read to prove transfer syntax and identity preservation and that the restored VM persisted.

The existing diagnostic repair tool now delegates to the same authority.

## Regression and verification evidence

The new guard initially failed during collection because the normalization authority did not exist. After implementation:

- `test_dicom_vm_normalization.py`: 5 passed.
- DICOM media/DICOMDIR adjacent suite: 27 passed.
- Socket cancellation boundary: 8 passed.
- Offline selection, CD payload, and plugin-builder boundary: 13 passed, 4 deselected.
- Plugin mirrors: 462/462 matched.

The real 360-instance flow set was then normalized in memory:

- 360/360 objects changed; 0 normalization errors.
- Image Type, Scanning Sequence, Sequence Variant, and Scan Options equal the reference multi-values after correction: 360/360.
- Pixel Data, both CSA blocks, and all four identity levels remain equal: 360/360.
- Received Implicit VR Little Endian remains unchanged: 360/360.
- Measured normalization time: median 7.711 ms/instance, p95 10.741 ms/instance, 2.982 seconds total for 360 instances on the development machine.

The pre-existing tolerant socket-payload suite remains red for five unrelated missing/drifted guards already named by the repository readiness baseline; the VM correction did not introduce those failures.

## Remaining gate

Restart the source build, export the same study again, import that new media into cvi42, and confirm that flow quantification is enabled for the phase/magnitude groups. This human interoperability check is still required; automated DICOM equivalence is not a cvi42 clinical validation.

Previously downloaded local source files are intentionally not rewritten in place. Their new media exports are corrected during DICOMDIR creation. A re-download after the source update stores corrected objects at ingestion.
