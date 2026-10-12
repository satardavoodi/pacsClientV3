"""Aggregate retained server usage without exporting clinical text or identities."""
from contextlib import contextmanager, closing
from contextvars import ContextVar
import json
import sqlite3
import threading

_collector = ContextVar('eagle_eye_token_collector', default=None)
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'total_tokens')
GROUP_LABELS = {
    'eagle_eye': {
        'breast': 'Breast / mammography', 'bone-age': 'Bone age',
        'brain': 'Brain volumetry', 'brain-lesions': 'Brain white matter lesions',
        'lumbar': 'Lumbar spine', 'lumbar-marrow': 'Lumbar bone marrow',
        'alignment': 'Lower limb alignment', 'total-spine': 'Total spine alignment',
        'dental-panorama': 'Panoramic dental research',
    },
    'echomind': {
        'report': 'Report', 'turbo': 'Report - Turbo / HQ', 'chat': 'Chat',
        'assistant': 'Radiopaedia Assist', 'search': 'Textbook / DI Assist',
        'web_search': 'Web Assist', 'standardize': 'Report standardization',
        'standardize_assist': 'Assist standardization', 'translate_report': 'Report translation',
        'translate_text': 'Text translation', 'correction': 'Report correction',
        'breast': 'Breast expert', 'organize_template': 'Template organization',
        'template_languages': 'Template languages', 'add_reference': 'Add reference',
    },
    'agent': {
        'route': 'Action routing', 'plan': 'Action planning', 'repair': 'Action repair',
        'ask': 'Ask', 'guide': 'Guide', 'help_ticket': 'Help ticket',
    },
}


def group_labels(category):
    """Use the admission catalog as authority, with stable friendly legacy labels."""
    labels = dict(GROUP_LABELS[category])
    if category == 'eagle_eye':
        from .contracts import MODULES
        for key in MODULES:
            labels.setdefault(key, key.replace('-', ' ').title())
    return labels


def _grouped_summary(category, available=True, *, by_client=False):
    summary = empty_summary(available)
    summary['groups'] = [dict(empty_summary(available), key=key, label=label)
                         for key, label in group_labels(category).items()]
    if by_client:
        summary['clients'] = []
    return summary


def _add_client(summary, clients, category, owner, key, state, accounting):
    # The owner is supplied by server authentication, never by request fields.
    identity = owner if isinstance(owner, str) and 0 < len(owner) <= 256 and all(ord(c) >= 32 for c in owner) else 'Unknown sender'
    if identity not in clients:
        row = dict(_grouped_summary(category), client_id=identity)
        clients[identity] = row
        summary['clients'].append(row)
    _add_group(clients[identity], key, state, accounting)


def _add_group(summary, key, state, accounting):
    # Unknown legacy values are never exported as labels (they may contain private text).
    _add(summary, state, accounting)
    rows = {row['key']: row for row in summary['groups']}
    if key not in rows:
        key = 'other'
    if key not in rows:
        row = dict(empty_summary(), key=key, label='Other / unclassified')
        summary['groups'].append(row)
    else:
        row = rows[key]
    _add(row, state, accounting)


def _workflow_key(category, workflow, mode):
    if category != 'agent':
        return workflow
    if not isinstance(workflow, str) or not workflow.startswith('secretary:'):
        return 'other'
    if mode in ('ask', 'guide', 'help_ticket'):
        return mode
    return workflow.removeprefix('secretary:')


def _count(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


class TokenCollector:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def record(self, value, model='unspecified'):
        value = value if isinstance(value, dict) else {}
        incoming = _count(value.get('input_tokens', value.get('prompt_tokens')))
        outgoing = _count(value.get('output_tokens', value.get('completion_tokens')))
        total = _count(value.get('total_tokens'))
        if total is None and incoming is not None and outgoing is not None:
            total = incoming + outgoing
        event = dict(input_tokens=incoming, output_tokens=outgoing, total_tokens=total)
        event['model'] = str(model or 'unspecified')[:128]
        with self.lock:
            self.events.append(event)

    def snapshot(self):
        with self.lock:
            events = list(self.events)
        result = {key: sum(e[key] for e in events if e[key] is not None)
                  if any(e[key] is not None for e in events) else None for key in TOKEN_FIELDS}
        result['reported_calls'] = sum(e['input_tokens'] is not None and e['output_tokens'] is not None for e in events)
        result['unreported_calls'] = len(events) - result['reported_calls']
        result['models'] = sorted({e['model'] for e in events})
        return result


@contextmanager
def collect_tokens():
    collector = TokenCollector()
    token = _collector.set(collector)
    try:
        yield collector
    finally:
        _collector.reset(token)


def record_tokens(value, model='unspecified'):
    collector = _collector.get()
    if collector is not None:
        collector.record(value, model)


def result_tokens(result):
    collector = TokenCollector()
    collector.record(result.get('usage') if isinstance(result, dict) else None)
    return collector.snapshot()


def empty_summary(available=True):
    return dict(available=available, requests=0, completed=0, failed=0, pending=0,
                input_tokens=None, output_tokens=None, total_tokens=None,
                reported_calls=0, unreported_calls=0, requests_without_complete_token_usage=0)


def _add(summary, state, accounting):
    summary['requests'] += 1
    field = 'completed' if state == 'succeeded' else 'failed' if state in ('failed', 'cancelled', 'interrupted') else 'pending'
    summary[field] += 1
    accounting = accounting if isinstance(accounting, dict) else {}
    for key in TOKEN_FIELDS:
        value = _count(accounting.get(key))
        if value is not None:
            summary[key] = (summary[key] or 0) + value
    for key in ('reported_calls', 'unreported_calls'):
        summary[key] += _count(accounting.get(key)) or 0
    if any(_count(accounting.get(key)) is None for key in ('input_tokens', 'output_tokens')):
        summary['requests_without_complete_token_usage'] += 1


def history_summary(history, owners=None, *, category='echomind', by_client=False):
    if history is None or not (history.directory / 'history.sqlite3').is_file():
        return _grouped_summary(category, False, by_client=by_client)
    if owners == []:
        return _grouped_summary(category, by_client=by_client)
    summary = _grouped_summary(category, by_client=by_client)
    clients = {}
    where = '' if owners is None else f" WHERE owner IN ({','.join('?' for _ in owners)})"
    # Extract accounting in SQLite; never load response content or case context.
    query = ("SELECT state, json_extract(response_json, '$.accounting'), workflow, "
             "json_extract(request_json, '$.interaction_mode'), owner FROM requests" + where)
    with closing(sqlite3.connect((history.directory / 'history.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        for state, raw, workflow, mode, owner in db.execute(query, () if owners is None else owners):
            key = _workflow_key(category, workflow, mode)
            accounting = json.loads(raw) if raw else None
            _add_group(summary, key, state, accounting)
            if by_client:
                _add_client(summary, clients, category, owner, key, state, accounting)
    return summary


def job_summary(states, owner=None, *, available=True, by_client=False):
    summary = _grouped_summary('eagle_eye', available, by_client=by_client)
    clients = {}
    for state in states:
        if owner is None or state.get('owner') == owner:
            _add_group(summary, state.get('module'), state.get('status'), state.get('token_accounting'))
            if by_client:
                _add_client(summary, clients, 'eagle_eye', state.get('owner'), state.get('module'),
                            state.get('status'), state.get('token_accounting'))
    return summary


def server_summary(jobs, owner, echomind=None, secretary=None):
    with jobs.lock:
        states = [dict(state) for state in jobs.jobs.values() if state.get('owner') == owner]
    return dict(version=1, scope='this_paired_client', period='retained_server_history',
                eagle_eye=job_summary(states, owner),
                echomind=history_summary(getattr(echomind, 'history', None), [owner]),
                agent=history_summary(getattr(secretary, 'history', None), [owner], category='agent'))
