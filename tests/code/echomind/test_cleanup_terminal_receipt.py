"""Cleanup receipt waiting never repeats deletion or invents completion."""
import asyncio
from types import SimpleNamespace

def test_waits_for_refresh_and_reports_terminal_counts():
    from modules.EchoMind.secretary.cleanup_receipt import wait_for_cleanup
    states=iter([{'state':'running','operation_id':'synthetic'},
                 {'state':'refreshing_storage','operation_id':'synthetic','files_deleted':3},
                 {'state':'succeeded','operation_id':'synthetic','files_deleted':3,'db_rows_affected':1}])
    calls=[]
    class Bus:
        def execute(self,plan):calls.append(plan['action']);return SimpleNamespace(ok=True,data=next(states))
    async def sleep(_):pass
    initial={'ok':True,'action':'request_storage_cleanup','data':{'state':'awaiting_local_confirmation','operation_id':'synthetic'}}
    result=asyncio.run(wait_for_cleanup(Bus(),initial,sleep=sleep,attempts=3))
    assert result['ok'] and result['data']['files_deleted']==3
    assert calls==['get_storage_cleanup_status']*3
    assert '3' in result['message']

def test_missing_or_changed_receipt_never_claims_success():
    from modules.EchoMind.secretary.cleanup_receipt import wait_for_cleanup
    async def sleep(_):pass
    initial={'ok':True,'action':'request_storage_cleanup','data':{'state':'awaiting_local_confirmation','operation_id':'synthetic'}}
    for data in ({'state':'running','operation_id':'synthetic'},{'state':'succeeded','operation_id':'different'}):
        bus=SimpleNamespace(execute=lambda plan:SimpleNamespace(ok=True,data=data))
        result=asyncio.run(wait_for_cleanup(bus,initial,sleep=sleep,attempts=1))
        assert not result['ok'] and result['error_code'] in ('CLEANUP_PENDING','CLEANUP_RECEIPT_CHANGED')



def test_storage_refresh_completion_waits_for_new_scan_not_old_pending_scan():
    from PacsClient.pacs.workstation_ui.settings_ui.storage_cleanup_panel import StorageCleanupPanelWidget as StorageCleanupPanel
    state={'state':'refreshing_storage','cleanup_state':'succeeded','files_deleted':3}
    panel=SimpleNamespace(_assistant_cleanup_state=state,_assistant_cleanup_owned=True,
                          _folder_size_pending=True,_apply_drive_rows=lambda value:None,
                          _apply_folder_sizes=lambda value:None)
    StorageCleanupPanel._on_folder_sizes_ready(panel,{'folder_sizes':{},'drive_rows':[]})
    assert state['state']=='refreshing_storage' and panel._assistant_cleanup_owned
    panel._folder_size_pending=False
    StorageCleanupPanel._on_folder_sizes_ready(panel,{'folder_sizes':{},'drive_rows':[]})
    assert state['state']=='succeeded' and state['storage_refreshed']
    assert state['files_deleted']==3 and not panel._assistant_cleanup_owned


def test_refresh_failure_preserves_deletion_count_without_claiming_fresh_usage():
    from PacsClient.pacs.workstation_ui.settings_ui.storage_cleanup_panel import StorageCleanupPanelWidget as StorageCleanupPanel
    panel=SimpleNamespace(_assistant_cleanup_state={'state':'refreshing_storage','files_deleted':3},
                          _assistant_cleanup_owned=True,_folder_size_pending=False,storage_summary_label=None)
    StorageCleanupPanel._on_folder_sizes_failed(panel,'Synthetic failure')
    assert panel._assistant_cleanup_state['state']=='completed_with_warnings'
    assert panel._assistant_cleanup_state['files_deleted']==3
    assert panel._assistant_cleanup_state['storage_refreshed'] is False
