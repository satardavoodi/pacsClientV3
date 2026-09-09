"""DICOM Print Management SCU and bounded background submission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List
import re

from pydicom.dataset import Dataset
from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian, generate_uid
from PySide6.QtCore import QObject, QRunnable, Signal

BASIC_FILM_SESSION_UID = "1.2.840.10008.5.1.1.1"
BASIC_FILM_BOX_UID = "1.2.840.10008.5.1.1.2"
BASIC_GRAYSCALE_IMAGE_BOX_UID = "1.2.840.10008.5.1.1.4"
PRINTER_SOP_UID = "1.2.840.10008.5.1.1.16"
GRAYSCALE_META_UID = "1.2.840.10008.5.1.1.9"


@dataclass
class DicomPrinterSettings:
    ip_address: str
    port: int
    ae_title: str
    local_ae_title: str = "AIPACS"


@dataclass(frozen=True)
class PrintResult:
    accepted: bool
    operation: str
    status: int | None = None
    detail: str = ""

    def __bool__(self):
        return self.accepted

    @property
    def message(self):
        code = f" (0x{self.status:04X})" if self.status is not None else ""
        return f"{self.operation}{code}: {self.detail}"


class DicomPrintHandler:
    def __init__(self, settings: DicomPrinterSettings):
        self.settings = settings
        self.last_result = PrintResult(False, "Prepare job", detail="Not submitted")

    def _status_ok(self, status, operation):
        code = getattr(status, "Status", None)
        descriptions = {
            0xB600: "Printer returned a memory allocation warning",
            0xB604: "Printer demagnified the image",
            0xB605: "Printer substituted its supported density limits",
            0xB609: "Printer cropped the image",
            0xB60A: "Printer decimated the image",
        }
        accepted = code == 0
        detail = "Accepted" if accepted else descriptions.get(code, "Request failed" if code is not None else "No response; acceptance is unconfirmed")
        self.last_result = PrintResult(accepted, operation, code, detail)
        # Do not silently accept altered image quality or retransmit a print.
        return accepted

    def send_print_job(self, payload: "DicomPrintJob") -> bool:
        self.last_result = PrintResult(False, "Validate settings", detail="Invalid printer settings or grayscale payload")
        titles = (self.settings.ae_title, self.settings.local_ae_title)
        if any(not isinstance(t, str) or not t.strip() or len(t) > 16
               or any(ord(c) < 32 or ord(c) > 126 or c == "\\" for c in t) for t in titles):
            return False
        if not self.settings.ip_address.strip() or not 1 <= self.settings.port <= 65535:
            return False
        if payload.number_of_copies < 1 or payload.film_orientation not in {"PORTRAIT", "LANDSCAPE"}:
            return False
        if payload.film_destination not in {"PROCESSOR", "MAGAZINE"} and not re.fullmatch(r"BIN_[1-9][0-9]*", payload.film_destination):
            return False
        if not payload.images or any(
            not 1 <= image.rows <= 65535 or not 1 <= image.columns <= 65535
            or image.samples_per_pixel != 1 or image.pixel_representation != 0
            or image.photometric_interpretation not in {"MONOCHROME1", "MONOCHROME2"}
            or (image.bits_allocated, image.bits_stored, image.high_bit) not in {(8, 8, 7), (16, 12, 11)}
            or len(image.pixel_data) != image.rows * image.columns * (image.bits_allocated // 8)
            for image in payload.images
        ):
            return False
        # pynetdicom >= 2.0 renamed the SOP class constants (dropped the
        # ``SOPClass`` suffix). Older releases still use the *SOPClass names.
        # Import both and bind to a stable alias so the rest of the method
        # works against either version without an `ImportError` at runtime.
        try:
            from pynetdicom import AE
        except Exception:
            raise RuntimeError("pynetdicom is required for DICOM printing.")

        try:
            from pynetdicom.sop_class import (
                BasicFilmSession as BasicFilmSessionSOPClass,
                BasicFilmBox as BasicFilmBoxSOPClass,
                BasicGrayscaleImageBox as BasicGrayscaleImageBoxSOPClass,
                Printer as PrinterSOPClass,
            )
        except Exception:
            try:
                from pynetdicom.sop_class import (  # type: ignore[no-redef]
                    BasicFilmSessionSOPClass,
                    BasicFilmBoxSOPClass,
                    BasicGrayscaleImageBoxSOPClass,
                    PrinterSOPClass,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"pynetdicom SOP class symbols not found: {exc}. "
                    f"Install pynetdicom (any version >= 1.5)."
                )

        self.last_result = PrintResult(False, "Connect", detail="Association not established")
        ae = AE(ae_title=self.settings.local_ae_title)
        ae.acse_timeout = 10
        ae.dimse_timeout = 30
        ae.network_timeout = 30
        ae.add_requested_context(GRAYSCALE_META_UID, [ExplicitVRLittleEndian, ImplicitVRLittleEndian])
        ae.add_requested_context(BasicFilmSessionSOPClass, [ExplicitVRLittleEndian, ImplicitVRLittleEndian])
        ae.add_requested_context(BasicFilmBoxSOPClass, [ExplicitVRLittleEndian, ImplicitVRLittleEndian])
        ae.add_requested_context(BasicGrayscaleImageBoxSOPClass, [ExplicitVRLittleEndian, ImplicitVRLittleEndian])
        ae.add_requested_context(PrinterSOPClass, [ExplicitVRLittleEndian, ImplicitVRLittleEndian])

        assoc = ae.associate(
            self.settings.ip_address,
            self.settings.port,
            ae_title=self.settings.ae_title,
        )

        if not assoc.is_established:
            return False

        try:
            meta = {}
            if any(str(c.abstract_syntax) == GRAYSCALE_META_UID for c in assoc.accepted_contexts):
                meta = {"meta_uid": GRAYSCALE_META_UID}
            film_session_uid = generate_uid()
            film_box_uid = generate_uid()

            film_session = Dataset()
            film_session.NumberOfCopies = payload.number_of_copies
            film_session.PrintPriority = payload.print_priority
            film_session.MediumType = payload.medium_type
            film_session.FilmDestination = payload.film_destination

            self.last_result = PrintResult(False, "Create film session", detail="Awaiting response")
            status, film_session_rsp = assoc.send_n_create(
                film_session,
                class_uid=BASIC_FILM_SESSION_UID,
                instance_uid=film_session_uid,
                **meta,
            )
            if not self._status_ok(status, "Create film session"):
                return False

            film_box = Dataset()
            film_box.ImageDisplayFormat = payload.image_display_format
            film_box.FilmOrientation = payload.film_orientation
            film_box.FilmSizeID = payload.film_size_id
            film_box.MagnificationType = payload.magnification_type
            if payload.smoothing_type:
                film_box.SmoothingType = payload.smoothing_type
            film_box.BorderDensity = payload.border_density
            film_box.EmptyImageDensity = payload.empty_image_density
            if payload.min_density is not None:
                film_box.MinDensity = payload.min_density
            if payload.max_density is not None:
                film_box.MaxDensity = payload.max_density
            film_box.Trim = payload.trim
            if payload.configuration_information:
                film_box.ConfigurationInformation = payload.configuration_information
            film_box.ReferencedFilmSessionSequence = [
                Dataset()
            ]
            film_box.ReferencedFilmSessionSequence[0].ReferencedSOPClassUID = BasicFilmSessionSOPClass
            film_box.ReferencedFilmSessionSequence[0].ReferencedSOPInstanceUID = film_session_uid

            self.last_result = PrintResult(False, "Create film box", detail="Awaiting response")
            status, film_box_rsp = assoc.send_n_create(
                film_box,
                class_uid=BASIC_FILM_BOX_UID,
                instance_uid=film_box_uid,
                **meta,
            )
            if not self._status_ok(status, "Create film box"):
                return False

            image_box_uids = []
            if film_box_rsp and hasattr(film_box_rsp, "ReferencedImageBoxSequence"):
                for item in film_box_rsp.ReferencedImageBoxSequence:
                    image_box_uids.append(item.ReferencedSOPInstanceUID)

            if not payload.images or len(image_box_uids) < len(payload.images):
                self.last_result = PrintResult(False, "Create film box", detail="Printer did not return the required image boxes")
                return False
            for index, image in enumerate(payload.images):
                image_box_uid = image_box_uids[index]

                image_box = Dataset()
                image_box.ImageBoxPosition = index + 1
                image_box.BasicGrayscaleImageSequence = [image.to_dataset()]

                self.last_result = PrintResult(False, "Set image box", detail="Awaiting response")
                status, _ = assoc.send_n_set(
                    image_box,
                    class_uid=BASIC_GRAYSCALE_IMAGE_BOX_UID,
                    instance_uid=image_box_uid,
                    **meta,
                )
                if not self._status_ok(status, "Set image box"):
                    return False

            self.last_result = PrintResult(False, "Submit film box", detail="Awaiting response; do not retry automatically")
            status, _ = assoc.send_n_action(
                Dataset(),
                action_type=1,
                class_uid=BASIC_FILM_BOX_UID,
                instance_uid=film_box_uid,
                **meta,
            )
            return self._status_ok(status, "Submit film box")
        finally:
            try:
                assoc.release()
            except Exception:
                # A confirmed N-ACTION is not undone by release failure.
                if not self.last_result.accepted:
                    self.last_result = PrintResult(False, self.last_result.operation, self.last_result.status, self.last_result.detail + "; association release failed")


class PrintSignals(QObject):
    completed = Signal(str, object)


class DicomPrintWorker(QRunnable):
    """Own one immutable job snapshot; never touch widgets or retry a print."""

    def __init__(self, settings, payload, study_uid):
        super().__init__()
        self.settings = settings
        self.payload = payload
        self.study_uid = study_uid
        self.signals = PrintSignals()

    def run(self):
        handler = DicomPrintHandler(self.settings)
        try:
            success = handler.send_print_job(self.payload)
            result = handler.last_result
            if success:
                result = PrintResult(True, "Submit film box", 0, "Accepted by printer; physical completion is not confirmed")
        except Exception:
            result = PrintResult(False, handler.last_result.operation, detail="Submission interrupted; check the printer queue before retrying")
        self.signals.completed.emit(self.study_uid, result)


@dataclass
class DicomImagePayload:
    rows: int
    columns: int
    pixel_data: bytes
    bits_allocated: int = 8
    bits_stored: int = 8
    high_bit: int = 7
    samples_per_pixel: int = 1
    photometric_interpretation: str = "MONOCHROME2"
    pixel_representation: int = 0
    sop_class_uid: str = BASIC_GRAYSCALE_IMAGE_BOX_UID
    sop_instance_uid: str = ""

    def to_dataset(self) -> Dataset:
        ds = Dataset()
        ds.SamplesPerPixel = self.samples_per_pixel
        ds.PhotometricInterpretation = self.photometric_interpretation
        ds.Rows = self.rows
        ds.Columns = self.columns
        ds.BitsAllocated = self.bits_allocated
        ds.BitsStored = self.bits_stored
        ds.HighBit = self.high_bit
        ds.PixelRepresentation = self.pixel_representation
        ds.PixelData = self.pixel_data
        ds.SOPClassUID = self.sop_class_uid
        ds.SOPInstanceUID = self.sop_instance_uid or generate_uid()
        return ds


@dataclass
class DicomPrintJob:
    images: List[DicomImagePayload]
    number_of_copies: int = 1
    print_priority: str = "MED"
    medium_type: str = "PAPER"
    film_destination: str = "PROCESSOR"
    image_display_format: str = "STANDARD\\1,1"
    film_orientation: str = "PORTRAIT"
    film_size_id: str = "14INX17IN"
    magnification_type: str = "REPLICATE"
    smoothing_type: str | None = None
    border_density: str = "BLACK"
    empty_image_density: str = "BLACK"
    min_density: int | None = None
    max_density: int | None = None
    trim: str = "NO"
    configuration_information: str | None = None
