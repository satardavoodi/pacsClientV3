"""Validation helpers for printing module."""

from __future__ import annotations

from typing import List

from modules.printing.core.models import FilmLayout, FilmSize, PrintJob, PrinterConfig


def validate_print_job(job: PrintJob) -> List[str]:
    errors: List[str] = []

    if not job.patient_id or not job.patient_name:
        errors.append("Missing patient information.")
    if not isinstance(job.film_size, FilmSize):
        errors.append("Invalid film size.")
    if not isinstance(job.layout, FilmLayout):
        errors.append("Invalid layout.")
    if not isinstance(job.printer, PrinterConfig):
        errors.append("Invalid printer configuration.")
    if job.layout.rows <= 0 or job.layout.cols <= 0:
        errors.append("Layout rows/cols must be positive.")
    return errors
