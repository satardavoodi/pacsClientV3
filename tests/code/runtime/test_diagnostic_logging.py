from __future__ import annotations

import logging


from PacsClient.utils.diagnostic_logging import SafeRotatingFileHandler


def test_safe_rotating_handler_falls_back_when_rollover_locked(tmp_path, monkeypatch):
    log_path = tmp_path / "viewer_diagnostics.log"
    handler = SafeRotatingFileHandler(log_path, maxBytes=1, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("tests.runtime.safe_rotating")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    monkeypatch.setattr(handler, "shouldRollover", lambda record: True)

    def _raise_locked():
        raise PermissionError(32, "locked", str(log_path))

    monkeypatch.setattr(handler, "doRollover", _raise_locked)

    logger.info("hello-viewer-log")
    handler.flush()

    text = log_path.read_text(encoding="utf-8")
    assert "hello-viewer-log" in text
    assert handler._rollover_failure_count == 1

    logger.removeHandler(handler)
    handler.close()


def test_safe_rotating_handler_retries_later_not_every_emit(tmp_path, monkeypatch):
    log_path = tmp_path / "viewer_diagnostics.log"
    handler = SafeRotatingFileHandler(log_path, maxBytes=1, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("tests.runtime.safe_rotating_retry")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    monkeypatch.setattr(handler, "shouldRollover", lambda record: True)
    calls = {"count": 0}

    def _raise_locked():
        calls["count"] += 1
        raise PermissionError(32, "locked", str(log_path))

    monkeypatch.setattr(handler, "doRollover", _raise_locked)

    logger.info("first")
    logger.info("second")
    handler.flush()

    assert calls["count"] == 1

    logger.removeHandler(handler)
    handler.close()