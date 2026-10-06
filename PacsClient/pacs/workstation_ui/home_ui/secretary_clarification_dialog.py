"""Display bounded server questions and replan the selected meaning on a worker."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QLineEdit
from modules.ai_imaging.eagle_eye_remote.secretary.clarification import validate_clarification



def question_from_result(result):
    if result.get('error_code') != 'NEEDS_CLARIFICATION':
        return None
    data=result.get('data') or {}
    if data.get('clarification'):
        return validate_clarification(data['clarification'])
    question=str(result.get('message') or data.get('reason') or '').strip()
    return _display_question({'question':question, 'options':[]})


def _display_question(value):
    if isinstance(value,dict) and set(value)=={'question','options'} and value['options']==[]:
        question=value['question']
        if isinstance(question,str) and question.strip() and len(question)<=2000:
            return {'question':question,'options':[]}
        raise ValueError('Invalid clarification question.')
    return validate_clarification(value)


def clarification_reply(payload, clarification, answer):
    value=_display_question(clarification)
    if not isinstance(answer,str) or not answer.strip() or len(answer)>2000:
        raise ValueError('Enter a clarification answer.')
    # Replan the original request plus explicit answer, not a guessed action.
    result={k:v for k,v in payload.items() if k not in (
        '_preplanned','_confirmation_response','_defer_execution_repair','modules')}
    result['text']=json.dumps({'original_request':payload['text'],
        'clarification_question':value['question'], 'user_answer':answer},ensure_ascii=False)
    return result


class SecretaryClarificationDialog(QDialog):
    def __init__(self, clarification, parent=None):
        super().__init__(parent)
        value=_display_question(clarification)
        self.answer=None
        self.setWindowTitle('EchoMind Secretary - Clarification')
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setModal(True)
        self.setMinimumWidth(320)
        self.setMaximumWidth(480)
        self.setStyleSheet('QDialog { background: #0d1824; color: #dbeaf6; } '
            'QLabel { color: #dbeaf6; } QPushButton, QLineEdit { '
            'background: #1a3244; color: #dbeaf6; border: 1px solid #35566a; '
            'border-radius: 6px; padding: 8px; }')
        layout=QVBoxLayout(self)
        label=QLabel(value['question']); label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True); layout.addWidget(label)
        for option in value['options']:
            button=QPushButton(option['label'])
            button.clicked.connect(lambda checked=False, text=option['label']: self.choose(text))
            layout.addWidget(button)
        self.custom=QLineEdit(); self.custom.setPlaceholderText('Or explain what you mean...')
        self.custom.setMaxLength(2000); layout.addWidget(self.custom)
        submit=QPushButton('Send answer'); submit.setEnabled(False)
        self.custom.textChanged.connect(lambda text: submit.setEnabled(bool(text.strip())))
        submit.clicked.connect(lambda: self.choose(self.custom.text().strip()))
        self.custom.returnPressed.connect(lambda: self.choose(self.custom.text().strip()) if self.custom.text().strip() else None)
        layout.addWidget(submit)
        cancel=QPushButton('Cancel'); cancel.clicked.connect(self.reject); layout.addWidget(cancel)

    def choose(self, answer):
        self.answer=answer
        self.accept()
