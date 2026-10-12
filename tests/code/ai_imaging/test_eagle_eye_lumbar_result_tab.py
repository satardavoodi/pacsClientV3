"""The Lumbar result stays in the study workspace with its immutable cards."""
from __future__ import annotations

import json

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QTabWidget

from modules.ai_imaging.eagle_eye_lumbar.analysis_store import AnalysisRecord, STATE_COMPLETE


def _app():
    return QApplication.instance() or QApplication([])


def test_lumbar_result_page_contains_report_and_stage_card_gallery(tmp_path):
    _app()
    anatomy = tmp_path / ".evidence" / "anatomy-gate-v4"
    anatomy.mkdir(parents=True)
    image = anatomy / "anatomy_01_disc.png"
    QImage(64, 64, QImage.Format.Format_RGB32).save(str(image))
    (anatomy / "anatomy_manifest.json").write_text(json.dumps({
        "cards": [{
            "request_key": "disc",
            "image_file": image.name,
            "tile_count": 3,
        }]
    }))
    (tmp_path / "llm_stage1_structured.json").write_text(json.dumps({
        "data": {"level_map": [{"level": "L4-L5", "axial_frames": [1, 3]}]}
    }))
    record = AnalysisRecord(
        STATE_COMPLETE,
        tmp_path,
        text="PATHOLOGICAL FINDINGS\n  Synthetic finding.",
        document={"pipeline_version": "8.7.0", "completed_at": "2026-10-10T17:28:18+00:00"},
    )
    from modules.ai_imaging.eagle_eye_lumbar.result_tab import LumbarAnalysisResultPage

    page = LumbarAnalysisResultPage()
    page.show_record(record)

    assert "Synthetic finding" in page.report.toPlainText()
    assert page.findChild(QTabWidget, "eagleEyeStageCardTabs").count() >= 2
    assert page.stage_gallery.session_dir == tmp_path
    page.deleteLater()
