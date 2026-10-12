"""Small composed-content editor and renderer; DICOM stays in its own domain."""
import html
import re
from html.parser import HTMLParser

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCharFormat, QTextListFormat, QColor, QTextCursor
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
    QFontComboBox, QSpinBox, QPushButton, QTextEdit, QTextBrowser, QLabel, QColorDialog)

LAYOUTS = [('Title and text', 'text'), ('Text / media right', 'right'),
    ('Media left / text', 'left'), ('Text above media', 'below'),
    ('Media above text', 'above'), ('Media only', 'media')]
THEMES = {'Clinical Dark': ('#172c43', '#edf3fa'),
    'Clean Light': ('#fafbfe', '#172c43'), 'Conference Teal': ('#103d42', '#effbf9')}


def media_kind(path):
    from pathlib import Path
    suffix = Path(path).suffix.lower()
    if suffix in {'.png','.jpg','.jpeg','.bmp','.tif','.tiff'}: return 'image'
    if suffix in {'.wav','.mp3','.ogg','.m4a','.aac'}: return 'audio'
    if suffix in {'.mp4','.avi','.mov','.mkv','.wmv'}: return 'video'
    raise ValueError('Unsupported multimedia file')


def safe_rich_text(value):
    """Permit formatting only, never embedded resources, scripts or links."""
    class Cleaner(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out = []
            self.hidden = 0

        def handle_starttag(self, tag, attrs):
            if tag in {'script', 'style'}:
                self.hidden += 1
            if self.hidden or tag not in {'p','br','b','strong','i','em','u','ul','ol','li','span','h1','h2','h3','div'}:
                return
            styles = []
            for key, value in attrs:
                if key != 'style':
                    continue
                for pair in str(value).split(';'):
                    name, _, val = pair.partition(':')
                    if name.strip() in {'font-family','font-size','font-weight','font-style',
                            'text-decoration','color','text-align','margin-left','margin-top','margin-bottom'} and re.fullmatch(r"[\w #.,%'\-]+", val.strip()):
                        styles.append(name.strip()+':'+val.strip())
            self.out.append('<'+tag+(' style="'+html.escape(';'.join(styles),quote=True)+'"' if styles else '')+'>')

        def handle_endtag(self, tag):
            if tag in {'script','style'}:
                self.hidden = max(0, self.hidden-1)
            elif not self.hidden and tag in {'p','b','strong','i','em','u','ul','ol','li','span','h1','h2','h3','div'}:
                self.out.append('</'+tag+'>')

        def handle_data(self, data):
            if not self.hidden:
                self.out.append(html.escape(data))
    parser = Cleaner()
    parser.feed(str(value)[:200000])
    return ''.join(parser.out)


class TeachingTextEdit(QTextEdit):
    def insertFromMimeData(self, source):
        if source.hasHtml():
            self.textCursor().insertHtml(safe_rich_text(source.html()))
        else:
            self.insertPlainText(source.text())


class SlideContentEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        choices = QHBoxLayout()
        self.layout_choice = QComboBox()
        for name,key in LAYOUTS:
            self.layout_choice.addItem(name,key)
        self.layout_choice.setCurrentIndex(1)
        self.theme = QComboBox()
        self.theme.addItems(THEMES)
        self.title_position = QComboBox()
        for label,key in [('Title above','above'),('Title below','below'),('No title','none')]:
            self.title_position.addItem(label,key)
        for widget in (self.layout_choice,self.theme,self.title_position):
            choices.addWidget(widget)
        self.background = '#172c43'
        self.foreground = '#edf3fa'
        self.theme.currentTextChanged.connect(self._theme)
        background = QPushButton('Background')
        background.clicked.connect(self._background)
        choices.addWidget(background)
        layout.addLayout(choices)
        self.toolbar = QWidget()
        tools = QHBoxLayout(self.toolbar)
        tools.setContentsMargins(0,0,0,0)
        self.body = TeachingTextEdit()
        self.body.setMinimumHeight(140)
        self.body.setPlaceholderText('Optional teaching text. Add media using Select File.')
        font = QFontComboBox()
        font.setMaximumWidth(145)
        font.currentFontChanged.connect(lambda f:self._format(font=f.family()))
        tools.addWidget(font)
        size = QSpinBox()
        size.setRange(8,72)
        size.setValue(24)
        size.valueChanged.connect(lambda v:self._format(size=v))
        tools.addWidget(size)
        for label,key in [('B','bold'),('I','italic'),('Heading','heading'),('Bullets','bullets'),('1. List','numbered')]:
            button = QPushButton(label)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda checked=False,k=key:self._format(**{k:True}))
            tools.addWidget(button)
        layout.addWidget(self.toolbar)
        self.alignment_tools = QWidget()
        alignment = QHBoxLayout(self.alignment_tools)
        alignment.setContentsMargins(0,0,0,0)
        for label, flag in [('Left',Qt.AlignLeft),('Center',Qt.AlignHCenter),('Right',Qt.AlignRight)]:
            button = QPushButton(label)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda checked=False,f=flag:self.body.setAlignment(f))
            alignment.addWidget(button)
        color = QPushButton('Text Color')
        color.clicked.connect(self._text_color)
        alignment.addWidget(color)
        layout.addWidget(self.alignment_tools)
        layout.addWidget(self.body)
        self.hint = QLabel('Media is optional. Clear media to keep text only.')
        layout.addWidget(self.hint)

    def _theme(self, name):
        self.background,self.foreground = THEMES[name]

    def _background(self):
        color = QColorDialog.getColor(QColor(self.background),self,'Slide background')
        if color.isValid():
            self.background = color.name()

    def _text_color(self):
        color = QColorDialog.getColor(QColor(self.foreground),self,'Text color')
        if color.isValid():
            self.body.setTextColor(color)

    def _format(self, **values):
        cursor = self.body.textCursor()
        char = QTextCharFormat()
        if 'font' in values: char.setFontFamilies([values['font']])
        if 'size' in values: char.setFontPointSize(values['size'])
        if 'bold' in values: char.setFontWeight(QFont.Normal if cursor.charFormat().fontWeight()>=QFont.Bold else QFont.Bold)
        if 'italic' in values: char.setFontItalic(not cursor.charFormat().fontItalic())
        if 'heading' in values: char.setFontPointSize(32); char.setFontWeight(QFont.Bold)
        cursor.mergeCharFormat(char)
        self.body.mergeCurrentCharFormat(char)
        if 'bullets' in values or 'numbered' in values:
            form = QTextListFormat()
            form.setStyle(QTextListFormat.ListDecimal if 'numbered' in values else QTextListFormat.ListDisc)
            cursor.createList(form)
        self.body.setFocus()

    def document_mode(self, enabled):
        self.body.setVisible(not enabled)
        self.toolbar.setVisible(not enabled)
        self.alignment_tools.setVisible(not enabled)
        self.layout_choice.setVisible(not enabled)
        self.hint.setVisible(not enabled)

    def load(self, data):
        if data.get('rich_text'):
            self.body.setHtml(safe_rich_text(data['rich_text']))
        else:
            self.body.setPlainText(str(data.get('text') or ''))
        self.layout_choice.setCurrentIndex(max(0,self.layout_choice.findData(data.get('layout','right'))))
        self.title_position.setCurrentIndex(max(0,self.title_position.findData(data.get('title_position','above'))))
        for key,default in [('background','#172c43'),('foreground','#edf3fa')]:
            color = str(data.get(key,default))
            setattr(self,key,color if re.fullmatch(r'#[0-9a-fA-F]{6}',color) else default)

    def payload(self):
        return {'text':self.body.toPlainText(),'rich_text':safe_rich_text(self.body.toHtml()),
            'layout':self.layout_choice.currentData(),'title_position':self.title_position.currentData(),
            'background':self.background,'foreground':self.foreground}


class SlideContentFrame(QWidget):
    """Compose the existing media stack with a formatted text region."""
    def __init__(self, media, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.outer = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        self.title.setStyleSheet('font-size:24px;font-weight:600;')
        self.outer.addWidget(self.title)
        self.host = QWidget()
        self.host.setStyleSheet('background:transparent;')
        self.outer.addWidget(self.host,1)
        self.row = QHBoxLayout(self.host)
        self.row.setContentsMargins(0,0,0,0)
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.setOpenExternalLinks(False)
        self.text.setStyleSheet('background:transparent;border:0;')
        self.media = media
        self.row.addWidget(self.text,1)
        self.row.addWidget(media,1)
        self.reset()

    def reset(self):
        self._text_zoom_steps = 0
        self._original_html = ''
        self.title.hide()
        self.text.hide()
        self.media.show()
        self.setStyleSheet('')

    def present(self, data, document=False):
        self.reset()
        bg = str(data.get('background','#172c43'))
        fg = str(data.get('foreground','#edf3fa'))
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',bg): bg='#172c43'
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',fg): fg='#edf3fa'
        self.setStyleSheet('SlideContentFrame {background:'+bg+';color:'+fg+';}')
        self.text.setStyleSheet('background:transparent;border:0;color:'+fg+';font-size:24px;')
        self.title.setStyleSheet('background:transparent;font-size:24px;font-weight:600;color:'+fg+';')
        self.title.setText(str(data.get('name') or ''))
        position = data.get('title_position','above')
        self.outer.removeWidget(self.title)
        self.outer.insertWidget(0 if position!='below' else 1,self.title)
        self.title.setVisible(position!='none' and bool(self.title.text()))
        if document:
            return
        self.text.setHtml(safe_rich_text(data.get('rich_text')) if data.get('rich_text') else html.escape(str(data.get('text') or '')).replace('\n','<br>'))
        mode = data.get('layout','right')
        self.row.setDirection(QHBoxLayout.TopToBottom if mode in {'below','above'} else QHBoxLayout.LeftToRight)
        self.row.removeWidget(self.text)
        self.row.removeWidget(self.media)
        first,second = (self.media,self.text) if mode in {'left','above'} else (self.text,self.media)
        self.row.addWidget(first,1)
        self.row.addWidget(second,1)
        self.media.setVisible(bool(data.get('path')) and mode!='text')
        self.text.setVisible(bool(str(data.get('text') or '').strip()) and
            (mode!='media' or not data.get('path')))
        self._original_html = self.text.toHtml()

    def can_zoom_text(self):
        return not self.text.isHidden() or not self.title.isHidden()

    def zoom_text(self, step):
        """Scale displayed typography without changing course content or media zoom."""
        if not self.can_zoom_text():
            return
        self._text_zoom_steps = max(-5, min(10, self._text_zoom_steps + (1 if step > 0 else -1)))
        scale = 1.1 ** self._text_zoom_steps
        self.title.setStyleSheet(re.sub(r'font-size:[\d.]+px',
            f'font-size:{24 * scale:.3f}px', self.title.styleSheet()))
        if not self._original_html:
            return
        scroll = self.text.verticalScrollBar().value()
        self.text.setHtml(self._original_html)
        if self._text_zoom_steps:
            document = self.text.document()
            block = document.begin()
            runs = []
            while block.isValid():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid():
                        fmt = fragment.charFormat()
                        font = fmt.font().resolve(document.defaultFont())
                        size = font.pointSizeF()
                        if size <= 0:
                            size = font.pixelSize() * 72 / self.text.logicalDpiY()
                        runs.append((fragment.position(), fragment.length(), size))
                    iterator += 1
                block = block.next()
            for position, length, size in runs:
                cursor = QTextCursor(document)
                cursor.setPosition(position)
                cursor.setPosition(position + length, QTextCursor.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setFontPointSize(size * scale)
                cursor.mergeCharFormat(fmt)
        self.text.verticalScrollBar().setValue(scroll)
