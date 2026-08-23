"""The case side panel: collapsible sections, each with a one-line summary.

THE SUMMARY LINE IS THE POINT. A collapsed section still answers its own
question — "Location — Australia", "Case — Brain MRI", "Imaging — Google
Drive" — so an operator can read the whole case at a glance and open only the
one they need. Every one of those strings is computed on the server by
``PatientCase::imagingSummary()`` and its siblings, because the answer is not
a field: imagingSummary has to weigh a Drive folder against pasted links
against uploads before it can say which is the study.

THE ORDER IS DELIBERATE and was arrived at by using the thing:

    identity → imaging → drive → location → CASE → provenance → mail → actions

Case sits in the middle rather than at the top because by the time you need
the clinical detail you have already decided who you are talking to; identity
and the phone number are what you reach for first.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .styles import RADIUS_SM, theme_tokens, tone_color


class Section(QToolButton):
    """A collapsible section header that keeps its answer while closed."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatPanelSection")
        self.setCheckable(True)
        self.setChecked(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setArrowType(Qt.RightArrow)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._title = title
        self._summary = ""
        self._refresh()

        self.toggled.connect(self._on_toggled)

    def set_summary(self, summary: str) -> None:
        self._summary = summary or ""
        self._refresh()

    def _refresh(self) -> None:
        self.setText(f"{self._title} — {self._summary}" if self._summary else self._title)

    def _on_toggled(self, checked: bool) -> None:
        self.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)


class _Body(QWidget):
    """The rows a section reveals. Hidden until its header is opened."""

    linkActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 2, 8, 8)
        self._layout.setSpacing(3)
        self.setVisible(False)

    def clear(self) -> None:
        """Empty this section NOW, not at the end of the event loop.

        ``deleteLater`` alone schedules destruction but leaves the widget
        parented until Qt gets back to its event loop — so a row rendered from
        the previous answer is still a child, still findable, and still
        paintable, while the next answer is being drawn on top of it. Detaching
        first makes "cleared" mean cleared.
        """
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def add_row(self, label: str, value: str) -> None:
        if value in (None, ""):
            return
        row = QLabel(f"<b>{label}</b>&nbsp; {value}", self)
        row.setObjectName("ChatPanelRow")
        row.setWordWrap(True)
        row.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        # NOT setOpenExternalLinks. Every http(s) link in this panel is an
        # AI-PACS page — a study link, a Drive folder, a landing page — and the
        # workstation opens those in its OWN browser, not the operating
        # system's. mailto: and tel: still leave, because there is no internal
        # mail client to hand them to.
        row.setOpenExternalLinks(False)
        row.linkActivated.connect(self.linkActivated.emit)
        self._layout.addWidget(row)

    def add_button(self, text: str, on_click, *, tooltip: str = "") -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName("ChatPanelAction")
        button.setCursor(Qt.PointingHandCursor)
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(lambda _=False: on_click())
        self._layout.addWidget(button)
        return button

    def add_note(self, text: str) -> None:
        note = QLabel(text, self)
        note.setObjectName("ChatPanelNote")
        note.setWordWrap(True)
        self._layout.addWidget(note)


class CasePanel(QScrollArea):
    """Everything about the patient except what they said."""

    rotateLinkRequested = Signal()
    pinCaseRequested = Signal()
    linkActivated = Signal(str)   # every http(s) link, for the internal browser
    retryRequested = Signal()     # the detail fetch failed; try it again

    SECTIONS = (
        ("identity", "Identity"),
        ("imaging", "Imaging"),
        ("drive", "Drive"),
        ("location", "Location"),
        ("case", "Case"),
        ("provenance", "How they found us"),
        ("mail", "Email"),
        ("actions", "Actions"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatCasePane")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._host = QWidget(self)
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(10, 10, 6, 10)
        self._layout.setSpacing(2)

        self.header = QLabel("No conversation selected", self._host)
        self.header.setObjectName("ChatPanelHeader")
        self.header.setWordWrap(True)
        self._layout.addWidget(self.header)

        self.status_chip = QLabel("", self._host)
        self.status_chip.setObjectName("ChatPanelStatus")
        self._layout.addWidget(self.status_chip)
        self._layout.addSpacing(6)

        self._sections: dict[str, Section] = {}
        self._bodies: dict[str, _Body] = {}

        for key, title in self.SECTIONS:
            section = Section(title, self._host)
            body = _Body(self._host)
            section.toggled.connect(body.setVisible)
            body.linkActivated.connect(self.linkActivated.emit)
            self._layout.addWidget(section)
            self._layout.addWidget(body)
            self._sections[key] = section
            self._bodies[key] = body

        # Identity open by default: it is the one an operator reads every time.
        self._sections["identity"].setChecked(True)

        self._layout.addStretch(1)
        self.setWidget(self._host)

        self._detail: dict = {}

    # --- content ----------------------------------------------------------

    def clear(self) -> None:
        self._detail = {}
        self.header.setText("No conversation selected")
        self.status_chip.setText("")
        for key in self._bodies:
            self._sections[key].set_summary("")
            self._bodies[key].clear()

    def set_preliminary(self, row) -> None:
        """Draw what is ALREADY KNOWN, the instant the operator clicks.

        THE PANEL MUST NEVER BE BLANK WHILE A CLICK IS IN FLIGHT. The
        conversation row the operator just clicked already carries the name,
        the reference, the status, the tone and the presence dot — that is a
        usable answer to "who am I talking to", and it is on this machine
        before any request goes out.

        Rendering it first also means a detail fetch that FAILS degrades to
        something useful rather than to nothing: identity and status stay on
        screen, and only the sections that genuinely need the server say so.
        The detail answer, when it lands, replaces this wholesale.
        """
        if row is None:
            self.clear()
            return

        self._detail = {}
        case_id = getattr(row, "id", None)
        self.header.setText(
            f"<b>{_esc(getattr(row, 'title', '') or '')}</b><br>"
            f"<span>#{_esc(getattr(row, 'ref', '') or case_id)}</span>"
        )

        status = str(getattr(row, "status", "") or "")
        tone = tone_color(str(getattr(row, "tone", "work") or "work"))
        self.status_chip.setText(_esc(status.replace("_", " ")))
        self.status_chip.setStyleSheet(
            f"color:{tone}; border:1px solid {tone}; border-radius:{RADIUS_SM}px;"
            " padding:2px 8px; font-size:11px;"
        )

        for key in self._bodies:
            self._sections[key].set_summary("")
            self._bodies[key].clear()

        body = self._bodies["identity"]
        self._sections["identity"].set_summary(str(getattr(row, "title", "") or ""))
        body.add_row("Name", _esc(getattr(row, "title", "")))
        body.add_row("Reference", _esc(getattr(row, "ref", "")))
        body.add_row("Online", "yes" if getattr(row, "online", False) else "no")
        unread = int(getattr(row, "unread", 0) or 0)
        if unread:
            body.add_row("Unread", f"{unread} message{'s' if unread != 1 else ''}")
        body.add_note("Loading the rest of this case…")

        self._bodies["case"].add_row("Status", _esc(status.replace("_", " ")))

    def set_error(self, message: str) -> None:
        """The detail fetch failed. Say so where the answer should have been.

        Not in the typing strip under the transcript, which is where this used
        to go: an operator looking at an empty right-hand column looks at the
        right-hand column. Whatever ``set_preliminary`` drew stays — name,
        reference and status are still true — and only the missing part is
        reported, with a way to ask again.
        """
        body = self._bodies["identity"]
        body.add_note(
            "The full case details could not be loaded from ai-pacs.com.\n"
            f"{message}"
        )
        body.add_button("Try again", self.retryRequested.emit)
        self._sections["identity"].setChecked(True)

    def set_case(self, detail: dict) -> None:
        """Render one case. Every string here came from the server."""
        self._detail = dict(detail or {})
        if not self._detail:
            self.clear()
            return

        d = self._detail
        summaries = d.get("summaries") or {}

        self.header.setText(
            f"<b>{_esc(d.get('display_label'))}</b><br><span>#{_esc(d.get('reference'))}</span>"
        )

        stage = d.get("stage") or {}
        tone = tone_color(str(d.get("status_tone") or "work"))
        self.status_chip.setText(_esc(stage.get("label") or d.get("status")))
        self.status_chip.setStyleSheet(
            f"color:{tone}; border:1px solid {tone}; border-radius:{RADIUS_SM}px;"
            " padding:2px 8px; font-size:11px;"
        )

        for key in self._bodies:
            self._bodies[key].clear()

        # --- identity ------------------------------------------------------
        body = self._bodies["identity"]
        identity_bits = [b for b in (d.get("email"), d.get("phone")) if b]
        self._sections["identity"].set_summary(
            identity_bits[0] if identity_bits else str(d.get("display_label") or "")
        )
        body.add_row("Name", _esc(d.get("display_label")))
        body.add_row("Reference", _esc(d.get("reference")))
        if d.get("email"):
            body.add_row("Email", f"<a href='mailto:{_esc(d['email'])}'>{_esc(d['email'])}</a>")
        if d.get("phone"):
            body.add_row("Phone", f"<a href='tel:{_esc(d['phone'])}'>{_esc(d['phone'])}</a>")
        body.add_row("Online", "yes" if d.get("patient_online") else "no")
        if d.get("mirrored"):
            body.add_note("Mirrored from Crisp — this conversation started elsewhere.")

        # --- imaging -------------------------------------------------------
        body = self._bodies["imaging"]
        self._sections["imaging"].set_summary(str(summaries.get("imaging") or ""))
        primary_id = d.get("primary_study_file_id")
        files = d.get("files") or []
        for entry in files:
            if entry.get("storage_kind") == "drive":
                continue
            marker = "★ " if entry.get("id") == primary_id else ""
            name = entry.get("host_label") or entry.get("original_name") or "file"
            url = entry.get("external_url") or entry.get("download_url")
            value = f"<a href='{_esc(url)}'>{_esc(entry.get('short_url') or name)}</a>" if url else _esc(name)
            body.add_row(f"{marker}{_esc(name)}", value)
        if not files:
            body.add_note("No study recorded yet.")

        # --- drive ---------------------------------------------------------
        body = self._bodies["drive"]
        self._sections["drive"].set_summary(str(summaries.get("drive") or ""))
        drive = d.get("drive") or {}
        if drive.get("linked"):
            folder_url = drive.get("folder_url")
            body.add_row(
                "Folder",
                f"<a href='{_esc(folder_url)}'>{_esc(drive.get('folder_name') or 'Open in Drive')}</a>"
                if folder_url else _esc(drive.get("folder_name")),
            )
        else:
            body.add_note(f"Not filed yet. Suggested folder name: {_esc(drive.get('suggested_name'))}")
        for entry in files:
            if entry.get("storage_kind") != "drive":
                continue
            url = entry.get("drive_url")
            name = entry.get("original_name") or "file"
            body.add_row("File", f"<a href='{_esc(url)}'>{_esc(name)}</a>" if url else _esc(name))

        # --- location ------------------------------------------------------
        body = self._bodies["location"]
        self._sections["location"].set_summary(str(summaries.get("location") or ""))
        location = d.get("location") or {}
        body.add_row("Place", _esc(location.get("line")))
        body.add_row("Country", _esc(location.get("country_code")))
        if location.get("local_time"):
            # Their wall clock. The entire reason this field exists is "do not
            # call this patient at 3am".
            body.add_row("Their local time", _esc(str(location["local_time"])[11:16]))
        if location.get("approximate"):
            body.add_note("Approximate — resolved from the IP address, not stated by the patient.")
        body.add_row("Device", _esc(d.get("device_label")))

        # --- case ----------------------------------------------------------
        body = self._bodies["case"]
        self._sections["case"].set_summary(str(summaries.get("case") or ""))
        body.add_row("Modality", _esc(d.get("modality")))
        body.add_row("Status", _esc(d.get("status")))
        body.add_row("Stage", _esc(stage.get("label")))
        if stage.get("note"):
            body.add_note(_esc(stage.get("note")))
        if d.get("needs_price_nudge"):
            body.add_note("No price sent yet after several patient messages — this is the measured leak.")

        # --- provenance ----------------------------------------------------
        body = self._bodies["provenance"]
        self._sections["provenance"].set_summary(str(summaries.get("source") or ""))
        body.add_row("Source", _esc(d.get("source_label")))
        body.add_row("Landing page", _esc(d.get("landing_title") or d.get("landing_path")))
        body.add_row("Referrer", _esc(d.get("referrer_host")))
        if summaries.get("visit"):
            body.add_row("Visit", _esc(summaries.get("visit")))
        for step in d.get("journey_steps") or []:
            body.add_row(_esc(step.get("label")), _esc(step.get("note")))

        # --- mail ----------------------------------------------------------
        body = self._bodies["mail"]
        sends = d.get("email_sends") or []
        opened = sum(1 for s in sends if s.get("state") == "opened")
        self._sections["mail"].set_summary(
            f"{len(sends)} sent · {opened} opened" if sends else "Nothing sent"
        )
        for send in sends[:12]:
            # "Sent" and not "Delivered", deliberately: SMTP acceptance says
            # nothing about reaching an inbox rather than a spam folder.
            body.add_row(_esc(send.get("kind_label")), _esc(send.get("state_label")))
        if not sends:
            body.add_note("No email has been sent for this case.")

        # --- actions -------------------------------------------------------
        body = self._bodies["actions"]
        pinned = bool(d.get("pinned"))
        self._sections["actions"].set_summary("Pinned" if pinned else "")
        body.add_button(
            "Unpin this case" if pinned else "Pin this case",
            self.pinCaseRequested.emit,
            tooltip="Pinned cases stay at the top of the list for every operator.",
        )
        body.add_button(
            "Issue a fresh access link…",
            self.rotateLinkRequested.emit,
            tooltip=(
                "Generates a new link for the patient and INVALIDATES the old one. "
                "The new link is shown once and is not stored."
            ),
        )

    def set_theme(self, tokens: dict | None = None) -> None:
        t = tokens if isinstance(tokens, dict) and tokens else theme_tokens()
        self.setStyleSheet(f"""
        QWidget {{ background: {t.get('panel_bg')}; color: {t.get('text_primary')}; }}
        QLabel#ChatPanelHeader {{ font-size: 15px; color: {t.get('text_primary')}; }}
        QLabel#ChatPanelRow {{ color: {t.get('text_secondary')}; font-size: 12px; }}
        QLabel#ChatPanelNote {{ color: {t.get('text_muted')}; font-size: 11px; font-style: italic; }}
        QToolButton#ChatPanelSection {{
            background: transparent;
            color: {t.get('text_primary')};
            border: none;
            border-top: 1px solid {t.get('border')};
            padding: 7px 2px;
            text-align: left;
            font-size: 12px;
        }}
        QToolButton#ChatPanelSection:hover {{ color: {t.get('accent')}; }}
        QPushButton#ChatPanelAction {{
            background: {t.get('card_bg')};
            color: {t.get('text_primary')};
            border: 1px solid {t.get('border')};
            border-radius: {RADIUS_SM}px;
            padding: 5px 10px;
            font-size: 12px;
            text-align: left;
        }}
        QPushButton#ChatPanelAction:hover {{ border-color: {t.get('accent')}; }}
        """)


def _esc(value) -> str:
    """Escape for the rich-text labels this panel uses.

    Everything here is patient- or visitor-supplied — a name, a referrer, a
    page title — and the labels render HTML so links work. Unescaped, a
    display name containing a tag would render as markup.
    """
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
