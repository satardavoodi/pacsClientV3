"""Synthetic Home image-I/O ownership; no clinical data, DB or sockets."""
import asyncio
import base64
import threading
import time

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel
from qasync import QEventLoop
from shiboken6 import delete, isValid

from PacsClient.pacs.workstation_ui.home_ui import right_panel_widget as module
from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService as Images


def image_bytes(color):
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(color)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(buffer.data())


def payload(path, count=3, suffix='a'):
    return [dict(study_uid='synthetic-study', series_uid=f'{suffix}-{i}',
                 series_number=str(i), file_path=str(path), image_count=2)
            for i in range(count)]


@pytest.fixture
def home(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    widget = module.RightPanelWidget()
    builds = []
    monkeypatch.setattr(module, '_inside_input_synchronous_dispatch', lambda: False)
    monkeypatch.setattr(widget, '_new_action_thumbnail_manager', lambda: object())
    def build(manager, pixmap, thumb, ordinal):
        builds.append((thumb['series_uid'], threading.get_ident(), pixmap.toImage().pixelColor(0, 0).name()))
        return QLabel('Synthetic card', widget.content_widget)
    monkeypatch.setattr(widget, '_create_action_thumbnail', build)
    path = tmp_path / 'source.png'
    path.write_bytes(image_bytes('#ff0000'))
    yield widget, loop, path, builds
    if isValid(widget):
        widget.clear_content()
        delete(widget)
    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)


async def until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        await asyncio.sleep(.005)
    assert predicate(), 'Synthetic Home render did not finish'


@pytest.mark.parametrize('progressive,count', [(False, 3), (True, 19)])
def test_real_render_does_not_read_pixmap_files_on_gui(home, monkeypatch, progressive, count):
    widget, loop, path, builds = home
    reads = []
    class Pixmap:
        def __new__(cls, *args):
            if args and isinstance(args[0], str):
                reads.append(threading.get_ident())
            return QPixmap(*args)
        fromImage = staticmethod(QPixmap.fromImage)
    monkeypatch.setattr(module, 'QPixmap', Pixmap)
    records = payload(path, count)
    async def run():
        widget.display_thumbnails(records, progressive=progressive)
        await until(lambda: len(builds) == count)
        assert reads == [], 'Home render performed synchronous QPixmap(path) I/O'
        assert all(t == threading.get_ident() and color == '#ff0000' for _, t, color in builds)
        assert [uid for uid, _, _ in builds] == [r['series_uid'] for r in records]
        assert all(not any(k.startswith('_home_') for k in r) for r in records)
    with loop:
        loop.run_until_complete(run())


@pytest.mark.parametrize('progressive', [False, True])
@pytest.mark.parametrize('retire', ['clear', 'delete'])
def test_slow_preparation_yields_and_cannot_publish_after_retirement(home, monkeypatch, progressive, retire):
    widget, loop, path, builds = home
    entered, release = threading.Event(), threading.Event()
    threads = []
    def prepare(thumb, file_path=None):
        threads.append(threading.get_ident())
        entered.set()
        release.wait(2)
        return QImage(str(path))
    monkeypatch.setattr(Images, 'prepare_home_image', staticmethod(prepare), raising=False)
    async def run():
        widget.display_thumbnails(payload(path), progressive=progressive)
        await until(entered.is_set)
        assert threads[0] != threading.get_ident()
        assert builds == []
        if retire == 'delete':
            delete(widget)
        else:
            widget.clear_content()
        release.set()
        await asyncio.sleep(.08)
        assert builds == []
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()


@pytest.mark.parametrize('progressive', [False, True])
def test_hidden_home_pauses_image_preparation_and_resumes_without_losing_cards(
        home, monkeypatch, progressive):
    """A patient tab must not compete with the hidden Home thumbnail producer."""
    widget, loop, path, builds = home
    first_started = threading.Event()
    release_first = threading.Event()
    reads = []
    original = Images.prepare_home_image

    def prepare(thumb, file_path=None):
        reads.append(thumb['series_uid'])
        if len(reads) == 1:
            first_started.set()
            release_first.wait(2)
        return original(thumb, file_path)

    monkeypatch.setattr(Images, 'prepare_home_image', staticmethod(prepare))

    async def run():
        widget.show()
        widget.display_thumbnails(payload(path, count=5), progressive=progressive)
        await until(first_started.is_set)

        # Switching from Home to a patient tab hides this panel. Only the
        # already-admitted read may finish; no further disk work may start.
        widget.hide()
        release_first.set()
        await asyncio.sleep(.1)
        assert reads == ['a-0']
        assert builds == []

        # Returning Home resumes the same generation and publishes every card
        # exactly once; suspension must not discard selection state or pixels.
        widget.show()
        await until(lambda: len(builds) == 5)
        assert reads == [f'a-{i}' for i in range(5)]
        assert [uid for uid, _, _ in builds] == reads

    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release_first.set()


@pytest.mark.parametrize('key', ['thumbnail_data', 'thumbnail_base64', 'thumbnailBase64',
                               'thumbnailData', 'image_data', 'imageBase64'])
def test_home_source_keeps_file_first_then_embedded_fallback(tmp_path, key):
    path = tmp_path / 'thumb.png'
    path.write_bytes(image_bytes('#ff0000'))
    record = {key: base64.b64encode(image_bytes('#0000ff')).decode(), 'file_path': str(path)}
    assert Images.prepare_home_image(record).pixelColor(0, 0).name() == '#ff0000'
    path.write_bytes(b'broken synthetic PNG')
    assert Images.prepare_home_image(record).pixelColor(0, 0).name() == '#0000ff'


def test_large_grouped_preparation_is_bounded_and_source_less_rows_do_not_deadlock(home, monkeypatch):
    widget, loop, path, builds = home
    records = payload(path, 141)
    for i, record in enumerate(records):
        record['study_uid'] = f'synthetic-study-{i // 47}'
        record['series_number'] = str(i % 47)
    records[0]['file_path'] = ''
    records[1]['file_path'] = ''
    reads = []
    original = Images.prepare_home_image
    def prepare(thumb, file_path=None):
        reads.append(threading.get_ident())
        return original(thumb, file_path)
    monkeypatch.setattr(Images, 'prepare_home_image', staticmethod(prepare))
    async def run():
        widget.display_thumbnails(records, progressive=True)
        await until(lambda: widget.thumbnail_timer is not None)
        widget.thumbnail_timer.stop()
        await until(lambda: widget._home_image_preparation['buffered'] == 2)
        await asyncio.sleep(.05)
        assert len(reads) == 2, 'Do not prepare all large-series images ahead of the UI'
        widget.thumbnail_timer.start(1)  # Exercise scale without 141 legacy 120-ms delays.
        await until(lambda: len(builds) == 139)
        await until(lambda: widget.thumbnail_timer is None)
        assert [uid for uid, _, _ in builds] == [r['series_uid'] for r in records[2:]]
        assert widget.content_grid.count() == 142  # 139 cards plus three study headers.
        assert widget._home_image_preparation['buffered'] == 0
    with loop:
        loop.run_until_complete(run())


@pytest.mark.parametrize('progressive', [False, True])
def test_superseded_worker_only_publishes_latest_identity(home, monkeypatch, progressive):
    widget, loop, path, builds = home
    entered, release = threading.Event(), threading.Event()
    original = Images.prepare_home_image
    def prepare(thumb, file_path=None):
        if thumb['series_uid'].startswith('old'):
            entered.set()
            release.wait(2)
        return original(thumb, file_path)
    monkeypatch.setattr(Images, 'prepare_home_image', staticmethod(prepare))
    async def run():
        widget.display_thumbnails(payload(path, suffix='old'), progressive=progressive)
        await until(entered.is_set)
        widget.display_thumbnails(payload(path, suffix='new'), progressive=progressive)
        release.set()
        await until(lambda: len(builds) == 3)
        await asyncio.sleep(.05)
        assert [uid for uid, _, _ in builds] == ['new-0', 'new-1', 'new-2']
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()


def test_cancel_before_first_coroutine_tick_disconnects_destroy_callback(home):
    widget, loop, path, builds = home
    from PacsClient.pacs.patient_tab.utils.thumbnail_batch_runner import prepare_home_thumbnails
    async def run():
        # PySide installs one internal destruction observer on the first Python
        # connection (also present after a plain connect/disconnect on QWidget).
        sentinel = lambda *_args: None
        widget.destroyed.connect(sentinel)
        widget.destroyed.disconnect(sentinel)
        before = widget.receivers('2destroyed(QObject*)')
        for _ in range(10):
            prepare_home_thumbnails(widget, payload(path), widget._display_generation, progressive=True)
            widget.clear_content()
            await asyncio.sleep(.005)
            assert widget.receivers('2destroyed(QObject*)') == before
        assert builds == []
    with loop:
        loop.run_until_complete(run())


@pytest.mark.parametrize('raw_kind', ['bytes', 'bytearray', 'data_url', 'unpadded'])
def test_embedded_input_formats_preserve_pixels(raw_kind):
    data = image_bytes('#0000ff')
    raw = {'bytes': data, 'bytearray': bytearray(data),
           'data_url': 'data:image/png;base64,' + base64.b64encode(data).decode(),
           'unpadded': base64.urlsafe_b64encode(data).decode().rstrip('=')}[raw_kind]
    assert Images.prepare_home_image({'thumbnail_data': raw}).pixelColor(0, 0).name() == '#0000ff'


def test_small_same_identity_refresh_retains_cards_until_images_ready(home, monkeypatch):
    widget, loop, path, builds = home
    entered, release = threading.Event(), threading.Event()
    original = Images.prepare_home_image
    def prepare(thumb, file_path=None):
        entered.set()
        release.wait(2)
        return original(thumb, file_path)
    async def run():
        records = payload(path)
        widget.display_thumbnails(records, progressive=False)
        await until(lambda: len(builds) == 3)
        old_card = widget.content_grid.itemAt(0).widget()
        monkeypatch.setattr(Images, 'prepare_home_image', staticmethod(prepare))
        revised = [dict(record, image_count=420) for record in records]
        widget.display_thumbnails(revised, progressive=False)
        await until(entered.is_set)
        assert widget.content_grid.itemAt(0).widget() is old_card
        release.set()
        await until(lambda: len(builds) == 6)
        assert widget.content_grid.itemAt(0).widget() is not old_card
        assert widget.count_label.text() == '3 series'
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()


@pytest.mark.parametrize('progressive', [False, True])
def test_worker_failure_preserves_placeholder_and_completes(home, monkeypatch, progressive):
    widget, loop, path, builds = home
    def prepare(*args):
        raise OSError('synthetic read failure')
    monkeypatch.setattr(Images, 'prepare_home_image', staticmethod(prepare))
    async def run():
        widget.display_thumbnails(payload(path), progressive=progressive)
        await until(lambda: len(builds) == 3)
        await until(lambda: widget.count_label.text() == '3 series')
        assert widget._home_image_preparation['buffered'] == 0
    with loop:
        loop.run_until_complete(run())
