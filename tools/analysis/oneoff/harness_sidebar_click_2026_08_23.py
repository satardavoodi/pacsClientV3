"""End-to-end: click a sidebar row against the LIVE server and report what loads.

Real widget, real repository, real ChatClient, real ai-pacs.com. The unit tests
prove the wiring; this proves the wiring against the server as it actually
behaves today — including the cases whose detail endpoint answers 500.

SAFETY: the console is held INVISIBLE for the whole run, so every sync carries
``visible=0``. With visible=1 the server writes ``staff_last_read_at``, which
clears a patient's unread flag and cancels the staff notification email. A
diagnostic must not do that.

    .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\harness_sidebar_click_2026_08_23.py vahid
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize                                   # noqa: E402
from PySide6.QtGui import QPixmap                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel                 # noqa: E402

from modules.aipacs_chat.qt.repository import ChatRepository       # noqa: E402
from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget    # noqa: E402


def pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def panel_text(widget):
    return " | ".join(
        label.text() for body in widget.case_panel._bodies.values()
        for label in body.findChildren(QLabel) if label.text().strip()
    )


def main() -> int:
    user = sys.argv[1] if len(sys.argv) > 1 else "vahid"
    app = QApplication.instance() or QApplication([])

    repo = ChatRepository(user)

    # Tap the chain so a break is visible rather than inferred.
    original_run = repo._run_sync

    def traced(params):
        pairs = dict(params)
        response = original_run(params)
        thread = getattr(response, "thread", None)
        print(f"    [sync] case={pairs.get('case')} m={pairs.get('m')} "
              f"rev={pairs.get('rev')} visible={pairs.get('visible')} "
              f"-> rows={len(getattr(response, 'rows', ()) or ())} "
              f"cold={getattr(response, 'cold', None)} "
              f"thread={'None' if thread is None else f'case {thread.case}, '
                        f'{len(thread.messages)} msgs'}")
        return response

    repo._run_sync = traced

    original_tick = repo._tick
    original_resched = repo._reschedule

    def traced_tick():
        print(f"    [tick] started={repo._started} "
              f"inflight={repo._sync_worker is not None} urgent={repo._urgent}")
        return original_tick()

    def traced_resched(delay_ms=None):
        out = original_resched(delay_ms)
        print(f"    [resched] asked={delay_ms} started={repo._started} "
              f"timer_active={repo._timer.isActive()} "
              f"interval={repo._timer.interval()}")
        return out

    repo._tick = traced_tick
    repo._reschedule = traced_resched
    repo._timer.timeout.disconnect()
    repo._timer.timeout.connect(traced_tick)
    repo.threadReplaced.connect(
        lambda cid, msgs: print(f"    [signal] threadReplaced case={cid} n={len(msgs)}"))
    repo.messagesAppended.connect(
        lambda cid, msgs: print(f"    [signal] messagesAppended case={cid} n={len(msgs)}"))
    repo.presenceChanged.connect(
        lambda cid, on, ty: print(f"    [signal] presence case={cid} online={on}"))

    widget = AiPacsChatWidget(repository=repo)
    widget.resize(1300, 760)
    widget.show()

    # Never report visible. See the module docstring.
    repo.setVisible(False)
    repo.start()

    print("waiting for the first page of conversations…")
    for _ in range(40):
        pump(app, 0.5)
        if widget.conversation_list._model.rowCount():
            break
    rows = widget.conversation_list._model.rowCount()
    print(f"rows in the sidebar : {rows}")
    if not rows:
        print("!! no rows — cannot exercise a click")
        return 1

    ids = [widget.conversation_list._model.row_at(
        widget.conversation_list._model.index(i, 0)).id for i in range(rows)]
    print("case ids            :", ids[:12], "…" if len(ids) > 12 else "")

    # 51 answered 200 and 52 answered 500 when probed; try both if present.
    targets = [c for c in (51, 52) if c in ids] or ids[:2]

    for case_id in targets:
        print(f"\n=== clicking case {case_id} ===")
        widget._on_case_activated(case_id)
        app.processEvents()

        print("  immediately after the click (before any answer):")
        print("    header      :", widget.case_panel.header.text().replace("\n", " ")[:90])
        print("    panel rows  :", panel_text(widget)[:140])

        repo.setVisible(False)
        pump(app, 7.0)

        print("  after the answers landed:")
        print("    open_case   :", repo.open_case)
        print("    selected row:", widget.conversation_list.current_case_id())
        print("    thread hdr  :", widget.thread_header.text())
        print("    messages    :", widget.transcript.message_count())
        print("    presence    :", widget.presence_label.text() or "(none)")
        print("    status chip :", widget.case_panel.status_chip.text() or "(none)")
        print("    panel       :", panel_text(widget)[:420])

        out = ROOT / "tools" / "analysis" / "oneoff" / f"sidebar_case_{case_id}.png"
        pixmap = QPixmap(QSize(widget.width(), widget.height()))
        widget.render(pixmap)
        pixmap.save(str(out), "PNG")
        print("    screenshot  :", out.name)

    widget.cleanup()
    pump(app, 1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
