"""Measurement-specific review tasks; proposals never imply reader approval."""
import hashlib
import json

from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
                              QTableWidget, QTableWidgetItem, QHeaderView)

from .geometry import CORNERS, LEVELS, measure_curve, suggest_apex
from .review_workflow import required_points, curve_is_reviewed


def review_tasks(view):
    image = view.get('image')
    if image is None:
        return []
    points, markers = view['points'], view.get('markers', {})
    approvals = view.get('provenance', {}).get('guided_reviews', {})
    tasks = []

    def add(kind, row, title, available, prompt, level='', evidence=None, confirmed=False):
        key = f'{row}:{kind}'
        payload = [image['identity'], image['source_sha256'], image['spacing'],
                   image['calibrated'], view.get('positive_image_right'),
                   view.get('acquisition_confirmed'), evidence]
        signature = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        ready = available and (confirmed or approvals.get(key) == signature)
        tasks.append(dict(key=key, kind=kind, row=row, title=title, level=level,
                          available=available, signature=signature, prompt=prompt,
                          status='Ready' if ready else 'Needs review' if available else 'Missing data'))

    if not view.get('curves'):
        add('curve', -1, 'Add a curve', False,
            'Assign the useful upper/lower bodies to levels. Review the proposed endplates and add your curve; whole-spine numbering is optional.')
    for row, spec in enumerate(view.get('curves', [])):
        prefix = f'Curve {row+1}: '
        try:
            used = required_points(points, spec)
            measure_curve(points, spec['upper'], spec['lower'],
                          lower_endplate=spec.get('lower_endplate', 'inferior'), spacing=image['spacing'])
            valid = True
        except (KeyError, ValueError, TypeError):
            used = {}; valid = False
        add('cobb', row, prefix+spec['name'], valid,
            'Review only the selected upper and lower endplates. Verify acquisition before confirming.',
            spec['upper'], [used, spec['upper'], spec['lower'], spec.get('lower_endplate')],
            curve_is_reviewed(view, spec))
        if image['projection'] != 'coronal':
            continue
        apex = spec.get('apex', '')
        levels = apex.split('/') if apex else []
        valid_apex = 1 <= len(levels) <= 2 and all(k in LEVELS and
            LEVELS.index(spec['upper']) < LEVELS.index(k) < LEVELS.index(spec['lower']) for k in levels)
        if valid_apex and len(levels) == 2:
            valid_apex = LEVELS.index(levels[1]) == LEVELS.index(levels[0])+1
        curve_points = {k: v for k,v in points.items() if k in LEVELS and
                        LEVELS.index(spec['upper']) <= LEVELS.index(k) <= LEVELS.index(spec['lower'])}
        add('apex', row, prefix+'Apex', valid_apex,
            'Review the proposed apex, or select the body/disc apex and update this curve.',
            levels[0] if levels else '', [apex, curve_points, spec['upper'], spec['lower']])
        rotation = next((r for r in view.get('rotations', []) if r['level'] == apex), None)
        add('rotation', row, prefix+'Apical rotation', valid_apex and len(levels) == 1 and rotation is not None,
            'Select a vertebral apex. Mark visible pedicles only and record a reader Nash-Moe grade; automatic pedicle detection is not available.',
            levels[0] if levels else '', [apex, points.get(apex), view.get('pedicles', {}).get(apex), rotation])
        for kind in ('neutral', 'stable', 'last_touched'):
            level = spec.get(kind, '')
            body = points.get(level, {})
            available = bool(level) and set(CORNERS).issubset(body)
            if kind != 'neutral':
                available = available and 'Sacral center' in markers
                prompt = 'Place the S1 center if missing, review CSVL against the available body outlines, and update the selected vertebra.'
                evidence = [level, points, markers.get('Sacral center'), spec['lower']]
            else:
                zero = next((r for r in view.get('rotations', []) if r['level'] == level and r['grade'] == 0), None)
                available = (available and zero is not None and bool(levels)
                             and levels[0] in LEVELS and LEVELS.index(level) > LEVELS.index(levels[0]))
                prompt = 'Review pedicle symmetry below the apex. Record the reader grade at the selected body and update the neutral vertebra.'
                evidence = [level, apex, body, view.get('pedicles', {}).get(level), zero]
            add(kind, row, prefix+kind.replace('_', ' ').title(), bool(available), prompt,
                level, evidence)
    reference = 'Sacral center' if image['projection'] == 'coronal' else 'S1 posterior superior'
    add('balance', -1, 'Coronal balance' if image['projection'] == 'coronal' else 'Sagittal balance',
        all(k in markers for k in ('C7 center', reference)) and image['calibrated'],
        'Place the S1 reference, then C7. Verify patient-plane calibration before reporting millimeters.',
        evidence=[markers, image['calibrated']])
    return tasks


class GuidedReview:
    """Right result list and left task card, sharing the existing editor controls."""
    def __init__(self, editor, left, right):
        self.editor = editor; self.tasks = []
        self.right = right
        self.section_positions = {name: (right.indexOf(toggle), right.indexOf(content))
                                  for name, (toggle, content) in editor.review_sections.items()}
        self.moved_section = None
        self.results = QTableWidget(0, 2)
        self.results.setHorizontalHeaderLabels(['Result', 'Status'])
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results.setSelectionBehavior(QTableWidget.SelectRows)
        self.results.setSelectionMode(QTableWidget.SingleSelection)
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results.setMinimumHeight(190)
        right.insertWidget(0, self.results)
        card = QWidget(); layout = QVBoxLayout(card)
        layout.addWidget(QLabel('Review selected result'))
        self.instruction = QLabel('Assign only the levels needed for your measurements, then add a curve.')
        self.instruction.setWordWrap(True); layout.addWidget(self.instruction)
        self.edit = QPushButton('Complete / edit required data'); layout.addWidget(self.edit)
        self.confirm = QPushButton('Confirm this result'); layout.addWidget(self.confirm)
        next_button = QPushButton('Next item to review'); layout.addWidget(next_button)
        self.context = QVBoxLayout(); layout.addLayout(self.context)
        self.edit.clicked.connect(self.edit_required)
        self.confirm.clicked.connect(self.confirm_result)
        next_button.clicked.connect(self.next_item)
        self.results.itemSelectionChanged.connect(self.select)
        left.insertWidget(0, card)

    def refresh(self):
        selected = self.current()
        key = selected['key'] if selected else None
        self.tasks = review_tasks(self.editor.snapshot())
        self.results.blockSignals(True)
        self.results.setRowCount(len(self.tasks))
        for row, task in enumerate(self.tasks):
            self.results.setItem(row, 0, QTableWidgetItem(task['title']))
            self.results.setItem(row, 1, QTableWidgetItem(task['status']))
        index = next((i for i,t in enumerate(self.tasks) if t['key'] == key), -1)
        if index >= 0: self.results.selectRow(index)
        self.results.blockSignals(False)
        task = self.current()
        self.edit.setEnabled(task is not None)
        self.confirm.setEnabled(bool(task and task['available'] and self.editor.confirm.isChecked()))
        if task: self.instruction.setText(task['prompt'])

    def current(self):
        row = self.results.currentRow()
        return self.tasks[row] if 0 <= row < len(self.tasks) else None

    def select(self):
        task = self.current()
        if task is None: return
        e = self.editor
        self.instruction.setText(task['title']+(' - '+task['level'] if task['level'] else '')+'\n'+task['prompt'])
        e.sam.setVisible(task['kind'] not in ('rotation', 'neutral'))
        self.confirm.setEnabled(task['available'] and e.confirm.isChecked())
        section = ('Pedicles and assisted placement' if task['kind'] in ('rotation', 'neutral')
                   else 'Correct endplates' if task['kind'] in ('cobb', 'balance')
                   else 'Curves and clinical assessment')
        self.show_section(section)
        if task['row'] >= 0: e.table.selectRow(task['row'])
        if task['level'] in LEVELS: e.level.setCurrentText(task['level'])
        if task['kind'] in ('rotation', 'neutral'):
            record = next((r for r in e.rotations if r['level'] == task['level']), None)
            e.grade.setCurrentText(str(record['grade']) if record else 'Not assessed')
            e.direction.setCurrentText(record['direction'] if record else 'none')
        # Existing geometry and viewport are reused; no AI rerun or image copy.
        values = list(e.points.get(task['level'], {}).values())
        if values:
            xs, ys = zip(*values)
            e.canvas.fitInView(QRectF(min(xs)-50, min(ys)-50,
                                     max(xs)-min(xs)+100, max(ys)-min(ys)+100), Qt.KeepAspectRatio)
        self.edit.setEnabled(True)

    def show_section(self, title):
        if self.moved_section:
            name = self.moved_section
            for widget, index in zip(self.editor.review_sections[name], self.section_positions[name]):
                self.context.removeWidget(widget)
                self.right.insertWidget(max(1, index+1), widget)
            self.moved_section = None
        for name, (toggle, _) in self.editor.review_sections.items():
            if name != 'Vertebral numbering': toggle.setChecked(name == title)
        if title in ('Correct endplates', 'Pedicles and assisted placement', 'Acquisition and scale'):
            for widget in self.editor.review_sections[title]:
                self.right.removeWidget(widget); self.context.addWidget(widget)
            self.moved_section = title
            self.editor.naming_scroll.ensureWidgetVisible(self.instruction)
            return
        content = self.editor.review_sections[title][1]
        self.editor.review_scroll.ensureWidgetVisible(content)

    def edit_required(self):
        task = self.current()
        if task is None: return
        e = self.editor; kind = task['kind']
        self.select()
        if kind == 'curve':
            self.show_section('Curves and clinical assessment')
            if len(e.points) >= 2: e._suggest_pair()
            return
        if kind == 'balance' or (kind in ('stable', 'last_touched') and 'Sacral center' not in e.markers):
            reference = 'Sacral center' if e.projection == 'coronal' else 'S1 posterior superior'
            missing = next((k for k in (reference, 'C7 center') if k not in e.markers), None)
            if missing:
                self.show_section('Correct endplates'); e.corner.setCurrentText(missing)
                e.canvas.fit()
            elif not e.calibrated.isChecked(): self.show_section('Acquisition and scale')
            return
        if kind in ('rotation', 'neutral'):
            self.show_section('Pedicles and assisted placement')
            if kind == 'neutral':
                e.review_sections['Curves and clinical assessment'][0].setChecked(True)
                self.suggest_assessment(task)
            return
        self.show_section('Curves and clinical assessment')
        if kind == 'cobb':
            self.show_section('Correct endplates')
            e._edit_required(False)
            e.review_sections['Curves and clinical assessment'][0].setChecked(True)
        elif kind == 'apex' and not e.apex.currentIndex():
            try:
                proposal = suggest_apex(e.points, e.upper.currentText(), e.lower.currentText(), e.image['spacing'])
                if proposal: e.apex.setCurrentText(proposal)
            except (KeyError, ValueError): pass
        elif kind in ('stable', 'last_touched'):
            self.suggest_assessment(task)

    def suggest_assessment(self, task):
        from .assessment import coronal_assessment
        e = self.editor
        try:
            result = coronal_assessment(e.snapshot(), e.curves[task['row']])
            proposal = result.get(task['kind']+'_candidate')
            if proposal and not e.assessment_fields[task['kind']].currentIndex():
                e.assessment_fields[task['kind']].setCurrentText(proposal)
                self.instruction.setText(task['prompt']+' Proposal: '+proposal+
                    '. Based on available levels only; review and Update selected curve to apply.')
        except (KeyError, ValueError): pass

    def confirm_result(self):
        task = self.current()
        if not task or not task['available'] or not self.editor.confirm.isChecked(): return
        e = self.editor
        if task['kind'] == 'cobb':
            e.table.selectRow(task['row']); e._confirm_curve()
        else:
            e._remember_edit()
            e.provenance.setdefault('guided_reviews', {})[task['key']] = task['signature']
            e.invalidate()
        self.next_item()

    def next_item(self):
        self.refresh()
        if not self.tasks:
            self.instruction.setText('Load an image to begin reviewing measurements.')
            return
        start = self.results.currentRow()
        for step in range(1, len(self.tasks)+1):
            index = (start+step) % len(self.tasks)
            if self.tasks[index]['status'] != 'Ready':
                self.results.selectRow(index); self.select(); return
        self.instruction.setText('All available review items are complete.')
