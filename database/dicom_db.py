"""database.dicom_db — DICOM hierarchy CRUD and schema management.

Public API
----------
init_database()                     — create/migrate all tables and indexes
ensure_report_status_schema()       — add reportStatus columns to studies
insert_patient(...)                 — upsert patient row
insert_study(...)                   — upsert study row
migrate_fix_null_study_paths()      — one-off migration for NULL study_path
insert_series(...)                  — upsert series row
insert_instances_batch(instances)   — bulk insert instances (fast path)
insert_instance(...)                — single instance upsert
deserialize_instance_metadata(row)  — decode JSON geometry columns
get_all_patients()                  — all patients joined with studies
search_patients_local(search_data)  — filtered patient/study search
get_patient_by_id(patient_id)       — single patient by patient_id
find_patient_pk(patient_id)         — PK lookup for patient_id
find_study_pk(patient_fk)           — first study PK for patient
find_study_pk_with_study_uid(uid)   — study PK by study_uid
find_series_pk(series_uid)          — series PK by series_uid
find_series_pk_by_number(n, study)  — series PK by number + study FK
find_instance_pk(sop_uid)           — instance PK by sop_uid
find_instances_by_sop_uids(uids)    — bulk existence check
bulk_insert_instances(data)         — bulk INSERT OR REPLACE instances
bulk_update_instances(data)         — bulk UPDATE instances
get_patients_ordered_by_date(...)   — patients sorted by earliest study
get_patient_storage_info(pk)        — file paths for a patient (cleanup)
delete_patient_cascade(pk)          — CASCADE delete patient/studies/series
get_patients_by_date_range(...)     — patients within date range

Split from database/core.py (v2.2.9.0).
"""

import json
import logging
import sqlite3

from database._pool import get_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_database():
    """Create (if required) the four DICOM hierarchy tables."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                patient_pk     INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id     TEXT UNIQUE,
                patient_name   TEXT,
                birth_date     TEXT DEFAULT NULL,
                sex            TEXT DEFAULT NULL,
                age            TEXT DEFAULT NULL,
                patient_weight TEXT DEFAULT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS studies (
                study_pk           INTEGER PRIMARY KEY AUTOINCREMENT,
                study_uid          TEXT UNIQUE,
                patient_fk         INTEGER NOT NULL,
                study_date         TEXT DEFAULT NULL,
                study_time         TEXT DEFAULT NULL,
                study_description  TEXT DEFAULT NULL,
                institution_name   TEXT DEFAULT NULL,
                modality         TEXT DEFAULT NULL,
                body_part        TEXT DEFAULT NULL,
                number_of_series   INTEGER DEFAULT 0,
                number_of_instances INTEGER DEFAULT 0,
                study_path      TEXT DEFAULT NULL,
                attachments_uploaded TEXT DEFAULT NULL,
                FOREIGN KEY(patient_fk) REFERENCES patients(patient_pk) ON DELETE CASCADE
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS series (
                series_pk        INTEGER PRIMARY KEY AUTOINCREMENT,
                series_uid       TEXT UNIQUE,
                series_name      TEXT,
                study_fk         INTEGER NOT NULL,
                series_number    INTEGER DEFAULT NULL,
                series_thk       TEXT DEFAULT NULL,
                series_description TEXT DEFAULT NULL,
                orientation      TEXT DEFAULT NULL,
                modality         TEXT DEFAULT NULL,
                image_count      INTEGER DEFAULT 0,
                protocol_name    TEXT DEFAULT NULL,
                body_part_examined TEXT DEFAULT NULL,
                manufacturer     TEXT DEFAULT NULL,
                institution_name TEXT DEFAULT NULL,
                main_thumbnail   BOOLEAN DEFAULT 0,
                thumbnail_path   TEXT DEFAULT NULL,
                series_path      TEXT DEFAULT NULL,
                FOREIGN KEY(study_fk) REFERENCES studies(study_pk) ON DELETE CASCADE
            )
            """
        )

        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_token_usage (
                center_name TEXT NOT NULL,
                model_name  TEXT NOT NULL,
                total_tokens INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (center_name, model_name)
            )
        """)

        # Per-API (hashed) token usage table (API key itself is never stored).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS api_token_usage (
                api_hash     TEXT NOT NULL,
                api_mask     TEXT NOT NULL,
                center_name  TEXT DEFAULT NULL,
                model_name   TEXT NOT NULL,
                total_tokens INTEGER DEFAULT 0,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (api_hash, model_name)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_api_token_usage_last_used ON api_token_usage(last_used_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_api_token_usage_mask ON api_token_usage(api_mask)")

        # Per-API transcript usage table (unit: seconds; API key itself is never stored).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS api_transcript_usage (
                api_hash       TEXT NOT NULL,
                api_mask       TEXT NOT NULL,
                center_name    TEXT DEFAULT NULL,
                model_name     TEXT NOT NULL,
                total_seconds  INTEGER DEFAULT 0,
                last_used_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (api_hash, model_name)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_api_transcript_usage_last_used ON api_transcript_usage(last_used_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_api_transcript_usage_mask ON api_transcript_usage(api_mask)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS instances (
                instance_pk     INTEGER PRIMARY KEY AUTOINCREMENT,
                sop_uid         TEXT UNIQUE,
                series_fk       INTEGER NOT NULL,
                instance_path   TEXT,
                instance_number INTEGER DEFAULT NULL,
                rows            INTEGER DEFAULT NULL,
                columns         INTEGER DEFAULT NULL,
                window_width    REAL DEFAULT NULL,
                window_center   REAL DEFAULT NULL,
                is_rgb          BOOLEAN DEFAULT 0,
                group_id        INTEGER,
                image_position_patient  TEXT DEFAULT NULL,
                image_orientation_patient  TEXT DEFAULT NULL,
                pixel_spacing  TEXT DEFAULT NULL,
                direction  TEXT DEFAULT NULL,
                slice_thickness REAL DEFAULT NULL,
                spacing_between_slices REAL DEFAULT NULL,
                rescale_slope REAL DEFAULT 1.0,
                rescale_intercept REAL DEFAULT 0.0,
                bits_allocated INTEGER DEFAULT 16,
                pixel_representation INTEGER DEFAULT 1,
                FOREIGN KEY(series_fk) REFERENCES series(series_pk) ON DELETE CASCADE
            )
            """
        )

        # ── FK indexes for high-frequency JOIN/WHERE columns ──────────
        cur.execute("CREATE INDEX IF NOT EXISTS idx_studies_patient_fk ON studies(patient_fk)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_series_study_fk ON series(study_fk)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_instances_series_fk ON instances(series_fk)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_instances_series_group ON instances(series_fk, group_id)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS download_progress (
                progress_pk     INTEGER PRIMARY KEY AUTOINCREMENT,
                study_uid       TEXT UNIQUE NOT NULL,
                downloaded_count INTEGER DEFAULT 0,
                total_instances INTEGER DEFAULT 0,
                progress_percent REAL DEFAULT 0.0,
                current_batch   INTEGER DEFAULT 0,
                total_batches   INTEGER DEFAULT 0,
                status          TEXT DEFAULT 'in_progress',
                last_update     TEXT DEFAULT NULL,
                created_at      TEXT DEFAULT NULL,
                completed_at    TEXT DEFAULT NULL
            )
            """
        )

        # Tools settings table for customizing reference line and measurement tools
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tools_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                settings_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Educational courses tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                course_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                course_name TEXT NOT NULL,
                course_description TEXT,
                author_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                outline TEXT,
                thumbnail_path TEXT,
                tags TEXT DEFAULT '[]',
                modality TEXT DEFAULT '',
                body_regions TEXT DEFAULT '[]',
                level TEXT DEFAULT 'Intermediate',
                is_my_course INTEGER DEFAULT 1,
                is_downloaded INTEGER DEFAULT 0,
                resource_type TEXT DEFAULT 'Course',
                content_origin TEXT DEFAULT 'local',
                validation_status TEXT DEFAULT 'ok',
                needs_attention INTEGER DEFAULT 0,
                import_source_path TEXT DEFAULT '',
                import_manifest_path TEXT DEFAULT ''
            )
        """)

        # Case of the Day (My Course) tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_of_day_entries (
                case_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                saved_by TEXT NOT NULL,
                modality TEXT NOT NULL,
                body_part TEXT NOT NULL,
                diagnosis TEXT NOT NULL,
                anatomical_classification TEXT DEFAULT '',
                protocol_details TEXT DEFAULT '',
                description TEXT DEFAULT '',
                differential_diagnosis TEXT DEFAULT '',
                dicom_folder_path TEXT NOT NULL,
                original_source_path TEXT DEFAULT '',
                source_type TEXT DEFAULT 'manual',
                patient_id TEXT DEFAULT '',
                study_uid TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_of_day_body_parts (
                body_part TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migrate existing courses table if needed
        try:
            cur.execute("PRAGMA table_info(courses)")
            columns = [col[1] for col in cur.fetchall()]

            if 'tags' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN tags TEXT DEFAULT '[]'")
            if 'modality' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN modality TEXT DEFAULT ''")
            if 'body_regions' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN body_regions TEXT DEFAULT '[]'")
            if 'level' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN level TEXT DEFAULT 'Intermediate'")
            if 'is_my_course' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN is_my_course INTEGER DEFAULT 1")
            if 'is_downloaded' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN is_downloaded INTEGER DEFAULT 0")
            if 'resource_type' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN resource_type TEXT DEFAULT 'Course'")
            if 'content_origin' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN content_origin TEXT DEFAULT 'local'")
            if 'validation_status' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN validation_status TEXT DEFAULT 'ok'")
            if 'needs_attention' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN needs_attention INTEGER DEFAULT 0")
            if 'import_source_path' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN import_source_path TEXT DEFAULT ''")
            if 'import_manifest_path' not in columns:
                cur.execute("ALTER TABLE courses ADD COLUMN import_manifest_path TEXT DEFAULT ''")
        except Exception as e:
            print(f"Migration warning: {e}")

        try:
            cur.execute("PRAGMA table_info(instances)")
            instance_columns = [col[1] for col in cur.fetchall()]
            if 'slice_thickness' not in instance_columns:
                cur.execute("ALTER TABLE instances ADD COLUMN slice_thickness REAL DEFAULT NULL")
            if 'spacing_between_slices' not in instance_columns:
                cur.execute("ALTER TABLE instances ADD COLUMN spacing_between_slices REAL DEFAULT NULL")
            if 'rescale_slope' not in instance_columns:
                cur.execute("ALTER TABLE instances ADD COLUMN rescale_slope REAL DEFAULT 1.0")
            if 'rescale_intercept' not in instance_columns:
                cur.execute("ALTER TABLE instances ADD COLUMN rescale_intercept REAL DEFAULT 0.0")
            if 'bits_allocated' not in instance_columns:
                cur.execute("ALTER TABLE instances ADD COLUMN bits_allocated INTEGER DEFAULT 16")
            if 'pixel_representation' not in instance_columns:
                cur.execute("ALTER TABLE instances ADD COLUMN pixel_representation INTEGER DEFAULT 1")
        except Exception as e:
            print(f"Instance migration warning: {e}")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS slides (
                slide_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                course_fk INTEGER NOT NULL,
                slide_order INTEGER NOT NULL,
                slide_title TEXT,
                slide_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(course_fk) REFERENCES courses(course_pk) ON DELETE CASCADE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS slide_content (
                content_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                slide_fk INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content_order INTEGER NOT NULL,
                content_data TEXT NOT NULL,
                layout_position TEXT,
                FOREIGN KEY(slide_fk) REFERENCES slides(slide_pk) ON DELETE CASCADE
            )
        """)

        conn.commit()

        # Ensure report status schema exists
        ensure_report_status_schema()


def ensure_report_status_schema():
    """
    Ensure report status fields exist in studies table.
    Adds reportStatus and reportStatusHistory columns if they don't exist.
    """
    _logger = logging.getLogger(__name__)

    with get_db_connection() as conn:
        cur = conn.cursor()

        # Add reportStatus column if missing
        try:
            cur.execute("SELECT reportStatus FROM studies LIMIT 1")
        except Exception:
            cur.execute("ALTER TABLE studies ADD COLUMN reportStatus TEXT DEFAULT 'pending'")
            cur.execute("UPDATE studies SET reportStatus = 'pending' WHERE reportStatus IS NULL")
            _logger.info("✅ Added reportStatus column to studies table")

        # Add reportStatusHistory column if missing (stored as JSON text)
        try:
            cur.execute("SELECT reportStatusHistory FROM studies LIMIT 1")
        except Exception:
            cur.execute("ALTER TABLE studies ADD COLUMN reportStatusHistory TEXT DEFAULT '[]'")
            cur.execute("UPDATE studies SET reportStatusHistory = '[]' WHERE reportStatusHistory IS NULL")
            _logger.info("✅ Added reportStatusHistory column to studies table")

        # Add updatedAt column if missing (for tracking when status was last updated)
        try:
            cur.execute("SELECT reportStatusUpdatedAt FROM studies LIMIT 1")
        except Exception:
            cur.execute("ALTER TABLE studies ADD COLUMN reportStatusUpdatedAt TEXT DEFAULT NULL")
            _logger.info("✅ Added reportStatusUpdatedAt column to studies table")

        # Create indexes for better query performance
        try:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_studies_reportStatus ON studies(reportStatus)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_studies_reportStatus_date ON studies(reportStatus, study_date)")
            _logger.info("✅ Created indexes for report status")
        except Exception as e:
            _logger.warning(f"⚠️ Could not create indexes: {e}")

        conn.commit()


# ---------------------------------------------------------------------------
# Patient / Study / Series CRUD
# ---------------------------------------------------------------------------

def insert_patient(patient_id: str, name: str, birth_date: str = None, sex: str = None,
                   age: str = None, patient_weight: str = None) -> int:
    """Insert a patient and return its primary key (PK).

    Uses ``INSERT OR IGNORE`` to prevent duplicates based on ``patient_id``.
    If the record already exists, the existing PK is returned.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO patients
                (patient_id, patient_name, birth_date, sex, age, patient_weight)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (patient_id, name, birth_date, sex, age, patient_weight),
        )
        conn.commit()
        cur.execute("SELECT patient_pk FROM patients WHERE patient_id = ?", (patient_id,))
        return cur.fetchone()[0]


def insert_study(study_uid: str, patient_fk: int, study_date: str = None, study_time: str = None,
                 study_description: str = None, institution_name: str = None, modality: str = None,
                 body_part: str = None, number_of_series: int = 0,
                 number_of_instances: int = 0, study_path: str = None) -> int:
    """Insert a study row and return its PK. Updates study_path if study already exists."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute(
                """
                INSERT INTO studies
                    (study_uid, patient_fk, study_date, study_time, study_description,
                     institution_name, modality, body_part, number_of_series, number_of_instances, study_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    study_uid, patient_fk, study_date, study_time, study_description,
                    institution_name, modality, body_part, number_of_series, number_of_instances, study_path,
                ),
            )
            study_pk = cur.lastrowid
        except sqlite3.IntegrityError:
            cur.execute(
                """
                UPDATE studies
                SET patient_fk = ?, study_date = ?, study_time = ?, study_description = ?,
                    institution_name = ?, modality = ?, body_part = ?,
                    number_of_series = ?, number_of_instances = ?,
                    study_path = COALESCE(?, study_path)
                WHERE study_uid = ?
                """,
                (
                    patient_fk, study_date, study_time, study_description,
                    institution_name, modality, body_part,
                    number_of_series, number_of_instances,
                    study_path, study_uid,
                ),
            )
            cur.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (study_uid,))
            study_pk = cur.fetchone()[0]

        conn.commit()
        return study_pk


def migrate_fix_null_study_paths() -> dict:
    """
    Migration function to fix studies with NULL study_path by checking disk.

    When studies are imported from Socket/PACS, they may have study_path=NULL in the database.
    This function:
    1. Finds all studies with study_path IS NULL
    2. Checks if files exist on disk at SOURCE_PATH/{study_uid}
    3. Updates database with correct study_path if files exist

    Returns:
        dict: {'updated': count, 'checked': count, 'not_found': count}
    """
    from pathlib import Path
    from PacsClient.utils.config import SOURCE_PATH

    _logger = logging.getLogger(__name__)
    _logger.debug("=" * 80)
    _logger.debug("🔧 [MIGRATION] Starting study_path NULL fix migration...")
    _logger.debug("=" * 80)

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT s.study_pk, s.study_uid, s.patient_fk, p.patient_name
                FROM studies s
                LEFT JOIN patients p ON s.patient_fk = p.patient_pk
                WHERE s.study_path IS NULL
                ORDER BY s.study_pk
            """)

            null_studies = cur.fetchall()
            _logger.debug(f"📋 Found {len(null_studies)} studies with NULL study_path")

            if not null_studies:
                _logger.debug("✅ No studies with NULL study_path found")
                return {'updated': 0, 'checked': 0, 'not_found': 0}

            updated = 0
            not_found = 0

            for study_pk, study_uid, patient_fk, patient_name in null_studies:
                try:
                    if study_uid:
                        potential_path = Path(SOURCE_PATH) / study_uid
                        if potential_path.exists():
                            cur.execute(
                                "UPDATE studies SET study_path = ? WHERE study_pk = ?",
                                (str(potential_path), study_pk),
                            )
                            _logger.debug(f"✅ Updated: {patient_name} ({study_uid[:40]}...)")
                            updated += 1
                        else:
                            _logger.debug(f"❌ Not found: {patient_name} ({study_uid[:40]}...)")
                            not_found += 1
                    else:
                        _logger.debug(f"❌ No study_uid for study_pk={study_pk}")
                        not_found += 1
                except Exception as e:
                    _logger.error(f"❌ Error processing study_pk={study_pk}: {e}")
                    not_found += 1

            conn.commit()

            if updated > 0 or not_found > 0:
                _logger.info("-" * 80)
                _logger.info("📊 Migration Summary:")
                if updated > 0:
                    _logger.info(f"   ✅ Updated: {updated}")
                if not_found > 0:
                    _logger.info(f"   ⚠️  Not found on disk: {not_found}")
                _logger.info(f"   📋 Total checked: {len(null_studies)}")
                _logger.info("=" * 80)

            return {
                'updated': updated,
                'checked': len(null_studies),
                'not_found': not_found,
            }

    except Exception as e:
        _logger = logging.getLogger(__name__)
        _logger.error(f"❌ Migration error: {e}")
        import traceback
        traceback.print_exc()
        return {'updated': 0, 'checked': 0, 'not_found': 0, 'error': str(e)}


def insert_series(series_uid: str, study_fk: int, series_name: str = None, series_number: str = None,
                  series_thk: str = None, series_description: str = None, orientation: str = None,
                  modality: str = None, image_count: int = 0, protocol_name: str = None,
                  body_part_examined: str = None, manufacturer: str = None, institution_name: str = None,
                  main_thumbnail: bool = False, thumbnail_path: str = None, series_path: str = None) -> int:
    """Insert a series row and return its PK. Updates series_path if series already exists."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute(
                """
                INSERT INTO series
                    (series_uid, series_name, study_fk, series_number,
                     series_thk, series_description, orientation, modality, image_count,
                     protocol_name, body_part_examined, manufacturer, institution_name,
                     main_thumbnail, thumbnail_path, series_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    series_uid, series_name, study_fk, series_number, series_thk, series_description,
                    orientation, modality, image_count, protocol_name, body_part_examined, manufacturer,
                    institution_name, int(main_thumbnail), thumbnail_path, series_path,
                ),
            )
            series_pk = cur.lastrowid
        except sqlite3.IntegrityError:
            cur.execute(
                """
                UPDATE series
                SET study_fk = ?, series_name = ?, series_number = ?, series_thk = ?,
                    series_description = ?, orientation = ?, modality = ?, image_count = ?,
                    protocol_name = ?, body_part_examined = ?, manufacturer = ?,
                    institution_name = ?, main_thumbnail = ?, thumbnail_path = ?,
                    series_path = COALESCE(?, series_path)
                WHERE series_uid = ?
                """,
                (
                    study_fk, series_name, series_number, series_thk, series_description, orientation,
                    modality, image_count, protocol_name, body_part_examined, manufacturer,
                    institution_name, int(main_thumbnail), thumbnail_path, series_path, series_uid,
                ),
            )
            cur.execute("SELECT series_pk FROM series WHERE series_uid = ?", (series_uid,))
            series_pk = cur.fetchone()[0]

        conn.commit()
        return series_pk


def insert_instances_batch(instances: list) -> int:
    """
    Insert multiple instances in a single transaction (MUCH faster than individual inserts).

    Args:
        instances: List of dicts with keys: sop_uid, series_fk, instance_path,
                   instance_number, rows, columns (and optional geometry fields)

    Returns:
        Number of instances inserted
    """
    if not instances:
        return 0

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            insert_data = []
            for inst in instances:
                insert_data.append((
                    inst.get('sop_uid'),
                    inst.get('series_fk'),
                    inst.get('instance_path'),
                    inst.get('instance_number'),
                    inst.get('rows'),
                    inst.get('columns'),
                    inst.get('window_width'),
                    inst.get('window_center'),
                    inst.get('is_rgb', False),
                    inst.get('group_id', 0),
                    inst.get('image_position_patient'),
                    inst.get('image_orientation_patient'),
                    inst.get('pixel_spacing'),
                    inst.get('direction'),
                    inst.get('slice_thickness'),
                    inst.get('spacing_between_slices'),
                    inst.get('rescale_slope', 1.0),
                    inst.get('rescale_intercept', 0.0),
                    inst.get('bits_allocated', 16),
                    inst.get('pixel_representation', 1),
                ))

            cur.executemany(
                """
                INSERT OR REPLACE INTO instances
                    (sop_uid, series_fk, instance_path, instance_number, rows, columns,
                     window_width, window_center, is_rgb, group_id,
                     image_position_patient, image_orientation_patient, pixel_spacing, direction,
                     slice_thickness, spacing_between_slices, rescale_slope, rescale_intercept,
                     bits_allocated, pixel_representation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                insert_data,
            )

            conn.commit()
            return len(insert_data)

    except Exception as e:
        logging.getLogger(__name__).error(f"❌ Batch insert failed: {e}")
        raise


def insert_instance(sop_uid: str, series_fk: int, instance_path: str, instance_number: int = None,
                    rows: int = None, columns: int = None, window_width: float = None,
                    window_center: float = None, is_rgb: bool = False, group_id=0,
                    image_position_patient=None, image_orientation_patient=None,
                    pixel_spacing=None, direction=None, slice_thickness: float = None,
                    spacing_between_slices: float = None, rescale_slope: float = None,
                    rescale_intercept: float = None, bits_allocated: int = None,
                    pixel_representation: int = None) -> int:
    """Insert an instance row and return its PK. Updates metadata if instance already exists.

    Lists (image_position_patient, image_orientation_patient, pixel_spacing, direction)
    are stored as JSON strings for proper serialization.
    """
    def _serialize(value):
        if value is None:
            return None
        elif isinstance(value, (list, tuple)):
            return json.dumps(value)
        else:
            try:
                return json.dumps(list(value))
            except (TypeError, ValueError):
                return str(value)

    image_position_json = _serialize(image_position_patient)
    image_orientation_json = _serialize(image_orientation_patient)
    pixel_spacing_json = _serialize(pixel_spacing)
    direction_json = _serialize(direction)

    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute(
                """
                INSERT INTO instances
                    (sop_uid, series_fk, instance_path, instance_number, rows, columns,
                     window_width, window_center, is_rgb, group_id, image_position_patient,
                      image_orientation_patient, pixel_spacing, direction, slice_thickness,
                      spacing_between_slices, rescale_slope, rescale_intercept, bits_allocated,
                      pixel_representation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sop_uid, series_fk, instance_path, instance_number, rows, columns,
                    window_width, window_center, int(is_rgb), int(group_id),
                    image_position_json, image_orientation_json, pixel_spacing_json, direction_json,
                    slice_thickness, spacing_between_slices, rescale_slope, rescale_intercept,
                    bits_allocated, pixel_representation,
                ),
            )
            instance_pk = cur.lastrowid
        except sqlite3.IntegrityError:
            cur.execute(
                """
                UPDATE instances
                SET series_fk = ?, instance_path = ?, instance_number = ?,
                    rows = COALESCE(?, rows), columns = COALESCE(?, columns),
                    window_width = ?, window_center = ?, is_rgb = ?, group_id = ?,
                    image_position_patient = COALESCE(?, image_position_patient),
                    image_orientation_patient = COALESCE(?, image_orientation_patient),
                    pixel_spacing = COALESCE(?, pixel_spacing),
                    direction = COALESCE(?, direction),
                    slice_thickness = COALESCE(?, slice_thickness),
                    spacing_between_slices = COALESCE(?, spacing_between_slices),
                    rescale_slope = COALESCE(?, rescale_slope),
                    rescale_intercept = COALESCE(?, rescale_intercept),
                    bits_allocated = COALESCE(?, bits_allocated),
                    pixel_representation = COALESCE(?, pixel_representation)
                WHERE sop_uid = ?
                """,
                (
                    series_fk, instance_path, instance_number,
                    rows, columns,
                    window_width, window_center, int(is_rgb), int(group_id),
                    image_position_json, image_orientation_json,
                    pixel_spacing_json, direction_json,
                    slice_thickness, spacing_between_slices,
                    rescale_slope, rescale_intercept,
                    bits_allocated, pixel_representation,
                    sop_uid,
                ),
            )
            cur.execute("SELECT instance_pk FROM instances WHERE sop_uid = ?", (sop_uid,))
            instance_pk = cur.fetchone()[0]

        conn.commit()
        return instance_pk


# ---------------------------------------------------------------------------
# Deserialization helpers
# ---------------------------------------------------------------------------

def deserialize_instance_metadata(instance_row: dict) -> dict:
    """
    Deserialize JSON fields in an instance row.

    Args:
        instance_row: Dictionary containing instance data from database

    Returns:
        Dictionary with JSON fields deserialized to Python objects
    """
    if not instance_row:
        return instance_row

    json_fields = ['image_position_patient', 'image_orientation_patient', 'pixel_spacing', 'direction']

    for field in json_fields:
        if field in instance_row and instance_row[field] is not None:
            try:
                if isinstance(instance_row[field], str):
                    instance_row[field] = json.loads(instance_row[field])
            except (json.JSONDecodeError, ValueError):
                pass

    return instance_row


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_all_patients() -> list:
    """Return *all* patients as list of dictionaries."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT
                p.*,
                s.*
            FROM patients p
            LEFT JOIN studies s ON p.patient_pk = s.patient_fk
            ORDER BY p.patient_name, s.study_date DESC
        """)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def search_patients_local(search_data: dict) -> list:
    """
    Search patients in local database with filters.

    Args:
        search_data: Dictionary containing search criteria:
            - patient_id, patient_name, patient_sex, study_id
            - date_from, date_to  (YYYYMMDD)
            - study_description, series_description
            - modality  (comma-separated, e.g. "CT,MR")

    Returns:
        List of patient dictionaries matching the criteria
    """
    print(f"\n[DB_SEARCH] search_patients_local called")

    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        has_series_filter = bool(search_data.get('series_description'))

        if has_series_filter:
            query = """
                SELECT DISTINCT
                    p.*,
                    s.*
                FROM patients p
                LEFT JOIN studies s ON p.patient_pk = s.patient_fk
                LEFT JOIN series sr ON s.study_pk = sr.study_fk
                WHERE 1=1
            """
        else:
            query = """
                SELECT
                    p.*,
                    s.*
                FROM patients p
                LEFT JOIN studies s ON p.patient_pk = s.patient_fk
                WHERE 1=1
            """

        params = []

        if search_data.get('patient_id'):
            query += " AND LOWER(p.patient_id) LIKE LOWER(?)"
            params.append(f"%{search_data['patient_id']}%")

        if search_data.get('patient_name'):
            query += " AND LOWER(p.patient_name) LIKE LOWER(?)"
            params.append(f"%{search_data['patient_name']}%")

        if search_data.get('patient_sex'):
            query += " AND LOWER(p.patient_sex) = LOWER(?)"
            params.append(search_data['patient_sex'])

        if search_data.get('study_id'):
            query += " AND LOWER(s.study_id) LIKE LOWER(?)"
            params.append(f"%{search_data['study_id']}%")

        if search_data.get('date_from') and search_data['date_from'] is not None:
            query += " AND s.study_date >= ?"
            params.append(search_data['date_from'])

        if search_data.get('date_to') and search_data['date_to'] is not None:
            query += " AND s.study_date <= ?"
            params.append(search_data['date_to'])

        if search_data.get('study_description'):
            query += " AND LOWER(s.study_description) LIKE LOWER(?)"
            params.append(f"%{search_data['study_description']}%")

        if has_series_filter:
            query += " AND LOWER(sr.series_description) LIKE LOWER(?)"
            params.append(f"%{search_data['series_description']}%")

        if search_data.get('modality'):
            modalities = [m.strip() for m in search_data['modality'].split(',') if m.strip()]
            if modalities:
                placeholders = ','.join(['?' for _ in modalities])
                query += f" AND s.modality IN ({placeholders})"
                params.extend(modalities)

        query += " ORDER BY p.patient_name, s.study_date DESC"

        cur.execute(query, params)
        rows = cur.fetchall()
        result = [dict(r) for r in rows]
        print(f"[DB_SEARCH] Returned {len(result)} results")
        return result


def get_patient_by_id(patient_id: str) -> dict:
    """Return patient row as dict or ``None`` if not found."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def find_patient_pk(patient_id: str) -> int:
    """Find patient primary key by patient_id. Returns None if not found."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT patient_pk FROM patients WHERE patient_id = ?", (patient_id,))
        result = cur.fetchone()
        return result[0] if result else None


def find_study_pk(patient_fk: int) -> int:
    """Find study primary key by patient_fk. Returns None if not found."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT study_pk FROM studies WHERE patient_fk = ?", (patient_fk,))
        result = cur.fetchone()
        return result[0] if result else None


def find_study_pk_with_study_uid(study_uid: str) -> int:
    """Find study primary key by study_uid. Returns None if not found."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (study_uid,))
        result = cur.fetchone()
        return result[0] if result else None


def find_series_pk(series_uid: str) -> int:
    """Find series primary key by series_uid. Returns None if not found."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT series_pk FROM series WHERE series_uid = ?", (series_uid,))
        result = cur.fetchone()
        return result[0] if result else None


def find_series_pk_by_number(series_number, study_pk) -> int:
    """Find series primary key by series_number and study_pk. Returns None if not found."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT series_pk FROM series WHERE series_number = ? AND study_fk = ?",
            (str(series_number), study_pk),
        )
        result = cur.fetchone()
        return result[0] if result else None


def find_instance_pk(sop_uid: str) -> int:
    """Find instance primary key by sop_uid. Returns None if not found."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT instance_pk FROM instances WHERE sop_uid = ?", (sop_uid,))
        result = cur.fetchone()
        return result[0] if result else None


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

def find_instances_by_sop_uids(sop_uids: list) -> list:
    """
    Bulk check which instances already exist in database.
    Returns list of dicts with instance info.
    """
    if not sop_uids:
        return []

    with get_db_connection() as conn:
        cur = conn.cursor()

        placeholders = ','.join(['?' for _ in sop_uids])
        cur.execute(
            f"SELECT instance_pk, sop_uid FROM instances WHERE sop_uid IN ({placeholders})",
            sop_uids,
        )
        results = cur.fetchall()
        return [{'instance_pk': row[0], 'sop_uid': row[1]} for row in results]


def bulk_insert_instances(instances_data: list):
    """
    Bulk insert multiple instances at once for better performance.
    Uses INSERT OR REPLACE to handle duplicates gracefully.
    """
    if not instances_data:
        return

    insert_sql = """
        INSERT OR REPLACE INTO instances (
            sop_uid, series_fk, instance_path, instance_number,
            rows, columns, window_width, window_center, is_rgb, group_id,
            image_position_patient, image_orientation_patient, pixel_spacing, direction,
            slice_thickness, spacing_between_slices, rescale_slope, rescale_intercept,
            bits_allocated, pixel_representation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    values = []
    for inst in instances_data:
        instance_path = inst.get('instance_path')
        if instance_path is not None:
            try:
                instance_path = str(instance_path)
            except Exception:
                instance_path = None
        values.append((
            inst['sop_uid'], inst['series_fk'], instance_path, inst['instance_number'],
            inst['rows'], inst['columns'], inst['window_width'], inst['window_center'],
            int(inst['is_rgb']), inst['group_id'],
            inst['image_position_patient'], inst['image_orientation_patient'],
            inst['pixel_spacing'], inst['direction'],
            inst.get('slice_thickness'), inst.get('spacing_between_slices'),
            inst.get('rescale_slope', 1.0), inst.get('rescale_intercept', 0.0),
            inst.get('bits_allocated', 16), inst.get('pixel_representation', 1),
        ))

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.executemany(insert_sql, values)
            conn.commit()
    except Exception as e:
        print(f"⚠️ Warning during bulk_insert_instances: {e}")
        return


def bulk_update_instances(instances_data: list):
    """
    Bulk update multiple instances at once for better performance.
    """
    if not instances_data:
        return

    update_sql = """
        UPDATE instances
        SET series_fk = ?, instance_path = ?, instance_number = ?,
            rows = COALESCE(?, rows), columns = COALESCE(?, columns),
            window_width = ?, window_center = ?, is_rgb = ?, group_id = ?,
            image_position_patient = COALESCE(?, image_position_patient),
            image_orientation_patient = COALESCE(?, image_orientation_patient),
            pixel_spacing = COALESCE(?, pixel_spacing),
            direction = COALESCE(?, direction),
            slice_thickness = COALESCE(?, slice_thickness),
            spacing_between_slices = COALESCE(?, spacing_between_slices),
            rescale_slope = COALESCE(?, rescale_slope),
            rescale_intercept = COALESCE(?, rescale_intercept),
            bits_allocated = COALESCE(?, bits_allocated),
            pixel_representation = COALESCE(?, pixel_representation)
        WHERE sop_uid = ?
    """

    values = []
    for inst in instances_data:
        instance_path = inst.get('instance_path')
        if instance_path is not None:
            try:
                instance_path = str(instance_path)
            except Exception:
                instance_path = None
        values.append((
            inst['series_fk'], instance_path, inst['instance_number'],
            inst['rows'], inst['columns'],
            inst['window_width'], inst['window_center'],
            int(inst['is_rgb']), inst['group_id'],
            inst['image_position_patient'], inst['image_orientation_patient'],
            inst['pixel_spacing'], inst['direction'],
            inst.get('slice_thickness'), inst.get('spacing_between_slices'),
            inst.get('rescale_slope', 1.0), inst.get('rescale_intercept', 0.0),
            inst.get('bits_allocated', 16), inst.get('pixel_representation', 1),
            inst['sop_uid'],
        ))

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.executemany(update_sql, values)
        conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Storage / cleanup helpers
# ---------------------------------------------------------------------------

def get_patients_ordered_by_date(limit: int = None, oldest_first: bool = True) -> list:
    """
    Get patients ordered by earliest study date for cleanup selection.

    Args:
        limit: Maximum number of patients to return (None for all)
        oldest_first: If True, order by oldest first (default), else newest first

    Returns:
        List of dicts with patient info and study count
    """
    order = "ASC" if oldest_first else "DESC"
    limit_clause = f"LIMIT {limit}" if limit else ""

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT
                    p.patient_pk,
                    p.patient_id,
                    p.patient_name,
                    p.sex,
                    p.age,
                    MIN(s.study_date) as earliest_study,
                    MAX(s.study_date) as latest_study,
                    COUNT(DISTINCT s.study_pk) as study_count
                FROM patients p
                LEFT JOIN studies s ON p.patient_pk = s.patient_fk
                GROUP BY p.patient_pk
                HAVING study_count > 0
                ORDER BY earliest_study {order}
                {limit_clause}
            """)

            results = cur.fetchall()
            return [
                {
                    'patient_pk': row[0], 'patient_id': row[1], 'patient_name': row[2],
                    'sex': row[3], 'age': row[4], 'earliest_study': row[5],
                    'latest_study': row[6], 'study_count': row[7],
                }
                for row in results
            ]

    except Exception as e:
        print(f"[WARNING] Database error in get_patients_ordered_by_date: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_patient_storage_info(patient_pk: int) -> dict:
    """
    Get comprehensive storage information for a patient including all file references.

    Args:
        patient_pk: Patient primary key

    Returns:
        Dict with patient_id, patient_name, study_uids, and file path lists
    """
    empty = {
        'patient_id': None, 'patient_name': None, 'study_uids': [],
        'study_paths': [], 'series_paths': [], 'instance_paths': [], 'attachment_paths': [],
    }

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            cur.execute(
                "SELECT patient_id, patient_name FROM patients WHERE patient_pk = ?",
                (patient_pk,),
            )
            patient_row = cur.fetchone()
            if not patient_row:
                return empty

            patient_id, patient_name = patient_row

            cur.execute(
                "SELECT study_uid, study_path, attachments_uploaded FROM studies WHERE patient_fk = ?",
                (patient_pk,),
            )
            studies = cur.fetchall()
            study_uids = [row[0] for row in studies if row[0]]
            study_paths = [row[1] for row in studies if row[1]]

            attachment_paths = []
            for row in studies:
                if row[2]:
                    paths = [p.strip() for p in row[2].split(',') if p.strip()]
                    attachment_paths.extend(paths)

            cur.execute("""
                SELECT DISTINCT se.series_path
                FROM series se
                JOIN studies s ON se.study_fk = s.study_pk
                WHERE s.patient_fk = ?
                AND se.series_path IS NOT NULL
            """, (patient_pk,))
            series_paths = [row[0] for row in cur.fetchall()]

            cur.execute("""
                SELECT DISTINCT i.instance_path
                FROM instances i
                JOIN series se ON i.series_fk = se.series_pk
                JOIN studies s ON se.study_fk = s.study_pk
                WHERE s.patient_fk = ?
                AND i.instance_path IS NOT NULL
            """, (patient_pk,))
            instance_paths = [row[0] for row in cur.fetchall()]

            return {
                'patient_id': patient_id,
                'patient_name': patient_name,
                'study_uids': study_uids,
                'study_paths': study_paths,
                'series_paths': series_paths,
                'instance_paths': instance_paths,
                'attachment_paths': attachment_paths,
            }

    except Exception as e:
        print(f"[WARNING] Database error in get_patient_storage_info: {e}")
        import traceback
        traceback.print_exc()
        return empty


def delete_patient_cascade(patient_pk: int) -> bool:
    """
    Delete patient and all related records from database using CASCADE.

    Args:
        patient_pk: Patient primary key

    Returns:
        True if successful, False otherwise
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM patients WHERE patient_pk = ?", (patient_pk,))
            deleted = cur.rowcount
            conn.commit()

            if deleted > 0:
                print(f"[OK] Deleted patient {patient_pk} from database (CASCADE)")
                return True
            else:
                print(f"[WARNING] Patient {patient_pk} not found in database")
                return False

    except Exception as e:
        print(f"[WARNING] Database error in delete_patient_cascade: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_patients_by_date_range(start_date: str = None, end_date: str = None) -> list:
    """
    Get patients with studies within a specific date range.

    Args:
        start_date: Start date in YYYYMMDD format (inclusive, None for no start limit)
        end_date: End date in YYYYMMDD format (inclusive, None for no end limit)

    Returns:
        List of dicts with patient info
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            where_clauses = []
            params = []

            if start_date:
                where_clauses.append("s.study_date >= ?")
                params.append(start_date)

            if end_date:
                where_clauses.append("s.study_date <= ?")
                params.append(end_date)

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            cur.execute(f"""
                SELECT
                    p.patient_pk,
                    p.patient_id,
                    p.patient_name,
                    MIN(s.study_date) as earliest_study,
                    MAX(s.study_date) as latest_study,
                    COUNT(DISTINCT s.study_pk) as study_count
                FROM patients p
                JOIN studies s ON p.patient_pk = s.patient_fk
                {where_sql}
                GROUP BY p.patient_pk
                ORDER BY earliest_study DESC
            """, params)

            results = cur.fetchall()
            return [
                {
                    'patient_pk': row[0], 'patient_id': row[1], 'patient_name': row[2],
                    'earliest_study': row[3], 'latest_study': row[4], 'study_count': row[5],
                }
                for row in results
            ]

    except Exception as e:
        print(f"[WARNING] Database error in get_patients_by_date_range: {e}")
        import traceback
        traceback.print_exc()
        return []
