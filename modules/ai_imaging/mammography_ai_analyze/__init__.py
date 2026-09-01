"""Intelligent AI Analyze for Mammography.

Reuses the existing GAPGPT/EchoMind infrastructure established by Eagle Eye
Lumbar — same backend module, same ``EagleEyeImageAnalysis`` transport, same
``ApiWorker`` QThread, same authentication path — but with mammography-specific
data collection (multi-view images, bounding boxes, CSV detection results) and
a specialised multimodal clinical-analysis prompt.
"""
