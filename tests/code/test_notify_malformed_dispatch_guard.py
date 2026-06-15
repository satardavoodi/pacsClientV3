"""Guard for the QApplication.notify() malformed-dispatch hardening (FIX-020).

Client PC 'pc user 3 vahid' logged a CRITICAL crash: the notify() override called
super().notify(receiver, event) with a non-QObject receiver (a rare Qt/teardown edge
case — "QApplication.notify() called with wrong argument types: notify(QEvent,
QEvent)"). The override re-raises after logging (correct for real handler crashes),
so the spurious call propagated to the excepthook and crashed the app.

The fix treats ONLY that malformed case (TypeError + receiver is not a QObject) as an
unhandled event (return False); every genuine handler exception is still captured and
re-raised. The notify class is defined locally inside main()'s setup, so this is a
source-level invariant guard (the happy path must stay byte-identical).
"""
import re
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "main.py"


def _notify_block():
    src = MAIN.read_text(encoding="utf-8")
    i = src.index("def notify(self, receiver, event):")
    return src[i:i + 8000]


def test_happy_path_unchanged():
    block = _notify_block()
    # The normal dispatch must remain a direct super().notify(receiver, event).
    assert "return super().notify(receiver, event)" in block


def test_malformed_dispatch_returns_false_not_raise():
    block = _notify_block()
    assert "_malformed_dispatch" in block
    # Detects the specific case: TypeError AND receiver is not a QObject.
    assert "isinstance(_notify_exc, TypeError)" in block
    assert "not isinstance(receiver, _QObjectCheck)" in block
    # The malformed branch (from its `if` up to the real-exception snapshot path)
    # returns False (unhandled) and does NOT re-raise.
    mref = block.index("if _malformed_dispatch:")
    snapshot = block.index("EXCEPTION in Qt event dispatch")
    branch = block[mref:snapshot]
    assert "return False" in branch
    assert "raise" not in branch  # malformed branch must not re-raise


def test_real_exceptions_still_reraise():
    """A genuine handler exception (receiver IS a QObject) must still be captured
    and propagated — the crash-capture purpose of the override is preserved."""
    block = _notify_block()
    assert "EXCEPTION in Qt event dispatch" in block
    # After the snapshot critical log, real exceptions are re-raised.
    after = block[block.index("EXCEPTION in Qt event dispatch"):]
    assert re.search(r"\n\s+raise\b", after) is not None
