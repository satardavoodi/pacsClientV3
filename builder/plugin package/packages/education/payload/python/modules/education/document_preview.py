"""Bounded local document reads, dispatched away from the Qt GUI thread."""
import codecs
import locale
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

TEXT_SUFFIXES = {'.txt', '.md', '.csv', '.tsv', '.log', '.json', '.xml'}
MAX_TEXT_BYTES = 2 * 1024 * 1024


def read_text_preview(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_TEXT_BYTES + 1)
    truncated = len(raw) > MAX_TEXT_BYTES
    raw = raw[:MAX_TEXT_BYTES]
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = raw.decode('utf-16', errors='replace')
    else:
        try:
            text = codecs.getincrementaldecoder('utf-8-sig')().decode(raw, final=not truncated)
        except UnicodeDecodeError:
            text = raw.decode(locale.getencoding(), errors='replace')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if '\x00' in text:
        raise ValueError('This file is not a supported text document.')
    if truncated:
        text += '\n\n[Preview limited to 2 MiB. Open the original file for the complete text.]'
    return text


class _Result(QObject):
    ready = Signal(int, dict)


class TextPreviewTask(QRunnable):
    def __init__(self, path, generation):
        super().__init__()
        self.path = path
        self.generation = generation
        self.signals = _Result()

    def run(self):
        try:
            result = {'path': self.path, 'name': Path(self.path).name,
                      'text': read_text_preview(self.path)}
        except Exception:
            result = {'path': self.path, 'error': 'The text file could not be read. Open the original file to check its encoding or contents.'}
        self.signals.ready.emit(self.generation, result)


def start_text_preview(path, generation, receiver):
    task = TextPreviewTask(path, generation)
    task.signals.ready.connect(receiver)
    QThreadPool.globalInstance().start(task)


class PresentationPreviewTask(QRunnable):
    def __init__(self, path, generation):
        super().__init__()
        self.path = path
        self.generation = generation
        self.signals = _Result()

    def run(self):
        try:
            from PacsClient.utils.config import EDUCATION_STORAGE_PATH
            from modules.education.presentation_conversion import presentation_pdf
            pdf = presentation_pdf(self.path, Path(EDUCATION_STORAGE_PATH) / "presentation_previews")
            result = {"path": self.path, "pdf": pdf}
        except ValueError as exc:
            result = {"path": self.path, "error": str(exc)}
        except Exception:
            result = {"path": self.path, "error": "The presentation preview could not be created. Check the source file and available disk space."}
        self.signals.ready.emit(self.generation, result)


_presentation_pool = None


def start_presentation_preview(path, generation, receiver):
    global _presentation_pool
    if _presentation_pool is None:
        _presentation_pool = QThreadPool()
        _presentation_pool.setMaxThreadCount(2)
    task = PresentationPreviewTask(path, generation)
    task.signals.ready.connect(receiver)
    _presentation_pool.start(task)
