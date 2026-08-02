"""Home-panel handler for the right-click ▸ "Edit patient / study info…" action.

Opens :class:`PatientEditDialog`, then — once the DICOM files on disk have been
rewritten — brings the local ``dicom.db`` into line so the patient list and the
viewer overlays show the corrected values immediately instead of the stale ones.

WHY THE DB SYNC IS HERE AND NOT IN THE PURE MODULE
--------------------------------------------------
``PacsClient.utils.dicom_demographics_edit`` deliberately knows nothing about
Qt or the database — that is what keeps it unit-testable offscreen. Disk is the
authority; the DB is a derived index of it. So the order is always: files
first, DB second. If the DB sync fails, the files are still correct and a
re-import rebuilds the rows.

PATIENT ID COLLISIONS
---------------------
``patients.patient_id`` is UNIQUE. Editing an ID to one that already exists
therefore cannot be a plain UPDATE — it would raise IntegrityError. When the
target ID already has a row we re-point this patient's studies at that existing
row (``studies.patient_fk``) rather than creating a duplicate identity, which
is what the user means by "this exam belongs to that patient".
"""

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class _HPPatientEditMixin:
    """Mixed into ``HomePanelWidget``."""

    def _on_edit_patient_info_requested(self, patient_id, patient_name, study_uids):
        """Open the demographic editor for a patient row."""
        try:
            from ..patient_edit_dialog import PatientEditDialog
        except Exception:
            logger.exception("[DICOM-EDIT] editor dialog unavailable")
            return

        try:
            uids = [str(u or "").strip() for u in (study_uids or []) if str(u or "").strip()]
            if not uids:
                return
            dialog = PatientEditDialog(
                str(patient_id or "").strip(),
                str(patient_name or "").strip(),
                uids,
                parent=self,
            )
            dialog.editApplied.connect(self._on_patient_edit_applied)
            dialog.exec()
        except Exception:
            logger.exception("[DICOM-EDIT] failed to open the editor dialog")

    # -- post-edit reconciliation -----------------------------------------

    def _on_patient_edit_applied(self, patient_id_before: str, values: dict, study_uids: list):
        """Files are already rewritten — now reconcile the DB and the table."""
        try:
            self._sync_edited_demographics_to_db(patient_id_before, values, study_uids)
        except Exception:
            logger.exception(
                "[DICOM-EDIT] DB sync failed — the DICOM files on disk ARE "
                "correct; the patient list may show stale values until reimport"
            )
        try:
            self._refresh_patient_table_after_edit()
        except Exception:
            logger.exception("[DICOM-EDIT] table refresh after edit failed")

    def _sync_edited_demographics_to_db(
        self, patient_id_before: str, values: Dict[str, str], study_uids: List[str]
    ) -> None:
        from database.dicom_db import find_patient_pk, find_study_pk_with_study_uid
        from database.manager import (
            force_update_patient_demographics,
            force_update_series_institution,
            force_update_study_demographics,
        )

        patient_pk = find_patient_pk(str(patient_id_before or "").strip())

        # --- patient-level ------------------------------------------------
        new_patient_id = values.get("patient_id")
        target_pk = patient_pk
        if patient_pk is not None:
            collision_pk = None
            if new_patient_id:
                existing = find_patient_pk(new_patient_id)
                if existing is not None and existing != patient_pk:
                    collision_pk = existing

            if collision_pk is not None:
                # The new ID already belongs to another row. Re-point this
                # patient's studies at it instead of breaking the UNIQUE
                # constraint or duplicating the identity.
                logger.warning(
                    "[DICOM-EDIT] patient_id %s already exists (pk=%s) — "
                    "re-pointing %d study(ies) to it",
                    new_patient_id,
                    collision_pk,
                    len(study_uids),
                )
                target_pk = collision_pk
                force_update_patient_demographics(
                    collision_pk,
                    patient_name=values.get("patient_name"),
                    age=values.get("patient_age"),
                )
            else:
                force_update_patient_demographics(
                    patient_pk,
                    patient_id=new_patient_id,
                    patient_name=values.get("patient_name"),
                    age=values.get("patient_age"),
                )

        # --- local display alias (server has no demographic-write endpoint) --
        # Record original_server_id -> corrected_id so the patient list can keep
        # SHOWING the corrected ID after a server refresh re-sends the original.
        # This is display-only: the row's real identity stays the server's key
        # (see database/patient_overrides.py). Never let it break the edit.
        try:
            if new_patient_id and str(new_patient_id).strip() != str(patient_id_before or "").strip():
                from database.patient_overrides import set_patient_id_override

                set_patient_id_override(
                    patient_id_before,
                    new_patient_id,
                    corrected_patient_name=values.get("patient_name"),
                    source="demographic_edit",
                )
        except Exception:
            logger.exception("[DICOM-EDIT] recording the local Patient-ID alias failed")

        # --- study-level --------------------------------------------------
        institution = values.get("institution_name")
        for uid in study_uids:
            study_pk = find_study_pk_with_study_uid(str(uid or "").strip())
            if study_pk is None:
                continue
            force_update_study_demographics(
                study_pk,
                study_date=values.get("study_date"),
                study_time=values.get("study_time"),
                institution_name=institution,
                patient_fk=target_pk if target_pk != patient_pk else None,
            )
            if institution is not None:
                # series carries its own institution_name column; leaving it
                # stale would make the study and its series disagree.
                force_update_series_institution(study_pk, institution)

        logger.info(
            "[DICOM-EDIT] db sync done patient_pk=%s -> %s studies=%d fields=%s",
            patient_pk,
            target_pk,
            len(study_uids),
            sorted(values.keys()),
        )

    def _refresh_patient_table_after_edit(self) -> None:
        """Re-run the current search so the row shows the corrected values.

        Uses whatever refresh entry point this build exposes; a missing one is
        not an error — the values are already on disk and in the DB, and the
        next search picks them up.
        """
        for name in ("refresh_current_search", "_rerun_last_search", "search_patients"):
            fn = getattr(self, name, None)
            if callable(fn):
                try:
                    fn()
                    return
                except TypeError:
                    continue
                except Exception:
                    logger.exception("[DICOM-EDIT] refresh via %s failed", name)
                    return
