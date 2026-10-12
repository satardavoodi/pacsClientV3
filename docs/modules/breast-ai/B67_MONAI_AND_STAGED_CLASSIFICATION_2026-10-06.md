# B67: MONAI inventory and staged classification decision

Date: 2026-10-06. Literature/artifact review only. No training, downloads of weights,
inference or deployment. Extends B66; its paired ROI comparator remains next.

## Verified inventory and applicability

Checked the official Project-MONAI/model-zoo `models` directory through GitHub API,
the public catalog, relevant bundle source documentation and NVIDIA NGC search.
No pretrained mammographic Mass/asymmetry/architectural-distortion ROI typing bundle
was identified in the inspected inventory. This is a bounded search result, not a
claim that no community model exists.

- [Breast density bundle](https://github.com/Project-MONAI/model-zoo/tree/dev/models/breast_density_classification):
  official pretrained InceptionV3, Mayo data, input 299x299 with three channels.
  [Metadata](https://raw.githubusercontent.com/Project-MONAI/model-zoo/dev/models/breast_density_classification/configs/metadata.json)
  version 0.1.9 specifies density A-D, not lesion BI-RADS assessment 0-6. Its reported
  accuracy 0.96 is density performance, not lesion typing. Intended use is an example,
  not diagnosis. Weights were not downloaded or load-tested. README says training
  pipeline is work in progress. Possible later use: density-stratified error analysis
  or an explicitly tested contextual feature, never a substitute lesion classifier.
- [Pathology tumor detection](https://github.com/Project-MONAI/model-zoo/tree/dev/models/pathology_tumor_detection)
  concerns histopathology whole-slide metastases (CAMELYON16), not mammography.
  Nuclei classification bundles likewise must not be selected by the word breast.
- [MONAI EfficientNet implementation](https://github.com/Project-MONAI/MONAI/blob/dev/monai/networks/nets/efficientnet.py)
  provides architectures, not task-trained mammographic typing weights. Its B0-B8
  family must not silently replace the EfficientNetV2 comparator selected in B66.
  A framework change alone is not an accuracy intervention.

## Complementary stages: proposed experiment, not proven improvement

1. Frozen localization and shared native-image preprocessing/crop cache.
2. Independent ROI appearance typing with context: Mass, asymmetry family, AD and
   explicit uncertainty. First compare the compact B66 candidate against control.
3. Conditional specialist heads for shape/margin and difficult type discrimination.
   Preserve probabilities and uncertain cases; do not irreversibly route a wrongly
   typed lesion away from every other expert. Compare flat versus staged predictions
   on exactly the same cases, including routing errors and total CPU cost.
4. Multi-view evidence and subsequent BI-RADS assessment are separate endpoints.
   Density A-D is neither malignancy nor lesion assessment. Missing views or missing
   descriptor labels remain unknown, not negative labels.

Do not run all networks on every region merely because each is available. Train and
evaluate each component separately, then test incremental benefit. Specialist
training uses reference labels; evaluation also measures the actual predicted route.
Select routes and thresholds on grouped inner development data, not the outer test.
Full deployed-stage throughput must include preprocessing and all invoked experts.

## Decision and next action

Retain the B66 EfficientNetV2 experiment priority. MONAI is eligible as training and
packaging infrastructure, not a new assumed pretrained solution. Defer density-model
integration until lesion typing has a controlled result; existing source density
labels can support stratified analysis without another inference pass. Add specialists
only if paired evaluation improves minority typing without unacceptable Mass loss.
No new accuracy evidence in B67. Research documents updated; runtime/GUI tests not
applicable to this documentation-only change.
