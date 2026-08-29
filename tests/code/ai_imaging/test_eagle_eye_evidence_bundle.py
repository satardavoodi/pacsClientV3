"""Guards for the opt-in Eagle Eye focused evidence bundle.

The production capture remains the immutable source of truth. Focused evidence
is a deterministic, worker-side derivative that gives diagnostic panes more
pixels while retaining the localizer panes and one output image per source
frame. The default path must remain byte-for-byte untouched for safe A/B use.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.ai_imaging.eagle_eye_lumbar import evidence_bundle as evidence  # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import analysis_store               # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import llm_backend                  # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import llm_package as package_mod   # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import protocols                    # noqa: E402


def _capture(bounds=True):
    document = {
        "driving_pane": "sagittal_t2",
        "reference_lines_hidden_on": ["sagittal_t2", "sagittal_t1"],
        "panes": {
            "sagittal_t2": {"label": "Sagittal T2", "role": "primary"},
            "sagittal_t1": {"label": "Sagittal T1", "role": "synced"},
            "axial_t2": {"label": "Axial T2", "role": "reference"},
        },
    }
    if bounds:
        document["viewport_bounds"] = {
            "sagittal_t2": {"x": 100 / 900, "y": 10 / 320,
                             "width": 250 / 900, "height": 300 / 320},
            "sagittal_t1": {"x": 370 / 900, "y": 10 / 320,
                             "width": 250 / 900, "height": 300 / 320},
            "axial_t2": {"x": 640 / 900, "y": 10 / 320,
                          "width": 250 / 900, "height": 300 / 320},
        }
    return document


def _source_package(tmp_path, *, bounds=True, count=1):
    root = tmp_path / "session"
    source_dir = root / "Sagittal"
    source_dir.mkdir(parents=True)
    packaged = []
    for index in range(1, count + 1):
        path = source_dir / f"sagittal_{index:03d}.png"
        image = Image.new("RGB", (900, 320), (255, 0, 255))
        for box, color in (
            ((100, 10, 350, 310), (220, 20, 20)),
            ((370, 10, 620, 310), (20, 210, 20)),
            ((640, 10, 890, 310), (20, 20, 220)),
        ):
            patch = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), color)
            image.paste(patch, box[:2])
        image.save(path, "PNG")
        packaged.append(package_mod.PackagedImage(
            path=path,
            caption=f"[lumbar_sagittal] frame {index} of {count}",
            session="sagittal",
            index=index,
            capture=_capture(bounds=bounds),
        ))

    protocol = protocols.get_protocol("lumbar_mri")
    return package_mod.AnalysisPackage(
        session_dir=root,
        session_id="test-session",
        protocol_id=protocol.id,
        analysis=protocol.analysis,
        header="test header",
        images=packaged,
        study_instance_uid="1.2.3",
    )


def test_default_layout_mode_returns_the_original_package_without_writes(tmp_path):
    package = _source_package(tmp_path)

    prepared = evidence.prepare_package(package, mode=evidence.MODE_LAYOUT)

    assert prepared is package
    assert not (package.session_dir / ".evidence").exists()


def test_focused_bundle_removes_chrome_but_retains_diagnostic_and_localizer_pixels(tmp_path):
    package = _source_package(tmp_path)

    prepared = evidence.prepare_package(package, mode=evidence.MODE_FOCUSED_V1)

    assert prepared is not package
    assert prepared.image_count == package.image_count == 1
    derived = prepared.images[0]
    assert derived.path != package.images[0].path
    assert derived.path.is_file()
    assert derived.source_path == package.images[0].path
    assert derived.evidence_mode == evidence.MODE_FOCUSED_V1
    assert "FOCUSED EVIDENCE" in derived.caption

    with Image.open(derived.path) as image:
        assert image.width <= evidence.MAX_CANVAS_WIDTH
        assert image.height <= evidence.MAX_CANVAS_HEIGHT
        colors = image.convert("RGB").getcolors(maxcolors=image.width * image.height)

    counts = {color: count for count, color in (colors or [])}
    diagnostic = counts.get((220, 20, 20), 0) + counts.get((20, 210, 20), 0)
    localizer = counts.get((20, 20, 220), 0)
    assert diagnostic > localizer > 0
    assert counts.get((255, 0, 255), 0) == 0


def test_focused_bundle_preserves_source_order_and_image_count(tmp_path):
    package = _source_package(tmp_path, count=3)

    prepared = evidence.prepare_package(package, mode=evidence.MODE_FOCUSED_V1)

    assert [item.index for item in prepared.images] == [1, 2, 3]
    assert [item.session for item in prepared.images] == ["sagittal"] * 3
    assert [item.source_path for item in prepared.images] == [
        item.path for item in package.images
    ]
    assert "previous source frame: none" in prepared.images[0].caption
    assert "next source frame: 2" in prepared.images[0].caption
    assert "previous source frame: 2" in prepared.images[-1].caption
    assert "next source frame: none" in prepared.images[-1].caption


def test_focused_bundle_refuses_legacy_captures_without_measured_viewport_bounds(tmp_path):
    package = _source_package(tmp_path, bounds=False)

    with pytest.raises(evidence.EvidenceBundleError, match="viewport bounds"):
        evidence.prepare_package(package, mode=evidence.MODE_FOCUSED_V1)


def test_evidence_mode_is_an_explicit_strict_ab_switch(monkeypatch):
    monkeypatch.delenv(evidence.ENV_EVIDENCE_MODE, raising=False)
    assert evidence.resolve_mode() == evidence.MODE_LAYOUT

    monkeypatch.setenv(evidence.ENV_EVIDENCE_MODE, "focused-v1")
    assert evidence.resolve_mode() == evidence.MODE_FOCUSED_V1

    monkeypatch.setenv(evidence.ENV_EVIDENCE_MODE, "typo")
    with pytest.raises(evidence.EvidenceBundleError, match="unsupported evidence mode"):
        evidence.resolve_mode()


@pytest.mark.parametrize(
    "values,expected",
    [
        ((10, 20, 200, 100, 1000, 500),
         {"x": 0.01, "y": 0.04, "width": 0.2, "height": 0.2}),
        ((-10, -20, 50, 50, 100, 100),
         {"x": 0.0, "y": 0.0, "width": 0.4, "height": 0.3}),
    ],
)
def test_normalized_bounds_are_clipped_to_the_capture_widget(values, expected):
    assert evidence.normalized_bounds(*values) == expected


def test_capture_controller_measures_real_viewports_instead_of_assuming_thirds():
    from modules.ai_imaging.eagle_eye_lumbar.capture_controller import (
        EagleEyeCaptureController,
    )

    class Point:
        def __init__(self, x, y):
            self._x = x
            self._y = y

        def x(self):
            return self._x

        def y(self):
            return self._y

    class Widget:
        def __init__(self, x, y, width, height):
            self.geometry = x, y, width, height

        def mapTo(self, container, point):
            return Point(self.geometry[0], self.geometry[1])

        def width(self):
            return self.geometry[2]

        def height(self):
            return self.geometry[3]

    container = Widget(0, 0, 1000, 500)
    selection = SimpleNamespace(protocol=None, slot_order=("a", "b"))
    controller = EagleEyeCaptureController(
        patient_widget=SimpleNamespace(),
        selection=selection,
        capture_widget=container,
    )
    controller._nodes = {
        "a": SimpleNamespace(vtk_widget=Widget(120, 50, 300, 400)),
        "b": SimpleNamespace(vtk_widget=Widget(460, 50, 300, 400)),
    }

    assert controller._viewport_bounds() == {
        "a": {"x": 0.12, "y": 0.1, "width": 0.3, "height": 0.8},
        "b": {"x": 0.46, "y": 0.1, "width": 0.3, "height": 0.8},
    }


def test_capture_step_persists_bounds_and_source_dimensions(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_lumbar import capture_controller as capture_mod
    from modules.viewer import viewport_capture

    class Point:
        def x(self):
            return 100

        def y(self):
            return 50

    class Widget:
        def width(self):
            return 1000

        def height(self):
            return 500

        def mapTo(self, container, point):
            return Point()

        def repaint(self):
            return None

    class Pixmap:
        def width(self):
            return 2000

        def height(self):
            return 1000

        def devicePixelRatio(self):
            return 2.0

    class SessionStore:
        def __init__(self):
            self.captures = []

        def next_capture_path(self, pass_name):
            return tmp_path / "frame.png"

        def add_capture(self, pass_name, frame):
            self.captures.append((pass_name, frame))

    widget = Widget()
    selection = SimpleNamespace(protocol=None, slot_order=("sagittal_t2",))
    controller = capture_mod.EagleEyeCaptureController(
        patient_widget=SimpleNamespace(),
        selection=selection,
        capture_widget=widget,
    )
    controller._nodes = {
        "sagittal_t2": SimpleNamespace(vtk_widget=widget),
    }
    controller._session = SimpleNamespace(name="sagittal", label="sagittal sweep")
    controller.session = SessionStore()
    controller._running = True
    controller._queue = [0]
    controller._queue_pos = 0

    monkeypatch.setattr(viewport_capture, "grab_widget_pixmap", lambda target: Pixmap())
    monkeypatch.setattr(capture_mod, "save_pixmap", lambda pixmap, path: True)
    monkeypatch.setattr(capture_mod, "QApplication",
                        SimpleNamespace(processEvents=lambda: None))
    monkeypatch.setattr(capture_mod, "QTimer",
                        SimpleNamespace(singleShot=lambda delay, callback: None))

    controller._capture_step({"panes": {"sagittal_t2": {}}})

    stored = controller.session.captures[0][1]
    assert stored["viewport_bounds"] == {
        "sagittal_t2": {"x": 0.1, "y": 0.1, "width": 0.9, "height": 0.9}
    }
    assert stored["source_image"] == {
        "pixel_width": 2000,
        "pixel_height": 1000,
        "device_pixel_ratio": 2.0,
    }


_SCREENING = """LEVEL MAP
  L4-L5: axial frames 1-2

CANDIDATE FINDINGS
```json
{"findings": [{"level": "L4-L5", "candidate": "disc_bulge",
"laterality": "bilateral", "confidence": "moderate",
"evidence": ["sagittal_t2", "axial_t2"], "note": "posterior contour"}]}
```
"""

_VERIFICATION = """VERIFICATION
```json
{"verifications": [{"candidate": "L4-L5 disc_bulge", "status": "CONFIRMED",
"refined_finding": "Mild broad-based bulge.", "reason": "axial confirmation",
"decided_on": ["axial_t2"]}]}
```

FINAL REPORT
PATHOLOGICAL FINDINGS
  L4-L5: Mild broad-based posterior disc bulge.
"""


def test_worker_prepares_focused_evidence_before_gapgpt_dispatch(tmp_path, monkeypatch):
    package = _source_package(tmp_path)
    monkeypatch.setenv(evidence.ENV_EVIDENCE_MODE, evidence.MODE_FOCUSED_V1)
    dispatched = []

    def call(prepared, backend_name, model, stage, header):
        dispatched.append(prepared)
        content = _SCREENING if stage.name == "screening" else _VERIFICATION
        return {"content": content}

    record = llm_backend.run_analysis(
        package.session_dir,
        backend=llm_backend.BACKEND_OPENAI,
        model="test-model",
        package=package,
        call=call,
    )

    assert record.state == analysis_store.STATE_COMPLETE
    assert len(dispatched) == 2
    assert all(run.images[0].evidence_mode == evidence.MODE_FOCUSED_V1
               for run in dispatched)
    request = (package.session_dir / "llm_stage1_request.json").read_text("utf-8")
    assert '"evidence_mode": "focused-v1"' in request
    assert '"source_file": "Sagittal/sagittal_001.png"' in request
