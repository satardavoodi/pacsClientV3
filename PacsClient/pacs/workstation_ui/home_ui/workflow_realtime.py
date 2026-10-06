"""GUI adapter for small authoritative workflow snapshots, never full refreshes."""
import os

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QLabel

from modules.network.workflow_realtime import WorkflowReceiver
from modules.network.socket_token_manager import get_socket_token_manager


class WorkflowRealtime(QObject):
    def __init__(self, home):
        super().__init__(home)
        self.home = home
        self.binding = None
        self.receiver = None
        self.receiver_key = None
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        # No QObject access from receiver threads, including after destruction.
        self._receiver_holder = [None]
        holder = self._receiver_holder
        self.destroyed.connect(lambda: holder[0] and holder[0].stop())

    def bind(self, host, port, server_name, generation):
        self.binding = (host, int(port), server_name, generation)

    def close(self):
        self.closed = True
        self.timer.stop()
        if self.receiver:
            self.receiver.stop()

    def _active_key(self):
        if self.closed or not self.binding or os.environ.get("AIPACS_WORKFLOW_REALTIME", "1") == "0":
            return None
        host, port, name, generation = self.binding
        panel = self.home.data_access_panel_widget
        if (getattr(panel, "tab_selected_name", "") != "Server" or
                getattr(panel, "server_selected", None) != name or
                getattr(self.home, "_search_generation", None) != generation):
            return None
        token = get_socket_token_manager().get_token()
        return (host, port, name, generation, token) if token else None

    def _rows(self):
        from .patient_table_widget import COL
        table = self.home.patient_table_widget.results_table
        if not table.isVisible() or not table.rowCount():
            return {}
        first = table.rowAt(0)
        last = table.rowAt(max(0, table.viewport().height() - 1))
        first = max(0, first)
        last = min(table.rowCount() - 1, first + 99) if last < 0 else min(last, first + 99)
        rows = {}
        for row in range(first, last + 1):
            uid_item = table.item(row, COL["study_uid"])
            pid_item = table.item(row, COL["patient_id"])
            if uid_item and pid_item and uid_item.text():
                rows[uid_item.text()] = (row, pid_item.text())
        return rows

    def tick(self):
        key = self._active_key()
        if key != self.receiver_key:
            self.home.patient_table_widget.results_table._secretary_workflow_binding = key[:4] if key else None
            if self.receiver:
                self.receiver.stop()
                if self.receiver.is_alive():
                    return  # No join on the GUI thread; at most one worker alive.
            self.receiver = None
            self._receiver_holder[0] = None
            self.receiver_key = key
            if key:
                self.receiver = WorkflowReceiver(key[0], key[1], key[4])
                self._receiver_holder[0] = self.receiver
                self.receiver.start()
        if not key or not self.receiver:
            return
        rows = self._rows()
        self.receiver.watch(rows)
        for state in self.receiver.mailbox.drain():
            target = rows.get(state["study_uid"])
            if target and target[1] == state["patient_id"]:
                self._apply(target[0], state)

    def _apply(self, row, state):
        from .patient_table_widget import COL
        from modules.network.ino_assignment_models import effective_assign_status, assign_icon_for_status
        owner = self.home.patient_table_widget
        table = owner.results_table
        uid, pid = state["study_uid"], state["patient_id"]
        import time
        from PacsClient.utils.patient_workflow_facts import WORKFLOW_ROLE_OFFSET
        item = table.item(row, COL['study_uid'])
        if item is not None and item.text() == uid:
            item.setData(Qt.UserRole + WORKFLOW_ROLE_OFFSET, {
                'study_uid':uid, 'patient_id':pid, 'audio_count':state['audio_count'],
                'observed_at':time.monotonic(), 'binding':self.receiver_key[:4] if self.receiver_key else None})
        status = state["report_status"]
        display = state.get("display_assignment", {})
        names = str(display.get("assignee_name") or "")[:240]
        effective = effective_assign_status(display.get("status", ""), status)
        icon = assign_icon_for_status(effective, names)
        assign_widget = table.cellWidget(row, COL["assign"])
        if state.get("assignment_enabled", True) and assign_widget and getattr(assign_widget, "_workflow_snapshot", None) != (effective, names):
            assign_widget.setPixmap(owner._icon_pixmap(icon["icon"], icon["color"], 16, 16))
            assign_widget.setToolTip(icon["tooltip"])
            assign_widget._workflow_snapshot = (effective, names)
        report_widget = table.cellWidget(row, COL["report"])
        if report_widget and report_widget.layout() and report_widget.layout().count():
            label = report_widget.layout().itemAt(0).widget()
            name_item = table.item(row, COL["patient_name"])
            physician = str(name_item.data(Qt.UserRole + 2) or "") if name_item else ""
            signature = (status, names, physician, effective)
            if label and getattr(label, "_workflow_snapshot", None) != signature:
                report_widget.report_status = status
                if not hasattr(owner, '_report_status_cache'):
                    owner._report_status_cache = {}
                owner._report_status_cache[uid] = status
                owner._apply_report_status_display(label, status, physician, workflow_assignment=display)
                patient_name = name_item.text() if name_item else ""
                label.mousePressEvent = lambda event, u=uid, s=status, n=patient_name, p=pid, ph=physician: owner._on_report_status_clicked(u, s, n, p, ph)
                label._workflow_snapshot = signature
        status_widget = table.cellWidget(row, COL["status"])
        if status_widget and status_widget.layout():
            voice = status_widget.findChild(QLabel, "serverVoiceAvailability")
            if voice is None and state["audio_count"]:
                voice = QLabel(status_widget)
                voice.setObjectName("serverVoiceAvailability")
                voice.setPixmap(owner._icon_pixmap("fa5s.microphone", "#60a5fa", 14, 14))
                status_widget.layout().addWidget(voice)
            if voice:
                voice.setToolTip(f"Server voice files: {state['audio_count']}")
                voice.setVisible(state["audio_count"] > 0)
