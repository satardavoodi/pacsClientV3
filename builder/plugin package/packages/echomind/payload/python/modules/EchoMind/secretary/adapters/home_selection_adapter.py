"""Exact multi-study selection shared by MCP and Secretary."""
from copy import deepcopy
import uuid
import hashlib
import json
from ..command_envelope import CommandResult


def list_identity(rows,source="unknown"):
    return hashlib.sha256(json.dumps([source,[(str((r or {}).get('patient_id') or ''),
        str((r or {}).get('study_uid') or '')) for r in rows]],separators=(',',':')).encode()).hexdigest()


class HomeSelectionAdapter:
    def __init__(self, home):
        self.home = home
        self.receipts = {}
        self.source=None

    def _source(self):
        panel=getattr(self.home,"data_access_panel_widget",None)
        return panel.get_result() if panel is not None else "unknown"

    def _rows(self):
        table = self.home.patient_table_widget
        return [table.get_patient_data_by_row(i) for i in range(table.results_table.rowCount())]

    def select_patients(self, plan, state):
        task=getattr(self.home, "_search_task", None)
        if task is not None and not task.done():
            return CommandResult(ok=False,action=plan.action,error_code="SEARCH_PENDING")
        rows = self._rows()
        ent = plan.entities
        indices = ent.get('row_indices', [])
        uids = ent.get('study_uids', [])
        ids = ent.get('patient_ids', [])
        if sum(bool(x) for x in (indices,uids,ids)) != 1:
            return CommandResult(ok=False, action=plan.action, error_code='EXACT_SELECTOR_REQUIRED')
        if indices:
            snapshot = state.get('home_ordered_studies')
            current = [str((row or {}).get('study_uid') or '') for row in rows]
            if plan.entities.get('list_id'):
                snapshot_ok = plan.entities['list_id']==list_identity(rows,self._source())
            else:
                snapshot_ok = bool(snapshot) and current==snapshot
            if not snapshot_ok:
                return CommandResult(ok=False, action=plan.action, error_code='STALE_LIST')
            if any(type(index) is not int or index<1 or index > len(rows) for index in indices):
                return CommandResult(ok=False, action=plan.action, error_code='ROW_OUT_OF_RANGE')
            uids = [current[index-1] for index in indices]
        elif ids:
            matches = [[row for row in rows if row and str(row.get('patient_id'))==pid] for pid in ids]
            if any(len(match)!=1 for match in matches):
                return CommandResult(ok=False, action=plan.action, error_code='AMBIGUOUS_PATIENT')
            uids = [match[0].get('study_uid') for match in matches]
        positions=[]
        for uid in dict.fromkeys(uids):
            found=[i for i,row in enumerate(rows) if row and row.get('study_uid')==uid]
            if len(found)!=1:
                return CommandResult(ok=False, action=plan.action, error_code='STUDY_NOT_UNIQUE')
            positions.append(found[0])
        table=self.home.patient_table_widget
        table.clear_all_selections()
        for index in positions:
            table.set_row_checked(index,True)
        selected=table.get_selected_patient_data_list() or []
        wanted={rows[index]['study_uid'] for index in positions}
        if {row.get('study_uid') for row in selected} != wanted:
            return CommandResult(ok=False,action=plan.action,error_code='SELECTION_NOT_APPLIED')
        handle=uuid.uuid4().hex
        self.receipts={handle:deepcopy(selected)}
        self.source=self._source()
        return CommandResult(ok=True,action=plan.action,data={'selection_id':handle,'selected_count':len(selected)})

    def selected(self,handle):
        if self._source()!=self.source:
            return None
        expected=self.receipts.get(handle)
        actual=self.home.patient_table_widget.get_selected_patient_data_list() or []
        if not expected or {r.get('study_uid') for r in expected}!={r.get('study_uid') for r in actual}:
            return None
        return deepcopy(expected)

    def selection_status(self,plan,state):
        rows=self.selected(plan.entities['selection_id'])
        return CommandResult(ok=rows is not None,action=plan.action,
            error_code=None if rows else 'STALE_SELECTION',
            data={'selected_count':len(rows or [])})

    def download_selection(self,plan,state):
        if not state.get("confirmed"):
            return CommandResult(ok=False,action=plan.action,error_code="CONFIRM_REQUIRED")
        rows=self.selected(plan.entities['selection_id'])
        if rows is None:
            return CommandResult(ok=False,action=plan.action,error_code='STALE_SELECTION')
        self.home._on_download_requested(rows,set_current_tab=False)
        return CommandResult(ok=True,action=plan.action,data={'selection_id':plan.entities['selection_id'],'state':'queued','count':len(rows)})

    def download_selection_status(self,plan,state):
        rows=self.selected(plan.entities['selection_id'])
        if rows is None:
            return CommandResult(ok=False,action=plan.action,error_code='STALE_SELECTION')
        from modules.download_manager.state import state_store
        store=state_store._state_store_instance
        if store is None:
            return CommandResult(ok=False,action=plan.action,error_code='DOWNLOAD_STATE_UNAVAILABLE')
        statuses=[]
        for row in rows:
            item=store.get(row['study_uid'])
            statuses.append(str(getattr(getattr(item,'status',None),'value','unknown')).lower())
        terminal='succeeded' if all(value=='completed' for value in statuses) else (
            'failed' if any(value in ('failed','cancelled') for value in statuses) else 'running')
        return CommandResult(ok=True,action=plan.action,data={'state':terminal,'count':len(rows)})

    def film_selection(self,plan,state):
        if self.selected(plan.entities['selection_id']) is None:
            return CommandResult(ok=False,action=plan.action,error_code='STALE_SELECTION')
        from aipacs_runtime import is_module_enabled
        if not is_module_enabled('printing'):
            return CommandResult(ok=False,action=plan.action,error_code='MODULE_UNAVAILABLE')
        self.home.open_printing_module()
        from PacsClient.pacs.workstation_ui.home_ui.home_module_tabs import find_existing_module_tab
        index=find_existing_module_tab(self.home.tab_widget,self.home.custom_tab_manager,'is_printing_tab')
        if index is None:
            return CommandResult(ok=False,action=plan.action,error_code='PRINTING_OPEN_FAILED')
        return CommandResult(ok=True,action=plan.action,data={'state':'printing_open','tab_index':index})
