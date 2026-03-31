import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "modules.viewer.backends.pydicom_2d_backend",
        "modules.viewer.backends.pydicom_lazy_volume",
        "modules.viewer.advanced.filter_config_widget",
        "modules.viewer.advanced.viewer_2d_with_tools",
        "modules.download_manager.utils",
        "modules.network.multi",
        "modules.network.dicom_downloader_client_help",
        "modules.web_browser",
        "PacsClient.pacs.patient_tab.ui",
        "PacsClient.pacs.workstation_ui.settings_ui",
        "PacsClient.pacs.workstation_ui.web_browser_ui",
    ],
)
def test_module_imports_are_build_safe(module_name):
    module = importlib.import_module(module_name)

    assert module.__name__ == module_name


def test_patient_tab_utils_lazy_exports_resolve_without_circular_imports():
    utils_module = importlib.import_module("PacsClient.pacs.patient_tab.utils")

    assert getattr(utils_module, "load_images").__name__ == "load_images"
    assert getattr(utils_module, "ThumbnailManager").__name__ == "ThumbnailManager"


def test_patient_tab_ui_package_exports_patient_widget():
    ui_module = importlib.import_module("PacsClient.pacs.patient_tab.ui")

    assert getattr(ui_module, "PatientWidget").__name__ == "PatientWidget"


def test_web_browser_package_exports_widget():
    browser_module = importlib.import_module("modules.web_browser")

    assert getattr(browser_module, "WebBrowserWidget").__name__ == "WebBrowserWidget"
