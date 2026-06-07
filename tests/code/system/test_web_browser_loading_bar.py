"""Guard: web-browser loading bar must not cause layout jumps (2026-06-06).

The 3px page-load progress bar under the address bar used plain show()/hide(),
which inserted/removed its slot from the layout — the content area jumped
down on loadStarted and back up on loadFinished. The bar's size policy now
sets retainSizeWhenHidden, so the slot is reserved permanently and
visibility toggles only painting.

Functional check uses a plain QWidget stand-in (QtWebEngine isn't loadable
in the headless test env) replicating the exact layout recipe + policy, and
source pins guard the real widget wiring.
"""
import inspect
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_retain_size_keeps_geometry_stable(qapp):
    """Replicates the browser-tab layout: bar show/hide must not move content."""
    from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    nav = QLabel("navbar")
    nav.setFixedHeight(40)
    bar = QProgressBar()
    bar.setFixedHeight(3)
    policy = bar.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    bar.setSizePolicy(policy)
    bar.hide()
    content = QLabel("content")
    layout.addWidget(nav)
    layout.addWidget(bar)
    layout.addWidget(content, 1)

    host.resize(800, 600)
    host.show()
    qapp.processEvents()
    y_hidden = content.geometry().y()

    bar.show()
    qapp.processEvents()
    y_loading = content.geometry().y()

    bar.hide()
    qapp.processEvents()
    y_after = content.geometry().y()

    assert y_hidden == y_loading == y_after, (
        f"content moved: hidden={y_hidden} loading={y_loading} after={y_after}"
    )


def test_real_browser_widget_reserves_bar_slot():
    """Source pins on modules/web_browser/widget.py (QtWebEngine-free)."""
    src_path = _ROOT / "modules" / "web_browser" / "widget.py"
    src = src_path.read_text(encoding="utf-8", errors="ignore")

    assert "setRetainSizeWhenHidden(True)" in src, (
        "loading bar must reserve its layout slot when hidden"
    )
    # the retain policy must be applied to the page-load bar BEFORE its
    # initial hide() (otherwise the first show still jumps)
    retain_pos = src.index("setRetainSizeWhenHidden(True)")
    hide_pos = src.index("self.progress_bar.hide()", retain_pos - 1200)
    assert retain_pos < hide_pos, "retain policy must be set before initial hide()"

    # mirror parity with the plugin payload copy
    mirror = (_ROOT / "builder" / "plugin package" / "packages" / "web_browser"
              / "payload" / "python" / "modules" / "web_browser" / "widget.py")
    if mirror.exists():
        assert "setRetainSizeWhenHidden(True)" in mirror.read_text(
            encoding="utf-8", errors="ignore"
        ), "plugin payload mirror is stale"
