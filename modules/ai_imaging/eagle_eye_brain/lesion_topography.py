"""Indication-independent distribution pages for white-matter lesion reports."""
from html import escape


def topography_pages(result):
    if result.get('clinical_context', {}).get('primary_disease') == 'ms':
        return []  # The MS pages include this distribution and their criteria scope.
    data = result.get('lesion_topography', {})
    page = '<h1>White-matter lesion anatomical distribution</h1>'
    if not data.get('regions'):
        return [page + '<p>Not assessed: anatomical distribution is unavailable for this result. '
                'This is not evidence of absent lesions.</p>']
    page += ('<table width="100%"><tr><th>Region</th><th>Candidate count</th>'
             '<th>Volume mm3</th></tr>')
    for row in data['regions']:
        values = [str(row['count']), f"{row['volume_mm3']:.1f}"] if row['available'] else ['Not assessed', '-']
        page += '<tr><td align="left">' + escape(row['region']) + '</td>'
        page += ''.join('<td align="center">' + v + '</td>' for v in values) + '</tr>'
    page += ('</table><p>Categories overlap and must not be added together. Counts describe '
             'connected candidate components, not confirmed lesions. Periventricular and '
             'juxtacortical contacts use white-matter-side voxel-face adjacency after registration; '
             'boundary and registration review is required. An unavailable callosal label is not '
             'a negative finding. Distribution alone does not determine MS or vascular disease.</p>')
    return [page]
