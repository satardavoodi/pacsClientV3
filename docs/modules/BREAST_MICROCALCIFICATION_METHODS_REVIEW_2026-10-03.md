# Microcalcification methods: primary-study review

Checked 2026-10-03. Target: autonomous native-resolution calcification localization with high lesion retention and a controlled false-mark burden. This is a focused primary-source review, not a systematic review or a ranking of current commercial products. No new model was trained or promoted during this literature review.

## 1. Local detail plus surrounding context

[Wang and Yang, 2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC6242284/) combined a small-detail CNN branch with a surrounding-context branch after a sensitive DoG candidate stage. On 292 evaluation mammograms, the individual-object experiment reported 79.7% sensitivity at 1 FP/cm² versus 62.9% for its local-only network. Cluster sensitivity was 87.4% at 0.5 FP clusters/image. Cluster evaluation used a pre-scouting step selecting up to four suspicious regions, so it is not unrestricted whole-image exhaustive detection.

Local application: test an explicit two-branch candidate scorer against our existing stacked detail/context channels. The concept alone is not new to our experiments; the improvement must come from training coverage, candidate distribution and end-to-end validation. FP/cm² and FP clusters/image are different units.

## 2. Native-scale compact segmentation and hard negatives

[Segmenting Microcalcifications in Mammograms and its Applications, 2021](https://www.weizmann.ac.il/math/bagon/sites/math.bagon/files/publications/mc_segmentation_spie21_full.pdf) preserves original image scale and emphasizes online hard-negative mining. Its training uses a 1:3 positive-to-hard-negative ratio instead of allowing easy background pixels to dominate the loss. The indexed author PDF supplied training details; full PDF fetch timed out during this review, so no uninspected numeric detection endpoint is asserted.

Local application: train a native-resolution candidate/pixel model on valid point or mask labels and real model-generated negative examples. Prior negative mining was used mainly for a verifier; it did not demonstrate equivalent backbone adaptation. The paper's ratio is a comparator, not a universally optimal setting. Unknown pixels in positive regions cannot enter negative mining.

## 3. Bright-object physics plus learned proximity

[HDoGReg, final journal study](https://link.springer.com/article/10.1007/s10278-022-00751-3) combines multi-scale DoG/Hessian candidates with a learned proximity map. It accommodates point and precise-boundary labels and was trained/validated on 435 mammograms. INbreast test TPR was 74.4% at 0.4 FP/cm², versus 58.1% for its implemented comparator. Local fine-tuning improved portions of the local FROC curve, but residual false detections remained substantial.

Local application: a task-matched alternative to broad U-Net components; bright intensity proposes objects while a network judges them. Physician cluster rectangles do not provide individual centers for proximity-map supervision. Use actual publisher points or region-level weak objectives, preserving unknown labels.

[Author repository](https://github.com/cmarasinou/HDoGReg) advertises code and pretrained-model download scripts. Downloads, checkpoint hashes, inference compatibility and commercial model rights have not been verified locally; repository existence is not a qualified bundle.

## 4. DeepMiCa: tiny-target loss and separated tasks

[DeepMiCa, 2023](https://www.sciencedirect.com/science/article/pii/S0169260723001499) uses preprocessing, patch U-Net segmentation and a separate malignancy classifier. The indexed [author manuscript](https://iris.unipv.it/retrieve/784885f2-7bff-48a2-b621-ce1e571b5d99/DeepMica.pdf) describes keeping positive-pixel loss and the hardest three times as many negative-pixel losses. It also restricts CBIS-DDSM outputs to known reference ROIs for downstream ROI preparation; that operation must not be copied into autonomous inference. Segmentation AUROC 0.95 and malignancy-classification AUROC 0.89 are distinct outcomes, not screening detection percentages.

Local application: compare staged decoder/encoder fine-tuning and a tiny-target objective rather than only adapting the final 65 parameters. Match input/label semantics first and retain the rejected original transfer as a comparator.

## 5. Why 98% may not mean whole-image localization

[Pesapane et al., 2023](https://link.springer.com/article/10.1186/s41747-023-00384-3) reports AlexNet sensitivity 98% and specificity 89% for microcalcification presence. The methods/results use 112×112 patches, separate detection-presence and malignancy tasks, and group patient/image-derived patches across splits. Whole-image heatmaps are assembled by sliding-window predictions. The reported patch metrics do not establish full-image FROC at a clinical false-mark budget. Increasing network complexity did not improve performance in that comparison.

Local application: credible support for a compact patch classifier, but our patch-to-whole-image gap requires its own audit; the paper does not justify adopting AlexNet as the best detector.

## 6. Coarse-region supervision

[LatentCADx, 2021](https://www.frontiersin.org/journals/big-data/articles/10.3389/fdata.2021.742779/full) combines classification/segmentation with constraints for imprecise region annotations. It addresses over-segmentation induced by coarse labels. The dataset includes masses and calcifications and uses substantial image downsampling, so it is methodological support for weak supervision rather than proof of native tiny-calcification sensitivity.

Local application: use physician rectangles as region constraints, not filled positive masks. Outside-box penalties require sufficiently complete reviewed labels; incomplete annotations make those pixels unknown.

## 7. Emerging refinement: exploratory, not first choice

[Kim et al., 2025 preprint](https://pubmed.ncbi.nlm.nih.gov/41356355/) uses a segmentation prior and generative reconstruction/subtraction for refinement. It reports pixel PPV increasing from 3.2% to 7.3% while retaining sensitivity above 95%. The indexed [full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC12676427/) acknowledges lack of true normal full-field mammograms in evaluation. These are pixel endpoints, and 7.3% PPV still does not establish acceptable screening boxes. Do not prioritize this added complexity before simpler candidate/scoring controls.

## Indirect evidence that must not become calcification claims

[Ultra-high-resolution multi-scale context-aware mammography, 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9270480/) isolates resolution, scale and context in ablations, supporting the value of actual native crops rather than upsampling compressed images. Its calcification support was only three diagnostic and nine screening images; the authors explicitly state that microcalcification performance was inadequately studied. It is not a calcification sensitivity benchmark.

## Recommended bounded comparison for our pipeline

The recommendation is an inference from published mechanisms and our local failures, not a proven best architecture.

1. Compare two native candidate sources on frozen development groups: the original segmentation before broad grouping, and multiscale DoG/Hessian. Inspect candidate coverage and burden before adding a scorer. A scorer cannot recover objects absent from its candidate set.
2. Compare an explicit detail/context scorer with staged native segmentation adaptation. Use genuine point labels, region-bag supervision and verified hard negatives from training only. Run a tiny training-subset fit before scale-up; do not reuse previously inspected patch-test scores for tuning.
3. Cluster accepted objects using physical spacing and bounded geometry, retaining individual-object evidence. Avoid dilation chains spanning most of the image and arbitrary deletion of large true clusters.
4. Measure individual-object recall where point truth exists, region/cluster recall where region truth exists, negative-image false marks, positive-pixel footprint and box area. Select on full-image FROC at matched false-positive budgets, not isolated patch accuracy or box occupancy.
5. Begin with an 8 GiB research process cap on the actual A100 40 GB, measure full-image latency/VRAM and refresh free memory before execution. Hardware feasibility and quality remain separate gates. No need for H200 has been demonstrated by this review.

First alternative to qualify for reproducibility: HDoGReg candidate/proximity components, with staged native segmentation as fallback if its candidates miss reviewed lesions. Asset access/license and domain transfer checks precede reuse. Eight reviewed training cases support debugging, not clinical qualification.
