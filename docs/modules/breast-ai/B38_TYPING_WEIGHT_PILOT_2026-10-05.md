# B38: Real typing pilots and source audit

Date: 2026-10-05. Research only; no production changes.

## Source readiness

Indexed 19,012 files under the original Windows A100 VinDr image root, including
alternate extensions. The 62 missing images remain absent there, affecting 69
target rows. This is not a search of all drives. Of 1,280 target rows, 1,191 have
files with matching DICOM header dimensions and in-bounds boxes; 20 need bounds
review, 69 lack files. No clipping or source edits occurred. Deferring two mixed
target rows leaves 1,189 rows from 594 studies. Pixel decoding remains unverified.

## Actual experiment

Nine HistGradientBoostingClassifier fits used 59 cached feat_* columns only.
Identifiers, targets, BI-RADS, density labels, mv_* and bl_* were excluded from
model inputs. Reference-box dependence and cached extraction remain limitations.
Publisher TRAIN only; first fold of five-fold StratifiedGroupKFold for seeds
17, 29, 43. All study views stay together. Exact partition identities match across
variants. Repeated development splits can overlap, so cannot be pooled as independent.
These groups were exposed to legacy training; this is not independent qualification.

Fixed settings: 120 iterations, seven leaves, minimum 15 samples per leaf,
learning rate 0.06, L2 5, no early stopping. Three-way argmax, no threshold tuning.
Missing numeric values remain NaN, handled by the estimator. Two CPU threads.

- A0: inverse study-row-count fitting weights, equal total study weight.
- A1: A0 multiplied by training-only square-root inverse class-study frequency,
  capped at 3; final sample weights normalized to mean 1.
- A2: fitting studies drawn with replacement using mean class factors, then one
  random row per selected study; fitting-row-count draws and plain loss. This
  tests stochastic resampling as well as altered exposure.

All nine saved models reloaded with identical validation probabilities. Private
row order, split indices, probabilities and confusion matrices are retained.

## Results and decision

Arithmetic means across the three development splits, percent:

| Variant | Macro F1 | Mass recall | FA recall | Asymmetry recall |
|---|---:|---:|---:|---:|
| A0 | 38.28 | 94.31 | 21.08 | 0.00 |
| A1 | 39.81 | 87.91 | 31.24 | 0.00 |
| A2 | 40.46 | 86.25 | 28.18 | 6.67 |

A1 gains 10.16 percentage points FA recall but loses 6.40 Mass recall points.
A2 loses 8.06 Mass recall points. Its Asymmetry success consists of two rows in
one split and zero in the other two. Reject both for promotion under B37's
no-observed-Mass-recall-loss gate. These are not comparable to B37's legacy metrics:
cohort, feature contract and prediction rule differ. No deployed regression occurred.

Source audit took 3.19 seconds. Six A0/A1 fits, predictions and serialization took
3.37 seconds; three A2 fits took 1.84 seconds. CSV loading and pixel preparation
are excluded. These are not whole-image inference timings. No GPU or CNN ran.

## Next discriminating action

Do not continue blind weighting/epoch sweeps. Inspect confusion examples, rebuild
native local plus surrounding-context inputs, then compare a compact image encoder
and label-blind view context separately on fixed development groups. Missing
opposite-view detection must not define Asymmetry. Resolve missing files/bounds
before full-cohort expansion. Independent evaluation and patient linkage remain gates.

Protected P artifacts: typing-source-audit-20261005, typing-weight-pilot-20261005,
typing-sampler-pilot-20261005. Scripts: audit_typing_sources_20261005.py,
typing_weight_pilot_20261005.py, typing_sampler_pilot_20261005.py. Receipts include
source, code and model hashes. Private manifests remain outside the project.
Feature CSV SHA-256: 33554753927b2e9054e8fdd36cf2510de171b485902570a182696f413158c01b.
Python 3.12.3 / sklearn 1.4.2. No GUI acceptance or deployment is claimed.
