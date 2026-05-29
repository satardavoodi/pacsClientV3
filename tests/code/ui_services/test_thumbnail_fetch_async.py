import asyncio
from types import SimpleNamespace

from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_search as _hp_search_mod
from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_search import _HPSearchMixin
from PacsClient.pacs.workstation_ui.home_ui.home_panel.widget import SourceOfPatientLoad


class _FakeHome(_HPSearchMixin):
    def __init__(self):
        self.source_of_patient_load = SourceOfPatientLoad.SERVER
        self._displayed = None
        self._saved = None
        self._deferred = False
        self._thumbnail_fetch_token = 0
        self._thumbnail_fetch_study_uid = ""
        self.data_access_panel_widget = SimpleNamespace(
            get_server_selected=lambda: {"host": "127.0.0.1"}
        )

    def _is_first_series_visible_for_study(self, study_uid):
        return True

    def _defer_patient_studies_refresh(self, patient_info):
        self._deferred = True

    def display_thumbnails(self, thumbnails, **kwargs):
        self._displayed = thumbnails

    def save_thumbnail(self, thumbnails):
        return thumbnails

    def save_series_info_to_database(self, study_uid, thumbnails):
        self._saved = (study_uid, thumbnails)


class _FakeSocketClient:
    def __init__(self, host="localhost", port=50052, timeout=None):
        self.host = host
        self.port = port

    def get_study_thumbnails(self, study_uid, include_base64=True, include_image_data=True):
        return {
            "study_instance_uid": study_uid,
            "series_thumbnails": [
                {
                    "series_uid": "suid-1",
                    "series_number": "1",
                    "series_description": "A",
                    "modality": "CT",
                    "image_count": 10,
                    "thumbnail_path": "",
                    "thumbnail_data": b"abc",
                }
            ],
        }

    def disconnect(self):
        return None


def _run(coro):
    return asyncio.run(coro)


def test_show_patient_studies_uses_background_to_thread(monkeypatch):
    home = _FakeHome()
    patient_info = {"StudyInstanceUID": "study-1", "PatientID": "p1"}

    to_thread_calls = []

    async def _fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append(True)
        return func(*args, **kwargs)

    async def _fake_wait_for(awaitable, timeout=None):
        return await awaitable

    monkeypatch.setattr(_hp_search_mod, "PatientListSocketClient", _FakeSocketClient)
    monkeypatch.setattr(_hp_search_mod, "check_study_complete", lambda study_uid: False)
    monkeypatch.setattr(_hp_search_mod.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(_hp_search_mod.asyncio, "wait_for", _fake_wait_for)

    _run(home.show_patient_studies(patient_info))

    assert to_thread_calls, "thumbnail fetch must run via asyncio.to_thread"
    assert home._displayed is not None


def test_show_patient_studies_discards_stale_background_result(monkeypatch):
    home = _FakeHome()
    patient_info = {"StudyInstanceUID": "study-2", "PatientID": "p2"}

    async def _fake_to_thread(func, *args, **kwargs):
        # Simulate a newer request arriving before this one returns.
        home._thumbnail_fetch_token += 1
        home._thumbnail_fetch_study_uid = "study-newer"
        return func(*args, **kwargs)

    async def _fake_wait_for(awaitable, timeout=None):
        return await awaitable

    monkeypatch.setattr(_hp_search_mod, "PatientListSocketClient", _FakeSocketClient)
    monkeypatch.setattr(_hp_search_mod, "check_study_complete", lambda study_uid: False)
    monkeypatch.setattr(_hp_search_mod.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(_hp_search_mod.asyncio, "wait_for", _fake_wait_for)

    _run(home.show_patient_studies(patient_info))

    assert home._displayed is None, "stale thumbnail payload must be discarded"
