"""
Database / persistence service for the Home panel.

Encapsulates all direct DB access that was previously inlined inside
HomePanelWidget.  Every public method is a plain (non-UI) function or
instance method that can be called from a background thread via
``asyncio.to_thread`` / ``loop.run_in_executor``.

This follows the **Service Layer** pattern:
  UI (HomePanelWidget) → Service (HomeDbService) → Repository (db_manager)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PacsClient.utils import (
    find_patient_pk,
    find_study_pk,
    insert_patient,
    insert_study,
    insert_series,
    find_series_pk,
    find_study_pk_with_study_uid,
    search_patients_local,
)
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.db_manager import get_study_by_study_uid


class HomeDbService:
    """Stateless service – instantiate once and keep for the app lifetime."""

    # ------------------------------------------------------------------
    # Patient / Study persistence
    # ------------------------------------------------------------------

    @staticmethod
    def get_study(study_uid: str) -> Optional[dict]:
        return get_study_by_study_uid(study_uid=study_uid)

    @staticmethod
    def ensure_patient(patient_id: str, patient_name: str = "N/A",
                       birth_date=None, sex=None, age=None, weight=None) -> int:
        """Return existing patient PK or create a new record."""
        pk = find_patient_pk(patient_id)
        if pk is None:
            pk = insert_patient(patient_id, patient_name, birth_date or "N/A",
                                sex or "N/A", age or "N/A", weight or "N/A")
        return pk

    @staticmethod
    def ensure_study(study_uid: str, patient_pk: int, study_info: dict) -> int:
        """Return existing study PK or create from *study_info* dict."""
        pk = find_study_pk_with_study_uid(study_uid)
        if pk is not None:
            # Update path + metadata if stale
            from PacsClient.utils.db_manager import update_study_missing_fields
            study_path = SOURCE_PATH / study_uid
            study_path.mkdir(parents=True, exist_ok=True)
            update_study_missing_fields(
                pk,
                study_path=str(study_path),
                study_date=study_info.get("study_date", ""),
                study_time=study_info.get("study_time", ""),
                number_of_series=study_info.get("count_of_series",
                                                len(study_info.get("series", []))),
                number_of_instances=sum(
                    s.get("image_count", 0) for s in study_info.get("series", [])
                ),
            )
            return pk

        first_series: dict = (study_info.get("series") or [{}])[0] if study_info.get("series") else {}
        study_path = SOURCE_PATH / study_uid
        study_path.mkdir(parents=True, exist_ok=True)

        pk = insert_study(
            study_uid=study_uid,
            patient_fk=patient_pk,
            study_date=study_info.get("study_date", ""),
            study_time=study_info.get("study_time", ""),
            study_description=study_info.get("study_description", ""),
            institution_name=first_series.get("institution_name"),
            modality=first_series.get("modality"),
            body_part=first_series.get("body_part_examined"),
            number_of_series=study_info.get("count_of_series",
                                            len(study_info.get("series", []))),
            number_of_instances=sum(
                s.get("image_count", 0) for s in study_info.get("series", [])
            ),
            study_path=str(study_path),
        )
        return pk

    @staticmethod
    def save_series_batch(study_uid: str, study_pk: int,
                          series_list: list[dict]) -> int:
        """Persist a batch of series records. Returns count saved."""
        saved = 0
        for series in series_list:
            series_uid = series.get("series_uid", "")
            if not series_uid:
                continue
            if find_series_pk(series_uid):
                continue

            series_number = series.get("series_number", "unknown")
            series_path_name = str(series.get("series_path_name") or series_number)
            series_path = SOURCE_PATH / study_uid / series_path_name
            series_path.mkdir(parents=True, exist_ok=True)

            insert_series(
                series_uid=series_uid,
                study_fk=study_pk,
                series_name=f"Series {series_number}",
                series_number=str(series_number),
                series_description=series.get("series_description", ""),
                modality=series.get("modality", ""),
                image_count=series.get("image_count", 0),
                protocol_name=series.get("protocol_name", ""),
                body_part_examined=series.get("body_part_examined", ""),
                manufacturer=series.get("manufacturer", ""),
                institution_name=series.get("institution_name", ""),
                main_thumbnail=False,
                thumbnail_path=None,
                series_path=str(series_path),
            )
            saved += 1
        return saved

    # ------------------------------------------------------------------
    # Series info queries
    # ------------------------------------------------------------------

    @staticmethod
    def get_series_info_from_database(study_uid: str, series_number: str) -> dict:
        try:
            from PacsClient.utils.db_manager import get_series_by_study_and_number
            info = get_series_by_study_and_number(study_uid, int(series_number))
            if info:
                return {
                    "series_uid": info.get("series_uid", ""),
                    "series_number": info.get("series_number", series_number),
                    "series_description": info.get("series_description", ""),
                    "modality": info.get("modality", ""),
                    "image_count": info.get("image_count", 0),
                    "protocol_name": info.get("protocol_name", ""),
                    "body_part_examined": info.get("body_part_examined", ""),
                }
        except Exception as exc:
            print(f"Error getting series info from database: {exc}")
        return {}

    @staticmethod
    def save_series_info_to_database(study_uid: str,
                                     series_thumbnails: list[dict]) -> bool:
        """Save series metadata received from gRPC thumbnail response."""
        try:
            from database.core import get_db_connection
            study_pk = find_study_pk_with_study_uid(study_uid)
            if not study_pk:
                return False

            saved = 0
            for sd in series_thumbnails:
                series_uid = sd.get("series_uid", "")
                existing = find_series_pk(series_uid)
                if existing:
                    with get_db_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            """UPDATE series
                               SET series_description=?, modality=?, image_count=?,
                                   protocol_name=?, body_part_examined=?, manufacturer=?,
                                   institution_name=?, thumbnail_path=?
                               WHERE series_uid=?""",
                            (
                                sd.get("series_description", ""),
                                sd.get("modality", ""),
                                sd.get("image_count", 0),
                                sd.get("protocol_name", ""),
                                sd.get("body_part_examined", ""),
                                sd.get("manufacturer", ""),
                                sd.get("institution_name", ""),
                                sd.get("thumbnail_path", ""),
                                series_uid,
                            ),
                        )
                        conn.commit()
                    saved += 1
                    continue

                insert_series(
                    series_uid=series_uid,
                    study_fk=study_pk,
                    series_name=f"Series {sd.get('series_number', '')}",
                    series_number=sd.get("series_number", ""),
                    series_description=sd.get("series_description", ""),
                    modality=sd.get("modality", ""),
                    image_count=sd.get("image_count", 0),
                    protocol_name=sd.get("protocol_name", ""),
                    body_part_examined=sd.get("body_part_examined", ""),
                    manufacturer=sd.get("manufacturer", ""),
                    institution_name=sd.get("institution_name", ""),
                    main_thumbnail=bool(sd.get("thumbnail_path")),
                    thumbnail_path=sd.get("thumbnail_path"),
                    series_path=None,
                )
                saved += 1
            return saved > 0
        except Exception as exc:
            print(f"Error in save_series_info_to_database: {exc}")
            return False

    # ------------------------------------------------------------------
    # Patient-study detail views (legacy study_details table)
    # ------------------------------------------------------------------

    @staticmethod
    def get_patient_study(study_uid: str) -> Optional[dict]:
        from database.core import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT StudyInstanceUID, PatientID, PatientName, PatientSex,
                          PatientAge, PatientWeight, StudyDate, StudyTime,
                          StudyDescription, Modality, BodyPart, ProtocolName,
                          StationName, InstitutionName, NumberOfSeries,
                          NumberOfInstances
                   FROM study_details WHERE StudyInstanceUID = ?""",
                (study_uid,),
            )
            row = cursor.fetchone()
        if not row:
            return None

        keys = [
            "study_uid", "patient_id", "patient_name", "PatientSex",
            "PatientAge", "PatientWeight", "study_date", "StudyTime",
            "StudyDescription", "Modality", "BodyPart", "ProtocolName",
            "StationName", "InstitutionName", "NumberOfSeries",
            "NumberOfInstances",
        ]
        return dict(zip(keys, row))

    @staticmethod
    def save_study_details(dataset) -> None:
        """Persist a pydicom Dataset into the study_details table."""
        from database.core import get_db_connection
        try:
            description_parts = []
            if hasattr(dataset, "StudyDescription"):
                description_parts.append(str(dataset.StudyDescription))
            if hasattr(dataset, "BodyPartExamined"):
                description_parts.append(f"Body: {dataset.BodyPartExamined}")
            if hasattr(dataset, "NumberOfStudyRelatedSeries"):
                description_parts.append(f"Series: {dataset.NumberOfStudyRelatedSeries}")
            if hasattr(dataset, "NumberOfStudyRelatedInstances"):
                description_parts.append(f"Images: {dataset.NumberOfStudyRelatedInstances}")
            description = " | ".join(description_parts)

            vals = (
                getattr(dataset, "StudyInstanceUID", ""),
                getattr(dataset, "PatientID", ""),
                str(getattr(dataset, "PatientName", "")),
                getattr(dataset, "PatientSex", ""),
                getattr(dataset, "PatientAge", ""),
                getattr(dataset, "PatientWeight", ""),
                getattr(dataset, "StudyDate", ""),
                getattr(dataset, "StudyTime", ""),
                description,
                getattr(dataset, "Modality", ""),
                getattr(dataset, "BodyPartExamined", ""),
                getattr(dataset, "ProtocolName", ""),
                getattr(dataset, "StationName", ""),
                getattr(dataset, "InstitutionName", ""),
                int(getattr(dataset, "NumberOfStudyRelatedSeries", 0)),
                int(getattr(dataset, "NumberOfStudyRelatedInstances", 0)),
            )
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO study_details VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    vals,
                )
                conn.commit()
        except Exception as exc:
            print(f"Error saving study details: {exc}")

    @staticmethod
    def save_socket_patient_to_db(patient: dict) -> None:
        """Persist a patient dict obtained from Socket API."""
        try:
            patient_id = patient.get("patient_id", "N/A")
            patient_name = patient.get("patient_name", "N/A")

            pk = find_patient_pk(patient_id)
            if pk is None:
                pk = insert_patient(
                    patient_id, patient_name,
                    patient.get("patient_birth_date", "N/A"),
                    patient.get("patient_sex", "N/A"),
                    patient.get("patient_age", "N/A"),
                    "N/A",
                )

            study_uid = patient.get("latest_study_uid")
            if study_uid and study_uid != "N/A":
                study_pk = find_study_pk(pk)
                if study_pk is None:
                    study_date = patient.get("latest_study_date", "N/A")
                    if study_date and study_date != "N/A" and len(study_date) == 8:
                        try:
                            study_date = datetime.strptime(study_date, "%Y%m%d").strftime("%Y/%m/%d")
                        except Exception:
                            pass

                    modality = ", ".join(patient.get("modalities", []))
                    study_path = None
                    potential = SOURCE_PATH / study_uid
                    if potential.exists():
                        study_path = str(potential)

                    insert_study(
                        study_uid, pk, study_date, "N/A",
                        patient.get("latest_study_description", "N/A"),
                        "N/A", modality, "N/A",
                        patient.get("count_of_series", 0),
                        patient.get("count_of_instances", 0),
                        study_path=study_path,
                    )
        except Exception as exc:
            print(f"Error saving Socket patient to database: {exc}")

    @staticmethod
    def save_patient_and_study_on_db(dataset) -> None:
        """Persist patient + study from a pydicom Dataset (C-FIND result)."""
        patient_id = str(getattr(dataset, "PatientID", "N/A"))
        patient_pk = find_patient_pk(patient_id)
        if patient_pk is None:
            patient_pk = insert_patient(
                patient_id,
                str(getattr(dataset, "PatientName", "N/A")),
                str(getattr(dataset, "PatientBirthDate", "N/A")),
                str(getattr(dataset, "PatientSex", "N/A")),
                str(getattr(dataset, "PatientAge", "N/A")),
                str(getattr(dataset, "PatientWeight", "N/A")),
            )

        study_pk = find_study_pk(patient_pk)
        if study_pk is None:
            study_uid = str(getattr(dataset, "StudyInstanceUID", "N/A"))
            study_date = str(getattr(dataset, "StudyDate", None))
            if study_date:
                try:
                    study_date = datetime.strptime(study_date, "%Y%m%d").strftime("%Y/%m/%d")
                except Exception:
                    study_date = str(study_date)

            description_parts = []
            if hasattr(dataset, "StudyDescription"):
                description_parts.append(str(dataset.StudyDescription))
            if hasattr(dataset, "BodyPartExamined"):
                description_parts.append(f"Body: {dataset.BodyPartExamined}")
            if hasattr(dataset, "NumberOfStudyRelatedSeries"):
                description_parts.append(f"Series: {dataset.NumberOfStudyRelatedSeries}")
            if hasattr(dataset, "NumberOfStudyRelatedInstances"):
                description_parts.append(f"Images: {dataset.NumberOfStudyRelatedInstances}")
            description = " | ".join(description_parts)

            insert_study(
                study_uid, patient_pk, study_date,
                str(getattr(dataset, "StudyTime", "N/A")),
                description,
                str(getattr(dataset, "InstitutionName", "N/A")),
                str(getattr(dataset, "Modality", "N/A")),
                str(getattr(dataset, "BodyPartExamined", "N/A")),
                int(getattr(dataset, "NumberOfStudyRelatedSeries", 0)),
                int(getattr(dataset, "NumberOfStudyRelatedInstances", 0)),
            )

    @staticmethod
    def search_local(search_data: dict) -> list:
        """Wrapper around search_patients_local (safe for executor)."""
        return search_patients_local(search_data)
