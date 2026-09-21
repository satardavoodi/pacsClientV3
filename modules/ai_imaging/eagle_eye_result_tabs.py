"""Separate module review from image preparation, retaining one viewer instance."""
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QSplitter


class AnalysisResultTabs(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pages = {}
        window.tab_widget.currentChanged.connect(self._changed)

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
        target = (page.viewer_layout if page in self.pages.values()
                  else imaging.vertical_layout)
        for widget in (imaging.viewer_toolbar, imaging.patient_widget_container):
            if target.indexOf(widget) < 0:
                target.addWidget(widget)
                widget.show()
        target.setStretch(target.indexOf(imaging.patient_widget_container), 5)
