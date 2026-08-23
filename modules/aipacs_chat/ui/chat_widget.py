"""AiPacsChatWidget — the tab root.

A plain ``QWidget`` opened as a singleton tab through
``home_module_tabs.activate_or_create_module_tab``, exactly like the web
browser, education and printing modules. Not a dialog, not a second window:
the operator console belongs beside the patient tabs, not floating over them.

FIVE STATES, ONE STACK. not-configured / signed-out / loading / error /
content. A console that shows an empty list when it actually cannot reach the
server is a console that gets trusted when it should not be.

VISIBILITY IS THIS WIDGET'S JOB TO REPORT. ``visible`` is what makes the server
write ``staff_last_read_at`` — the patient's second tick — so it has to mean
"an operator is looking at this conversation", not "the tab object exists". The
answer is: this is the current tab, of an active window, that is not minimised.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from modules.aipacs_chat.services.models import Filters
from modules.aipacs_chat.ui.case_panel import CasePanel
from modules.aipacs_chat.ui.composer import Composer
from modules.aipacs_chat.ui.conversation_list import ConversationListView
from modules.aipacs_chat.ui.message_view import ChatView
from modules.aipacs_chat.ui.styles import (
    composer_qss,
    counts_chip_qss,
    pane_qss,
    shell_qss,
    theme_tokens,
    tone_color,
)

logger = logging.getLogger(__name__)


class _StatePage(QWidget):
    """One of the four non-content states: a title, a sentence, one button."""

    def __init__(self, title: str, body: str, action: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("ChatStateTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.body_label = QLabel(body, self)
        self.body_label.setObjectName("ChatStateBody")
        self.body_label.setAlignment(Qt.AlignCenter)
        self.body_label.setWordWrap(True)
        layout.addWidget(self.body_label)

        self.action_button = QPushButton(action or "", self)
        self.action_button.setObjectName("ChatStateAction")
        self.action_button.setCursor(Qt.PointingHandCursor)
        self.action_button.setVisible(bool(action))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.action_button)
        row.addStretch(1)
        layout.addSpacing(14)
        layout.addLayout(row)

        layout.addStretch(2)

    def set_body(self, text: str) -> None:
        self.body_label.setText(text or "")


class AiPacsChatWidget(QWidget):
    """The manager console."""

    def __init__(self, parent=None, host_tab_widget=None, host_custom_tab_manager=None,
                 auth_user=None, repository=None) -> None:
        super().__init__(parent)
        self.setObjectName("AiPacsChatShell")

        self._host_tab_widget = host_tab_widget
        self._host_custom_tab_manager = host_custom_tab_manager
        self._auth_user = auth_user
        self._filters = Filters()
        self._closing = False
        self._notifications = None      # NotificationStack, built with the content page
        self._tab_unread = -1           # -1 = never written, so 0 still paints once
        self._tab_base_title = None
        # Cases this console has already announced, by any route. Server events
        # and the client's own new-conversation detector both write here, which
        # is what stops one arrival raising two banners.
        self._announced: set[int] = set()
        self._seen_first_page = False
        self._detail_retries = 0

        self._build_ui()
        self._apply_theme()

        self._repository = repository if repository is not None else self._build_repository()
        if self._repository is not None:
            self._connect_repository()

        # Not inline: opening the tab should paint before it talks to the
        # network. singleShot(0) hands the first frame to Qt first.
        QTimer.singleShot(0, self._start)

        try:
            from PacsClient.utils.theme_manager import get_theme_manager

            get_theme_manager().themeChanged.connect(self._on_theme_changed)
        except Exception as exc:  # pragma: no cover - theming must never block the tab
            logger.debug("aipacs_chat: theme signal unavailable: %s", exc)

    # ── construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack)

        self.page_loading = _StatePage(
            "Connecting to AI-PACS Consultation…",
            "Fetching the conversation list.",
        )
        self.page_not_configured = _StatePage(
            "Not signed in to AI-PACS",
            "This workstation has no linked AI-PACS Consultation account, so there "
            "is nothing to show. Sign in from the account menu, then reopen this tab.",
            action="Try again",
        )
        self.page_signed_out = _StatePage(
            "Your session expired",
            "The workstation's access token is no longer accepted. Sign in again "
            "from the account menu.",
            action="Try again",
        )
        self.page_error = _StatePage(
            "Cannot reach the consultation server",
            "Retrying automatically.",
            action="Retry now",
        )
        self.page_content = self._build_content()

        for page in (
            self.page_loading,
            self.page_not_configured,
            self.page_signed_out,
            self.page_error,
            self.page_content,
        ):
            self.stack.addWidget(page)

        self.stack.setCurrentWidget(self.page_loading)

        for page in (self.page_not_configured, self.page_signed_out, self.page_error):
            page.action_button.clicked.connect(self._on_retry_clicked)

    def _build_content(self) -> QWidget:
        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.splitter = QSplitter(Qt.Horizontal, content)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)

        # --- list pane -----------------------------------------------------
        list_pane = QWidget(self.splitter)
        list_pane.setObjectName("ChatListPane")
        list_layout = QVBoxLayout(list_pane)
        list_layout.setContentsMargins(8, 6, 8, 8)
        list_layout.setSpacing(6)

        title = QLabel("CONVERSATIONS", list_pane)
        title.setObjectName("ChatPaneTitle")
        list_layout.addWidget(title)

        self.search_box = QLineEdit(list_pane)
        self.search_box.setObjectName("ChatSearch")
        self.search_box.setPlaceholderText("Search name, reference, phone or message…")
        self.search_box.setClearButtonEnabled(True)
        list_layout.addWidget(self.search_box)

        # Debounced: the list re-queries on every keystroke otherwise, and the
        # server LIKE-scans message bodies for the term.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._apply_search)
        self.search_box.textChanged.connect(lambda _: self._search_timer.start())

        # The chips are the questions an operator actually asks — "who is
        # waiting?", "who is here now?", "who never got a price?" — so they
        # are the filter control, not decoration. The Filters model carries
        # every group; these four reach the ones that matter daily.
        self.counts_bar = QHBoxLayout()
        self.counts_bar.setSpacing(6)
        self.chip_unread = self._chip(list_pane, "Unread 0")
        self.chip_online = self._chip(list_pane, "Online 0")
        self.chip_stalled = self._chip(list_pane, "Stalled 0")
        self.chip_unpriced = self._chip(list_pane, "No price 0")
        self.chip_unread.toggled.connect(
            lambda on: self._toggle_attention("unread", on))
        self.chip_stalled.toggled.connect(
            lambda on: self._toggle_attention("stalled", on))
        self.chip_online.toggled.connect(self._toggle_online)
        self.chip_unpriced.toggled.connect(self._toggle_unpriced)
        for chip in (self.chip_unread, self.chip_online, self.chip_stalled, self.chip_unpriced):
            self.counts_bar.addWidget(chip)
        self.counts_bar.addStretch(1)
        list_layout.addLayout(self.counts_bar)

        self.conversation_list = ConversationListView(list_pane)
        self.conversation_list.caseActivated.connect(self._on_case_activated)
        list_layout.addWidget(self.conversation_list, 1)

        # --- thread pane ---------------------------------------------------
        thread_pane = QWidget(self.splitter)
        thread_pane.setObjectName("ChatThreadPane")
        thread_layout = QVBoxLayout(thread_pane)
        thread_layout.setContentsMargins(12, 10, 12, 12)
        thread_layout.setSpacing(4)

        header_row = QHBoxLayout()
        self.thread_header = QLabel("Select a conversation", thread_pane)
        self.thread_header.setObjectName("ChatThreadHeader")
        header_row.addWidget(self.thread_header, 1)

        self.presence_label = QLabel("", thread_pane)
        self.presence_label.setObjectName("ChatPresence")
        header_row.addWidget(self.presence_label, 0)
        thread_layout.addLayout(header_row)

        self.transcript = ChatView(thread_pane)
        self.transcript.editRequested.connect(self._on_edit_message)
        self.transcript.removeRequested.connect(self._on_remove_message)
        self.transcript.reactRequested.connect(self._on_react)
        self.transcript.pinRequested.connect(self._on_pin_message)
        self.transcript.emailRequested.connect(self._on_email_message)
        self.transcript.attachmentRequested.connect(self._on_attachment)
        thread_layout.addWidget(self.transcript, 1)

        self.typing_label = QLabel("", thread_pane)
        self.typing_label.setObjectName("ChatTyping")
        thread_layout.addWidget(self.typing_label)

        self.composer = Composer(thread_pane)
        self.composer.sendRequested.connect(self._on_send)
        self.composer.sendWithFilesRequested.connect(self._on_send_with_files)
        self.composer.attachmentRejected.connect(self.typing_label.setText)
        self.composer.priceRequested.connect(self._on_price)
        self.composer.statusChangeRequested.connect(self._on_status_change)
        self.composer.hasTextChanged.connect(self._on_composer_text)
        self.composer.set_enabled_for_case(False)
        thread_layout.addWidget(self.composer, 0)

        # --- case panel ----------------------------------------------------
        self.case_panel = CasePanel(self.splitter)
        self.case_panel.pinCaseRequested.connect(self._on_pin_case)
        self.case_panel.rotateLinkRequested.connect(self._on_rotate_link)
        self.case_panel.linkActivated.connect(self._open_link)
        self.case_panel.retryRequested.connect(self._reload_case_detail)

        self.splitter.addWidget(list_pane)
        self.splitter.addWidget(thread_pane)
        self.splitter.addWidget(self.case_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([320, 760, 320])
        self._restore_splitter()

        layout.addWidget(self.splitter, 1)

        # Banners are overlay children of the content page, so they float over
        # the transcript rather than reflowing it — a strip that pushes the
        # conversation down while somebody is reading is its own interruption.
        from modules.aipacs_chat.ui.notifications import NotificationStack

        self._notifications = NotificationStack(content)
        self._notifications.caseRequested.connect(self._on_notification_activated)
        return content

    @staticmethod
    def _chip(parent: QWidget, text: str) -> QPushButton:
        """A count chip that is also a filter toggle.

        Checkable and INDEPENDENT — the four chips AND together across the
        server's facet groups (attention / presence / price), which is what
        `Filters` was built for. They are deliberately not the old
        mutually-exclusive chips the model's docstring warns about: "unread
        AND online" is the most useful question an operator can ask.
        """
        chip = QPushButton(text, parent)
        chip.setProperty("chatChip", "true")
        chip.setCheckable(True)
        chip.setFlat(True)
        chip.setCursor(Qt.PointingHandCursor)
        chip.setFocusPolicy(Qt.NoFocus)
        return chip

    # ── filter chips ──────────────────────────────────────────────────────────
    def _toggle_attention(self, value: str, on: bool) -> None:
        """`attention` is multi-value: unread and stalled can both be on."""
        current = set(self._filters.attention)
        current.add(value) if on else current.discard(value)
        order = tuple(v for v in ("unread", "stalled") if v in current)
        self._set_filters(attention=order)

    def _toggle_online(self, on: bool) -> None:
        self._set_filters(presence="online" if on else "any")

    def _toggle_unpriced(self, on: bool) -> None:
        # The server's value is "none" — cases nobody has quoted yet.
        self._set_filters(price="none" if on else "any")

    def _set_filters(self, **changes) -> None:
        """Replace the filter model and push it, in one place.

        `Filters` is frozen on purpose, so every change is a new value rather
        than a mutation something else might be holding a stale view of.
        """
        from dataclasses import replace

        self._filters = replace(self._filters, **changes)
        if self._repository is not None:
            self._repository.setFilters(self._filters)

    def _build_repository(self):
        """Built here rather than injected, so the tab factory stays a one-liner.

        Returns None only if the Qt bridge itself cannot be imported, which is
        a packaging fault rather than a runtime state — the console shows its
        error page and says so.
        """
        try:
            from modules.aipacs_chat.qt.repository import ChatRepository
            from modules.Identity.identity_service import IdentityService

            # A caller that could not supply the login dict must not silently
            # become identity "local" — that is how this console ended up
            # claiming "Not signed in" while Settings showed the same operator
            # signed in (live bug 2026-08-22). Fall back to the shared resolver
            # so any entry point (menu, Secretary command bus, deep link) lands
            # on the same key the rest of the app files identities under.
            auth_user = self._auth_user
            if not auth_user:
                try:
                    from modules.Identity.ui.host_user import resolve_host_auth_user

                    auth_user = resolve_host_auth_user(self)
                    self._auth_user = auth_user
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("aipacs_chat: host user lookup failed: %s", exc)

            user = IdentityService.resolve_aipacs_user(auth_user)
            logger.info("aipacs_chat: acting as AI-PACS identity %r", user)
            return ChatRepository(user, parent=self, ev_cursor=self._load_event_cursor())
        except Exception as exc:
            logger.exception("aipacs_chat: could not build the repository: %s", exc)
            self.page_error.set_body(f"The chat module failed to start: {exc}")
            self.stack.setCurrentWidget(self.page_error)
            return None

    def _connect_repository(self) -> None:
        repo = self._repository
        repo.stateChanged.connect(self._on_state_changed)
        repo.rowsReplaced.connect(self._on_rows)
        repo.countsChanged.connect(self._on_counts)
        repo.errorRaised.connect(self._on_error)
        repo.authRequired.connect(self._on_auth_required)

        repo.threadReplaced.connect(self._on_thread_replaced)
        repo.messagesAppended.connect(self._on_messages_appended)
        repo.messagesRevised.connect(self._on_messages_revised)
        repo.presenceChanged.connect(self._on_presence)
        repo.receiptsChanged.connect(self._on_receipts)
        repo.caseStatusChanged.connect(self._on_case_status)

        # The engine has been de-duplicating events, persisting the cursor and
        # keeping a slow watch on a hidden tab since day one — and nothing was
        # listening. Without this line the console only works while somebody is
        # staring at it, which defeats putting it in the workstation at all.
        repo.eventsArrived.connect(self._on_events)
        repo.setNotificationsEnabled(self._notifications_enabled())

        repo.caseDetailLoaded.connect(self._on_case_detail)
        repo.caseDetailFailed.connect(self._on_case_detail_failed)
        repo.savedRepliesLoaded.connect(self.composer.set_saved_replies)
        repo.pricingLoaded.connect(self.composer.set_pricing)
        repo.statusesLoaded.connect(self.composer.set_statuses)

        repo.fileDownloaded.connect(self._on_file_downloaded)

        repo.writeFailed.connect(self._on_write_failed)
        repo.writeSucceeded.connect(self._on_write_succeeded)

    def _start(self) -> None:
        if self._repository is not None:
            self._repository.start()
            self._push_visibility()

    # ── event-cursor persistence ───────────────────────────────────────────
    # Non-secret UI state, so QSettings is the right home. WITH NO AGE LIMIT —
    # the web client expired its cursor after five minutes, which made every
    # page load a cold start and silently dropped half the notifications.

    _SETTINGS_ORG = "AIPacs"
    _SETTINGS_APP = "AiPacsChat"
    _SETTINGS_KEY = "notifications/event_cursor"
    _SETTINGS_SPLITTER = "layout/splitter_sizes"

    def _settings(self):
        """One QSettings group for this module's remembered state."""
        from PySide6.QtCore import QSettings

        return QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)

    def _load_event_cursor(self) -> int:
        try:
            from PySide6.QtCore import QSettings

            settings = QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)
            return int(settings.value(self._SETTINGS_KEY, 0) or 0)
        except Exception:
            return 0

    def _save_event_cursor(self) -> None:
        if self._repository is None:
            return
        try:
            from PySide6.QtCore import QSettings

            settings = QSettings(self._SETTINGS_ORG, self._SETTINGS_APP)
            settings.setValue(self._SETTINGS_KEY, int(self._repository.event_cursor))
        except Exception as exc:  # pragma: no cover
            logger.debug("aipacs_chat: could not persist the event cursor: %s", exc)

    # ── pane widths ────────────────────────────────────────────────────────
    # An operator who widens the case panel every morning is telling us
    # something; making them do it again after every restart is the kind of
    # small rudeness that makes a tool feel unfinished.

    def _restore_splitter(self) -> None:
        try:
            raw = self._settings().value(self._SETTINGS_SPLITTER, None)
            sizes = [int(v) for v in (raw or [])]
        except Exception:
            return
        # A stale value from a build with a different pane count would collapse
        # a pane to nothing, so it is only honoured when it still fits.
        if len(sizes) == self.splitter.count() and all(s >= 0 for s in sizes) and sum(sizes) > 0:
            self.splitter.setSizes(sizes)

    def _save_splitter(self) -> None:
        try:
            self._settings().setValue(
                self._SETTINGS_SPLITTER, [int(s) for s in self.splitter.sizes()]
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("aipacs_chat: could not persist the pane widths: %s", exc)

    # ── repository signals ─────────────────────────────────────────────────

    @Slot(str)
    def _on_state_changed(self, state: str) -> None:
        page = {
            "notconfigured": self.page_not_configured,
            "signedout": self.page_signed_out,
            "loading": self.page_loading,
            "error": self.page_error,
            "ready": self.page_content,
        }.get(state, self.page_loading)
        self.stack.setCurrentWidget(page)

    @Slot(object)
    def _on_rows(self, rows) -> None:
        self._announce_new_requests(rows)
        self.conversation_list.set_rows(rows)

    def _announce_new_requests(self, rows) -> None:
        """Pop up a banner for a conversation nobody has been told about.

        THE FIRST PAGE IS NOT NEWS. Opening the console would otherwise raise a
        banner for every conversation on it — sixty of them, for work that has
        been sitting there since yesterday. So the first page only records what
        exists; announcements start from the second.

        DE-DUPLICATED AGAINST THE SERVER'S OWN FEED via ``_announced``, which
        both this and ``_on_events`` write to. The feed is the source of truth
        when it carries a ``request`` event; this is the safety net for when it
        does not — a server build older than that event kind, or a request that
        arrived while this console was closed and so was never in a feed page
        this client saw.
        """
        try:
            incoming = [int(getattr(r, "id", 0) or 0) for r in (rows or ())]
        except Exception:  # pragma: no cover - defensive
            return
        incoming = [case_id for case_id in incoming if case_id]

        if not self._seen_first_page:
            self._seen_first_page = True
            self._announced.update(incoming)
            return

        fresh = [case_id for case_id in incoming if case_id not in self._announced]
        self._announced.update(incoming)
        if not fresh or self._notifications is None:
            return
        if not self._notifications_enabled():
            return

        from modules.aipacs_chat.ui.notifications import LocalEvent

        by_id = {int(getattr(r, "id", 0) or 0): r for r in (rows or ())}
        for case_id in fresh[:3]:      # the stack caps at three anyway
            row = by_id.get(case_id)
            self._notifications.show_local(LocalEvent(
                kind="request",
                case=case_id,
                title=getattr(row, "title", None) or f"Case #{case_id}",
                who=str(getattr(row, "status", "") or "").replace("_", " "),
                body=str(getattr(row, "preview", "") or "")[:120],
            ))

    @Slot(object)
    def _on_counts(self, counts) -> None:
        self.chip_unread.setText(f"Unread {counts.unread}")
        self.chip_online.setText(f"Online {counts.online}")
        self.chip_stalled.setText(f"Stalled {counts.stalled}")
        # `none` is the server's name for "not priced yet" — the measured
        # 72% leak. Spelled out here because "None 4" means nothing.
        self.chip_unpriced.setText(f"No price {counts.none}")

        # A chip standing at zero is information; a chip standing at six is a
        # QUEUE, and should not look the same. The alert property drives a
        # filled badge in the stylesheet, so the two states differ in weight
        # rather than only in a digit nobody reads.
        self._set_chip_alert(self.chip_unread, counts.unread > 0)
        self._set_chip_alert(self.chip_unpriced, counts.none > 0)
        self._set_chip_alert(self.chip_stalled, counts.stalled > 0)
        # Counts are UNFILTERED by design, which is exactly what a tab badge
        # wants: it must report work waiting anywhere, not work waiting inside
        # the operator's current filter.
        self._set_tab_unread(int(getattr(counts, "unread", 0) or 0))

    @staticmethod
    def _set_chip_alert(chip, alert: bool) -> None:
        """Flip a chip's badge state and make Qt actually restyle it.

        A dynamic property alone changes nothing on screen: Qt resolves the
        stylesheet once and does not re-run the selector until it is told the
        widget's properties moved. unpolish/polish is that telling.
        """
        if chip is None:
            return
        current = chip.property("chatAlert")
        # ``is not None`` and not a plain truthiness test: an unset property
        # reads as None, and skipping the write because "None is falsey, and
        # so is False" would leave the chip's style state undefined for the
        # whole session — fine until some later rule needs to select on it.
        if current is not None and bool(current) == bool(alert):
            return
        chip.setProperty("chatAlert", bool(alert))
        style = chip.style()
        style.unpolish(chip)
        style.polish(chip)
        chip.update()

    # ── notifications ─────────────────────────────────────────────────────────
    def _notifications_enabled(self) -> bool:
        """Operator preference, remembered across sessions.

        The sync engine uses it to decide whether a console hidden for more
        than fifteen minutes keeps a 45-second watch or stops entirely — so
        this is a polling decision, not only a cosmetic one.
        """
        try:
            value = self._settings().value("notifications/enabled", True)
        except Exception:
            return True
        if isinstance(value, str):
            return value.strip().lower() not in ("0", "false", "no", "off")
        return bool(value)

    def set_notifications_enabled(self, enabled: bool) -> None:
        try:
            self._settings().setValue("notifications/enabled", bool(enabled))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("aipacs_chat: could not persist notification pref: %s", exc)
        if self._repository is not None:
            self._repository.setNotificationsEnabled(bool(enabled))
        if not enabled and self._notifications is not None:
            self._notifications.clear()

    @Slot(object)
    def _on_events(self, events) -> None:
        """Announce what arrived while the operator was elsewhere."""
        if not events:
            return
        # Recorded even when banners are switched off, and even before the
        # first row page: this set is what stops the client-side detector
        # announcing a conversation the server has already spoken for.
        for event in events:
            case_id = int(getattr(event, "case", 0) or 0)
            if case_id:
                self._announced.add(case_id)

        if self._notifications is None or not self._notifications_enabled():
            return
        self._notifications.show_events(events)

    @Slot(int)
    def _on_notification_activated(self, case_id: int) -> None:
        """Open the conversation a banner refers to.

        By `case`, never by `event.url` — see notifications.py. Routed through
        the same handler as a click in the list so selection, the case panel
        and the composer all follow.
        """
        if not case_id:
            return
        self.conversation_list.select_case(case_id)
        self._on_case_activated(int(case_id))

    def _set_tab_unread(self, unread: int) -> None:
        """Show the unread count on this module's tab title.

        The console is a tab among many; a number that only exists inside the
        tab is a number nobody sees. Best-effort: the tab may be wrapped by
        the host's custom tab manager, so walk up until a widget the tab
        widget actually knows about is found.
        """
        if self._tab_unread == unread:
            return
        self._tab_unread = unread
        tabs = self._host_tab_widget
        if tabs is None:
            return
        try:
            index, widget = -1, self
            while widget is not None and index < 0:
                index = tabs.indexOf(widget)
                widget = widget.parentWidget()
            if index < 0:
                return
            base = self._tab_base_title or tabs.tabText(index) or "AiPacs Chat"
            # Remember the clean title once, or the count compounds:
            # "AiPacs Chat (2) (3)".
            if self._tab_base_title is None:
                self._tab_base_title = base.split("  (")[0]
                base = self._tab_base_title
            tabs.setTabText(index, f"{base}  ({unread})" if unread > 0 else base)
        except Exception as exc:  # pragma: no cover - cosmetic only
            logger.debug("aipacs_chat: tab badge failed: %s", exc)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        # A transient failure while the console is already usable must not
        # blank the screen — the operator keeps what they were reading and the
        # loop keeps retrying behind it.
        if self.stack.currentWidget() is self.page_content:
            return
        self.page_error.set_body(f"{message}\n\nRetrying automatically.")

    @Slot(str)
    def _on_auth_required(self, message: str) -> None:
        self.page_signed_out.set_body(
            f"{message}\n\nSign in again from the account menu, then press Try again."
        )

    @Slot(int)
    def _on_case_activated(self, case_id: int) -> None:
        if self._repository is None:
            return
        self._detail_retries = 0
        self._repository.openCase(case_id)

        # Keep the list in step. A conversation can be opened without being
        # clicked — from a notification banner, or a deep link — and the row
        # must end up selected either way.
        self.conversation_list.select_case(case_id)

        row = self.conversation_list.row_for_case(case_id)
        self.thread_header.setText(row.title if row is not None else f"Case #{case_id}")

        # Empty the transcript NOW rather than when the answer lands. Leaving
        # the previous patient's words on screen while the next conversation
        # loads is the one mistake this module must never make.
        self.transcript.replace([])
        self.typing_label.setText("")
        self.presence_label.setText("")
        self.composer.set_enabled_for_case(True)

        # Draw the panel from the row we already hold, BEFORE the request goes
        # out. Name, reference, status and presence are known on this machine
        # the moment the operator clicks; making them wait on a round trip is
        # what made a click look like it had done nothing.
        self.case_panel.set_preliminary(row)
        self._repository.loadCaseDetail(case_id)

    # ── thread signals ─────────────────────────────────────────────────────

    @Slot(int, object)
    def _on_thread_replaced(self, case_id: int, messages) -> None:
        if not self._is_open(case_id):
            return
        self.transcript.replace(messages)

    @Slot(int, object)
    def _on_messages_appended(self, case_id: int, messages) -> None:
        if not self._is_open(case_id):
            return
        self.transcript.append(messages)

    @Slot(int, object)
    def _on_messages_revised(self, case_id: int, messages) -> None:
        if not self._is_open(case_id):
            return
        self.transcript.apply_revised(messages)

    @Slot(int, bool, bool)
    def _on_presence(self, case_id: int, online: bool, typing: bool) -> None:
        if not self._is_open(case_id):
            return
        self.presence_label.setText("online" if online else "offline")
        self.presence_label.setStyleSheet(
            f"color:{tone_color('good' if online else 'done')}; font-size:11px;"
        )
        self.typing_label.setText("The patient is typing…" if typing else "")

    @Slot(int, object, object)
    def _on_receipts(self, case_id: int, read_at, seen_at) -> None:
        if not self._is_open(case_id):
            return
        # BOTH timestamps. ``seen_at`` was arriving on every sync and being
        # dropped on the floor here, which is why an outbound message only ever
        # had two states to show instead of the three the server publishes.
        self.transcript.set_receipts(read_at, seen_at)

    @Slot(int, str, str)
    def _on_case_status(self, case_id: int, status: str, tone: str) -> None:
        if not self._is_open(case_id):
            return
        self.case_panel.status_chip.setText(status.replace("_", " "))

    @Slot(object)
    def _on_case_detail(self, detail) -> None:
        if isinstance(detail, dict) and detail:
            if not self._is_open(int(detail.get("id") or 0)):
                return
            self._detail_retries = 0
            self.case_panel.set_case(detail)

    @Slot(int, str)
    def _on_case_detail_failed(self, case_id: int, message: str) -> None:
        """The side panel's own request failed.

        Guarded by case id like every other late answer: a fetch that failed
        for the conversation the operator has already left must not write an
        error over the one they are reading now.

        RETRIED ONCE, then reported. A 500 from this endpoint is usually not
        transient — it is the server failing to build the payload for that
        particular case — so retrying forever would be a request loop that
        never succeeds, and reporting immediately would blame the network for
        a server fault. One retry distinguishes the two.
        """
        if not self._is_open(int(case_id)):
            return
        if self._detail_retries < 1 and self._repository is not None:
            self._detail_retries += 1
            QTimer.singleShot(
                1200, lambda cid=int(case_id): self._retry_case_detail(cid)
            )
            return
        logger.warning(
            "aipacs_chat: case detail unavailable for case %s: %s", case_id, message
        )
        self.case_panel.set_error(message)

    def _retry_case_detail(self, case_id: int) -> None:
        # The operator may have moved on during the second the retry waited.
        if self._repository is not None and self._is_open(int(case_id)):
            self._repository.loadCaseDetail(int(case_id))

    @Slot()
    def _reload_case_detail(self) -> None:
        """The operator pressed Try again in the panel."""
        case_id = self._repository.open_case if self._repository else None
        if not case_id:
            return
        self._detail_retries = 0
        row = self.conversation_list.row_for_case(case_id)
        if row is not None:
            self.case_panel.set_preliminary(row)
        self._repository.loadCaseDetail(int(case_id))

    def _is_open(self, case_id: int) -> bool:
        """Guard every thread signal.

        The repository already drops an answer for a conversation the operator
        has left, but a case-detail fetch is a separate request with its own
        flight time — and painting the wrong patient into an open panel is the
        failure this whole module is most careful about.
        """
        return bool(self._repository) and self._repository.open_case == case_id

    # ── writes ─────────────────────────────────────────────────────────────

    @Slot(str)
    def _on_send(self, body: str) -> None:
        if self._repository is not None:
            self._repository.sendMessage(body)

    @Slot(str, object, bool)
    def _on_send_with_files(self, body: str, paths, is_report: bool) -> None:
        if self._repository is None:
            return
        count = len(paths or [])
        self.typing_label.setText(
            "Uploading 1 file…" if count == 1 else f"Uploading {count} files…"
        )
        self._repository.sendMessageWithFiles(body, list(paths or []), bool(is_report))

    @Slot(str)
    def _on_price(self, tier: str) -> None:
        if self._repository is not None:
            self._repository.sendPrice(tier)

    @Slot(str)
    def _on_status_change(self, status: str) -> None:
        if self._repository is not None:
            self._repository.setStatus(status)

    @Slot(bool)
    def _on_composer_text(self, has_text: bool) -> None:
        if self._repository is not None:
            self._repository.setComposerHasText(has_text)

    @Slot(int)
    def _on_edit_message(self, message_id: int) -> None:
        message = self.transcript.message_by_id(message_id)
        if message is None or self._repository is None:
            return
        body, accepted = QInputDialog.getMultiLineText(
            self, "Edit message", "The patient sees the correction, marked as edited.",
            message.body or "",
        )
        if accepted and body.strip() and body.strip() != (message.body or "").strip():
            self._repository.editMessage(message_id, body.strip())

    @Slot(int)
    def _on_remove_message(self, message_id: int) -> None:
        if self._repository is None:
            return
        # Confirmed HERE, not on the server: a POST that arrives has already
        # been confirmed, and asking twice would be a second round trip.
        answer = QMessageBox.question(
            self, "Withdraw message",
            "Withdraw this message?\n\nThe patient will see that a message was "
            "removed. This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._repository.removeMessage(message_id)

    @Slot(int, object)
    def _on_react(self, message_id: int, value) -> None:
        if self._repository is not None:
            self._repository.react(message_id, value)

    @Slot(int)
    def _on_pin_message(self, message_id: int) -> None:
        if self._repository is not None:
            self._repository.pinMessage(message_id)

    @Slot(int)
    def _on_email_message(self, message_id: int) -> None:
        if self._repository is None:
            return
        answer = QMessageBox.question(
            self, "Email this message",
            "Send this message to the patient's inbox?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._repository.emailMessage(message_id)

    @Slot()
    def _on_pin_case(self) -> None:
        case_id = self._repository.open_case if self._repository else None
        if case_id:
            self._repository.pinCase(case_id)

    @Slot()
    def _on_rotate_link(self) -> None:
        """Ask first. The old link stops working the moment this succeeds.

        A patient who is midway through uploading a study on the link they
        already have is cut off by this, so it is never a one-click action.
        """
        if self._repository is None:
            return
        answer = QMessageBox.question(
            self, "Issue a fresh access link",
            "Generate a new access link for this patient?\n\n"
            "The link they already have will stop working immediately, and the "
            "new one is shown ONCE — it is not stored anywhere.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._repository.rotateLink()

    def _show_rotated_link(self, link: str) -> None:
        """Shown once, copyable, never written down.

        Not put in the transcript, not logged, not stored in QSettings: it is a
        bearer credential for the whole conversation. The operator copies it
        into whatever channel they are already using with the patient.
        """
        text = str(link or "").strip()
        if not text:
            self.typing_label.setText("The server did not return a new link.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("New access link")
        box.setText(
            "This link is shown once. Copy it now — it is not stored anywhere "
            "in the workstation."
        )
        box.setDetailedText(text)
        box.setIcon(QMessageBox.Information)
        copy_button = box.addButton("Copy link", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is copy_button:
            QGuiApplication.clipboard().setText(text)
            self.typing_label.setText("The new link is on the clipboard.")

    @Slot(str)
    def _open_link(self, url: str) -> None:
        """Every http(s) link this module opens goes through the internal browser.

        The workstation has its own browser module and that is where AI-PACS
        pages belong — an operator sent out to Edge loses the session, the
        window arrangement and the audit trail. mailto: and tel: are the two
        exceptions: there is no internal client to hand those to.
        """
        target = str(url or "").strip()
        if not target:
            return
        if target.lower().startswith(("mailto:", "tel:")):
            QDesktopServices.openUrl(QUrl(target))
            return
        try:
            from modules.Identity.providers.google.oauth_flow import open_verification_url

            if open_verification_url(target):
                return
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("aipacs_chat: internal browser unavailable (%s)", exc)
        # Headless, or the browser module is not installed in this build.
        QDesktopServices.openUrl(QUrl(target))

    @Slot(int, str)
    def _on_attachment(self, file_id: int, file_name: str) -> None:
        """The operator clicked an attachment chip.

        Nothing is opened here — the repository answers with ``fileDownloaded``
        once the bytes are on disk, and a copy already downloaded comes back
        just as fast without a second request.
        """
        if self._repository is None:
            return
        self.typing_label.setText(f"Opening {file_name}…")
        self._repository.downloadFile(int(file_id), str(file_name or ""))

    @Slot(int, object)
    def _on_file_downloaded(self, file_id: int, path) -> None:
        """Hand the file to whatever Windows opens it with.

        NOT the workstation's internal browser. That rule is about LINKS — a
        page on ai-pacs.com belongs inside the application. This is a file the
        patient sent: a DICOM, a PDF, a phone photo. The operator's own viewer
        is the right program for it, and forcing a browser in between would
        mean a DICOM opened as a download prompt.
        """
        self.typing_label.setText("")
        if not path:
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if not opened:
            # Windows has no handler for this extension. The bytes are still
            # on disk, so say where — that is more useful than "failed".
            self.typing_label.setText(f"Saved to {path}")
            logger.info("aipacs_chat: no handler for attachment %s (%s)", file_id, path)

    @Slot(str, object)
    def _on_write_succeeded(self, kind: str, payload) -> None:
        if kind == "send":
            self.composer.confirm_sent()
            # Clears an "Uploading…" strip that would otherwise sit there until
            # the next presence update overwrote it.
            self.typing_label.setText("")
        if kind == "rotate_link":
            self._show_rotated_link(payload if isinstance(payload, str) else "")
        if kind in ("pin_message", "pin_case", "status", "price", "email"):
            # None of these travel on the poll — a pin is written quietly and a
            # status change lands on the case, not the transcript — so the
            # panel is refetched rather than waited on.
            case_id = self._repository.open_case if self._repository else None
            if case_id:
                self._repository.loadCaseDetail(case_id)

    @Slot(str, str)
    def _on_write_failed(self, kind: str, message: str) -> None:
        if kind == "send":
            # Nothing is ever lost to a dropped packet.
            self.composer.restore_pending()
        self.typing_label.setText(f"Could not {kind.replace('_', ' ')}: {message}")

    def _on_retry_clicked(self) -> None:
        if self._repository is not None:
            self._repository.retryAfterSignIn()

    def _apply_search(self) -> None:
        # One place changes the filter model (`_set_filters`), so the search
        # box and the chips can never overwrite each other's group.
        self._set_filters(term=self.search_box.text())

    # ── visibility ─────────────────────────────────────────────────────────

    def _is_really_visible(self) -> bool:
        """Current tab, active window, not minimised.

        Deliberately strict. Over-reporting visibility would tell a patient
        their message had been read because a background tab happened to poll,
        and two ticks on a message nobody read is the most corrosive thing this
        feature could do.
        """
        if self._closing or not self.isVisible():
            return False

        window = self.window()
        if window is None:
            return False
        if window.isMinimized() or not window.isActiveWindow():
            return False

        tabs = self._host_tab_widget
        if tabs is not None:
            try:
                return tabs.currentWidget() is self
            except Exception:
                return True

        return True

    def _push_visibility(self) -> None:
        if self._repository is not None:
            self._repository.setVisible(self._is_really_visible())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._push_visibility()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._push_visibility()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.ActivationChange, QEvent.WindowStateChange):
            self._push_visibility()

    # ── theming ────────────────────────────────────────────────────────────

    def _on_theme_changed(self, tokens=None) -> None:
        self._apply_theme(tokens)

    def _apply_theme(self, tokens=None) -> None:
        t = tokens if isinstance(tokens, dict) and tokens else theme_tokens()
        try:
            self.setStyleSheet(
                shell_qss(t) + pane_qss(t) + counts_chip_qss(t) + composer_qss(t)
            )
            if hasattr(self, "conversation_list"):
                self.conversation_list.set_theme(t)
            if hasattr(self, "transcript"):
                self.transcript.set_theme(t)
            if hasattr(self, "case_panel"):
                self.case_panel.set_theme(t)
        except Exception as exc:  # pragma: no cover
            logger.debug("aipacs_chat: theme apply failed: %s", exc)

    # ── teardown ───────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Called by the tab manager on close. Safe to call twice.

        Stops the loop and DETACHES anything in flight — it never waits. A
        request against a 15-second timeout would freeze the close, and the
        operator would reasonably decide the application had hung.
        """
        if self._closing:
            return
        self._closing = True
        self._save_event_cursor()
        self._save_splitter()
        if self._repository is not None:
            self._repository.setVisible(False)
            self._repository.stop()

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)
