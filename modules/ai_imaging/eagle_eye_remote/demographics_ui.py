"""Client GUI-thread confirmation for a single pending Bone Age worker."""
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import (QInputDialog, QDialog, QFormLayout, QLineEdit,
                              QComboBox, QLabel, QDialogButtonBox)
from .demographics import normalize


class DemographicReviewDialog(QDialog):
    def __init__(self, parent, draft):
        super().__init__(parent)
        self.draft = draft
        self.setWindowTitle('Bone Age: Confirm Patient Information')
        self.setMinimumWidth(460)
        layout = QFormLayout(self)
        info = QLabel('Review these details before analysis. Fill every missing field.\n'
                      'Age must be the age at the time of imaging.')
        info.setWordWrap(True)
        layout.addRow(info)
        self.name = QLineEdit(draft.get('name') or '')
        self.sex = QComboBox()
        self.sex.addItems(['Select sex', 'Male', 'Female'])
        self.sex.setCurrentIndex({'M': 1, 'F': 2}.get(draft.get('sex'), 0))
        age = draft.get('chronological_age_months')
        self.years = QLineEdit('' if age is None else str(age // 12))
        self.months = QLineEdit('' if age is None else str(age % 12))
        self.years.setPlaceholderText('Completed years')
        self.months.setPlaceholderText('Additional months: 0 to 11')
        layout.addRow('Patient name', self.name)
        layout.addRow('Sex used for analysis', self.sex)
        layout.addRow('Age at imaging: years', self.years)
        layout.addRow('Age at imaging: months', self.months)
        birth_label = draft.get('birth_date') or 'Not available'
        if draft.get('birth_calendar') == 'Jalali':
            birth_label += ' (Gregorian; converted from Reception Jalali date)'
        layout.addRow('Date of birth', QLabel(birth_label))
        layout.addRow('Imaging date', QLabel(draft.get('study_date') or 'Not available'))
        layout.addRow('Sources', QLabel(', '.join(f'{k}: {v}' for k, v in draft.get('sources', {}).items())))
        self.error = QLabel()
        layout.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Confirm and Analyze')
        buttons.accepted.connect(self.confirm)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        self.confirmed = None

    def confirm(self):
        from .demographics import validate_review
        try:
            years, months = int(self.years.text()), int(self.months.text())
            if not 0 <= years <= 20 or not 0 <= months <= 11:
                raise ValueError('Enter years from 0 to 20 and months from 0 to 11.')
            value = dict(self.draft, name=self.name.text(), sex=normalize(self.sex.currentText()),
                         chronological_age_months=years * 12 + months)
            value['age_source'] = ('birth_date' if self.draft.get('birth_date') and self.draft.get('study_date')
                                   and value['chronological_age_months'] ==
                                   self.draft.get('chronological_age_months') else 'physician')
            if value['age_source'] == 'physician':
                value['birth_date'] = ''
                value['birth_calendar'] = None
            value['edited_fields'] = [key for key in ('name', 'sex', 'chronological_age_months')
                                      if value.get(key) != self.draft.get(key)]
            from datetime import datetime, timezone
            value['confirmed_at'] = datetime.now(timezone.utc).isoformat()
            self.confirmed = validate_review(value, self.draft['study_uid'], self.draft['patient_id'])
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class SexConfirmation(QObject):
    def __init__(self, parent, worker, current_identity, timer=None):
        super().__init__(parent)
        self.worker = worker
        self.current_identity = current_identity
        self.timer = timer

    @Slot()
    def request(self):
        worker = self.worker
        if self.timer:
            self.timer.stop()
        expected = (worker.study_uid, str(worker.metadata_context.get('patient_id') or ''))
        if worker.canceled or self.current_identity() != expected or not expected[1]:
            worker.confirm_sex(None)
            return
        if hasattr(worker, 'demographic_draft'):
            dialog = DemographicReviewDialog(self.parent(), worker.demographic_draft)
            accepted = dialog.exec() == QDialog.Accepted
            value = dialog.confirmed if accepted and not worker.canceled and self.current_identity() == expected else None
            worker.confirm_demographics(value)
            if value and self.timer:
                self.timer.start(60000)
            return
        value, accepted = QInputDialog.getItem(
            self.parent(), 'Bone Age: Confirm Patient Sex',
            'DICOM and Reception do not provide a verified sex for this study.\n'
            'Confirm the patient sex required by the Bone Age model.\n'
            'The original DICOM will remain unchanged.',
            ['Select patient sex', 'Male', 'Female'], 0, False)
        # A case switch while the dialog was open must invalidate the answer.
        sex = normalize(value) if accepted and not worker.canceled and self.current_identity() == expected else None
        worker.confirm_sex(sex)
        if sex and self.timer:
            self.timer.start(60000)
