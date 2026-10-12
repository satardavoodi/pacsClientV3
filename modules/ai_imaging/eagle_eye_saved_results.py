"""Worker-only exact-study discovery; reopening never submits analysis jobs."""
import json
from pathlib import Path

TITLES = {'lumbar-marrow':'Lumbar Bone Marrow', 'lumbar':'Lumbar MRI',
          'alignment':'Lower Limb Alignment', 'total-spine':'Total Spine Alignment',
          'brain':'Brain Volumetry', 'brain-lesions':'Brain Lesions',
          'breast':'Mammography', 'bone-age':'Bone Age'}


def discover_lumbar(root, study):
    """Return the latest complete raw Lumbar session for one exact study.

    Lumbar LLM sessions predate the generic ``result.json`` archive contract.
    Their authority is the pair ``session.json`` + ``llm_result.json``.  Keep
    this reader bounded and exact-study so opening a workspace never submits a
    job and never presents a neighbouring study's result.
    """
    from .eagle_eye_lumbar import analysis_store

    root = Path(root).resolve()
    if not study or not root.is_dir():
        return []
    selected = None
    for index, state_path in enumerate(root.rglob('llm_result.json')):
        if index >= 10000:
            break
        try:
            resolved = state_path.resolve()
            if (not resolved.is_relative_to(root)
                    or resolved.stat().st_size > 4 * 1024**2):
                continue
            session_path = resolved.parent / 'session.json'
            if (not session_path.is_file()
                    or session_path.stat().st_size > 4 * 1024**2):
                continue
            text_path = resolved.parent / 'llm_result.txt'
            if (not text_path.is_file()
                    or text_path.stat().st_size > 4 * 1024**2):
                continue
            session = json.loads(session_path.read_text(encoding='utf-8'))
            if (session.get('session_kind') != 'lumbar_mri'
                    or str(session.get('study_instance_uid') or '') != str(study)):
                continue
            record = analysis_store.read_record(resolved.parent)
            if not record.has_result:
                continue
            stamp = max(resolved.stat().st_mtime_ns, text_path.stat().st_mtime_ns)
            row = dict(module='lumbar', record=record, result=record.document,
                       content=record.text, report='', pdf=None, stamp=stamp)
            if selected is None or stamp > selected['stamp']:
                selected = row
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return [selected] if selected is not None else []


def discover(root, study):
    from .eagle_eye_brain.saved_results import _same_study
    root = Path(root).resolve()
    selected = {}
    if not study or not root.is_dir():
        return []
    for index, path in enumerate(root.rglob('result.json')):
        if index >= 10000:
            break
        try:
            if not path.resolve().is_relative_to(root) or path.stat().st_size > 16*1024**2:
                continue
            result = json.loads(path.read_text(encoding='utf-8'))
            module = result.get('server_module')
            # Older brain reports predate the server module identifier.
            if not module:
                if result.get('analysis_type') == 'brain_lesions':
                    module = 'brain-lesions'
                elif result.get('analysis_type') == 'brain' or any(
                        key in result for key in ('posterior_rows', 'manual_rows', 'normative')):
                    module = 'brain'
            if module not in TITLES or not _same_study(result, study):
                continue
            directory = Path(result.get('artifact_directory', '')).resolve()
            if directory != path.parent.resolve():
                continue
            report = Path(result.get('report_html') or directory/'report.html').resolve()
            pdf = directory/'report.pdf'
            if pdf.is_file() and not pdf.resolve().is_relative_to(directory):
                continue
            spine_review = module == 'total-spine' and (
                isinstance(result.get('candidates'), list) or isinstance(result.get('review_views'), list))
            if not report.is_relative_to(directory) or not (report.is_file() or pdf.is_file() or spine_review):
                continue
            content = report.read_text(encoding='utf-8') if report.is_file() and report.stat().st_size <= 16*1024**2 else ''
            stamp = path.stat().st_mtime_ns
            if module not in selected or stamp > selected[module]['stamp']:
                # Validate paths used by the restored marrow view before handing
                # a server-produced result to presentation widgets.
                for key in ('preview', 'report_html'):
                    if result.get(key) and not Path(result[key]).resolve().is_relative_to(directory):
                        raise ValueError('Saved artifact escaped its directory.')
                if result.get('review_assets') and any(not Path(p).resolve().is_relative_to(directory)
                                                       for p in result['review_assets'].values()):
                    raise ValueError('Saved review assets escaped their directory.')
                selected[module] = dict(module=module, result=result, content=content,
                                        report=str(report), pdf=str(pdf) if pdf.is_file() else None, stamp=stamp)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return sorted(selected.values(), key=lambda row: row['module'])


def discover_workspace(root, attachments, study):
    rows = discover(root, study) + discover_lumbar(root, study)
    # Native mammography/bone-age archives are already study-keyed separately.
    if study and all(c.isdigit() or c == '.' for c in str(study)):
        rows += discover(Path(attachments)/str(study), study)
    latest = {}
    for row in rows:
        if row['module'] not in latest or row['stamp'] > latest[row['module']]['stamp']:
            latest[row['module']] = row
    return list(latest.values())
