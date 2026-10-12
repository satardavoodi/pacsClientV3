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
        self.mode = "Server"
        self.connection_badge = None
        refresh = getattr(home.patient_table_widget, 'refresh_btn', None)
        header = refresh.parentWidget() if refresh else None
        layout = header.layout() if header else None
        if layout and hasattr(layout, 'insertWidget'):
            self.connection_badge = QLabel('Offline', header)
            self.connection_badge.setObjectName('homeWorkflowConnectionBadge')
            layout.insertWidget(layout.indexOf(refresh) + 1, self.connection_badge)
        self.receiver = None
        self.receiver_key = None
        self.projection_epoch = 0
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        # No QObject access from receiver threads, including after destruction.
        self._receiver_holder = [None]
        holder = self._receiver_holder
        self.destroyed.connect(lambda: holder[0] and holder[0].stop())

    def bind(self, host, port, server_name, generation, *, mode="Server"):
        self.binding = (host, int(port), server_name, generation)
        self.mode = mode

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
        if (getattr(panel, "tab_selected_name", "") != self.mode or
                (self.mode == "Server" and getattr(panel, "server_selected", None) != name) or
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
                    self.home.setProperty('workflowRealtimeStatus', 'switching')
                    self._show_connection('switching')
                    return  # No join on the GUI thread; at most one worker alive.
            self.receiver = None
            self._receiver_holder[0] = None
            self.receiver_key = key
            self.projection_epoch += 1
            if key:
                helpers = [getattr(type(self.home), name, None) for name in (
                    '_fetch_reception_patient_payload', '_extract_reporting_physician_from_reception_payload',
                    '_extract_report_status_from_reception_payload')]
                transform = None
                if all(callable(helper) for helper in helpers):
                    from modules.network.home_legacy_workflow import ReceptionOverlay
                    def latest(pid):
                        from modules.network.socket_patient_service import get_socket_patient_service
                        return get_socket_patient_service().get_patient_status_sync(pid) or {}
                    def assignment(pid):
                        from modules.network.ino_assignment import get_internal_assignment_service
                        return get_internal_assignment_service().current_assignment(pid)
                    transform = ReceptionOverlay(*helpers, latest,
                        resolve=getattr(type(self.home.patient_table_widget), '_fetch_server_user_full_name', None),
                        is_actor=getattr(type(self.home), '_is_probable_actor_id', None), assignment=assignment)
                self.receiver = WorkflowReceiver(key[0], key[1], key[4], allow_legacy=True,
                    allow_legacy_events=True, enrich=transform)
                self._receiver_holder[0] = self.receiver
                self.receiver.start()
        status = getattr(self.receiver, 'status', 'connecting') if key and self.receiver else 'inactive'
        if not self.binding:
            status = 'waiting_for_search'
        self.home.setProperty('workflowRealtimeStatus', status)
        self._show_connection(status)
        if not key or not self.receiver:
            return
        rows = self._rows()
        self.receiver.watch(rows)
        states = self.receiver.mailbox.drain()
        states += getattr(self.receiver, 'drain_enrichment', lambda:[])()
        for state in states:
            target = rows.get(state["study_uid"])
            if target and target[1] == state["patient_id"]:
                self._apply(target[0], state)

    def _show_connection(self, status):
        if self.connection_badge is None:
            return
        states = {
            'connected': ('Online', '#34d399', 'Live broadcast connection is active.'),
            'connected_legacy': ('Online', '#34d399', 'Server-verified legacy broadcast connection is active.'),
            'compatibility': ('Periodic', '#fbbf24', 'Server uses periodic updates; live broadcast is unavailable.'),
            'compatibility_partial': ('Periodic', '#fbbf24', 'Periodic updates are active; some records could not be refreshed.'),
            'compatibility_reconnecting': ('Connecting', '#94a3b8', 'Retrying periodic updates.'),
            'connecting': ('Connecting', '#94a3b8', 'Connecting to the patient source.'),
            'reconnecting': ('Connecting', '#94a3b8', 'Reconnecting to the patient source.'),
            'switching': ('Connecting', '#94a3b8', 'Switching patient sources.'),
            'waiting_for_search': ('Waiting', '#94a3b8', 'Load a patient list to monitor its studies.'),
        }
        text, color, tip = states.get(status, ('Offline', '#f87171', 'Live updates are disconnected.'))
        failure = getattr(self.receiver, 'failure', None)
        if failure:
            tip += f' Last failure: {failure[0]} / {failure[1]}.'
        signature = (text, color, tip)
        if getattr(self.connection_badge, '_workflow_snapshot', None) == signature:
            return
        self.connection_badge._workflow_snapshot = signature
        self.connection_badge.setText(text)
        self.connection_badge.setToolTip(tip)
        self.connection_badge.setStyleSheet(f'color: {color}; font-size: 11px; padding: 0 3px;')

    def _apply(self, row, state):
        from .patient_table_widget import COL
        from modules.network.ino_assignment_models import effective_assign_status, assign_icon_for_status
        owner = self.home.patient_table_widget
        table = owner.results_table
        uid, pid = state["study_uid"], state["patient_id"]
        import time
        from PacsClient.utils.patient_workflow_facts import WORKFLOW_ROLE_OFFSET
        item = table.item(row, COL['study_uid'])
        observation = state.get('_observation')
        if item is not None and type(observation) is int:
            binding = self.projection_epoch
            previous_binding, previous = getattr(item, '_workflow_observation', (None, 0))
            if previous_binding == binding and observation < previous:
                return  # Late response from an older observation cannot repaint newer facts.
            item._workflow_observation = (binding, observation)
        if item is not None and item.text() == uid and not state.get('_report_only'):
            item.setData(Qt.UserRole + WORKFLOW_ROLE_OFFSET, {
                'study_uid':uid, 'patient_id':pid, 'audio_count':state['audio_count'],
                'observed_at':time.monotonic(), 'binding':self.receiver_key[:4] if self.receiver_key else None})
        status_widget = table.cellWidget(row, COL['status'])
        if status_widget and status_widget.layout() and not state.get('_report_only'):
            count = state['audio_count']
            if status_widget.property('serverVoiceCount') != count:
                status_widget.setProperty('serverVoiceCount', count)
                owner._populate_status_chips(status_widget.layout(), getattr(status_widget, 'status_flags', {}))
        if state.get('_voice_only'):
            return
        status = state["report_status"]
        report_widget = table.cellWidget(row, COL['report'])
        if state.get('_report_status_known') is False:
            status = getattr(report_widget, 'report_status', owner._report_status_cache.get(uid, status)
                             if hasattr(owner, '_report_status_cache') else status)
        display = state.get("display_assignment", {})
        assign_widget = table.cellWidget(row, COL['assign'])
        assignment_enabled = state.get('assignment_enabled', True)
        if assign_widget and assignment_enabled:
            assign_widget._workflow_assignment_display = dict(display)
        elif assign_widget and hasattr(assign_widget, '_workflow_assignment_display'):
            display = assign_widget._workflow_assignment_display
            assignment_enabled = True
        names = str(display.get("assignee_name") or "")[:240]
        effective = effective_assign_status(display.get("status", ""), status)
        icon = assign_icon_for_status(effective, names)
        if assignment_enabled and assign_widget and getattr(assign_widget, "_workflow_snapshot", None) != (effective, names):
            assign_widget.setPixmap(owner._icon_pixmap(icon["icon"], icon["color"], 16, 16))
            assign_widget.setToolTip(icon["tooltip"])
            assign_widget._workflow_snapshot = (effective, names)
        if report_widget and report_widget.layout() and report_widget.layout().count():
            label = report_widget.layout().itemAt(0).widget()
            name_item = table.item(row, COL["patient_name"])
            if name_item and 'reporting_physician' in state and state.get('_reporting_physician_known') is not False:
                name_item.setData(Qt.UserRole + 2, state['reporting_physician'])
            physician = str(name_item.data(Qt.UserRole + 2) or "") if name_item else ""
            signature = (status, physician)
            if label and getattr(label, "_workflow_snapshot", None) != signature:
                report_widget.report_status = status
                if not hasattr(owner, '_report_status_cache'):
                    owner._report_status_cache = {}
                owner._report_status_cache[uid] = status
                owner._apply_report_status_display(label, status, physician, workflow_assignment={})
                patient_name = name_item.text() if name_item else ""
                label.mousePressEvent = lambda event, u=uid, s=status, n=patient_name, p=pid, ph=physician: owner._on_report_status_clicked(u, s, n, p, ph)
                label._workflow_snapshot = signature
