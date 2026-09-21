"""Opt-in, synthetic-only provider checks; never use patient text or live databases.

Run with AIPACS_TEST_TEMPLATE_MODEL=1 and pytest -m live. Uses the configured
company reporting account and incurs six ordinary report-generation requests.
"""
import json
import os
import re

import pytest

from modules.EchoMind import normal_templates as nt

pytestmark = [pytest.mark.live, pytest.mark.skipif(
    os.environ.get("AIPACS_TEST_TEMPLATE_MODEL") != "1", reason="Explicit synthetic provider test opt-in required")]

CASES = [
    ("CT", "There is a 12 mm cyst in the liver.",
     "Liver: Normal size and attenuation. No focal lesion.\nGallbladder: No gallstones.\nSpleen: Normal size.\nPancreas: Normal morphology.",
     ["no gallstones", "normal size", "normal morphology"], ["no focal lesion", "kidneys", "adrenal"]),
    ("MRI", "There is a tear of the lateral meniscus.",
     "Both menisci demonstrate normal morphology and signal intensity.\nThe anterior and posterior cruciate ligaments are intact.\nNo joint effusion.",
     ["medial meniscus", "cruciate ligaments are intact", "no joint effusion"], ["both menisci", "lateral meniscus", "cartilage"]),
    ("SONOGRAPHY", "There is a gallstone in the gallbladder.",
     "Liver: Normal echogenicity.\nGallbladder: No gallstones.\nSpleen: Normal size.",
     ["normal echogenicity", "normal size"], ["no gallstones", "kidneys"]),
    ("RADIOLOGY", "There is a fracture of the distal radius.",
     "Radius: No fracture.\nUlna: No fracture.\nJoint spaces are preserved.",
     ["ulna", "no fracture", "joint spaces are preserved"], ["radius: no fracture", "soft tissues"]),
    ("MAMOGRAPHY", "There is a circumscribed mass in the upper outer quadrant of the right breast. BI-RADS 3.",
     "Right breast: No mass.\nLeft breast: No suspicious mass.\nNo suspicious calcification.",
     ["no suspicious mass", "no suspicious calcification"], ["no mass", "skin thickening"]),
    ("OBSTETRIC ULTRASOUND", "There is mild fetal left renal pelvic dilatation.",
     "Fetal kidneys: No renal pelvic dilatation.\nFetal bladder: Normal appearance.",
     ["right", "normal appearance"], ["left renal pelvis: no", "four chamber"]),
]


@pytest.mark.parametrize("modality,pathology,template,kept,removed", CASES)
def test_imported_template_controls_model_normals(tmp_path, monkeypatch, modality, pathology, template, kept, removed):
    from modules.EchoMind.reception_templates import import_selected
    from modules.EchoMind.settings_store import get_echomind_api_key
    from modules.EchoMind.api_manager import Manage
    from modules.EchoMind.viewer_chat.openai_reporter import reporter
    monkeypatch.setattr(nt, "library_path", lambda: str(tmp_path / "library.json"))
    key = get_echomind_api_key()
    if not key:
        pytest.skip("Company account is not configured")
    Manage.instance().detect_center(key)
    record, problem = nt.normalize_record({"Name": "Synthetic normal template", "Html": template, "Modality": modality})
    assert not problem
    import_selected(record)
    saved = nt.load_library()[0]
    result = reporter(pathology, modality=modality, normal_template=nt.template_body_text(saved))
    report = json.loads(result["content"].replace("<|end|>", "").strip())
    normals = json.dumps(report.get("Normal Findings", "")).lower()
    assert all(phrase in normals for phrase in kept), normals
    assert not any(phrase in normals for phrase in removed), normals
    if modality == "OBSTETRIC ULTRASOUND":
        # Narrowing a paired statement may insert laterality inside its phrase.
        assert re.search(r"no (?:right )?renal pelvic dilatation", normals), normals
