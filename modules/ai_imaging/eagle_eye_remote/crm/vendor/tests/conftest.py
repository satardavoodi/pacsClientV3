"""Shared fixtures.

The icon tests rasterise SVGs, which needs a QGuiApplication but no display —
hence the offscreen platform, set before Qt is imported.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolate_center_lexicon_runtime():
    """Tests that apply server config must not retarget later lexicon tests."""
    from reception_crm.lexicon import center

    names = ("RECEPTION_HTTP_API_CENTER", "RECEPTION_CENTER_CONFIG_PATH")
    saved = {name: os.environ.get(name) for name in names}
    center.reset_cache()
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    center.reset_cache()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
