"""Study-owned saved brain reports; disk discovery never runs on the GUI thread."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QSize, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QFrame


class SavedBrainResultsWidget(QWidget):
    def __init__(self, parent=None, *, study_uid, open_result):
        super().__init__(parent)
        self.study_uid = study_uid
        self._open_result = open_result
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='BrainResultHistory')
        executor = self._executor
        self.destroyed.connect(lambda: executor.shutdown(wait=False, cancel_futures=True))
        self._future = None
        self._kind = 'discover'
        self._open_error = False
        self._pending_open = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        card = QFrame(self)
        card.setMaximumWidth(1080)
        card.setObjectName('savedBrainCard')
        card.setStyleSheet('QFrame#savedBrainCard {border:1px solid #334155; border-radius:10px;}'
                          'QLabel {border:0; padding:0;}'
                          'QListWidget {font-size:14px; border:1px solid #334155; border-radius:6px;}'
                          'QListWidget::item {padding:10px;}'
                          'QPushButton {padding:8px 16px;}')
        outer.addWidget(card, 0, Qt.AlignTop | Qt.AlignLeft)
        outer.addStretch(1)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel('Saved Eagle Eye brain results')
        title.setStyleSheet('font-size:20px; font-weight:bold; color:#60a5fa;')
        layout.addWidget(title)
        hint = QLabel('Choose a saved result to read its PDF or review the segmentation.'); hint.setWordWrap(True)
        layout.addWidget(hint)
        self.results = QListWidget()
        self.results.setObjectName('savedBrainResults')
        self.results.setMinimumHeight(230)
        self.results.setMaximumHeight(320)
        layout.addWidget(self.results)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton('Refresh results')
        self.review_button = QPushButton('Review / correct segmentation')
        self.pdf_button = QPushButton('Open PDF')
        self.pdf_button.setEnabled(False)
        self.pdf_button.clicked.connect(lambda: self.open_selected(kind='pdf'))
        self.review_button.setStyleSheet('background:#2563a6; color:white; font-weight:bold; border-radius:6px;')
        for button in (self.review_button, self.pdf_button, self.refresh_button):
            button.setMaximumWidth(320)
            button.setMinimumHeight(38)
        self.review_button.setEnabled(False)
        self.refresh_button.clicked.connect(self.refresh)
        self.review_button.clicked.connect(self.open_selected)
        self.results.itemDoubleClicked.connect(lambda item: self.open_selected())
        self.results.currentRowChanged.connect(lambda row: self.review_button.setEnabled(row >= 0 and self._future is None))
        actions.addWidget(self.pdf_button); actions.addWidget(self.review_button)
        actions.addStretch(1); actions.addWidget(self.refresh_button)
        layout.addLayout(actions)
        self.count = QLabel(); layout.addWidget(self.count)
        self.status = QLabel('Looking for saved results...')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.timer = QTimer(self); self.timer.setInterval(150); self.timer.timeout.connect(self._poll)
        self.refresh_timer = QTimer(self); self.refresh_timer.setInterval(10000)
        self.refresh_timer.timeout.connect(lambda: self.refresh(automatic=True) if self.isVisible() else None)
        self.refresh_timer.start()
        QTimer.singleShot(0, self.refresh)

    def _root(self):
        from PacsClient.utils.data_paths import AI_DIR
        return Path(AI_DIR) / 'eagle_eye'

    def _submit(self, kind, function, *args):
        if self._future is not None:
            return
        self._kind = kind
        self.refresh_button.setEnabled(False)
        if kind != 'discover':
            self.review_button.setEnabled(False)
            self.pdf_button.setEnabled(False)
        self._future = self._executor.submit(function, *args)
        self.timer.start()

    def refresh(self, checked=False, *, automatic=False):
        if not automatic: self._open_error = False
        from .saved_results import discover_results
        self._submit('discover', discover_results, self._root(), self.study_uid)

    def open_selected(self, checked=False, *, kind='open'):
        item = self.results.currentItem()
        if item is None: return
        path = item.data(Qt.UserRole)['path']
        if self._future is not None:
            if self._kind == 'discover': self._pending_open = (kind, path)
            return
        self._load_selected(kind, path)

    def _load_selected(self, kind, path):
        from .saved_results import load_result
        self._open_error = False
        self.status.setText('Opening the saved result...')
        self._submit(kind, load_result, self._root(), self.study_uid, path)

    def _poll(self):
        if self._future is None or not self._future.done():
            return
        future, self._future = self._future, None
        self.timer.stop(); self.refresh_button.setEnabled(True)
        try:
            result = future.result()
            if self._kind == 'pdf':
                if not result.get('pdf_available'):
                    raise ValueError('PDF is unavailable.')
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(result['artifact_directory']) / 'report.pdf'))):
                    raise RuntimeError('PDF viewer could not be opened.')
                self.status.setText('PDF opened in your default viewer.')
            elif self._kind == 'open':
                self._open_result(result)
                self.status.setText('Saved result opened. Use its PDF or manual correction controls.')
            else:
                current = self.results.currentItem()
                selected = current.data(Qt.UserRole)['path'] if current else None
                self.results.clear()
                for row in result:
                    title = 'White-matter lesions' if row['kind'] == 'lesion' else 'Brain volumetry'
                    title += '  •  Manual revision' if row['revision'] else '  •  Original analysis'
                    title += ' | ' + datetime.fromtimestamp(row['modified']).strftime('%Y-%m-%d %H:%M')
                    item = QListWidgetItem(title); item.setData(Qt.UserRole, row)
                    item.setSizeHint(QSize(0, 48))
                    self.results.addItem(item)
                    if row['path'] == selected: self.results.setCurrentItem(item)
                if result and self.results.currentRow() < 0: self.results.setCurrentRow(0)
                self.count.setText(f'{len(result)} saved results for this examination.')
                if not self._open_error:
                    self.status.setText('Select a result above.' if result else 'No saved brain results found for this examination.')
        except Exception as exc:
            self._open_error = True
            import logging, traceback
            frames = [(frame.name, frame.lineno) for frame in traceback.extract_tb(exc.__traceback__)]
            logging.getLogger(__name__).error('Saved brain review failed: %s; frames=%s', type(exc).__name__, frames)
            self.status.setText('Could not open this result (' + type(exc).__name__ + '). Try Open PDF or reopen Eagle Eye. Your saved result has not been changed.')
        self.review_button.setEnabled(self.results.currentRow() >= 0)
        self.pdf_button.setEnabled(self.results.currentRow() >= 0)
        if self._pending_open is not None:
            kind, path = self._pending_open; self._pending_open = None
            self._load_selected(kind, path)
