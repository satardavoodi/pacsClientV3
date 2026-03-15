import aipacs_runtime as runtime


def test_module_enabled_map_keeps_all_modules_visible_in_source_runs(monkeypatch):
    monkeypatch.setattr(runtime, "is_frozen", lambda: False)
    monkeypatch.delenv(runtime.RESPECT_DEV_MODULE_PROFILE_ENV, raising=False)

    enabled = runtime.module_enabled_map()

    assert enabled["viewer"] is True
    assert enabled["printing"] is True
    assert enabled["run_cd"] is True
    assert enabled["web_browser"] is True
    assert enabled["echomind"] is True
    assert runtime.is_module_enabled("echomind") is True


def test_module_enabled_map_respects_profile_in_frozen_mode(monkeypatch):
    monkeypatch.setattr(runtime, "is_frozen", lambda: True)

    enabled = runtime.module_enabled_map(
        {
            "modules": {
                "viewer": True,
                "printing": False,
                "run_cd": True,
                "web_browser": False,
                "echomind": False,
            }
        }
    )

    assert enabled["viewer"] is True
    assert enabled["printing"] is False
    assert enabled["run_cd"] is True
    assert enabled["web_browser"] is False
    assert enabled["echomind"] is False


def test_module_enabled_map_can_simulate_installer_profile_in_source_runs(monkeypatch):
    monkeypatch.setattr(runtime, "is_frozen", lambda: False)
    monkeypatch.setenv(runtime.RESPECT_DEV_MODULE_PROFILE_ENV, "1")

    enabled = runtime.module_enabled_map(
        {
            "modules": {
                "viewer": True,
                "printing": False,
                "run_cd": False,
                "web_browser": False,
                "echomind": False,
            }
        }
    )

    assert enabled["viewer"] is True
    assert enabled["printing"] is False
    assert enabled["run_cd"] is False
    assert enabled["web_browser"] is False
    assert enabled["echomind"] is False
