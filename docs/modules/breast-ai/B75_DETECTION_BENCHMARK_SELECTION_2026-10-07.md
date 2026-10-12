# B75: Full-image, class-agnostic detection benchmark selection

## Objective and decision

Owner prioritizes finding actual abnormalities regardless of predicted type, with
few unnecessary marks. Select existing VinDr publisher TEST full images as the
immediate benchmark for annotated follow-up findings, complemented by explicit
BI-RADS1 negatives. This replaces reference-ROI typing as the primary next endpoint.
It does not establish detection of all benign findings or independent generalization
from historical Razi training. INbreast is the preferred external localization
confirmation candidate, pending legitimate complete data access and exposure audit.

## Verified local inventory

Read-only CSV/file inventory executed on Windows A100 on2026-10-07.
Source: `F:/Aisan-Rahimi-part2/MammoDicomData/original data`.
Annotation SHA256:59cae3a856026b8b5822ed545e5150efce43f8f2f8aca991ce69d1fd221e4cbc.
Protected inventory: `D:/Enhanced Mammography/candidates/20261001-calcification/b75-detection-benchmark-20261007/`.
Script: parent `b75-inventory.py`; summary copied to the equivalent B75 directory
under the established local point-review research root. No images copied externally.

| Stratum | Publisher TEST images | Locally available unique files |
|---|---:|---:|
| At least one finite, positive-area reference box | 357 | 295 |
| BI-RADS1 and all finding rows explicitly No Finding | 2682 | 2258 |
| Unboxed, not accepted as normal | 961 | 819 |
| Total | 4000 | 3372 |

Publisher TEST contains1000 studies. Local files cover843 complete four-view studies;
628 images are missing or ambiguous. Available positive images contain368 annotation
rows; these have not yet been checked for duplicate lesions, image bounds, reader
semantics or DICOM geometry. Box counts are not counts of distinct biological lesions
across views. File presence is not pixel-decode or checksum verification. A missingness
audit and native geometry/QC gate precede final manifest freezing.

## Dataset selection and limits

Sources checked2026-10-07:

- [VinDr-Mammo official release](https://physionet.org/content/vindr-mammo/1.0.0/):
  four-view FFDM, expert annotations, publisher TEST. The annotation policy explicitly
  omits BI-RADS2 finding boxes; BI-RADS3/4/5 findings are boxed. Thus no box does not
  imply no lesion. It cannot by itself assess every benign mass or calcification.
  Existing authorized local data can support the scoped experiment; credentialed
  access/license applies to any missing-file acquisition.
- [INbreast original paper](https://recipp.ipp.pt/bitstreams/8184de8f-c540-4f48-9ab9-a4cb5d0851a8/download):
  115 cases/410 digital images with detailed lesion annotations, including masses,
  calcifications, asymmetries and distortions. Useful independent-source candidate,
  small support and model-specific exposure still matter. Complete local availability
  is not established; prior work verified only a small author's sample. The historical
  official access URL could not be opened in this session. No complete download,
  license acceptance or request sent; do not substitute an unverified mirror.
- [CBIS-DDSM source paper](https://www.nature.com/articles/sdata2017177) and
  [TCIA collection](https://www.cancerimagingarchive.net/collection/cbis-ddsm/):
  complementary full-image mass/calcification localization with ROI masks and benign/
  malignant annotations. Digitized film acquisition differs from FFDM. Use as a
  secondary lesion challenge set, not a comprehensive asymmetry/distortion benchmark
  or a representative normal screening denominator. Benign is not no lesion.

## Prespecified comparison contract for the next run

1. Inputs are complete native images, not reference-guided crops. Reference boxes
   belong only to the evaluator. All models receive the same eligible images; each
   retains its documented frozen preprocessing. Preserve all four views per study.
2. Compare full detection paths: inspected Razi detector, research detector changes,
   and separately the added microcalcification branch and combined output. ROI-only
   classifiers cannot compete as autonomous detectors. A shared detector followed
   only by renamed types has identical discovery unless the later stage suppresses
   boxes; report detection before and after such filtering separately.
3. Primary endpoint is class-agnostic per-view reference-lesion recall. Freeze a
   one-to-one box matching rule before inference (proposed IoU>=0.3 primary,
   IoU>=0.5 secondary). Final evaluator must test matching on synthetic boxes.
   Oversized whole-breast boxes must not count as finding every lesion. Record box
   sizes and union tissue coverage. Calcification cluster regions and individual
   points require separate matching contracts, never pooled point/box denominators.
4. At frozen development-selected operating points report lesions found/missed,
   marks per image, normal-image false-alarm fraction and runtime. Summarize FROC
   at0.5,1,2 false marks/image without deploying TEST-optimized thresholds. Use paired
   study-bootstrap uncertainty and explicitly limited patient linkage.
5. Primary negative stratum requires explicit BI-RADS1/No Finding and QC. Do not
   treat the819 unresolved/unboxed images as negatives. On positive images, unmatched
   model marks may represent omitted benign findings: report unmatched marks and
   keep blinded adjudication separate from unchanged-label results. No automatic
   claim that every unmatched mark is a clinical false positive.
6. Record full-image pixel hashes, train/development/review overlap, model hashes,
   operating points and source exclusions before inference. B72/B74 already exposed
   part of TEST. Historical Razi exposure remains unknown; report a shared exposed
   benchmark, not universally unseen data. Later selected candidates need independent
   confirmation, preferably a blinded local temporal cohort or audited external source.
7. Failures/unavailable results remain explicit, including B74 classifier gate failure.
   Detector output can still be assessed separately; do not call failure normal.

## Status and next action

Dataset research and local inventory completed; no new model inference or accuracy.
Fit/optimizer/learning curves not applicable. No clinical rollout or GUI verification.
Next validate native image/annotation geometry, deduplicate boxes, audit exposure and
freeze the scoped full-image manifest. This dataset choice supports a useful immediate
comparison; broad all-lesion or clinical qualification remains beyond its label scope.
