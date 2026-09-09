"""No devices or network: verify printer contracts using synthetic transports."""
from types import SimpleNamespace
import pytest
from pydicom.dataset import Dataset


@pytest.fixture
def transport(monkeypatch):
    import pynetdicom
    from modules.printing.printers import dicom_printer as mod
    calls = []
    status = Dataset()
    status.Status = 0
    box = Dataset()
    ref = Dataset()
    ref.ReferencedSOPInstanceUID = "1.2.3.4"
    box.ReferencedImageBoxSequence = [ref]
    class Association:
        is_established = True
        accepted_contexts = [SimpleNamespace(abstract_syntax="1.2.840.10008.5.1.1.9")]
        def send_n_create(self, ds, **kw):
            calls.append(("create", dict(kw, dataset=ds)))
            return status, box
        def send_n_set(self, ds, **kw):
            calls.append(("set", kw))
            return status, None
        def send_n_action(self, ds, **kw):
            calls.append(("action", kw))
            return status, None
        def release(self):
            calls.append(("release", {}))
    class AE:
        def __init__(self, *args, **kwargs):
            calls.append(("ae", kwargs))
        def add_requested_context(self, *args):
            calls.append(("context", args))
        def associate(self, *args, **kwargs):
            return Association()
    monkeypatch.setattr(pynetdicom, "AE", AE)
    settings = mod.DicomPrinterSettings("127.0.0.1", 104, "TEST")
    settings.local_ae_title = "SYNTHETIC_SCU"
    job = mod.DicomPrintJob([mod.DicomImagePayload(2, 2, b"\x00" * 4)])
    return SimpleNamespace(mod=mod, calls=calls, handler=mod.DicomPrintHandler(settings), job=job, box=box, status=status)


def test_local_ae_and_meta_context_are_used(transport):
    t = transport
    assert t.handler.send_print_job(t.job)
    assert t.calls[0] == ("ae", {"ae_title": "SYNTHETIC_SCU"})
    for kind, kw in t.calls:
        if kind in {"create", "set", "action"}:
            assert kw["meta_uid"] == "1.2.840.10008.5.1.1.9"
    assert t.calls[-1][0] == "release"


def test_missing_image_box_aborts_without_inventing_uid(transport):
    t = transport
    t.box.ReferencedImageBoxSequence = []
    assert not t.handler.send_print_job(t.job)
    assert not any(kind in {"set", "action"} for kind, _ in t.calls)
    assert t.calls[-1][0] == "release"


def test_empty_status_is_a_controlled_failure(transport):
    del transport.status.Status
    assert not transport.handler.send_print_job(transport.job)
    assert transport.calls[-1][0] == "release"


def test_default_transfer_syntax_is_offered(transport):
    transport.handler.send_print_job(transport.job)
    for kind, args in transport.calls:
        if kind == "context":
            syntaxes = args[1] if isinstance(args[1], list) else [args[1]]
            assert "1.2.840.10008.1.2" in syntaxes


def test_status_detail_retains_failed_operation(transport):
    transport.status.Status = 0xC600
    assert not transport.handler.send_print_job(transport.job)
    assert transport.handler.last_result.operation == "Create film session"
    assert transport.handler.last_result.status == 0xC600


@pytest.mark.parametrize("title", ["X" * 17, "BAD\\TITLE", "", "BAD\nTITLE"])
def test_invalid_ae_is_rejected_before_network(transport, title):
    transport.handler.settings.ae_title = title
    assert not transport.handler.send_print_job(transport.job)
    assert not transport.calls
    assert transport.handler.last_result.operation == "Validate settings"


def test_malformed_pixel_payload_is_rejected_before_network(transport):
    transport.job.images[0].pixel_data = b"\x00"
    assert not transport.handler.send_print_job(transport.job)
    assert not transport.calls


def test_unspecified_smoothing_is_not_sent(transport):
    assert transport.handler.send_print_job(transport.job)
    film_box = [kw["dataset"] for kind, kw in transport.calls if kind == "create"][1]
    assert "SmoothingType" not in film_box


@pytest.mark.parametrize("code", [0xB604, 0xB605, 0xB609, 0xB60A])
def test_quality_warning_preserves_code_and_prevents_action(transport, code):
    transport.status.Status = code
    assert not transport.handler.send_print_job(transport.job)
    assert transport.handler.last_result.status == code
    assert not any(kind == "action" for kind, _ in transport.calls)


@pytest.mark.parametrize("end_ok,state,expected", [(False,0,False),(True,1,False),(True,2,False),(True,0,True)])
def test_os_checks_end_and_printer_state(monkeypatch, end_ok, state, expected):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import QRect
    from modules.printing.printers import os_printer as mod
    app = QApplication.instance() or QApplication([])
    class Printer:
        HighResolution = 1
        Error, Aborted = 1, 2
        def __init__(self, *args): pass
        def printerState(self): return state
    class Dialog:
        Accepted = 1
        def __init__(self, *args): pass
        def exec(self): return 1
    class Painter:
        def __init__(self, *args): pass
        def isActive(self): return True
        def viewport(self): return QRect(0,0,100,100)
        def drawPixmap(self, *args): pass
        def end(self): return end_ok
    monkeypatch.setattr(mod, "QPrinter", Printer)
    monkeypatch.setattr(mod, "QPrintDialog", Dialog)
    monkeypatch.setattr(mod, "QPainter", Painter)
    assert mod.OSPrinterHandler().print_film(QPixmap(2,2)) is expected


def test_os_printer_receives_physical_page_size(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPixmap, QPageSize
    from modules.printing.core.models import FilmSize
    from modules.printing.printers import os_printer as mod
    app = QApplication.instance() or QApplication([])
    sizes = []
    from PySide6.QtGui import QPageLayout
    class Printer:
        HighResolution = 1
        def __init__(self, mode):
            self.layout = QPageLayout()
        def setPageSize(self, size):
            self.layout.setPageSize(size)
        def pageLayout(self):
            return self.layout
    monkeypatch.setattr(mod, "QPrinter", Printer)
    class Dialog:
        Accepted = 1
        def __init__(self, printer):
            sizes.append(printer.pageLayout().pageSize().size(QPageSize.Inch))
        def exec(self):
            return 0  # Cancel before opening any device.
    monkeypatch.setattr(mod, "QPrintDialog", Dialog)
    mod.OSPrinterHandler().print_film(QPixmap(5, 5), film_size=FilmSize("A4", 8.27, 11.69))
    assert sizes[0].width() == pytest.approx(8.27, abs=0.02)
    assert sizes[0].height() == pytest.approx(11.69, abs=0.02)
