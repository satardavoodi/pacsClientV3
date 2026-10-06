"""Bounded support evidence; never return raw log or Windows messages."""
from collections import OrderedDict
from collections import deque
from copy import deepcopy
from pathlib import Path
import json
import os
import re
import subprocess
import threading
import time
from uuid import uuid4

LOG_NAMES = ('app.log', 'viewer_diagnostics.log', 'download_diagnostics.log', 'db_diagnostics.log')
MAX_BYTES = 65536
_RESULTS = deque(maxlen=100)
_RESULT_LOCK = threading.Lock()


def record_function_result(action, result, known=True):
    safe_codes = {'CONFIRM_REQUIRED', 'PERMISSION_DENIED', 'UNKNOWN_ACTION',
                  'INVALID_ARGUMENTS', 'PATIENT_CONTEXT_MISMATCH', 'ADAPTER_ERROR',
                  'MODULE_UNAVAILABLE', 'VOICE_NOT_SAVED', 'UNKNOWN_OPERATION'}
    with _RESULT_LOCK:
        _RESULTS.append({'action':action if known else 'unsupported_action',
                        'timestamp':time.time(), 'ok':result.ok,
                        'error_code':result.error_code if result.error_code in safe_codes else
                                     ('ACTION_FAILED' if not result.ok else None)})


def recent_function_results():
    with _RESULT_LOCK:
        return deepcopy(list(_RESULTS))


def project_source_frames(text, source_root):
    """Retain verified repository-relative source locations, never messages/locals."""
    frames = []
    for match in re.finditer(r'File "([^"\r\n]{1,1024})", line ([0-9]{1,7}),? in ([A-Za-z_][A-Za-z_0-9]*|<module>)', text):
        path, line, function = match.groups()
        path = path.replace('\\', '/')
        relative = re.search(r'(?:^|/)((?:PacsClient|modules|database)/[A-Za-z_0-9/]+\.py)$', path)
        if not relative:
            continue
        module = relative.group(1)
        if len(module) > 200 or len(function) > 100:
            continue
        candidate = Path(source_root) / module
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            candidate.resolve().relative_to(Path(source_root).resolve())
        except ValueError:
            continue
        frames.append({'module':module, 'line':int(line), 'function':function})
        if len(frames) >= 40:
            break
    return frames


def collect_log_evidence(root, *, source_root=None):
    sources = []
    for name in LOG_NAMES:
        item = {'source':name, 'state':'missing'}
        path = Path(root)/name
        try:
            if path.is_symlink():
                item['state'] = 'invalid_source'
            elif path.exists():
                with path.open('rb') as stream:
                    size = os.fstat(stream.fileno()).st_size
                    offset = max(0, size-MAX_BYTES)
                    stream.seek(offset)
                    data = stream.read(MAX_BYTES)
                if offset:
                    data = data.partition(b'\n')[2]
                text = data.decode('utf-8', errors='replace')
                item.update(state='sampled', bytes_read=len(data), truncated=bool(offset),
                            errors=len(re.findall(r'\b(?:ERROR|CRITICAL)\b', text)),
                            warnings=len(re.findall(r'\bWARNING\b', text)))
                item['exception_signals'] = {code:len(re.findall(r'\b'+code+r'\b', text))
                    for code in ('TimeoutError', 'ConnectionError', 'MemoryError',
                                 'PermissionError', 'RuntimeError')}
                if source_root is not None:
                    item['frames'] = project_source_frames(text, source_root)
                    item['exception_signals'].update({code:len(re.findall(r'\b'+code+r'\b', text))
                        for code in ('TypeError', 'ValueError', 'AttributeError', 'KeyError',
                                     'IndexError', 'ImportError', 'OSError', 'AssertionError')})
        except OSError:
            item['state'] = 'unreadable'
        sources.append(item)
    return {'sources':sources, 'scope':'bounded_tail_not_time_window',
            'root_cause_confirmed':False, 'raw_text_exported':False}


def project_windows_events(events):
    safe = []
    for event in events[:1000]:
        if str(event.get('app', '')).lower() != 'aipacs.exe':
            continue
        if event.get('id') not in (1000, 1001, 1002):
            continue
        code = str(event.get('code', ''))
        stamp = str(event.get('time', ''))
        safe.append({'event_id':event['id'],
                     'time_utc':stamp if re.fullmatch(r'[0-9T:Z.\-+]{10,40}', stamp) else None,
                     'exception_code':code if re.fullmatch(r'[0-9a-fA-F]{8}', code) else None})
    return {'state':'sampled', 'events':safe[:100],
            'truncated':len(events)>=1000 or len(safe)>100,
            'attribution':'product_basename_only', 'root_cause_confirmed':False,
            'source_python_events':'excluded_unverified', 'raw_text_exported':False}


def collect_windows_events():
    if os.name != 'nt':
        return {'state':'unsupported_platform', 'events':[]}
    script = r"""
$ErrorActionPreference = 'Stop'
try {
  $items = @(Get-WinEvent -FilterHashtable @{LogName='Application';
    Id=1000,1001,1002; StartTime=(Get-Date).AddHours(-24)} -MaxEvents 1000)
  $result = @($items | ForEach-Object {
    $xml = [xml]$_.ToXml()
    $values = @{}
    foreach ($d in $xml.Event.EventData.Data) { $values[[string]$d.Name] = [string]$d.'#text' }
    $app = $values['AppName']
    if ($app -eq 'AIPacs.exe') {
      @{app=$app; id=$_.Id; code=$values['ExceptionCode']; time=$_.TimeCreated.ToUniversalTime().ToString('o')}
    } else { @{app='excluded'; id=$_.Id} }
  })
  @{state='sampled'; events=$result} | ConvertTo-Json -Compress -Depth 4
} catch {
  if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {
    '{"state":"no_matches","events":[]}'
  } elseif ($_.Exception -is [UnauthorizedAccessException] -or $_.Exception.HResult -eq -2147024891) {
    '{"state":"access_denied","events":[]}'
  } else { '{"state":"unavailable","events":[]}' }
}
"""
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                                 '-Command', script], capture_output=True,
                                timeout=15, creationflags=0x08000000)
        if result.returncode or len(result.stdout)>256000:
            return {'state':'query_failed', 'events':[]}
        payload = json.loads(result.stdout.decode('utf-8-sig'))
        if payload.get('state') != 'sampled':
            return {'state':payload.get('state', 'unavailable'), 'events':[]}
        return project_windows_events(payload['events'])
    except subprocess.TimeoutExpired:
        return {'state':'timeout', 'events':[]}
    except Exception:
        return {'state':'unavailable', 'events':[]}


class OperationStore:
    """Workers keep plain data only; callers poll without blocking Qt."""
    def __init__(self):
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def start(self, kind, worker):
        key = str(uuid4())
        with self._lock:
            if len(self._items)>=32:
                terminal = next((k for k,v in self._items.items() if v['state']!='running'), None)
                if terminal is None:
                    raise ValueError('Operation capacity reached')
                del self._items[terminal]
            self._items[key] = {'operation_id':key, 'kind':kind, 'state':'running'}
        def run():
            try:
                data = worker()
                result = {'state':'succeeded', 'data':data}
            except Exception:
                result = {'state':'failed', 'error_code':'OPERATION_FAILED'}
            with self._lock:
                self._items[key].update(result)
        threading.Thread(target=run, name='assistant-support', daemon=True).start()
        return self.status(key)

    def status(self, key):
        with self._lock:
            if key not in self._items:
                raise ValueError('Unknown operation')
            return deepcopy(self._items[key])
