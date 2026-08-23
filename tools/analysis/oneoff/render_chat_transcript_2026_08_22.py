"""Render the chat transcript offscreen so the styling can be LOOKED at.

A scroll fix and a contrast fix are not things a unit test can fully judge.
This paints a representative transcript — both sides, an attachment, a long
clamped message, a day break, all three receipt states — to a PNG.

    .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\render_chat_transcript_2026_08_22.py

It also prints the sum of the row heights against the scrollbar range, which is
the number the scrollbar bug showed up in: they must match.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize                                  # noqa: E402
from PySide6.QtGui import QPixmap                                 # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from modules.aipacs_chat.services.models import ChatMessage       # noqa: E402
from modules.aipacs_chat.ui.message_view import ChatView          # noqa: E402
from modules.aipacs_chat.ui.styles import theme_tokens            # noqa: E402

NOW = datetime.now(timezone.utc)
YESTERDAY = NOW - timedelta(days=1)

LONG = (
    "Thank you for sending the study. I have reviewed the axial and coronal "
    "series. There is a small area of altered signal in the left frontal lobe "
    "which I would like to compare against any prior imaging you may have. If "
    "you have an earlier MRI, even from a different centre, please upload it "
    "and I will include the comparison in the final report. Otherwise I can "
    "proceed with what I have and note the absence of priors."
)


def _m(mid, sender_type, body, at, **extra):
    raw = {"id": mid, "sender_type": sender_type, "type": "text", "body": body,
           "at": at.isoformat()}
    raw.update(extra)
    return ChatMessage.parse(raw)


def build():
    return [
        _m(1, "system", "Conversation started from the consultation form", YESTERDAY),
        _m(2, "patient", "Hello, I would like a second opinion on a brain MRI.",
           YESTERDAY + timedelta(minutes=1), sender="Maria Rossi"),
        _m(3, "staff", "Of course. Please upload the study and I will take a look.",
           YESTERDAY + timedelta(minutes=3), sender="Admin"),
        _m(4, "patient", "I got 2 times maybe this is the bug",
           NOW - timedelta(hours=3), sender="Maria Rossi"),
        _m(5, "staff", LONG, NOW - timedelta(hours=2), sender="Admin"),
        ChatMessage.parse({
            "id": 6, "sender_type": "staff", "type": "file",
            "body": "Sent a document", "at": (NOW - timedelta(minutes=40)).isoformat(),
            "sender": "Admin",
            "meta": {"file_id": 501, "file_name": "CI2026-00308.pdf",
                     "file_size": 135_270, "mime": "application/pdf",
                     "is_image": False},
        }),
        _m(7, "patient", "Received, thank you.", NOW - timedelta(minutes=20),
           sender="Maria Rossi"),
        _m(8, "staff", "The final report will follow within 24 hours.",
           NOW - timedelta(minutes=10), sender="Admin"),
        _m(9, "staff", "One more thing — please confirm your date of birth.",
           NOW - timedelta(minutes=2), sender="Admin"),
    ]


def main() -> int:
    app = QApplication.instance() or QApplication([])

    host = QWidget()
    host.resize(980, 720)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(14, 14, 14, 14)

    view = ChatView(host)
    tokens = theme_tokens()
    view.set_theme(tokens)
    host.setStyleSheet(f"background: {tokens.get('panel_bg', '#232830')};")
    layout.addWidget(view)

    host.show()
    app.processEvents()

    view.replace(build())
    # Two receipts, so the transcript shows sent / delivered / seen at once:
    # everything up to message 6 seen, up to 8 delivered, 9 only sent.
    view.set_receipts(NOW - timedelta(minutes=15), NOW - timedelta(minutes=35))
    app.processEvents()
    view.scroll_to_end()
    app.processEvents()

    rows = view._model.rowCount()
    measured = sum(
        view.sizeHintForRow(r) for r in range(rows)
    )
    bar = view.verticalScrollBar()
    painted = view.viewport().height() + bar.maximum()
    print(f"rows            : {rows}")
    print(f"sum(sizeHint)   : {measured}")
    print(f"scroll extent   : {painted}")
    print(f"difference      : {abs(measured - painted)}  (0-8 px is layout spacing)")
    print(f"viewport width  : {view.viewport().width()}")
    print(f"delegate width  : {view._delegate._viewport_width}")

    out = ROOT / "tools" / "analysis" / "oneoff" / "chat_transcript_2026_08_22.png"
    pixmap = QPixmap(QSize(host.width(), host.height()))
    host.render(pixmap)
    pixmap.save(str(out), "PNG")
    print(f"written         : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
