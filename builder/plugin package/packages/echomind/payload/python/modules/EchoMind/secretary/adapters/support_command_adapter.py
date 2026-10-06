"""Read-only support evidence shared by local Secretary and mobile MCP."""
from ..command_envelope import CommandResult
from PacsClient.utils.support_diagnostics import OperationStore, collect_log_evidence, collect_windows_events

SUPPORT_ACTIONS = {name:name for name in ('collect_support_diagnostics',
    'support_operation_status', 'get_visible_app_errors', 'get_recent_function_results',
    'get_control_capabilities', 'open_support_issue', 'support_issue_status', 'prepare_help_ticket', 'submit_help_ticket', 'help_ticket_status')}


class SupportCommandAdapter:
    def __init__(self, home_widget=None):
        self._operations = OperationStore()
        self._get_capabilities = None
        self._home = home_widget

    def open_support_issue(self, plan, state):
        if self._home is None:
            return CommandResult(ok=False, action=plan.action, error_code='SUPPORT_FORM_UNAVAILABLE')
        try:
            from PacsClient.pacs.workstation_ui.home_ui.support_issue_dialog import open_support_issue_form
            dialog = open_support_issue_form(self._home, plan.entities.get('description', ''))
        except Exception:
            return CommandResult(ok=False, action=plan.action, error_code='SUPPORT_FORM_UNAVAILABLE')
        return CommandResult(ok=True, action=plan.action, data=dict(dialog.public_result),
            message='Review the description and approve sending in the local issue form.')

    def prepare_help_ticket(self, plan, state):
        return self.open_support_issue(plan, state)

    def help_ticket_status(self, plan, state):
        return self.support_issue_status(plan, state)

    def submit_help_ticket(self, plan, state):
        dialog = getattr(self._home, '_support_issue_dialog', None)
        if dialog is None or not dialog.isVisible():
            return CommandResult(ok=False, action=plan.action, error_code='SUPPORT_FORM_UNAVAILABLE')
        retry = dialog.public_result.get('state') == 'pending'
        button = dialog.retry if retry else dialog.send
        if not dialog.consent.isChecked() or not button.isEnabled():
            return CommandResult(ok=False, action=plan.action, error_code='LOCAL_REVIEW_REQUIRED', message='Review the local ticket and approve its contents before sending.')
        if retry:
            dialog._retry()
        else:
            dialog._submit()
        return CommandResult(ok=True, action=plan.action, data={'state':'running', 'ticket_submitted':False}, message='Submission started. Poll help_ticket_status for the validated website receipt.')

    def support_issue_status(self, plan, state):
        dialog = getattr(self._home, '_support_issue_dialog', None)
        return CommandResult(ok=True, action=plan.action, data=dict(dialog.public_result) if dialog else
            {'state':'not_opened', 'ticket_submitted':False})

    def get_control_capabilities(self, plan, state):
        if not callable(self._get_capabilities):
            return CommandResult(ok=False, action=plan.action, error_code='CAPABILITIES_UNAVAILABLE')
        return CommandResult(ok=True, action=plan.action, data=self._get_capabilities())

    def get_recent_function_results(self, plan, state):
        from PacsClient.utils.support_diagnostics import recent_function_results
        return CommandResult(ok=True, action=plan.action, data={
            'results':recent_function_results(), 'scope':'current_process_last_100',
            'background_completion':'poll_the_owning_operation'})

    def collect_support_diagnostics(self, plan, state):
        include_windows = plan.entities.get('include_windows_events', False)
        def collect():
            from PacsClient.utils.data_paths import LOGS_DIR
            data = {'logs':collect_log_evidence(LOGS_DIR), 'ticket_submitted':False}
            if include_windows:
                data['windows_events'] = collect_windows_events()
            return data
        return CommandResult(ok=True, action=plan.action,
            data=self._operations.start('support', collect),
            message='Diagnostic collection started. Poll for its result.')

    def support_operation_status(self, plan, state):
        try:
            data = self._operations.status(plan.entities.get('operation_id', ''))
        except ValueError:
            return CommandResult(ok=False, action=plan.action, error_code='UNKNOWN_OPERATION')
        return CommandResult(ok=True, action=plan.action, data=data)

    def get_visible_app_errors(self, plan, state):
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        severities = []
        if app:
            for widget in app.topLevelWidgets():
                if isinstance(widget, QMessageBox) and widget.isVisible():
                    icon = widget.icon()
                    if icon in (QMessageBox.Icon.Warning, QMessageBox.Icon.Critical):
                        severities.append('critical' if icon==QMessageBox.Icon.Critical else 'warning')
        return CommandResult(ok=True, action=plan.action,
            data={'visible_errors':severities, 'scope':'qt_message_boxes',
                  'message_text_exported':False, 'root_cause_confirmed':False})
