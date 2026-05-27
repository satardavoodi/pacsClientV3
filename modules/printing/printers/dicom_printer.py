"""DICOM Print Management SCU handler (placeholder)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from pydicom.dataset import Dataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

BASIC_FILM_SESSION_UID = "1.2.840.10008.5.1.1.1"
BASIC_FILM_BOX_UID = "1.2.840.10008.5.1.1.2"
BASIC_GRAYSCALE_IMAGE_BOX_UID = "1.2.840.10008.5.1.1.4"
PRINTER_SOP_UID = "1.2.840.10008.5.1.1.16"


@dataclass
class DicomPrinterSettings:
    ip_address: str
    port: int
    ae_title: str


class DicomPrintHandler:
    def __init__(self, settings: DicomPrinterSettings):
        self.settings = settings

    def send_print_job(self, payload: "DicomPrintJob") -> bool:
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

        ae = AE()
        ae.add_requested_context(BasicFilmSessionSOPClass, ExplicitVRLittleEndian)
        ae.add_requested_context(BasicFilmBoxSOPClass, ExplicitVRLittleEndian)
        ae.add_requested_context(BasicGrayscaleImageBoxSOPClass, ExplicitVRLittleEndian)
        ae.add_requested_context(PrinterSOPClass, ExplicitVRLittleEndian)

        assoc = ae.associate(
            self.settings.ip_address,
            self.settings.port,
            ae_title=self.settings.ae_title,
        )

        if not assoc.is_established:
            return False

        try:
            film_session_uid = generate_uid()
            film_box_uid = generate_uid()

            film_session = Dataset()
            film_session.NumberOfCopies = payload.number_of_copies
            film_session.PrintPriority = payload.print_priority
            film_session.MediumType = payload.medium_type
            film_session.FilmDestination = payload.film_destination

            status, film_session_rsp = assoc.send_n_create(
                film_session,
                class_uid=BASIC_FILM_SESSION_UID,
                instance_uid=film_session_uid,
            )
            if status is None or status.Status != 0x0000:
                return False

            film_box = Dataset()
            film_box.ImageDisplayFormat = payload.image_display_format
            film_box.FilmOrientation = payload.film_orientation
            film_box.FilmSizeID = payload.film_size_id
            film_box.MagnificationType = payload.magnification_type
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

            status, film_box_rsp = assoc.send_n_create(
                film_box,
                class_uid=BASIC_FILM_BOX_UID,
                instance_uid=film_box_uid,
            )
            if status is None or status.Status != 0x0000:
                return False

            image_box_uids = []
            if film_box_rsp and hasattr(film_box_rsp, "ReferencedImageBoxSequence"):
                for item in film_box_rsp.ReferencedImageBoxSequence:
                    image_box_uids.append(item.ReferencedSOPInstanceUID)

            for index, image in enumerate(payload.images):
                if index >= len(image_box_uids):
                    image_box_uid = generate_uid()
                else:
                    image_box_uid = image_box_uids[index]

                image_box = Dataset()
                image_box.ImageBoxPosition = index + 1
                image_box.BasicGrayscaleImageSequence = [image.to_dataset()]

                status, _ = assoc.send_n_set(
                    image_box,
                    class_uid=BASIC_GRAYSCALE_IMAGE_BOX_UID,
                    instance_uid=image_box_uid,
                )
                if status is None or status.Status != 0x0000:
                    return False

            status, _ = assoc.send_n_action(
                Dataset(),
                action_type=1,
                class_uid=BASIC_FILM_BOX_UID,
                instance_uid=film_box_uid,
            )
            return status is not None and status.Status == 0x0000
        finally:
            assoc.release()


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
    smoothing_type: str = "MEDIUM"
    border_density: str = "BLACK"
    empty_image_density: str = "BLACK"
    min_density: int | None = None
    max_density: int | None = None
    trim: str = "NO"
    configuration_information: str | None = None
