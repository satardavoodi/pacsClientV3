"""Separate module review from image preparation, retaining one viewer instance."""
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QSplitter


def configure_report_reader(browser):
    """Keep print-oriented report HTML readable independently of the PACS theme."""
    from PySide6.QtGui import QColor, QPalette, QTextCursor, QTextBlockFormat
    palette = browser.palette()
    palette.setColor(QPalette.Base, QColor('#ffffff'))
    palette.setColor(QPalette.Text, QColor('#203e50'))
    browser.setPalette(palette)
    browser.setStyleSheet('QTextBrowser { background: #ffffff; color: #203e50; border: 1px solid #b8c6d2; border-radius: 6px; }')
    document = browser.document()
    document.setDocumentMargin(24)
    block = document.begin()
    while block.isValid():
        fragments = []
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                fragments.append((fragment.position(), fragment.length(), fragment.charFormat()))
            it += 1
        for position, length, fmt in fragments:
            fmt.setFontPointSize(max(11.0, fmt.fontPointSize()))
            cursor = QTextCursor(document)
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.KeepAnchor)
            cursor.setCharFormat(fmt)
        cursor = QTextCursor(block)
        fmt = block.blockFormat()
        fmt.setLineHeight(135, QTextBlockFormat.ProportionalHeight.value)
        fmt.setBottomMargin(max(8.0, fmt.bottomMargin()))
        cursor.setBlockFormat(fmt)
        block = block.next()


class AnalysisResultTabs(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pages = {}
        window.tab_widget.currentChanged.connect(self._changed)
        from concurrent.futures import ThreadPoolExecutor
        from .eagle_eye_saved_results import discover_workspace
        from PacsClient.utils.data_paths import AI_DIR, ATTACHMENTS_DIR
        self._result_root = Path(AI_DIR) / 'eagle_eye'
        self._attachment_root = Path(ATTACHMENTS_DIR)
        self._saved_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='eagle-eye-history')
        self._saved_future = self._saved_executor.submit(
            discover_workspace,
            self._result_root,
            self._attachment_root,
            getattr(window, '_study_uid', ''),
        )
        self._saved_timer = QTimer(self)
        self._saved_timer.setInterval(150)
        self._saved_timer.timeout.connect(self._restore_saved)
        self._saved_timer.start()
        self._server_future = None
        self._server_binding = None
        self._server_seen = set()
        self._server_retry_after = 0.0
        self._server_cancel = threading.Event()
        self._server_timer = QTimer(self)
        self._server_timer.setInterval(500)
        self._server_timer.timeout.connect(self._poll_server_saved_result)
        self._server_timer.start()
        window.destroyed.connect(lambda *_args: self._dispose())

    def _dispose(self):
        self._server_cancel.set()
        self._server_timer.stop()
        self._saved_timer.stop()
        self._saved_executor.shutdown(wait=False, cancel_futures=True)

    def _restore_saved(self):
        if not self._saved_future.done():
            return
        self._saved_timer.stop()
        try:
            rows = self._saved_future.result()
        except Exception:
            return
        self._add_saved_rows(rows)

    def _add_saved_rows(self, rows):
        from .eagle_eye_saved_results import TITLES
        from PySide6.QtWidgets import QTextBrowser, QPushButton, QHBoxLayout, QLabel, QComboBox
        from PySide6.QtGui import QDesktopServices
        tabs = self.window.tab_widget
        original = tabs.currentWidget()
        first_brain = None
        for row in rows:
            server_job_id = (row.get('result') or {}).get('server_job_id')
            if isinstance(server_job_id, str):
                self._server_seen.add(server_job_id)
            if row['module'] == 'lumbar' and row.get('record') is not None:
                self.show_lumbar_record(row['record'], activate=False)
                continue
            title = TITLES[row['module']]
            if any(tabs.tabText(i) == title for i in range(tabs.count())):
                continue
            sources = row['result'].get('source_binding', [])
            if (row['module'] == 'alignment' and isinstance(row['result'].get('landmarks'), dict)
                    and isinstance(sources, list) and len(sources) == 1
                    and isinstance(sources[0], dict) and sources[0].get('series_uid')
                    and sources[0].get('study_uid') == str(self.window._study_uid)):
                self.window.workspace_controller.open_alignment(saved_result=row['result'])
                continue
            if row['module'] == 'total-spine' and (
                    isinstance(row['result'].get('candidates'), list)
                    or isinstance(row['result'].get('review_views'), list)):
                self.window.workspace_controller.open_total_spine(saved_result=row['result'])
                continue
            if row['module'] == 'lumbar-marrow':
                self.window.workspace_controller.open_marrow(saved_result=row['result'])
                continue
            page = QWidget()
            outer = QHBoxLayout(page)
            outer.setContentsMargins(12, 8, 12, 8)
            card = QWidget(page)
            card.setObjectName('savedReportCard')
            card.setMaximumWidth(1120)
            outer.addStretch(1)
            outer.addWidget(card, 20)
            outer.addStretch(1)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 12, 16, 12)
            layout.setSpacing(12)
            actions = QHBoxLayout()
            heading = QLabel(title, page)
            heading.setStyleSheet('font-size: 18px; font-weight: 600; color: #dcecff;')
            actions.addWidget(heading)
            actions.addStretch()
            layout.addLayout(actions)
            browser = QTextBrowser(page)
            browser.document().setBaseUrl(QUrl.fromLocalFile(row['report']))
            browser.setHtml(row['content'] or '<p>Saved report is available as PDF.</p>')
            configure_report_reader(browser)
            for label, step in [('A-', -1), ('A+', 1)]:
                zoom = QPushButton(label, page)
                zoom.setAccessibleName('Decrease text size' if step < 0 else 'Increase text size')
                zoom.setFixedWidth(44)
                zoom.setMinimumHeight(34)
                zoom.clicked.connect(lambda checked=False, reader=browser, amount=step: reader.zoomIn(amount))
                actions.addWidget(zoom)
            navigation = QComboBox(card)
            navigation.setObjectName('reportSectionNavigation')
            navigation.setAccessibleName('Go to report section')
            navigation.setMinimumHeight(34)
            block = browser.document().begin()
            while block.isValid():
                if block.blockFormat().headingLevel() in (1, 2) and block.text().strip():
                    navigation.addItem(block.text(), block.position())
                block = block.next()
            def go_to_section(index, reader=browser, selector=navigation):
                from PySide6.QtGui import QTextCursor
                position = selector.itemData(index)
                if position is not None:
                    cursor = QTextCursor(reader.document())
                    cursor.setPosition(position)
                    reader.setTextCursor(cursor)
                    reader.ensureCursorVisible()
            navigation.activated.connect(go_to_section)
            if navigation.count():
                section_row = QHBoxLayout()
                section_row.addWidget(QLabel('Report section', card))
                section_row.addWidget(navigation, 1)
                layout.addLayout(section_row)
            else:
                navigation.hide()
            layout.addWidget(browser, 1)
            if row['pdf']:
                button = QPushButton('Open PDF', page)
                button.clicked.connect(lambda checked=False, path=row['pdf']: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
                button.setMinimumHeight(36)
                actions.addWidget(button)
            if row['module'] in ('brain', 'brain-lesions'):
                correction = QPushButton('Review / correct segmentation', page)
                correction.setObjectName('savedBrainCorrection')
                correction.clicked.connect(lambda checked=False, result=row['result']:
                    self.window.workspace_controller.open_saved_brain_result(result))
                correction.setMinimumHeight(36)
                actions.addWidget(correction)
                if first_brain is None:
                    first_brain = page
            self.pages['saved-' + row['module']] = page
            tabs.addTab(page, title)
        if first_brain is not None and original is self.window.imaging_tab:
            tabs.setCurrentWidget(first_brain)
        elif original is not None:
            tabs.setCurrentWidget(original)

    def show_lumbar_record(self, record, activate=True):
        """Create or update the persistent Lumbar result tab."""
        page = self.pages.get('lumbar')
        if page is None:
            from .eagle_eye_lumbar.result_tab import LumbarAnalysisResultPage
            page = LumbarAnalysisResultPage(self.window.tab_widget)
            self.pages['lumbar'] = page
            self.window.tab_widget.addTab(page, 'Eagle Eye Result')
        page.show_record(record)
        if activate:
            self.window.tab_widget.setCurrentWidget(page)

    def _poll_server_saved_result(self):
        """Retrieve the newest existing Server result; never submit analysis."""
        if self._server_future is not None:
            if not self._server_future.done():
                return
            future, binding = self._server_future, self._server_binding
            self._server_future = None
            self._server_binding = None
            try:
                result = future.result()
            except Exception:
                self._server_retry_after = time.monotonic() + 15.0
                return
            self._server_seen.add(binding[2])
            self._apply_server_result(result, binding[0]['study_uid'])
            return
        if time.monotonic() < self._server_retry_after:
            return
        patient = getattr(self.window.imaging_tab, 'patient_widget', None)
        controller = getattr(patient, '_case_realtime', None)
        snapshot = getattr(controller, 'snapshot', None)
        receiver = getattr(controller, 'receiver', None)
        connection = getattr(receiver, 'connection', None)
        reference = getattr(controller, 'reference', None)
        expected_study = str(getattr(self.window, '_study_uid', '') or '')
        if (not isinstance(snapshot, dict) or not isinstance(reference, dict)
                or connection is None or reference.get('study_uid') != expected_study):
            return
        rows = snapshot.get('eagle_eye')
        if not isinstance(rows, list):
            return
        for row in rows:
            job_id = row.get('job_id') if isinstance(row, dict) else None
            if not isinstance(job_id, str) or job_id in self._server_seen:
                continue
            destination = self._attachment_root / expected_study
            binding = (dict(reference), connection, job_id)
            self._server_binding = binding
            self._server_future = self._saved_executor.submit(
                self._read_server_result,
                binding[0],
                connection,
                job_id,
                destination,
            )
            return

    def _read_server_result(self, reference, connection, job_id, destination):
        from .eagle_eye_remote.case_ui import require_current_source
        from .eagle_eye_saved_results import discover_workspace
        require_current_source(connection)
        result = connection.saved_analysis(
            reference, job_id, destination, cancel=self._server_cancel
        )
        require_current_source(connection)
        directory = Path(str(result.get('artifact_directory') or '')).resolve()
        if not directory.is_dir() or self._server_cancel.is_set():
            return []
        return discover_workspace(directory, directory, reference['study_uid'])

    def _apply_server_result(self, rows, study_uid):
        """Apply worker-prepared rows only while the same study still owns this UI."""
        if self._server_cancel.is_set() or str(getattr(self.window, '_study_uid', '') or '') != study_uid:
            return
        if rows:
            self._add_saved_rows(rows)

    def show_result(self, kind, activate=True):
        titles = {'MG': 'Mammography', 'DX': 'Bone Age'}
        if kind not in titles:
            return
        page = self.pages.get(kind)
        if page is None:
            panel = self.window.imaging_tab.result_panel(kind)
            if panel is None:
                return
            page = QWidget()
            page.uses_imaging_viewer = True
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            splitter = QSplitter(Qt.Horizontal, page)
            scroll = QScrollArea(splitter)
            scroll.setWidgetResizable(True)
            scroll.setMinimumWidth(300)
            scroll.setWidget(panel)
            viewer_host = QWidget(splitter)
            page.viewer_layout = QVBoxLayout(viewer_host)
            page.viewer_layout.setContentsMargins(0, 0, 0, 0)
            splitter.addWidget(scroll)
            splitter.addWidget(viewer_host)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([340, 1100])
            layout.addWidget(splitter)
            self.pages[kind] = page
            self.window.tab_widget.addTab(page, titles[kind])
        if activate:
            self.window.tab_widget.setCurrentWidget(page)

    def _changed(self, index):
        imaging = self.window.imaging_tab
        if not hasattr(imaging, 'patient_widget_container'):
            return
        page = self.window.tab_widget.widget(index)
        target = (page.viewer_layout if page in self.pages.values() and hasattr(page, 'viewer_layout')
                  else imaging.vertical_layout)
        for widget in (imaging.viewer_toolbar, imaging.patient_widget_container):
            if target.indexOf(widget) < 0:
                target.addWidget(widget)
                widget.show()
        target.setStretch(target.indexOf(imaging.patient_widget_container), 5)
