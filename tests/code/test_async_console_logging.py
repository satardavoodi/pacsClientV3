"""Guard: the console StreamHandler must never write on the caller's thread.

py-spy on the heavy-image stress retest (2026-06-07 22:23): the GUI thread
froze >188 s inside codecs.write under logging.emit — the synchronous console
StreamHandler on the root logger blocked when the process console/pipe wasn't
drained (detached launches, schedulers, console quick-edit selection). All
handlers, console included, must sit behind the async QueueListener."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "PacsClient" / "utils" / "diagnostic_logging.py"


def test_console_handler_not_added_synchronously():
    src = SRC.read_text(encoding="utf-8", errors="ignore")
    # The only root.addHandler(console_handler) allowed is in the sync
    # escape-hatch branch (AIPACS_LOG_SYNC=1).
    head = src[: src.index("if async_enabled:")]
    assert "root.addHandler(console_handler)" not in head
    # Console handler must ride the async listener list.
    async_block = src[src.index("if async_enabled:"):]
    assert "console_handler]" in async_block.replace("\n", "").replace(" ", "") \
        or "console_handler," in async_block


def test_logging_does_not_block_with_closed_stdout():
    """Configure logging in a subprocess whose stdout is a never-drained pipe,
    emit a burst, and require prompt exit (pre-fix this could block)."""
    code = (
        "import sys, logging;"
        "sys.path.insert(0, r'%s');"
        "from PacsClient.utils.diagnostic_logging import configure_diagnostic_logging;"
        "configure_diagnostic_logging(process_role='test');"
        "lg = logging.getLogger('burst');"
        "[lg.critical('x' * 2000) for _ in range(2000)];"
        "print('OK', file=sys.stderr)"
    ) % str(ROOT)
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    p = subprocess.run(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,  # we never read until completion → backpressure
        stderr=subprocess.PIPE,
        timeout=90,
        env=env,
        cwd=str(ROOT),
    )
    assert b"OK" in p.stderr
