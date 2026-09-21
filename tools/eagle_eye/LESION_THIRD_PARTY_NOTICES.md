# Eagle Eye white-matter lesion candidate runtime

This research integration does not establish clinical qualification or an MS diagnosis.

LST-AI 2.0.0rc1: https://github.com/CompImg/LST-AI
Code license: MIT, as provided in the installed wheel's license/metadata.
Model/atlas release: CompImg/LST-AI v2.0.0-data (unchanged upstream assets).
Wiltgen et al. LST-AI: A deep learning ensemble for accurate MS lesion segmentation.
NeuroImage: Clinical 42 (2024), 103611. https://doi.org/10.1016/j.nicl.2024.103611
The upstream project explicitly identifies the tool as research-only, without
clinical validation/licensing/approval. Review the separate asset terms before release.

HD-BET v1 weights: https://zenodo.org/records/2540695
The record identifies CC-BY-4.0 licensing. Five upstream weights are used unchanged.
Isensee et al. Automated brain extraction of multisequence MRI using artificial
neural networks. Human Brain Mapping 40 (2019), 4952-4964.
https://doi.org/10.1002/hbm.24750
Implementation package: brainles-hd-bet 0.0.11. Its own packaged license is retained.

Embedded Python license and the installed packages' dist-info license/METADATA
files remain in this payload, including PyTorch, torchvision, NumPy, SciPy,
SimpleITK, picsl-greedy and transitive dependencies. Exact dependency versions
are recorded in requirements-lock.txt. FastSurfer annotation is not executed;
this workflow uses segmentation-only mode and does not bundle FreeSurfer.

The AI-PACS adapter adds quoted Windows registration paths, offline-only network
behavior, bounded CPU threading and native-mask validation. These changes are
not an upstream clinical endorsement. Model-bound technical acceptance and
distribution review must be recorded separately before customer release.
