"""Source-wiring guard for the Previous-Exams feature.

Text-level assertions (no imports of Qt) that fail loudly if the feature's
functions / flags / call-sites are removed or renamed — the same style as
``test_unified_pipeline_wiring.py``. Protects against a silent revert or a stale
build dropping the wiring.
"""
import os

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(rel):
    with open(os.path.join(_REPO, *rel.split("/")), "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def test_socket_client_has_new_endpoints():
    src = _read("modules/network/socket_client.py")
    assert "def get_patient_status(" in src
    assert "def get_patient_reception_history(" in src
    assert "GetPatientStatus" in src
    assert "GetPatientReceptionHistory" in src


def test_socket_patient_service_has_sync_wrappers():
    src = _read("modules/network/socket_patient_service.py")
    assert "def get_patient_status_sync(" in src
    assert "def get_reception_history_sync(" in src


def test_previous_exams_module_surface():
    src = _read("PacsClient/utils/previous_exams.py")
    for name in (
        "class PreviousExamStudy",
        "class PreviousExamSet",
        "def parse_patient_status(",
        "def parse_reception_history(",
        "def build_previous_exam_set(",
        "def sanctioned_study_uids(",
    ):
        assert name in src, name
    # must stay pure (stdlib only) — no Qt/network/pydicom imports
    assert "PySide6" not in src
    assert "import socket" not in src


def test_merge_study_uids_has_sanctioned_param():
    src = _read("PacsClient/utils/patient_study_set.py")
    assert "sanctioned_uids" in src
    # both the public authority and the convenience resolver thread it through
    assert src.count("sanctioned_uids") >= 4


def test_previous_exams_mixin_surface():
    src = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_previous_exams.py")
    for name in (
        "class _PWPreviousExamsMixin",
        "def init_previous_exams(",
        "def _apply_previous_exam_button_state(",
        "def _toggle_previous_exams_view(",
        "def _on_previous_exam_row_clicked(",
        "def _apply_previous_exam_merge(",
        "def _register_previous_exam_with_dm(",
        "def _is_sanctioned_previous_exam(",
        "AIPACS_PREVIOUS_EXAMS",
    ):
        assert name in src, name
    # merges via the unified sink + canonical payload (no parallel workflow)
    assert "set_server_series_info" in src
    assert "build_download_payload" in src


def test_patient_widget_includes_mixin():
    src = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/widget.py")
    assert "_PWPreviousExamsMixin" in src
    assert "import _PWPreviousExamsMixin" in src
    # present in the class bases line
    base_line = next(l for l in src.splitlines() if l.startswith("class PatientWidget("))
    assert "_PWPreviousExamsMixin" in base_line


def test_panels_build_button_and_stack():
    src = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py")
    assert "prev_exam_btn" in src
    assert "thumb_content_stack" in src
    assert "_toggle_previous_exams_view" in src
    assert "QStackedWidget" in src


def test_open_path_triggers_fetch():
    src = _read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py")
    assert "init_previous_exams(" in src


def test_series_retry_registers_sanctioned_prev_exam():
    src = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_series.py")
    assert "_is_sanctioned_previous_exam" in src
    assert "_register_previous_exam_with_dm" in src


# ── follow-up UI refinements: exam date + origin borders ─────────────────────

def test_origin_border_colors_in_thumbnail_manager():
    src = _read("PacsClient/pacs/patient_tab/utils/thumbnail_manager.py")
    assert "_origin_border_color" in src
    assert "ORIGIN_BORDER_CURRENT" in src and "ORIGIN_BORDER_PREVIOUS" in src
    # origin is resolved against the sanctioned previous-exam set
    assert "_is_sanctioned_previous_exam" in src
    # single border: origin is painted on the existing CircularProgressborder via
    # an _is_previous flag, NOT a second ring on the content card.
    assert "_is_previous" in src
    # the content card itself must carry NO border (the fix for the double line)
    assert "border: none" in src
    # previous-exam status is a SPECTRUM OF RED (open/viewed/downloaded/pending)
    for shade in ("#fca5a5", "#f87171", "#ef4444", "#7f1d1d"):
        assert shade in src, shade


def test_study_header_shows_date_and_compact_count():
    src = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py")
    assert "_study_date_display" in src
    # header builds a date part and keeps a (smaller) series-count span
    assert "date_part" in src
    assert "series)" in src
    assert "RichText" in src


def test_viewport_border_origin_aware():
    src = _read("PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py")
    # viewport border styles take a `previous` flag and paint red for previous
    assert "def _viewport_container_styles(active: bool, previous: bool" in src
    assert "#ef4444" in src
    assert "_node_is_previous_exam" in src
    assert "def refresh_viewport_borders" in src
    # selection-preserving refresh is wired into the FAST container
    cont = _read("PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py")
    assert "set_method_refresh_viewport_borders" in cont
    assert "refresh_viewport_borders" in cont


def test_viewport_origin_stamped_at_load():
    # origin is stamped on the viewport at load time (authoritative), then the
    # border reads the stamp — so replacing the series flips the color.
    vc = _read("PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py")
    assert "def _series_is_previous_exam" in vc
    assert "_origin_is_previous" in vc  # _node_is_previous_exam prefers the stamp
    sw = _read("PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py")
    assert "_origin_is_previous = self._series_is_previous_exam(series_number)" in sw


def test_previous_study_header_is_red_tinted():
    src = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py")
    # previous-exam group header: red accent + PREVIOUS tag + own (prior) Patient ID
    assert "_is_sanctioned_previous_exam" in src
    assert "#ef4444" in src
    assert "PREVIOUS" in src
    assert "ID {prev_pid}" in src


def test_study_date_stamped_for_current_and_previous():
    # current studies: stamped in the central fetch
    s1 = _read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py")
    assert "setdefault('study_date'" in s1
    # previous exams: stamped onto merged series
    s2 = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_previous_exams.py")
    assert 'setdefault("study_date"' in s2
