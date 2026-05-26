"""
User Manual widget embedded in the AIPacs Help panel.

Layout (inside the 400px center-menu panel):
  ┌──────────────────────────────────────┐
  │  [logo]  User Manual          (52px) │
  ├──────────┬───────────────────────────┤
  │  TOC     │  Content (QTextBrowser)   │
  │  (120px) │                           │
  └──────────┴───────────────────────────┘
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from PacsClient.utils.config import IMAGES_LOGIN_PATH

# ---------------------------------------------------------------------------
# Section data
# ---------------------------------------------------------------------------

_SECTIONS = [
    {
        "id": "overview",
        "title": "Overview",
        "icon": "🏠",
        "content": """
<h2>AIPacs — Overview</h2>
<p>AIPacs is a comprehensive medical imaging workstation for DICOM study management,
viewing, and AI-assisted diagnostics.</p>
<h3>Key Features</h3>
<ul>
  <li>DICOM study management via PACS servers or local storage</li>
  <li>Multi-series viewer with MPR, zoom, pan, and windowing tools</li>
  <li>Fast and Advanced rendering backends</li>
  <li>Study download queue with real-time progress tracking</li>
  <li>AI imaging analysis and automated segmentation</li>
  <li>Modular architecture — enable only the tools you need</li>
</ul>
<h3>Quick Start</h3>
<ol>
  <li>Log in with your credentials on the login screen.</li>
  <li>The patient list opens automatically after login.</li>
  <li>Use the search bar and filters to locate a study.</li>
  <li>Double-click a patient row to open the study in the viewer.</li>
</ol>
""",
    },
    {
        "id": "patient_list",
        "title": "Patient List",
        "icon": "👤",
        "content": """
<h2>Patient List</h2>
<p>The patient list is your central hub for locating and opening DICOM studies.</p>
<h3>Searching &amp; Filtering</h3>
<ul>
  <li><b>Search bar</b> — type patient name, ID, or accession number.</li>
  <li><b>Date range</b> — filter by study date using the left panel calendar.</li>
  <li><b>Modality filter</b> — show only CT, MR, US, DR, etc.</li>
  <li><b>Server selector</b> — switch between configured PACS servers or local storage.</li>
</ul>
<h3>Table Columns</h3>
<ul>
  <li>Patient Name, Patient ID, Study Date, Modality, Description, Series Count, Status</li>
</ul>
<h3>Actions</h3>
<ul>
  <li><b>Double-click row</b> — open study in a viewer tab immediately</li>
  <li><b>Right-click</b> — context menu: Download, Export, Print, Delete</li>
  <li><b>Download icon</b> — queues the study into the Download Manager</li>
  <li><b>Column headers</b> — click to sort ascending/descending</li>
</ul>
""",
    },
    {
        "id": "viewer",
        "title": "Viewer",
        "icon": "🖥",
        "content": """
<h2>Image Viewer</h2>
<p>The viewer opens a DICOM study for review. Each series is displayed in its own panel,
and multiple series can be compared side by side.</p>
<h3>Toolbar Controls</h3>
<ul>
  <li><b>Window / Level</b> — adjust image brightness and contrast</li>
  <li><b>Zoom</b> — scroll wheel or pinch gesture; hold Ctrl + scroll</li>
  <li><b>Pan</b> — middle-click drag, or Shift + left drag</li>
  <li><b>Scroll slices</b> — mouse wheel moves through the DICOM stack</li>
  <li><b>Measure</b> — draw rulers, angle tools, or ROI annotations</li>
  <li><b>Reset view</b> — restore default window, zoom, and position</li>
</ul>
<h3>Backend Modes</h3>
<ul>
  <li><b>Fast</b> — PyDicom + Qt renderer; minimal latency for large stacks</li>
  <li><b>Advanced</b> — VTK-based renderer with full MPR and 3-D capabilities</li>
</ul>
<h3>Reference Lines (Lock Sync)</h3>
<p>When multiple series are open, enabling <b>Lock Sync</b> draws reference lines
across panels for spatial correlation through the volume.</p>
<h3>Keyboard Shortcuts</h3>
<ul>
  <li><b>W / L</b> — window / level mode</li>
  <li><b>Z</b> — zoom mode</li>
  <li><b>R</b> — reset view</li>
  <li><b>Arrow keys</b> — fine-grain slice navigation</li>
  <li><b>F</b> — toggle full-screen panel</li>
</ul>
""",
    },
    {
        "id": "settings",
        "title": "Settings",
        "icon": "⚙",
        "content": """
<h2>Settings</h2>
<p>Access Settings from the left sidebar gear icon to configure AIPacs behaviour.</p>
<h3>Server Configuration</h3>
<ul>
  <li>Add, edit, or remove PACS server connections (AE Title, Host, Port)</li>
  <li>Test server connectivity before saving</li>
  <li>Set a default server for auto-connect on startup</li>
</ul>
<h3>Viewer Settings</h3>
<ul>
  <li>Default window / level presets per modality (CT, MR, US …)</li>
  <li>Default rendering backend: Fast or Advanced</li>
  <li>Scroll speed multiplier and scroll direction</li>
  <li>Grid layout for multi-series display (1×1, 2×2, 2×3 …)</li>
</ul>
<h3>Storage Settings</h3>
<ul>
  <li>Local DICOM cache folder location</li>
  <li>Automatic cleanup threshold (% disk usage)</li>
  <li>Retention period (days) for downloaded studies</li>
</ul>
<h3>Theme</h3>
<ul>
  <li>Choose from preset themes or customise the accent colour</li>
  <li>Toggle compact mode for smaller screens</li>
  <li>Theme changes apply instantly without restart</li>
</ul>
<h3>Network</h3>
<ul>
  <li>Socket server host and port for real-time notifications</li>
  <li>gRPC streaming connection settings</li>
  <li>Proxy configuration for corporate environments</li>
</ul>
""",
    },
    {
        "id": "ai_imaging",
        "title": "AI Imaging",
        "icon": "🧠",
        "content": """
<h2>AI Imaging Module</h2>
<p>The AI Imaging module applies AI models to DICOM images for automated detection
and measurement.</p>
<h3>Features</h3>
<ul>
  <li>Automated organ segmentation with colour overlays</li>
  <li>Lesion detection with bounding-box highlights</li>
  <li>Automatic measurement extraction (volume, diameter, Hounsfield units)</li>
  <li>Confidence score per finding displayed in the result panel</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Open a study in the viewer.</li>
  <li>Click the <b>AI</b> button in the toolbar or sidebar.</li>
  <li>Select the analysis model from the dropdown list.</li>
  <li>Click <b>Run Analysis</b> — results appear as overlays within seconds.</li>
  <li>Click any finding in the result list to jump to that slice.</li>
</ol>
<h3>Requirements</h3>
<ul>
  <li>Requires an active AI server connection (Settings → AI Server).</li>
  <li>AI results are decision support only — not a substitute for radiologist review.</li>
</ul>
""",
    },
    {
        "id": "download_manager",
        "title": "Download Manager",
        "icon": "⬇",
        "content": """
<h2>Download Manager</h2>
<p>Handles all DICOM study downloads with queue management and real-time progress tracking.</p>
<h3>Features</h3>
<ul>
  <li>Queue multiple studies with priority ordering</li>
  <li>Per-series download progress bars with speed indicator</li>
  <li>Pause, resume, and cancel individual downloads</li>
  <li>Background prefetch for studies open in the viewer</li>
  <li>Automatic retry on network interruption</li>
  <li>Persistent queue — survives application restart</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Right-click a study in the patient list → <b>Download</b>, or
      click the download icon next to a row.</li>
  <li>Open the <b>Download Manager</b> tab from the left sidebar to monitor progress.</li>
  <li>Drag rows in the queue to re-order priority.</li>
  <li>Completed downloads are stored locally and flagged in the patient list.</li>
</ol>
<h3>Priority Levels</h3>
<ul>
  <li><b>High</b> — studies opened for immediate viewing (set automatically)</li>
  <li><b>Normal</b> — background queued downloads</li>
  <li><b>Low</b> — prefetch / speculative downloads</li>
</ul>
""",
    },
    {
        "id": "mpr",
        "title": "MPR / 3D Slicer",
        "icon": "🔲",
        "content": """
<h2>MPR / 3D Slicer Module</h2>
<p>Multi-Planar Reformation (MPR) reconstructs volumetric CT or MR data into arbitrary planes.</p>
<h3>Available Views</h3>
<ul>
  <li><b>Axial</b> — transverse (top-to-bottom) plane</li>
  <li><b>Coronal</b> — front-to-back plane</li>
  <li><b>Sagittal</b> — left-to-right plane</li>
  <li><b>3D Volume</b> — rendered 3-D model (CT / MR sequences)</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Open a CT or MR study in the viewer.</li>
  <li>Click the <b>MPR</b> button in the toolbar.</li>
  <li>Drag the crosshair in any plane to navigate the other planes simultaneously.</li>
  <li>Use the slice slider or scroll wheel to move through slices.</li>
</ol>
<h3>Advanced Tools</h3>
<ul>
  <li><b>Oblique slicing</b> — tilt the cutting plane to any angle</li>
  <li><b>Slab thickness</b> — average or MIP over N adjacent slices</li>
  <li><b>Independent zoom / pan</b> per plane</li>
  <li><b>Synchronised windowing</b> across all planes</li>
</ul>
""",
    },
    {
        "id": "cd_burner",
        "title": "CD / Media Burner",
        "icon": "💿",
        "content": """
<h2>CD / Media Burner Module</h2>
<p>Export DICOM studies to CD, DVD, or USB for patient delivery with an embedded viewer.</p>
<h3>Features</h3>
<ul>
  <li>Burn DICOM files with an embedded DICOM viewer (no software required on target PC)</li>
  <li>Output to CD, DVD, or a folder / USB drive</li>
  <li>Patient label and metadata printed on disc surface (label printers supported)</li>
  <li>Optional compression to fit within media capacity</li>
  <li>Anonymisation option before burning</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Select one or more studies in the patient list.</li>
  <li>Open the <b>CD Burner</b> module from the left sidebar.</li>
  <li>Choose media type and destination drive from the dropdowns.</li>
  <li>Configure label text and anonymisation options.</li>
  <li>Click <b>Start Burn</b> and wait for the completion notification.</li>
</ol>
""",
    },
    {
        "id": "data_analysis",
        "title": "Data Analysis",
        "icon": "📊",
        "content": """
<h2>Data Analysis Module</h2>
<p>Interactive statistics and visualisations over the patient and study database.</p>
<h3>Features</h3>
<ul>
  <li>Study volume charts by date range, modality, or referring physician</li>
  <li>Turnaround time analytics (study arrival to read time)</li>
  <li>Export reports as CSV or PDF</li>
  <li>Customisable chart types: bar, line, pie</li>
  <li>Saved dashboard views per user</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Open the <b>Data Analysis</b> module from the left sidebar.</li>
  <li>Select date range and grouping options at the top of the dashboard.</li>
  <li>Charts update automatically as filters change.</li>
  <li>Click <b>Export</b> to download the current report.</li>
</ol>
""",
    },
    {
        "id": "echomind",
        "title": "EchoMind AI",
        "icon": "🎙",
        "content": """
<h2>EchoMind AI Module</h2>
<p>AI-powered assistant and voice transcription tool integrated into the workstation.</p>
<h3>Features</h3>
<ul>
  <li>Voice-to-text transcription for radiology reports — real-time display</li>
  <li>Natural language query over patient data ("<i>Show CTs from last week</i>")</li>
  <li>AI-generated report templates per modality</li>
  <li>Dictation playback, editing, and formatting</li>
  <li>Structured report output compatible with RIS export</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Open the <b>EchoMind</b> module from the left sidebar.</li>
  <li>Click the microphone icon to start dictation.</li>
  <li>Speak naturally — transcription appears in real time.</li>
  <li>Use the template selector to structure the output by report type.</li>
  <li>Click <b>Insert into Report</b> to attach the transcription to the open study.</li>
</ol>
""",
    },
    {
        "id": "education",
        "title": "Education",
        "icon": "📚",
        "content": """
<h2>Education Module</h2>
<p>CME-accredited radiology courses and interactive case libraries.</p>
<h3>Features</h3>
<ul>
  <li>Browse and enrol in structured radiology courses</li>
  <li>Interactive case studies with quiz questions and annotations</li>
  <li>Progress tracking and completion certificates</li>
  <li>Offline course download for remote or on-call use</li>
  <li>"Case of the Day" feed with daily teaching cases</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Open the <b>Education</b> module from the left sidebar.</li>
  <li>Browse the course catalogue or search by topic or modality.</li>
  <li>Enrol in a course and follow the structured lesson plan.</li>
  <li>Complete quizzes at the end of each section to earn CME credits.</li>
</ol>
""",
    },
    {
        "id": "printing",
        "title": "Printing",
        "icon": "🖨",
        "content": """
<h2>Printing Module</h2>
<p>Generate and print radiology image sheets and reports directly from AIPacs.</p>
<h3>Features</h3>
<ul>
  <li>DICOM Print SCU — send directly to DICOM-capable printers or dry-imagers</li>
  <li>PDF report generation with patient header and institution logo</li>
  <li>Flexible image layout: 1×1, 2×2, 3×3, 4×4, and custom grids</li>
  <li>Window / level and zoom applied before print</li>
  <li>Annotations and measurements included in print layout</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Open a study in the viewer and select the images to print.</li>
  <li>Click the <b>Print</b> button in the toolbar, or open the Printing module.</li>
  <li>Choose printer, layout, orientation, and paper size.</li>
  <li>Preview the layout in the print dialog before sending.</li>
  <li>Click <b>Print</b> to send to the printer or <b>Save PDF</b> to export.</li>
</ol>
""",
    },
    {
        "id": "storage",
        "title": "Storage",
        "icon": "🗄",
        "content": """
<h2>Storage Module</h2>
<p>Manage the local DICOM cache and long-term study archiving.</p>
<h3>Features</h3>
<ul>
  <li>Visual disk-usage chart broken down by study and date</li>
  <li>Manual and automatic cache cleanup with configurable rules</li>
  <li>Archive studies to external drives or network shares</li>
  <li>Import DICOM files from local folders or DICOM media</li>
  <li>Integrity check — verify downloaded DICOM files are not corrupted</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Open the <b>Storage</b> module from the left sidebar.</li>
  <li>Review the storage-usage chart at the top.</li>
  <li>Select old or large studies in the list.</li>
  <li>Click <b>Delete</b> to free space or <b>Archive</b> to move to external storage.</li>
  <li>Use <b>Import DICOM</b> to load files from a local directory into the database.</li>
</ol>
""",
    },
    {
        "id": "web_browser",
        "title": "Web Browser",
        "icon": "🌐",
        "content": """
<h2>Web Browser Module</h2>
<p>An embedded web browser for accessing radiology references, RIS portals, or clinical
guidelines without leaving AIPacs.</p>
<h3>Features</h3>
<ul>
  <li>Full-featured Chromium-based browser</li>
  <li>Bookmarks for frequently visited sites (RIS, guidelines, PACS web portals)</li>
  <li>Open browser and DICOM viewer side by side in split view</li>
  <li>Private browsing mode available</li>
</ul>
<h3>How to Use</h3>
<ol>
  <li>Open the <b>Web Browser</b> module from the left sidebar.</li>
  <li>Type a URL in the address bar or select a saved bookmark.</li>
  <li>Multiple tabs are supported — right-click a tab to close or duplicate it.</li>
</ol>
""",
    },
    {
        "id": "zeta_boost",
        "title": "Zeta Boost",
        "icon": "⚡",
        "content": """
<h2>Zeta Boost Module</h2>
<p>Performance-acceleration layer for rendering large DICOM stacks at high frame rates.</p>
<h3>Features</h3>
<ul>
  <li>GPU-accelerated slice decoding and rendering pipeline</li>
  <li>Predictive prefetch — adjacent slices loaded before you scroll to them</li>
  <li>Memory-efficient LRU cache for stacks of 1 000+ slices</li>
  <li>Adaptive quality — maintains ≥60 fps during fast scroll bursts</li>
  <li>GC suppression during scroll to eliminate frame-time spikes</li>
</ul>
<h3>Configuration (Settings → Viewer → Boost)</h3>
<ul>
  <li><b>Boost level</b>: Off / Normal / Aggressive</li>
  <li><b>VRAM budget</b>: limit GPU memory (MB) used by the cache</li>
  <li><b>Warmup on open</b>: pre-decode entire stack when study is first opened</li>
</ul>
<h3>Notes</h3>
<ul>
  <li>Warmup subprocess runs at <b>Idle</b> CPU priority to avoid impacting scrolling.</li>
  <li>Do not set boost level above Normal on shared/server hardware.</li>
</ul>
""",
    },
]

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background-color: #1e2535;
    color: #e2e8f0;
    margin: 10px 12px;
    font-size: 12px;
    line-height: 1.5;
  }}
  h2 {{
    color: #63b3ed;
    border-bottom: 1px solid #2d3748;
    padding-bottom: 5px;
    margin-top: 0;
    font-size: 14px;
  }}
  h3 {{
    color: #90cdf4;
    margin-top: 14px;
    margin-bottom: 4px;
    font-size: 12px;
  }}
  ul, ol {{
    margin: 4px 0 8px 0;
    padding-left: 18px;
  }}
  li {{
    margin-bottom: 4px;
  }}
  b {{
    color: #fbd38d;
  }}
  i {{
    color: #a0aec0;
  }}
  p {{
    margin-top: 0;
    margin-bottom: 8px;
  }}
</style>
</head>
<body>
{content}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class UserManualWidget(QWidget):
    """
    Embedded user manual for the AIPacs Help center-menu panel.

    Left column  — clickable table of contents (TOC)
    Right column — QTextBrowser rendering the selected section's HTML
    Header row   — app logo + "User Manual" title
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UserManualWidget")
        self._build_ui()
        # Select Overview by default
        self._toc.setCurrentRow(0)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), stretch=1)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("ManualHeader")
        header.setMinimumHeight(50)  # Archetype 5
        header.setStyleSheet(
            "QFrame#ManualHeader {"
            "  background-color: #0f1623;"
            "  border-bottom: 1px solid #2d3748;"
            "}"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 6, 10, 6)
        hl.setSpacing(10)

        # App logo
        logo = QLabel()
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(str(IMAGES_LOGIN_PATH / "aiLogo.png"))
        if not pix.isNull():
            logo.setPixmap(
                pix.scaled(34, 34, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            )
        hl.addWidget(logo)

        # Title
        title = QLabel("User Manual")
        title.setStyleSheet(
            "color: #e2e8f0;"
            "font-size: 14px;"
            "font-weight: bold;"
            "background: transparent;"
        )
        hl.addWidget(title, stretch=1)
        return header

    def _build_body(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #2d3748; }")

        # ── TOC list ──────────────────────────────────────────
        self._toc = QListWidget()
        self._toc.setObjectName("ManualTOC")
        self._toc.setMinimumWidth(118)  # Archetype 5
        self._toc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._toc.setStyleSheet("""
            QListWidget#ManualTOC {
                background-color: #171f2e;
                border: none;
                color: #cbd5e0;
                font-size: 11px;
                outline: 0;
            }
            QListWidget#ManualTOC::item {
                padding: 7px 8px;
                border-bottom: 1px solid #252f41;
            }
            QListWidget#ManualTOC::item:selected {
                background-color: #2b6cb0;
                color: #ffffff;
                border-left: 3px solid #63b3ed;
                padding-left: 5px;
            }
            QListWidget#ManualTOC::item:hover:!selected {
                background-color: #1e2a3e;
            }
            QScrollBar:vertical {
                background: #171f2e;
                width: 4px;
            }
            QScrollBar::handle:vertical {
                background: #4a5568;
                border-radius: 2px;
            }
        """)

        for sec in _SECTIONS:
            item = QListWidgetItem(f"{sec['icon']}  {sec['title']}")
            item.setData(Qt.ItemDataRole.UserRole, sec["id"])
            self._toc.addItem(item)

        # ── Content browser ───────────────────────────────────
        self._content = QTextBrowser()
        self._content.setObjectName("ManualContent")
        self._content.setOpenExternalLinks(True)
        self._content.setStyleSheet("""
            QTextBrowser#ManualContent {
                background-color: #1e2535;
                border: none;
                color: #e2e8f0;
                font-size: 12px;
                selection-background-color: #2b6cb0;
            }
            QScrollBar:vertical {
                background: #1e2535;
                width: 5px;
            }
            QScrollBar::handle:vertical {
                background: #4a5568;
                border-radius: 2px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """)
        # Allow images to resolve from the images folder
        self._content.setSearchPaths([str(IMAGES_LOGIN_PATH)])

        splitter.addWidget(self._toc)
        splitter.addWidget(self._content)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([118, 9999])

        self._toc.currentRowChanged.connect(self._on_row_changed)
        return splitter

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(_SECTIONS):
            sec = _SECTIONS[row]
            html = _HTML_TEMPLATE.format(content=sec["content"])
            self._content.setHtml(html)
            self._content.verticalScrollBar().setValue(0)
