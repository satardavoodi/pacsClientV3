# B68: Practical classifier compatibility

Date: 2026-10-06. Code inspection and synthetic CPU forward test, not training or
accuracy evaluation. Extends B66/B67. No runtime/deployment changes.

## Evidence and choice

Inspected protected b64-train.py and b65-adapt.py. Current research uses PyTorch,
two grayscale inputs (local ROI and context), repeated RGB, ImageNet normalization,
shared encoder, concatenated embeddings and a three-class head. Fixed reference
labels/splits and available-source indices already support a paired comparison.

Choose torchvision EfficientNetV2-S as the first NEW comparator. It can reuse this
interface, input cache, group splits and evaluator while replacing the encoder and
head dimension. This is technical compatibility, not evidence of superior accuracy.
ResNet18 remains the most directly compatible incumbent. DINO already runs but B65
failed Mass retention. AsyDisNet lacks a verified ready implementation/checkpoint;
the ResNetV2 mass-descriptor ensemble has a different endpoint and integration cost.
MONAI density classification has the wrong target; MONAI need not be introduced as
a dependency merely to run this experiment.

[Official torchvision model documentation](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.efficientnet_v2_s.html)
provides ImageNet weights, not mammographic lesion-typing weights. Official default
transforms use 384; our matched 224-pixel experiment is an explicit adaptation.
Do not silently apply center cropping that changes the supplied ROI geometry.

## Executed check

On lina100, /usr/bin/python3: torch 2.11.0+cu130, torchvision 0.26.0+cu130.
The separately probed lumbar training environment lacks torchvision; no packages
were installed. GPU snapshot: A100 40 GB, 12,147 MiB free; test itself used CPU only.

Synthetic random weights, CPU FP32, two threads, one pair of 224x224 inputs batched
together, two warmups and ten measured forwards. Three finite normalized outputs.

| Architecture with replacement typing head | Parameters | Mean pair forward |
|---|---:|---:|
| ResNet18 | 11,179,587 | 40.68 ms |
| EfficientNetV2-S | 20,185,171 | 99.96 ms |

This measures shape/runtime feasibility only. It excludes file reading, image
preparation, detector, batching across lesions and target-server variability. It is
not a Razi benchmark, trained-weight load check or clinical response-time guarantee.
No optimizer/backward/checkpoint test ran here. Random output has no accuracy meaning.

Protected script and machine-readable receipt: P and R `b68-compatibility.py` and
`b68-cpu-compatibility.json`, using roots in the current-state document. Receipt was
copied back to P. No private images/identifiers were involved.

## Decision and remaining gates

EfficientNetV2-S passes the bounded input/output CPU compatibility check and is the
first candidate to train. It is slower than the incumbent in this test but its crop
forward cost is small; total study cost remains unmeasured. Existing weights cannot
be copied from ResNet because parameter structures differ. Start from verified
official initialization, replace the head, freeze a training protocol and perform
real update/reload checks before paired fitting. Same cohort and endpoints as B64;
report pretraining differences and repeated development exposure. Choose on macro-F1,
per-class retention and end-to-end CPU time, not feasibility alone. No accuracy winner
or newly qualified classifier has been established.
