"""Contracts for DownloadManagerWidget initialization lifecycle.

Regression covered:
- A large initialization block was accidentally moved into ``showEvent``.
- Worker progress signals can arrive before ``showEvent`` runs, causing
  missing attribute crashes in ``_on_worker_progress``.

This test enforces:
1) Critical state is initialized in ``__init__``.
2) ``showEvent`` remains lightweight (deferred-refresh only).
"""

from __future__ import annotations

import re
from pathlib import Path


_CANONICAL = Path("modules/download_manager/ui/widget/widget.py")
_PLUGIN = Path(
    "builder/plugin package/packages/download_manager/payload/python/"
    "modules/download_manager/ui/widget/widget.py"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_method(src: str, name: str) -> str:
    pattern = rf"def {name}\(.*?\):.*?(?=\n    def |\nclass )"
    m = re.search(pattern, src, re.DOTALL)
    assert m is not None, f"{name} not found"
    return m.group(0)


def _extract_init_to_showevent(src: str) -> str:
    m = re.search(
        r"def __init__\(.*?\):.*?(?=\n    def showEvent\()",
        src,
        re.DOTALL,
    )
    assert m is not None, "__init__ block before showEvent not found"
    return m.group(0)


def _assert_showevent_is_lightweight(show_body: str) -> None:
    forbidden_markers = [
        "self._setup_ui()",
        "self._progress_throttle_timer",
        "self._pending_progress",
        "self._last_series_number_by_study",
        "self._reception_service =",
        "self._speed_update_timer",
        "logger.info(\"✅ DownloadManagerWidget initialized",
    ]
    for marker in forbidden_markers:
        assert marker not in show_body, (
            f"showEvent must stay lightweight; found forbidden init marker: {marker}"
        )


def _assert_init_has_critical_state(init_body: str) -> None:
    required_markers = [
        "self._last_series_number_by_study",
        "self._completed_series_emitted",
        "self._pending_progress",
        "self._progress_throttle_timer",
        "self._reception_service =",
        "self._speed_update_timer",
        "self._setup_ui()",
    ]
    for marker in required_markers:
        assert marker in init_body, (
            f"__init__ missing critical initialization marker: {marker}"
        )


def test_dm_widget_init_contract_canonical() -> None:
    src = _read(_CANONICAL)
    init_body = _extract_init_to_showevent(src)
    show_body = _extract_method(src, "showEvent")

    _assert_init_has_critical_state(init_body)
    _assert_showevent_is_lightweight(show_body)


def test_dm_widget_init_contract_plugin_payload() -> None:
    src = _read(_PLUGIN)
    init_body = _extract_init_to_showevent(src)
    show_body = _extract_method(src, "showEvent")

    _assert_init_has_critical_state(init_body)
    _assert_showevent_is_lightweight(show_body)
