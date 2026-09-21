"""Immutable Qt 5/6 numeric-control styling shared by independent runtimes.

No Qt imports, scene access, filesystem writes or native step behavior changes.
Explicit SVG chevrons avoid OS-dependent native arrow rendering.
"""

from pathlib import Path


def numeric_control_style(prefix=''):
    def selectors(suffix=''):
        return ', '.join(prefix + name + suffix for name in ('QSpinBox', 'QDoubleSpinBox'))

    rules = [selectors() + ''' { background:#142737; color:#eff7ff;
        border:1px solid #52758e; border-radius:4px;
        padding:3px 30px 3px 6px; min-height:24px; }
    ''', selectors(':focus') + ' { border-color:#79d8ec; }',
        selectors(':disabled') + ' { color:#8d9dab; background:#202d38; }']
    for direction, position, edge in (('up', 'top', 'bottom'), ('down', 'bottom', 'top')):
        button = '::' + direction + '-button'
        arrow = '::' + direction + '-arrow'
        rules += [selectors(button) + ''' { subcontrol-origin:border;
            subcontrol-position:''' + position + ''' right; width:26px;
            border:1px solid #52758e; background:#29475d; margin:1px; }
        ''', selectors(button + ':hover') + ' { background:#386980; border-color:#79d8ec; }',
            selectors(button + ':pressed') + ' { background:#17516b; }',
            selectors(button + ':disabled') + ' { background:#263641; border-color:#405465; }',
            selectors(arrow) + ' { image:url("' + (Path(__file__).resolve().parent / 'icons' / ('numeric-' + direction + '.svg')).as_posix() + '"); width:12px; height:12px; border:0; }',
            selectors(arrow + ':disabled') + ' { image:url("' + (Path(__file__).resolve().parent / 'icons' / ('numeric-' + direction + '-disabled.svg')).as_posix() + '"); }',
            selectors(arrow + ':off') + ' { image:url("' + (Path(__file__).resolve().parent / 'icons' / ('numeric-' + direction + '-disabled.svg')).as_posix() + '"); }']
    return '\n'.join(rules)
