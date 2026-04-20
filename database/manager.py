from . import core as database
import ast

def init_database():
    return database.init_database()


def insert_patient(patient_id: str, name: str, birth_date: str = None, sex: str = None, age: str = None,
                   patient_weight: str = None) -> int:
    return database.insert_patient(patient_id, name, birth_date, sex, age, patient_weight)


def insert_study(study_uid: str, patient_fk: int, study_date: str = None, study_time: str = None,
                 study_description: str = None, institution_name: str = None, modality: str = None,
                 body_part: str = None, number_of_series: int = 0, number_of_instances: int = 0,
                 study_path: str = None) -> int:
    return database.insert_study(study_uid, patient_fk, study_date, study_time, study_description, institution_name,
                                 modality, body_part, number_of_series, number_of_instances, study_path)


def insert_series(series_uid: str, study_fk: int, series_name: str = None, series_number: str = None,
                  series_thk: str = None, series_description: str = None, orientation: str = None,
                  modality: str = None, image_count: int = 0, protocol_name: str = None,
                  body_part_examined: str = None, manufacturer: str = None, institution_name: str = None,
                  main_thumbnail: bool = False, thumbnail_path: str = None, series_path: str = None) -> int:
    return database.insert_series(series_uid, study_fk, series_name, series_number, series_thk,
                                  series_description, orientation, modality, image_count, protocol_name,
                                  body_part_examined, manufacturer, institution_name, main_thumbnail,
                                  thumbnail_path, series_path)


def insert_instance(sop_uid: str, series_fk: int, instance_path: str, instance_number: int = None, rows: int = None,
                    columns: int = None, window_width: float = None, window_center: float = None,
                    is_rgb: bool = False, group_id=0, image_position_patient=None, image_orientation_patient=None,
                    pixel_spacing=None, direction=None, slice_thickness: float = None,
                    spacing_between_slices: float = None, rescale_slope: float = None,
                    rescale_intercept: float = None, bits_allocated: int = None,
                    pixel_representation: int = None) -> int:
    return database.insert_instance(sop_uid, series_fk, instance_path, instance_number, rows, columns, window_width,
                                    window_center, is_rgb, group_id, image_position_patient, image_orientation_patient,
                                    pixel_spacing, direction, slice_thickness, spacing_between_slices,
                                    rescale_slope, rescale_intercept, bits_allocated, pixel_representation)


###############################################################################################


def find_patient_pk(patient_id: str):
    return database.find_patient_pk(patient_id)


def find_study_pk(patient_pk: str):
    return database.find_study_pk(patient_pk)


def find_study_pk_with_study_uid(study_uid: str):
    return database.find_study_pk_with_study_uid(study_uid)


def find_series_pk(series_uid: str):
    return database.find_series_pk(series_uid)


def find_instance_pk(sop_uid: str):
    return database.find_instance_pk(sop_uid)


###############################################################################################


def get_patient_by_patient_pk(patient_pk: str):
    with database.get_db_connection() as conn:
        conn.row_factory = None
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients WHERE patient_pk = ?", (patient_pk,))
        row = cur.fetchone()
        if row:
            columns = [d[0] for d in cur.description]
            return dict(zip(columns, row))
        return None


def get_studies_by_patient_pk(patient_pk: str):
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM studies WHERE patient_fk = ?", (patient_pk,))
        row = cur.fetchone()
        if row:
            columns = [d[0] for d in cur.description]
            return dict(zip(columns, row))
        return None


def get_study_by_study_uid(study_uid: str):
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM studies WHERE study_uid = ?", (study_uid,))
        row = cur.fetchone()
        if row:
            columns = [d[0] for d in cur.description]
            return dict(zip(columns, row))
        return None


def get_patient_by_study_uid(study_uid: str):
    """Get patient information by study UID"""
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                p.patient_pk,
                p.patient_id,
                p.patient_name,
                p.birth_date,
                p.sex,
                p.age,
                p.patient_weight
            FROM patients p
            JOIN studies s ON p.patient_pk = s.patient_fk
            WHERE s.study_uid = ?
        """, (study_uid,))
        
        row = cur.fetchone()
        if row:
            keys = [
                'patient_pk',
                'patient_id',
                'patient_name',
                'birth_date',
                'patient_sex',
                'patient_age',
                'patient_weight'
            ]
            return dict(zip(keys, row))
        return None


def get_series_by_study_pk(study_pk: int) -> list[dict]:
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM series WHERE study_fk = ? ORDER BY series_number", (study_pk,))
        rows = cur.fetchall()
        columns = [description[0] for description in cur.description]
        return [dict(zip(columns, row)) for row in rows]


def get_study_info_with_series(study_uid: str) -> dict:
    """
    Get complete study information including patient data and series list.
    Used for download retry when state is not found.
    """
    try:
        with database.get_db_connection() as conn:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT 
                    s.study_uid, s.study_date, s.study_time, s.study_description,
                    s.modality, s.body_part, s.number_of_series, s.number_of_instances,
                    p.patient_id, p.patient_name, p.birth_date, p.sex, p.age
                FROM studies s
                JOIN patients p ON s.patient_fk = p.patient_pk
                WHERE s.study_uid = ?
            """, (study_uid,))
            
            study_row = cur.fetchone()
            if not study_row:
                return None
            
            study_pk = find_study_pk_with_study_uid(study_uid)
            cur.execute("""
                SELECT series_uid, series_number, series_description, modality,
                       image_count, protocol_name, body_part_examined, manufacturer,
                       institution_name, thumbnail_path
                FROM series WHERE study_fk = ? ORDER BY series_number
            """, (study_pk,))
            
            series_list = [
                {
                    'series_uid': sr[0], 'series_number': sr[1],
                    'series_description': sr[2] or '', 'modality': sr[3] or '',
                    'image_count': sr[4] or 0, 'protocol_name': sr[5],
                    'body_part_examined': sr[6], 'manufacturer': sr[7],
                    'institution_name': sr[8], 'thumbnail_path': sr[9]
                }
                for sr in cur.fetchall()
            ]
            
            return {
                'study_uid': study_row[0], 'study_date': study_row[1] or '',
                'study_time': study_row[2] or '', 'study_description': study_row[3] or '',
                'modality': study_row[4] or '', 'body_part': study_row[5] or '',
                'series_count': study_row[6] or 0, 'images_count': study_row[7] or 0,
                'patient_id': study_row[8] or '', 'patient_name': study_row[9] or '',
                'patient_birth_date': study_row[10] or '', 'patient_sex': study_row[11] or '',
                'patient_age': study_row[12] or '', 'series': series_list
            }
        
    except Exception as e:
        print(f"❌ Error getting study info with series: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_series_by_study_and_number(study_uid: str, series_number: int) -> dict:
    """Get series information by study UID and series number"""
    try:
        with database.get_db_connection() as conn:
            cur = conn.cursor()
            study_pk = find_study_pk_with_study_uid(study_uid)
            if not study_pk:
                return {}
            cur.execute("SELECT * FROM series WHERE study_fk = ? AND series_number = ?", (study_pk, series_number))
            row = cur.fetchone()
            if row:
                columns = [d[0] for d in cur.description]
                return dict(zip(columns, row))
            return {}
    except Exception as e:
        print(f"Error getting series by study and number: {str(e)}")
        return {}


def get_series_by_series_pk(series_pk):
    try:
        with database.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM series WHERE series_pk = ?", (series_pk,))
            row = cur.fetchone()
            if row:
                columns = [d[0] for d in cur.description]
                return dict(zip(columns, row))
            return None
    except Exception:
        return None


def get_instances_by_series_pk(series_pk: int, group_id: int) -> list[dict]:
    import json as _json
    try:
        with database.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    instance_pk, sop_uid, series_fk, instance_path, instance_number,
                    rows, columns, window_width, window_center, is_rgb, group_id,
                    image_position_patient, image_orientation_patient, pixel_spacing, direction,
                    slice_thickness, spacing_between_slices, rescale_slope, rescale_intercept,
                    bits_allocated, pixel_representation
                FROM instances
                WHERE series_fk = ? AND group_id = ?
                ORDER BY instance_number
                """,
                (series_pk, group_id),
            )
            rows = cur.fetchall()
            if not rows:
                return []
            columns = [d[0] for d in cur.description]
            result = []
            for row in rows:
                d = dict(zip(columns, row))
                for field in ('image_position_patient', 'image_orientation_patient', 'pixel_spacing', 'direction'):
                    val = d.get(field)
                    if val is not None and isinstance(val, str):
                        try:
                            d[field] = _json.loads(val)
                        except (ValueError, _json.JSONDecodeError):
                            try:
                                d[field] = ast.literal_eval(val)
                            except Exception:
                                d[field] = None
                result.append(d)
            return result
    except Exception:
        return []


def update_series_thumbnail_path(series_pk: int, thumbnail_path: str) -> bool:
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE series
            SET thumbnail_path = ?
            WHERE series_pk = ?
        """, (thumbnail_path, series_pk))
        conn.commit()
        return cur.rowcount > 0


def update_series_image_count_by_uid(study_uid: str, series_number: str, image_count: int) -> bool:
    """Set image_count for a series identified by study UID + series number.

    Unlike ``update_series_missing_fields`` this always overwrites existing
    values (including 0).  Used when a reliable count arrives from the gRPC
    thumbnail response so the DB stays accurate across restarts.
    """
    if not study_uid or not series_number or image_count is None:
        return False
    try:
        study_pk = find_study_pk_with_study_uid(study_uid)
        if not study_pk:
            return False
        with database.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE series SET image_count = ? WHERE study_fk = ? AND series_number = ?",
                (int(image_count), study_pk, str(series_number)),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def get_series_thumbnail_path(series_pk: int):
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT thumbnail_path
            FROM series
            WHERE series_pk = ?
        """, (series_pk,))
        row = cur.fetchone()
        return row[0] if row else None


def get_count_instances_in_study(study_uid: str) -> int:
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM series AS s
            JOIN instances AS i ON i.series_fk = s.series_pk
            WHERE s.study_fk = (
                SELECT study_pk FROM studies WHERE study_uid = ?
            )
        """, (study_uid,))
        row = cur.fetchone()
        return row[0] if row else 0


def update_study_counts_by_uid(
        study_uid: str,
        number_of_series: int | None,
        number_of_instances: int | None,
) -> int:
    """
    با استفاده از study_uid، فیلدهای number_of_series و/یا number_of_instances را آپدیت می‌کند.
    برمی‌گرداند: تعداد ردیف‌های تغییر کرده (rows affected).
    """
    if number_of_series is None and number_of_instances is None:
        return 0

    sets = []
    params = []
    if number_of_series is not None:
        sets.append("number_of_series = ?")
        params.append(number_of_series)
    if number_of_instances is not None:
        sets.append("number_of_instances = ?")
        params.append(number_of_instances)

    params.append(study_uid)

    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE studies SET {', '.join(sets)} WHERE study_uid = ?", params)
        conn.commit()
        return cur.rowcount


###############################################################################################


# --- helpers for "update only if empty" ---
def _is_textlike(val):
    return isinstance(val, str)


def _build_update_if_missing_clause(fields: dict[str, object]) -> tuple[str, list]:
    """
    fields: mapping column -> new_value
    خروجی: (sql_set_clause, params)
    هر ستون به‌شکل:
      col = CASE WHEN (col IS NULL OR col='' OR col='N/A' OR col='Unknown') THEN ? ELSE col END   -- برای رشته‌ها
      col = CASE WHEN (col IS NULL) THEN ? ELSE col END                         -- برای عددی/غیررشته‌ای
    """
    sets = []
    params = []
    for col, val in fields.items():
        if val is None:
            # اگر مقدار جدید نداریم، از آپدیت آن ستون صرف‌نظر کن
            continue
        if _is_textlike(val):
            sets.append(f"{col} = CASE WHEN {col} IS NULL OR {col}='' OR {col}='N/A' OR {col}='Unknown' THEN ? ELSE {col} END")
        else:
            sets.append(f"{col} = CASE WHEN {col} IS NULL THEN ? ELSE {col} END")
        params.append(val)
    return ", ".join(sets), params


def update_patient_missing_fields(patient_pk: int, *,
                                  patient_id: str = None,
                                  name: str = None,
                                  birth_date: str = None,
                                  sex: str = None,
                                  age: str = None,
                                  patient_weight: str = None) -> int:
    fields = {
        "patient_id": patient_id,
        "patient_name": name,
        "birth_date": birth_date,
        "sex": sex,
        "age": age,
        "patient_weight": patient_weight,
    }
    set_sql, params = _build_update_if_missing_clause(fields)
    if not set_sql:
        return 0
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE patients SET {set_sql} WHERE patient_pk = ?", (*params, patient_pk))
        conn.commit()
        return cur.rowcount


def update_study_missing_fields(study_pk: int, *,
                                study_uid: str = None,
                                study_date: str = None,
                                study_time: str = None,
                                study_description: str = None,
                                institution_name: str = None,
                                modality: str = None,
                                body_part: str = None,
                                number_of_series: int = None,
                                number_of_instances: int = None,
                                study_path: str = None) -> int:
    fields = {
        "study_uid": study_uid,
        "study_date": study_date,
        "study_time": study_time,
        "study_description": study_description,
        "institution_name": institution_name,
        "modality": modality,
        "body_part": body_part,
        "number_of_series": number_of_series,
        "number_of_instances": number_of_instances,
        "study_path": study_path,
    }
    set_sql, params = _build_update_if_missing_clause(fields)
    if not set_sql:
        return 0
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE studies SET {set_sql} WHERE study_pk = ?", (*params, study_pk))
        conn.commit()
        return cur.rowcount


def force_update_study_path(study_pk: int, study_path: str) -> int:
    """Unconditionally overwrite study_path (even if not NULL)."""
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE studies SET study_path = ? WHERE study_pk = ?",
                    (study_path, study_pk))
        conn.commit()
        return cur.rowcount


def update_series_missing_fields(series_pk: int, *,
                                 series_uid: str = None,
                                 series_name: str = None,
                                 series_number: str = None,
                                 series_thk: str = None,
                                 series_description: str = None,
                                 orientation: str = None,
                                 modality: str = None,
                                 image_count: int = None,
                                 protocol_name: str = None,
                                 body_part_examined: str = None,
                                 manufacturer: str = None,
                                 institution_name: str = None,
                                 main_thumbnail: bool = None,
                                 thumbnail_path: str = None,
                                 series_path: str = None) -> int:
    # توجه: main_thumbnail مقدار بولی است؛ اگر None نبود، فقط وقتی NULL باشد آپدیت می‌شود
    fields = {
        "series_uid": series_uid,
        "series_name": series_name,
        "series_number": series_number,
        "series_thk": series_thk,
        "series_description": series_description,
        "orientation": orientation,
        "modality": modality,
        "image_count": image_count,
        "protocol_name": protocol_name,
        "body_part_examined": body_part_examined,
        "manufacturer": manufacturer,
        "institution_name": institution_name,
        "main_thumbnail": int(main_thumbnail) if main_thumbnail is not None else None,
        "thumbnail_path": thumbnail_path,
        "series_path": series_path,
    }
    set_sql, params = _build_update_if_missing_clause(fields)
    if not set_sql:
        return 0
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE series SET {set_sql} WHERE series_pk = ?", (*params, series_pk))
        conn.commit()
        return cur.rowcount


def update_instance_missing_fields(instance_pk: int, *,
                                   sop_uid: str = None,
                                   instance_path: str = None,
                                   instance_number: int = None,
                                   rows: int = None,
                                   columns: int = None,
                                   window_width: float = None,
                                   window_center: float = None,
                                   is_rgb: bool = None,
                                   group_id: int = None,
                                   image_position_patient: str = None,
                                   image_orientation_patient: str = None,
                                   pixel_spacing: str = None,
                                   direction: str = None) -> int:
    fields = {
        "sop_uid": sop_uid,
        "instance_path": instance_path,
        "instance_number": instance_number,
        "rows": rows,
        "columns": columns,
        "window_width": window_width,
        "window_center": window_center,
        "is_rgb": int(is_rgb) if is_rgb is not None else None,
        "group_id": group_id,
        "image_position_patient": image_position_patient,
        "image_orientation_patient": image_orientation_patient,
        "pixel_spacing": pixel_spacing,
        "direction": direction,
    }
    set_sql, params = _build_update_if_missing_clause(fields)
    if not set_sql:
        return 0
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE instances SET {set_sql} WHERE instance_pk = ?", (*params, instance_pk))
        conn.commit()
        return cur.rowcount


# =============================
# AI Chat passthroughs
# =============================
from . import core as _db_ai


def ai_ensure_schema(): return _db_ai.ai_ensure_schema()


# --- sessions ---
def ai_upsert_session(sid: str, title: str | None = None, study_uid: str | None = None):
    return _db_ai.ai_upsert_session(sid, title, study_uid)


def ai_update_session_title(sid: str, title: str):
    return _db_ai.ai_update_session_title(sid, title)


def ai_set_server_sid(sid: str, server_sid: str | None):
    return _db_ai.ai_set_server_sid(sid, server_sid)


def ai_get_server_sid(sid: str):
    return _db_ai.ai_get_server_sid(sid)


def ai_fetch_sid_pairs():
    return _db_ai.ai_fetch_sid_pairs()


def ai_fetch_sessions_by_study(study_uid: str):
    return _db_ai.ai_fetch_sessions_by_study(study_uid)


def ai_fetch_all_sessions():
    return _db_ai.ai_fetch_all_sessions()


# --- messages ---
def ai_append_message(sid: str, who: str, html: str, ts: int | None = None, origin: str | None = None):
    return _db_ai.ai_append_message(sid, who, html, ts, origin)


def ai_update_message(msg_id: int, new_html: str):
    return _db_ai.ai_update_message(msg_id, new_html)


def ai_fetch_messages_full(sid: str):
    return _db_ai.ai_fetch_messages_full(sid)


def ai_fetch_messages(sid: str):
    return _db_ai.ai_fetch_messages(sid)


def ai_reassign_session(old_sid: str, new_sid: str, new_title: str | None = None):
    return _db_ai.ai_reassign_session(old_sid, new_sid, new_title)


# --- last-session (global & per-study) ---
def ai_set_last_session(sid: str):
    return _db_ai.ai_set_last_session(sid)


def ai_get_last_session():
    return _db_ai.ai_get_last_session()


def ai_set_last_session_for_study(study_uid: str, sid: str):
    return _db_ai.ai_set_last_session_for_study(study_uid, sid)


def ai_get_last_session_for_study(study_uid: str):
    return _db_ai.ai_get_last_session_for_study(study_uid)


def ai_backfill_sessions_from_messages():
    return _db_ai.ai_backfill_sessions_from_messages()


def ai_reassign_sid():
    return None


def append_attachments_uploaded(study_uid: str, value: str, sep: str = ",") -> bool:
    """
    مقدار جدید را به انتهای attachments_uploaded اضافه می‌کند.
    اگر مقدار قبلی خالی/NULL باشد، همان value ذخیره می‌شود.
    برمی‌گرداند: True اگر ردیفی آپدیت شد.
    
    ✅ بهبود: مسیر را normalize می‌کند تا از تکرار جلوگیری شود
    """
    if not study_uid or value is None:
        return False
    
    # ✅ Normalize مسیر قبل از ذخیره (absolute path و حذف / یا \ اضافی)
    from pathlib import Path
    try:
        value_normalized = str(Path(value).resolve())
    except Exception:
        # اگر مسیر نامعتبر بود، همان value را استفاده کن
        value_normalized = value

    with database.get_db_connection() as conn:
        cur = conn.cursor()
        
        # ✅ بررسی که آیا این مسیر قبلاً ذخیره شده یا نه
        cur.execute(
            "SELECT attachments_uploaded FROM studies WHERE study_uid = ?",
            (study_uid,)
        )
        row = cur.fetchone()
        existing_value = row[0] if row and row[0] else ""
        
        # اگر قبلاً ذخیره شده، نباید دوباره اضافه شود
        if existing_value:
            existing_paths = existing_value.split(sep)
            # نرمال‌سازی مسیرهای موجود
            existing_normalized = set()
            for p in existing_paths:
                if p.strip():
                    try:
                        existing_normalized.add(str(Path(p).resolve()))
                    except Exception:
                        existing_normalized.add(p)
            
            # اگر مسیر قبلاً ذخیره شده، نیازی به آپدیت نیست
            if value_normalized in existing_normalized:
                return False

        # اگر قبلا مقداری داشته باشد، با sep بچسبان؛ در غیر اینصورت همان value
        cur.execute(
            f"""
            UPDATE studies
            SET attachments_uploaded = 
                CASE 
                    WHEN attachments_uploaded IS NULL OR attachments_uploaded='' 
                        THEN ?
                    ELSE attachments_uploaded || ?
                END
            WHERE study_uid = ?
            """,
            (value_normalized, f"{sep}{value_normalized}", study_uid)
        )
        conn.commit()
        return cur.rowcount > 0


def get_attachments_uploaded(study_uid: str) -> str | None:
    """
    مقدار attachments_uploaded را بر اساس study_uid برمی‌گرداند.
    """
    if not study_uid:
        return None
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT attachments_uploaded FROM studies WHERE study_uid = ?",
            (study_uid,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_series_path_with_study_pk_and_series_number(study_fk: int, series_number: int) -> str | None:
    """
    از جدول series، با داشتن study_fk و series_number، مسیر سری (series_path) را برمی‌گرداند.
    اگر پیدا نشد، None برمی‌گرداند.
    """
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT series_path
            FROM series
            WHERE study_fk = ?
              AND CAST(series_number AS INTEGER) = ?
            ORDER BY series_pk
            LIMIT 1
        """, (study_fk, series_number))
        row = cur.fetchone()
        return row[0] if row and row[0] else None


# ============================================================================
# Filming Folder Metadata Management
# ============================================================================

def ensure_filming_columns() -> None:
    """
    Ensure filming metadata columns exist on studies table.

    Columns:
      - has_filming: INTEGER (0/1)
      - filming_folder_path: TEXT
    """
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(studies)")
            columns = [info[1] for info in cur.fetchall()]

            if 'has_filming' not in columns:
                cur.execute("ALTER TABLE studies ADD COLUMN has_filming INTEGER DEFAULT 0")
            if 'filming_folder_path' not in columns:
                cur.execute("ALTER TABLE studies ADD COLUMN filming_folder_path TEXT DEFAULT NULL")

            conn.commit()
        except Exception as e:
            print(f"⚠️ [DB] Error ensuring filming columns: {e}")


def set_filming_folder_for_study(study_uid: str, folder_path: str) -> bool:
    """
    Mark study as having Filming data and store folder path.
    """
    if not study_uid or not folder_path:
        return False

    with database.get_db_connection() as conn:
        cur = conn.cursor()
        try:
            ensure_filming_columns()
            cur.execute(
                """
                UPDATE studies
                SET has_filming = 1,
                    filming_folder_path = ?
                WHERE study_uid = ?
                """,
                (folder_path, study_uid),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            print(f"⚠️ [DB] Error setting filming folder: {e}")
            return False


def get_filming_folder_for_study(study_uid: str) -> str | None:
    """
    Return filming folder path for a study if present.
    """
    if not study_uid:
        return None

    with database.get_db_connection() as conn:
        cur = conn.cursor()
        try:
            ensure_filming_columns()
            cur.execute(
                """
                SELECT filming_folder_path
                FROM studies
                WHERE study_uid = ? AND COALESCE(has_filming, 0) = 1
                """,
                (study_uid,),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] else None
        except Exception:
            return None


# ============================================================================
# Visit Status Management
# ============================================================================

def ensure_visit_status_column():
    """
    اطمینان از وجود ستون visit_status در جدول studies.
    اگر وجود نداشته باشد، اضافه می‌شود.
    """
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(studies)")
            columns = [info[1] for info in cur.fetchall()]
            
            if 'visit_status' not in columns:
                cur.execute("ALTER TABLE studies ADD COLUMN visit_status TEXT DEFAULT NULL")
                conn.commit()
        except Exception as e:
            print(f"⚠️ [DB] Error ensuring visit_status column: {e}")


def get_visit_status(study_uid: str) -> str | None:
    """
    وضعیت بازدید را برای یک study برمی‌گرداند.
    
    Returns:
        'opened': بیمار باز شده
        'synced': بیمار سینک شده
        None: بیمار دیده نشده
    """
    if not study_uid:
        return None
    
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT visit_status FROM studies WHERE study_uid = ?",
                (study_uid,)
            )
            row = cur.fetchone()
            return row[0] if row else None
        except Exception:
            return None


def set_visit_status(study_uid: str, status: str) -> bool:
    """
    وضعیت بازدید را برای یک study تنظیم می‌کند.
    
    Args:
        study_uid: شناسه study
        status: 'opened' یا 'synced'
    
    Returns:
        True اگر موفق بود، False در غیر این صورت
    """
    if not study_uid or status not in ('opened', 'synced', None):
        return False
    
    with database.get_db_connection() as conn:
        cur = conn.cursor()
        try:
            ensure_visit_status_column()
            
            cur.execute(
                "UPDATE studies SET visit_status = ? WHERE study_uid = ?",
                (status, study_uid)
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            print(f"⚠️ [DB] Error setting visit_status: {e}")
            return False

def get_series_by_study_uid(study_uid: str) -> list[dict]:
    """
    Get all series for a study by study UID
    Returns:
        List of series dictionaries with all relevant fields
    """
    try:
        with database.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT se.*
                FROM series AS se
                JOIN studies AS st ON st.study_pk = se.study_fk
                WHERE st.study_uid = ?
                ORDER BY se.series_number
                """,
                (study_uid,),
            )
            rows = cur.fetchall()
            columns = [description[0] for description in cur.description]
            return [dict(zip(columns, row)) for row in rows]
        
    except Exception as e:
        print(f"Error getting series by study UID: {str(e)}")
        return []


def migrate_fix_null_study_paths() -> dict:
    """
    Run migration to fix studies with NULL study_path by checking disk.
    
    When studies are imported from Socket/PACS, they may have study_path=NULL in the database.
    This function:
    1. Finds all studies with study_path IS NULL
    2. Checks if files exist on disk at SOURCE_PATH/{study_uid}
    3. Updates database with correct study_path if files exist
    
    Returns:
        dict: {'updated': count, 'checked': count, 'not_found': count}
    """
    return database.migrate_fix_null_study_paths()
