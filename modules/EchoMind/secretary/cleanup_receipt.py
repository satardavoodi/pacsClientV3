"""Read cached cleanup status asynchronously; never initiate/retry deletion."""
import asyncio
from copy import deepcopy

async def wait_for_cleanup(bus, initial, *, sleep=asyncio.sleep, attempts=600, progress=None):
    result=deepcopy(initial)
    expected=(result.get('data') or {}).get('operation_id')
    if bus is None or not expected:
        return dict(result,ok=False,error_code='CLEANUP_RECEIPT_UNAVAILABLE',message='Cleanup was requested, but its final receipt is unavailable. Check Storage; do not repeat deletion automatically.')
    stages={'awaiting_local_confirmation':'Awaiting Storage confirmation','preparing_preview':'Preparing cleanup preview',
            'running':'Deleting local files','refreshing_storage':'Refreshing disk usage'}
    for _ in range(attempts):
        receipt=bus.execute({'action':'get_storage_cleanup_status','entities':{}})
        data=receipt.data if receipt.ok and isinstance(receipt.data,dict) else {}
        if data.get('operation_id') != expected:
            return dict(result,ok=False,error_code='CLEANUP_RECEIPT_CHANGED',message='The cleanup receipt is unavailable or changed. Check Storage before issuing another cleanup.')
        result['data']=deepcopy(data)
        state=data.get('state')
        if state in ('succeeded','completed_with_warnings'):
            count=data.get('files_deleted')
            if type(count) is not int or count<0:
                break
            suffix = (' Storage refresh or deletion has warnings.' if state=='completed_with_warnings' else
                      ' Disk usage has been refreshed.' if data.get('storage_refreshed') else
                      ' Disk usage refresh is not confirmed.')
            return dict(result,ok=True,error_code=None,message=f'Cleanup completed: {count} files deleted; {data.get("db_rows_affected",0)} database rows affected.'+suffix)
        if state in ('failed','cancelled_or_blocked'):
            return dict(result,ok=False,error_code='CLEANUP_NOT_COMPLETED',message='Cleanup failed, was cancelled or was blocked. Review the Storage result.')
        if progress:progress(stages.get(state,'Waiting for cleanup result'))
        await sleep(1)
    return dict(result,ok=False,error_code='CLEANUP_PENDING',message='Cleanup or disk refresh is still pending. No final deletion result is confirmed; check Storage without repeating the cleanup.')
