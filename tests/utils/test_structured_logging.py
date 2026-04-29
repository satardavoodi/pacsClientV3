"""Unit tests for the typed structured-logging emit helpers.

These tests verify the contract documented in
``PacsClient/utils/structured_logging.py``:

- ``component=download`` ⇒ minimum level WARNING
- ``component=ipc/viewer/zetaboost/db/ui`` ⇒ minimum level INFO
- ``[TAG] k=v ...`` body format is deterministic and sanitized
- Extra fields propagate to the LogRecord

Run: ``.venv\\Scripts\\python.exe -m pytest tests/utils/test_structured_logging.py -v``
"""

from __future__ import annotations

import logging

import pytest

from PacsClient.utils.structured_logging import (
    MIN_LEVEL_BY_COMPONENT,
    emit_db_event,
    emit_download_event,
    emit_ipc_event,
    emit_ui_event,
    emit_viewer_event,
    emit_zetaboost_event,
    format_event_message,
)


@pytest.fixture
def captured(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


def test_emit_download_event_default_level_is_warning(captured):
    logger = logging.getLogger("aipacs.download.test")
    emit_download_event(logger, "TEST_TAG", a=1, b="x")
    rec = captured.records[-1]
    assert rec.levelno == logging.WARNING
    assert rec.message.startswith("[TEST_TAG]")
    assert "a=1" in rec.message
    assert "b=x" in rec.message
    assert getattr(rec, "component", None) == "download"


def test_emit_download_event_promotes_info_to_warning(captured):
    """Defense-in-depth: even if a caller passes INFO, level is bumped to WARNING."""
    logger = logging.getLogger("aipacs.download.test2")
    emit_download_event(logger, "INTENT_PRIORITY", level=logging.INFO, study="X")
    rec = captured.records[-1]
    assert rec.levelno == logging.WARNING, (
        "INFO must be promoted to WARNING for component=download or it is silently dropped"
    )
    assert getattr(rec, "component", None) == "download"


def test_emit_download_event_allows_explicit_higher_level(captured):
    logger = logging.getLogger("aipacs.download.test3")
    emit_download_event(logger, "FATAL_TAG", level=logging.ERROR, e="boom")
    rec = captured.records[-1]
    assert rec.levelno == logging.ERROR


def test_emit_ipc_event_default_level_is_info(captured):
    logger = logging.getLogger("aipacs.ipc.test")
    emit_ipc_event(logger, "SP", phase="boot")
    rec = captured.records[-1]
    assert rec.levelno == logging.INFO
    assert getattr(rec, "component", None) == "ipc"
    assert "phase=boot" in rec.message


def test_emit_viewer_event_default_level_is_info(captured):
    logger = logging.getLogger("aipacs.viewer.test")
    emit_viewer_event(logger, "OVERLAP_SCENARIO", idx=42, cache="hit")
    rec = captured.records[-1]
    assert rec.levelno == logging.INFO
    assert getattr(rec, "component", None) == "viewer"
    assert "idx=42" in rec.message


def test_emit_zetaboost_event_default_level_is_info(captured):
    logger = logging.getLogger("aipacs.zetaboost.test")
    emit_zetaboost_event(logger, "BOOST_TAG", n=3)
    rec = captured.records[-1]
    assert rec.levelno == logging.INFO
    assert getattr(rec, "component", None) == "zetaboost"


def test_emit_db_event_default_level_is_info(captured):
    logger = logging.getLogger("aipacs.db.test")
    emit_db_event(logger, "STAGE", duration_ms=12.5)
    rec = captured.records[-1]
    assert rec.levelno == logging.INFO
    assert getattr(rec, "component", None) == "db"


def test_emit_ui_event_default_level_is_info(captured):
    logger = logging.getLogger("aipacs.ui.test")
    emit_ui_event(logger, "UI_TAG", state="active")
    rec = captured.records[-1]
    assert rec.levelno == logging.INFO
    assert getattr(rec, "component", None) == "ui"


def test_extra_fields_propagate(captured):
    logger = logging.getLogger("aipacs.download.test_extra")
    emit_download_event(
        logger,
        "INTENT_PRIORITY",
        extra={"study_uid": "1.2.3", "series_uid": "4.5.6"},
        attempt=1,
    )
    rec = captured.records[-1]
    assert getattr(rec, "study_uid", None) == "1.2.3"
    assert getattr(rec, "series_uid", None) == "4.5.6"
    assert getattr(rec, "component", None) == "download"


def test_extra_fields_drop_none_values(captured):
    logger = logging.getLogger("aipacs.download.test_extra2")
    emit_download_event(
        logger,
        "TAG",
        extra={"study_uid": None, "series_uid": "S"},
    )
    rec = captured.records[-1]
    assert not hasattr(rec, "study_uid") or getattr(rec, "study_uid", None) is None
    assert getattr(rec, "series_uid", None) == "S"


def test_field_value_sanitization():
    msg = format_event_message(
        "T",
        [
            ("k1", "value;with;semicolons"),
            ("k2", "value=with=equals"),
            ("k3", "value\nwith\nnewlines"),
        ],
    )
    assert ";" not in msg.split("[T] ", 1)[1].replace("k1=", "")  # body has no ;
    # Verify replacements
    assert "k1=value,with,semicolons" in msg
    assert "k2=value:with:equals" in msg
    assert "\n" not in msg
    assert "\r" not in msg


def test_field_none_value_is_dropped_from_body():
    msg = format_event_message("T", [("a", 1), ("b", None), ("c", 3)])
    assert "b=" not in msg
    assert "a=1" in msg
    assert "c=3" in msg


def test_field_bool_serialization():
    msg = format_event_message("T", [("flag1", True), ("flag2", False)])
    assert "flag1=True" in msg
    assert "flag2=False" in msg


def test_field_float_default_precision():
    msg = format_event_message("T", [("ms", 12.34567)])
    assert "ms=12.346" in msg


def test_min_level_table_matches_diagnostic_logging():
    """Sanity: helper thresholds must mirror diagnostic_logging defaults."""
    from PacsClient.utils.diagnostic_logging import _DEFAULT_COMPONENT_THRESHOLDS
    for component, level in _DEFAULT_COMPONENT_THRESHOLDS.items():
        assert MIN_LEVEL_BY_COMPONENT.get(component) == level, (
            f"MIN_LEVEL_BY_COMPONENT[{component!r}] is out of sync with diagnostic_logging"
        )


def test_message_starts_with_bracket_tag():
    msg = format_event_message("MY_TAG", [("a", 1)])
    assert msg.startswith("[MY_TAG] ")


def test_emit_with_no_fields(captured):
    logger = logging.getLogger("aipacs.viewer.empty")
    emit_viewer_event(logger, "EMPTY_TAG")
    rec = captured.records[-1]
    assert rec.message == "[EMPTY_TAG]"
