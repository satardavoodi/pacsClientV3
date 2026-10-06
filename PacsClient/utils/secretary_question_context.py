"""Read-only Ask facts: capture cached shared state, then project logs on a worker."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re


def capture_question_context(bus):
    context = {'state':'unavailable'}
    if bus is None:
        return context
    summary = bus.execute({'action':'get_loaded_study_summary','entities':{}})
    if summary.ok and isinstance(summary.data, dict):
        context = deepcopy(summary.data)
    result = bus.execute({'action':'download_statistics','entities':{}})
    stats = result.data if result.ok and isinstance(result.data, dict) else {}
    safe = {'scope':'current_client_download_store','state':'available' if stats else 'unavailable'}
    for key in ('total','active','downloading'):
        value = stats.get(key)
        if type(value) is int and 0 <= value <= 10000000:
            safe[key] = value
    statuses = stats.get('by_status')
    if not isinstance(statuses,dict):
        statuses = {}
    safe['by_status'] = {key:value for key,value in statuses.items()
        if isinstance(key,str) and re.fullmatch(r'[a-z_]{1,40}',key)
        and type(value) is int and 0 <= value <= 10000000}
    context['download_state'] = safe
    return context


def collect_question_evidence(context, log_root):
    from modules.Identity.thread_guard import assert_off_gui_thread
    from .support_diagnostics import collect_log_evidence
    assert_off_gui_thread('Secretary Ask log evidence')
    result = deepcopy(context)
    result['diagnostics'] = {'sampled_at':datetime.now(timezone.utc).isoformat(),
        'logs':collect_log_evidence(log_root),
        'assessment_limit':'A bounded log tail and one state snapshot cannot prove throughput, absence of earlier errors, or that active transfers are not stalled.'}
    modified = {}
    for source in result['diagnostics']['logs']['sources']:
        if source.get('state') == 'sampled':
            try:
                modified[source['source']] = datetime.fromtimestamp(
                    (Path(log_root)/source['source']).stat().st_mtime,timezone.utc).isoformat()
            except OSError:
                pass
    result['diagnostics']['log_file_modified_at'] = modified
    return result


def capture_guide_context(bus):
    """Capture visible control metadata without navigation or reading field values."""
    context = {'tutorials': {}, 'screen_image': 'not_included_enable_screen_context'}
    if bus is None:
        return dict(context, ui_controls={'state': 'unavailable'})
    catalog = bus.execute({'action': 'get_tutorial_catalog', 'entities': {}})
    if catalog.ok and isinstance(catalog.data, dict):
        context.update(deepcopy(catalog.data))
    observation = bus.execute({'action': 'inspect_ui_controls', 'entities': {}})
    context['ui_controls'] = deepcopy(observation.data) if observation.ok else {'state': 'unavailable'}
    return context


def collect_settings_report(repository=None):
    """Read existing typed snapshots on a worker; never verify, save or navigate."""
    from modules.Identity.thread_guard import assert_off_gui_thread
    assert_off_gui_thread('Secretary Ask settings report')
    if repository is None:
        from .assistant_settings_repository import SettingsRepository
        repository = SettingsRepository()
    sections = {}
    for section in ('server', 'modality_grid', 'tools', 'image_filter', 'ai'):
        action = 'get_ai_settings' if section == 'ai' else 'get_settings_snapshot'
        try:
            data = repository.execute(action, {} if section == 'ai' else {'section': section})
            sections[section] = {'state': 'available', 'data': data}
        except Exception:
            sections[section] = {'state': 'unavailable'}
    return {'scope': 'persisted_configuration_not_unsaved_forms_or_connectivity',
            'sections': sections, 'complete': False,
            'unavailable_sections': ['installation', 'education', 'agent_policy', 'storage_usage'],
            'sampled_at': datetime.now(timezone.utc).isoformat()}
