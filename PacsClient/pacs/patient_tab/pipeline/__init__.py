"""Pipeline — State machine & coordination for the DICOM viewer pipeline.

Modules:
    orchestrator     State machine controlling ZetaBoost, preview engine,
                     and viewer routing across download / pre-downloaded modes.
    load_coordinator Prevents duplicate DICOM loads across interactive and
                     warmup paths.
    preview_engine   Lightweight first-slice previews for Mode B (concurrent
                     download) — NO ITK filters, minimal GIL contention.

Usage (viewer controller __init__):
    from PacsClient.pacs.patient_tab.pipeline import (
        PipelineOrchestrator, PipelineState,
        LoadCoordinator, PreviewEngine,
    )

    self.pipeline = PipelineOrchestrator(
        on_state_changed=self._on_pipeline_state_changed,
    )
    self._load_coordinator = LoadCoordinator()
    self._preview_engine  = PreviewEngine()
"""

from .orchestrator import PipelineOrchestrator, PipelineState
from .load_coordinator import LoadCoordinator
from .preview_engine import PreviewEngine

__all__ = [
    "PipelineOrchestrator",
    "PipelineState",
    "LoadCoordinator",
    "PreviewEngine",
]
