"""Descriptive regional reference chart and physician dementia-pattern checklist.

Published interval comparisons are not trained disease classifiers. A median is
not a mean, and a position relative to it is not a percentile or a Z-score.
"""
import base64
from html import escape
import math


FOCUS = (
    ('Hippocampus', 'hippocampus'), ('Amygdala', 'amygdala'),
    ('Entorhinal cortex', 'entorhinal'), ('Parahippocampal cortex', 'parahippocampal'),
    ('Frontal pole', 'frontalpole'), ('Precuneus', 'precuneus'), ('Cuneus', 'cuneus'),
)

SOURCES = (
    ('Scheltens et al. (1992), medial temporal atrophy visual assessment', 'https://doi.org/10.1136/jnnp.55.10.967'),
    ("Jack et al. (2024), revised Alzheimer's disease diagnostic criteria", 'https://doi.org/10.1002/alz.13859'),
    ('Rascovsky et al. (2011), behavioural variant frontotemporal dementia criteria', 'https://doi.org/10.1093/brain/awr179'),
    ('Gorno-Tempini et al. (2011), primary progressive aphasia variants', 'https://doi.org/10.1212/WNL.0b013e31821103e6'),
    ('Crutch et al. (2017), posterior cortical atrophy consensus', 'https://doi.org/10.1016/j.jalz.2017.01.014'),
)


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def chart_rows(result):
    """Use matching saved measurements; never fabricate bounds or sum endpoints."""
    reference = result.get('normative', {})
    if reference.get('reference_id') != 'volbrain' or reference.get('status') != 'published_intervals':
        return []
    values = {r['structure']: r.get('volume_cm3') for r in result.get('posterior_rows', [])}
    references = {r['structure']: r for r in reference.get('rows', [])}
    rows = []
    for title, name in FOCUS:
        for side, prefix in (('left', 'lh'), ('right', 'rh')):
            key = side + ' ' + name if name in ('hippocampus', 'amygdala') else f'ctx-{prefix}-{name}'
            row = references.get(key, {})
            measured, low, median, high = (row.get(k) for k in ('observed_cm3', 'lower_cm3', 'median_cm3', 'upper_cm3'))
            if (not all(_finite(v) for v in (measured, low, median, high)) or
                    not 0 <= low <= median <= high or median == 0 or
                    not _finite(values.get(key)) or
                    not math.isclose(measured, values[key], rel_tol=1e-8, abs_tol=1e-8)):
                continue
            analogue = row.get('mapping_status') == 'anatomical_analogue' or key.startswith('ctx-')
            rows.append(dict(structure=key, label=title + (' L' if side == 'left' else ' R'),
                measured_cm3=measured, lower_cm3=low, median_cm3=median, upper_cm3=high,
                observed_relative=100 * measured / median, lower_relative=100 * low / median,
                upper_relative=100 * high / median, analogue=analogue,
                position='Anatomical analogue only' if analogue else
                         'Below interval' if measured < low else 'Above interval' if measured > high else 'Within interval'))
    return rows


def chart_png(rows):
    """Paint an exportable PNG using existing Qt, on the report worker's QGui app."""
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter, QPen
    if not rows or QGuiApplication.instance() is None:
        return None
    if not QFontDatabase.families():
        import os
        from pathlib import Path
        fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for name in ('arial.ttf', 'arialbd.ttf'):
            if (fonts / name).is_file():
                QFontDatabase.addApplicationFont(str(fonts / name))
        if not QFontDatabase.families():
            raise ValueError('No fonts are available for the regional reference chart.')
    width, height = 1200, 125 + 38 * len(rows)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(QFont('Arial', 16))
    left, right = 340, 1060
    maximum = max(150., max(r['upper_relative'] for r in rows) * 1.1,
                  max(r['observed_relative'] for r in rows) * 1.1)
    def x(value): return left + (right - left) * value / maximum
    painter.setPen(QColor('#243b53'))
    painter.drawText(15, 28, 'Regional volumes relative to the published age/sex median')
    painter.setFont(QFont('Arial', 14))
    painter.drawText(15, 50, 'Band: published 95% interval. Dot: measured volume. *: anatomical analogue only.')
    painter.setPen(QPen(QColor('#94a3b8'), 1, Qt.PenStyle.DashLine))
    painter.drawLine(int(x(100)), 67, int(x(100)), height - 43)
    for i, row in enumerate(rows):
        y = 85 + 38 * i
        painter.setPen(QColor('#243b53'))
        painter.drawText(15, y + 5, row['label'] + (' *' if row['analogue'] else ''))
        painter.setPen(QPen(QColor('#cbd5e1'), 1))
        painter.drawLine(left, y, right, y)
        painter.setPen(QPen(QColor('#c7d2fe' if row['analogue'] else '#bfdbfe'), 12))
        painter.drawLine(int(x(row['lower_relative'])), y, int(x(row['upper_relative'])), y)
        color = '#6d28d9' if row['analogue'] else '#b45309' if row['position'] != 'Within interval' else '#0369a1'
        painter.setPen(QPen(QColor(color), 2)); painter.setBrush(QColor(color))
        painter.drawEllipse(int(x(row['observed_relative'])) - 5, y - 5, 10, 10)
        painter.drawText(1080, y + 5, f"{row['observed_relative']:.1f}%")
    painter.setPen(QColor('#243b53'))
    painter.drawText(left, height - 18, '0')
    painter.drawText(int(x(100)) - 40, height - 18, 'Median = 100%')
    painter.drawText(right - 70, height - 18, f'{maximum:.0f}%')
    painter.end()
    buffer = QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise RuntimeError('Regional reference chart could not be encoded.')
    return base64.b64encode(bytes(buffer.data())).decode('ascii')


def pages(result):
    from .organized_report import _table
    rows = chart_rows(result)
    reference = result.get('normative', {})
    demo = reference.get('demographics', {})
    age = demo.get('age_years')
    context = f'{age:.2f} years' if _finite(age) else 'age unavailable'
    chart = chart_png(rows)
    first = '<h1>Regional volume reference profile</h1><p>Age at examination: ' + context + '; recorded sex: ' + escape(demo.get('sex', 'unknown')) + '.</p>'
    first += ("<p>Each region is scaled to its own published median (100%). This is <b>not a percentile</b>, "
              "not a probability of disease and not an amount of tissue lost. Cross-method comparisons require boundary review.</p>")
    first += '<p>Blue: within interval. Amber: outside comparison interval, requiring measurement review; not confirmed pathology. Purple: anatomical analogue only.</p>'
    if chart:
        first += '<img width="650" src="data:image/png;base64,' + chart + '"/>'
    elif not rows:
        first += '<p>Applicable regional reference unavailable. No values are substituted.</p>'
    first += _table(['Region', 'Measured cm3', '95% interval cm3', 'Median cm3', 'Comparison'],
                    [[r['label'], f"{r['measured_cm3']:.3f}", f"{r['lower_cm3']:.3f} - {r['upper_cm3']:.3f}",
                      f"{r['median_cm3']:.3f}", r['position']] for r in rows], [27, 14, 23, 14, 22])
    first += '<p>* Cortical anatomical analogue: display comparison only. Atlas boundaries differ; no atrophy flag is assigned. Exact centiles and Z/T scores cannot be recovered from interval endpoints and a median.</p>'
    patterns = [
        ('Medial temporal / AD-related review', 'Hippocampus, entorhinal and parahippocampal cortex; also review posterior association cortex.', 'MTA visual grading requires hippocampal height, choroid fissure and temporal-horn assessment on coronal images. Volume alone cannot supply an MTA score.'),
        ('Frontotemporal pattern review', 'Frontal and anterior temporal cortex, including orbitofrontal and anterior cingulate regions.', 'Behavioural variant FTD requires a compatible progressive clinical syndrome; imaging is supportive. Complete lobar reference limits are unavailable.'),
        ('Language-predominant pattern review', 'Anterior temporal cortex for semantic variant; left posterior fronto-insular for nonfluent variant; left temporoparietal for logopenic variant.', 'Imaging-supported PPA requires the relevant language phenotype. A regional low volume is not sufficient.'),
        ('Posterior cortical pattern review', 'Occipito-parietal and occipito-temporal cortex; assess asymmetry and relative preservation elsewhere.', 'Posterior cortical atrophy is a clinical-radiological syndrome. Review visual and posterior cognitive symptoms; complete matched regional reference coverage is unavailable.'),
    ]
    second = '<h1>Atrophy pattern review</h1><h2>Findings in this examination</h2>'
    observed = [r for r in rows if not r['analogue']]
    if observed:
        second += '<ul>' + ''.join('<li>' + escape(r['label']) + ': ' +
            f"{r['measured_cm3']:.3f} cm3; " + escape(r['position'].lower()) +
            f" ({r['lower_cm3']:.3f} - {r['upper_cm3']:.3f} cm3).</li>" for r in observed) + '</ul>'
        hips = [r for r in observed if r['structure'].endswith(' hippocampus')]
        if len(hips) == 2:
            low_count = sum(r['position'] == 'Below interval' for r in hips)
            second += '<p>Bilateral hippocampal comparison: ' + str(low_count) + ' of 2 sides below the published interval. '
            second += 'This is a cross-method interval comparison; it does not grade atrophy or establish its cause. '
            second += 'Within-interval volume does not exclude a visually apparent or disease-related abnormality.</p>'
    else:
        second += '<p>Applicable hippocampal/amygdala reference comparison unavailable; no low-volume conclusion is assigned.</p>'
    analogue_count = sum(r['analogue'] for r in rows)
    second += '<p>Cortical reference coverage in the profile: ' + str(analogue_count) + ' anatomical analogue comparisons. '
    second += 'Matched cortical/whole-lobe limits and thickness are unavailable; frontotemporal, language-predominant and posterior patterns remain unclassified.</p>'
    second += '<h2>Clinical pattern checklist</h2><p>These are physician review targets derived from published criteria, not machine-assigned diagnoses. The current volume profile <b>cannot establish or exclude</b> these syndromes. Alzheimer\'s disease probability is not calculated.</p>'
    second += _table(['Review target', 'Anatomical distribution', 'Interpretation requirement'], patterns, [25, 38, 37], numeric=False)
    second += '<p>No cortical thickness or automated MTA/posterior-atrophy grade is measured. Clinical history, image review and disease-specific biomarkers determine interpretation. Missing references are not evidence of normality.</p>'
    second += '<h2>Scientific criteria</h2><ul>' + ''.join('<li><a href="' + url + '">' + escape(title) + '</a></li>' for title, url in SOURCES) + '</ul>'
    return [first, second]
