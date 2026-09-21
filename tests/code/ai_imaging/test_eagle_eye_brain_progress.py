"""Progress stays visible during long stages, without fabricated percentages."""
from concurrent.futures import Future

import pytest


@pytest.mark.parametrize('outcome', ['success', 'failure', 'cancel'])
def test_progress_tracks_pending_stage_and_stops_at_completion(outcome):
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    app = QApplication.instance() or QApplication([])
    widget = BrainVolumetryWidget()
    future = Future()
    widget._future = future
    try:
        widget._begin_progress()
        widget._messages.put('Checking the local model bundle')
        widget._poll()
        assert not widget.progress_bar.isHidden()
        assert widget.progress_bar.maximum() == 0
        assert 'Checking the local model bundle' in widget.status.text()
        assert 'Elapsed' in widget.progress_detail.text()
        assert '%' not in widget.progress_detail.text()
        widget._messages.put('Running local SynthSeg segmentation, parcellation and QC')
        widget._poll()
        assert 'SynthSeg' in widget.status.text()
        if outcome == 'success':
            future.set_result({'pdf_available': True, 'posterior_rows': [], 'normative': {}})
        else:
            if outcome == 'cancel':
                widget._cancel.set()
                widget._poll()
                assert 'Cancellation requested' in widget.progress_detail.text()
            future.set_exception(BrainError('Analysis stopped'))
        widget._poll()
        assert widget.progress_bar.isHidden()
        assert not widget.timer.isActive()
        assert ('Completed' if outcome == 'success' else 'Stopped') in widget.progress_detail.text()
    finally:
        widget._executor.shutdown(wait=False, cancel_futures=True)
        widget.deleteLater()
        app.processEvents()
