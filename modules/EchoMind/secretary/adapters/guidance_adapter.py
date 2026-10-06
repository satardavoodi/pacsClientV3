"""Read-only study summaries and verified tutorial targets shared by MCP."""
from collections import Counter
from ..command_envelope import CommandResult

TUTORIALS = {
    'open_patient': {'instruction':'Double-click a patient row to open the study.', 'target':'patient_table_widget'},
    'search_patients': {'instruction':'Set the modality and date filters, then click Search Patients.', 'target':'patient_search_widget'},
    'report_issue': {'instruction':'Select Help Ticket, describe the problem and review the issue before sending.', 'target':'secretary'},
}

WORKFLOW_GUIDE = {
    'report': {
        'pending': {'icon':'fa5s.clock', 'meaning':'Report pending; not completed.'},
        'awaiting_physician_approval': {'icon':'fa5s.user-md', 'meaning':'Awaiting physician approval.'},
        'awaiting_secretary_approval': {'icon':'fa5s.user-tie', 'meaning':'Awaiting secretary approval.'},
        'awaiting_approval': {'icon':'fa5s.hourglass-half', 'meaning':'Awaiting approval.'},
        'physician_approved': {'icon':'fa5s.check-circle', 'meaning':'Physician approved; not necessarily completed.'},
        'secretary_approved': {'icon':'fa5s.check-circle', 'meaning':'Secretary approved; not necessarily completed.'},
        'completed': {'icon':'fa5s.check-double', 'meaning':'Completed report; emerald double check or green reporting-physician name.'},
        'archived': {'icon':'fa5s.archive', 'meaning':'Archived; do not equate with an unfinished report.'},
    },
    'voice': {
        'local':'Red microphone indicates local voice files; it does not prove upload or authorship.',
        'server':'Blue microphone indicates server voice files from an authoritative workflow snapshot.',
        'unknown':'Missing or expired evidence means unknown, not no voice.',
    },
    'opening':'Use read_patients, then the original one-based row_index and its list_id. Re-read after list/source changes. Never guess a patient ID.',
    'scope_routing': {
        'act':'Execute a requested operation with the shared CommandBus and verify its receipt.',
        'ask':'Answer from supplied facts only; report unavailable metrics and incomplete scope.',
        'guide':'Explain verified controls; use only offered tutorial IDs for highlighting.',
        'settings':'Changing which modalities are offered is Settings / Modality Grid; filtering the current list is Home search.',
        'ambiguity':'Ask one focused choice only when intent or target cannot be safely resolved from current facts.',
    },
    'local_artifacts':'Local dicom/docs/voice/ai/case_of_day/printed flags describe cached workstation files or state, not remote delivery, diagnosis quality or personal authorship.',
    'limitations':'Voice presence does not identify its author. Assignment is not authorship. A displayed patient row can contain multiple studies. Loaded rows do not establish all daily admissions.',
}

class GuidanceAdapter:
    def __init__(self, home):
        self.home = home

    def get_loaded_study_summary(self, plan, state):
        from .home_widget_adapter import HomeWidgetAdapter
        adapter = HomeWidgetAdapter(home_widget=self.home)
        rows = adapter.list_rows()
        groups = {}
        for row in rows:
            date = str(row.get('date') or '').replace('-','').replace('/','')
            from datetime import datetime
            try:
                if len(date) != 8:
                    raise ValueError('Unknown date')
                datetime.strptime(date, '%Y%m%d')
            except ValueError:
                date = 'unknown'
            key = (date, str(row.get('modality') or 'unknown'))
            group = groups.setdefault(key, {'date':date, 'modality':key[1],
                'displayed_rows':0, 'voice_presence':Counter(), 'report_statuses':Counter()})
            group['displayed_rows'] += 1
            presence = row.get('voice_presence')
            group['voice_presence'][presence if presence in ('present','absent','unknown') else 'unknown'] += 1
            group['report_statuses'][row.get('report_status') or 'unknown'] += 1
        for group in groups.values():
            group['voice_presence'] = dict(group['voice_presence'])
            group['report_statuses'] = dict(group['report_statuses'])
        return CommandResult(ok=True, action=plan.action, data={
            'scope':'currently loaded studies, not all daily admissions',
            'source':adapter.get_active_source(), 'loaded_studies':len(rows),
            'modalities':dict(Counter(row.get('modality') or 'unknown' for row in rows)),
            'report_statuses':dict(Counter(row.get('report_status') or 'unknown' for row in rows)),
            'report_author_metrics':'unavailable', 'voice_author_metrics':'unavailable',
            'daily_population_complete':False, 'workflow_scope':'primary_study_of_displayed_row',
            'workflow_groups':list(groups.values())[:200], 'workflow_groups_truncated':len(groups)>200,
            'workflow_guide':WORKFLOW_GUIDE})

    def get_tutorial_catalog(self, plan, state):
        from ..guide_knowledge import page_guides
        return CommandResult(ok=True, action=plan.action, data={'tutorials':TUTORIALS, 'workflow_guide':WORKFLOW_GUIDE, 'page_guides':page_guides()})

    def show_tutorial(self, plan, state):
        tutorial = TUTORIALS[plan.entities['tutorial_id']]
        from PySide6.QtWidgets import QWidget
        target = self.home.findChild(QWidget, 'secretaryButtonWidget') if tutorial['target']=='secretary' else getattr(self.home, tutorial['target'], None)
        if target is None or not target.isVisible():
            return CommandResult(ok=False, action=plan.action, error_code='TUTORIAL_TARGET_NOT_VISIBLE', message='Open Home and retry the tutorial.')
        from PacsClient.pacs.workstation_ui.home_ui.tutorial_highlight import TutorialHighlight
        old = getattr(self.home, '_secretary_tutorial_highlight', None)
        if old is not None:
            old.close()
        overlay = TutorialHighlight(target)
        self.home._secretary_tutorial_highlight = overlay
        overlay.show()
        return CommandResult(ok=True, action=plan.action, message=tutorial['instruction'], data={'tutorial_id':plan.entities['tutorial_id'], 'state':'highlighted'})
