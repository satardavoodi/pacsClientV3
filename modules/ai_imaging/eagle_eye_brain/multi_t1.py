"""Same-study independent T1 consistency measurements; never fuse volumes."""
import csv
import json
from pathlib import Path

from .contracts import BrainError


def compare_volumes(primary, other):
    a = {r['structure']: r['volume_cm3'] for r in primary['posterior_rows']}
    b = {r['structure']: r['volume_cm3'] for r in other['posterior_rows']}
    ai, bi = a.get('total intracranial'), b.get('total intracranial')
    return [dict(structure=k, primary_cm3=a[k], supplementary_cm3=b.get(k),
                 difference_percent=100 * (b[k] - a[k]) / a[k] if a[k] and k in b else None,
                 primary_icv_percent=100 * a[k] / ai if ai else None,
                 supplementary_icv_percent=100 * b[k] / bi if bi and k in b else None)
            for k in a]


def run_multi_t1(source, study_uid, series_uid, *, root, supplementary=(), **kwargs):
    from .patient_context import dicom_context, require_same_examination
    from .study_workflow import run_study_analysis
    if len(supplementary) > 2:
        raise BrainError('Choose at most two supplementary T1 series.')
    primary_context = dicom_context(source)
    seen = {series_uid}
    for row in supplementary:
        context = dicom_context(row['path'])
        if (row['series_uid'] in seen or context.get('study_uid') != study_uid
                or context.get('series_uid') != row['series_uid']):
            raise BrainError('Supplementary T1 inputs must be distinct series from this examination.')
        require_same_examination(primary_context, context)
        seen.add(row['series_uid'])
    progress = kwargs.get('progress') or (lambda message: None)
    def run(path, uid, index, options):
        options = dict(options)
        options['progress'] = lambda message: progress(f'T1 {index}/{1 + len(supplementary)} | {message}')
        return run_study_analysis(path, study_uid, uid, root=root, **options)
    primary = run(source, series_uid, 1, kwargs)
    if not supplementary:
        return primary
    directory = Path(primary['artifact_directory'])
    record = {'status': 'running', 'interpretation': 'Independent measurements; acquisition independence unverified. No fusion or accuracy claim.', 'comparisons': []}
    record_file = directory / 't1-consistency.json'
    options = {k: v for k, v in kwargs.items() if k not in ('flair_source', 'flair_series_uid')}
    try:
        for index, row in enumerate(supplementary, 2):
            if kwargs.get('cancel') is not None and kwargs['cancel'].is_set():
                raise BrainError('Supplementary analysis cancelled; primary results were retained.')
            other = run(row['path'], row['series_uid'], index, options)
            comparison = {'input': index, 'artifact_directory': other['artifact_directory'],
                          'qc_scores': other.get('qc_scores', {}),
                          'rows': compare_volumes(primary, other)}
            record['comparisons'].append(comparison)
            with (directory / f't1-comparison-{index}.csv').open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(comparison['rows'][0]))
                writer.writeheader(); writer.writerows(comparison['rows'])
        write_comparison_pdf(primary, record, directory / 't1-consistency.pdf')
        record['status'] = 'completed'
    except Exception as exc:
        record['status'] = 'incomplete'
        raise BrainError('Supplementary T1 review did not complete. The primary report and completed jobs remain in User Data; no combined result was published.') from exc
    finally:
        record_file.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
    primary['t1_consistency_pdf'] = str(directory / 't1-consistency.pdf')
    primary['t1_input_count'] = 1 + len(supplementary)
    return primary


def write_comparison_pdf(primary, record, destination):
    from .organized_report import PAGE, _table, _num, write_paged_pdf
    from .report import report_html
    # Reuse the original report's identity/style metadata and running furniture.
    head = report_html(primary).split('<body>', 1)[0]
    pages = []
    for comparison in record['comparisons']:
        for offset in range(0, len(comparison['rows']), 12):
            rows = comparison['rows'][offset:offset + 12]
            pages.append(f"<h1>T1 consistency review | Input {comparison['input']}</h1>"
                         '<p>Primary report volumes remain unchanged. Differences do not establish error or disease. '
                         'Acquisition independence is unverified; reformats are not independent repeats.</p>' +
                         _table(['Region', 'Primary cm3', 'Other cm3', 'Change %', 'Primary % ICV', 'Other % ICV'],
                                [[r['structure'], *[_num(r[k]) for k in ('primary_cm3', 'supplementary_cm3',
                                  'difference_percent', 'primary_icv_percent', 'supplementary_icv_percent')]] for r in rows],
                                [30, 14, 14, 14, 14, 14]))
    write_paged_pdf(head + '<body>' + PAGE.join(pages) + '</body></html>', destination)
