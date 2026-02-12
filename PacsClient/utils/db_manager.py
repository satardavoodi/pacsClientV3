from . import database
import ast


def get_connection_database():
    return database.get_connection_database()


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
                    columns: int = None, window_width: float = 127.5, window_center: float = 255.0,
                    is_rgb: bool = False, group_id=0, image_position_patient=None, image_orientation_patient=None,
                    pixel_spacing=None, direction=None) -> int:
    return database.insert_instance(sop_uid, series_fk, instance_path, instance_number, rows, columns, window_width,
                                    window_center, is_rgb, group_id, image_position_patient, image_orientation_patient,
                                    pixel_spacing, direction)


###############################################################################################


def find_patient_pk(patient_id: str):
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT patient_pk FROM patients WHERE patient_id = ?", (patient_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    return


def find_study_pk(patient_pk: str):
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT study_pk FROM studies WHERE patient_fk = ?", (patient_pk,))
    row = cur.fetchone()
    if row:
        return row[0]
    return


def find_study_pk_with_study_uid(study_uid: str):
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (study_uid,))
    row = cur.fetchone()
    if row:
        return row[0]
    return


def find_series_pk(series_uid: str):
    conn = get_connection_database()
    cur = conn.cursor()

    cur.execute("SELECT series_pk FROM series WHERE series_uid = ?", (series_uid,))
    row = cur.fetchone()
    if row:
        return row[0]
    return


def find_instance_pk(sop_uid: str):
    conn = get_connection_database()
    cur = conn.cursor()

    cur.execute("SELECT instance_pk FROM instances WHERE sop_uid = ?", (sop_uid,))
    row = cur.fetchone()
    if row:
        return row[0]
    return


###############################################################################################


def get_patient_by_patient_pk(patient_pk: str):
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT * FROM patients WHERE patient_pk = ?", (patient_pk,))
    row = cur.fetchone()
    keys = [
        'patient_pk',
        'patient_id',
        'patient_name',
        'birthday',
        'patient_sex',
        'patient_age',
        'patient_weight'

    ]
    if row:
        return dict(zip(keys, row))
        # return dict(row) if row else None
    return


def get_studies_by_patient_pk(patient_pk: str):
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT * FROM studies WHERE patient_fk = ?", (patient_pk,))
    row = cur.fetchone()

    keys = [
        'study_pk',
        'study_uid',
        'patient_fk',
        'study_date',
        'study_time',
        'study_description',
        'institution_name',
        'modality',
        'body_part',
        'number_of_series',
        'number_of_instances',
        'study_path'
    ]
    if row:
        dic = dict(zip(keys, row))
        # del dic['patient_fk']
        return dic

    return

    # return dict(row) if row else None
    # cur.execute("SELECT * FROM studies WHERE patient_fk = ? ORDER BY study_date, study_time", (patient_pk,))
    # return [dict(r) for r in cur.fetchall()]


def get_study_by_study_uid(study_uid: str):
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute("SELECT * FROM studies WHERE study_uid = ?", (study_uid,))
    row = cur.fetchone()

    keys = [
        'study_pk',
        'study_uid',
        'patient_fk',
        'study_date',
        'study_time',
        'study_description',
        'institution_name',
        'modality',
        'body_part',
        'number_of_series',
        'number_of_instances',
        'study_path'

    ]
    if row:
        dic = dict(zip(keys, row))
        # del dic['patient_fk']
        return dic

    return


def get_patient_by_study_uid(study_uid: str):
    """Get patient information by study UID"""
    conn = get_connection_database()
    cur = conn.cursor()
    
    # Join studies and patients tables
    # ✅ CRITICAL FIX: Use correct column names from schema (birth_date, sex, age)
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
    conn = get_connection_database()
    cur = conn.cursor()

    cur.execute("SELECT * FROM series WHERE study_fk = ? ORDER BY series_number", (study_pk,))
    rows = cur.fetchall()

    # Convert rows to dictionaries
    columns = [description[0] for description in cur.description]
    return [dict(zip(columns, row)) for row in rows]


def get_series_by_study_and_number(study_uid: str, series_number: int) -> dict:
    """Get series information by study UID and series number"""
    try:
        conn = get_connection_database()
        cur = conn.cursor()

        # First get the study_pk
        study_pk = find_study_pk_with_study_uid(study_uid)
        if not study_pk:
            return {}

        # Then get the series
        cur.execute("SELECT * FROM series WHERE study_fk = ? AND series_number = ?", (study_pk, series_number))
        row = cur.fetchone()

        if row:
            # Convert row to dictionary
            columns = [description[0] for description in cur.description]
            return dict(zip(columns, row))
        return {}

    except Exception as e:
        print(f"Error getting series by study and number: {str(e)}")
        return {}


def get_series_by_series_pk(series_pk):
    conn = get_connection_database()
    cur = conn.cursor()

    cur.execute("SELECT * FROM series WHERE series_pk = ?", (series_pk,))
    row = cur.fetchone()

    keys = [
        'series_pk',
        'series_uid',
        'series_name',
        'study_fk',
        'series_number',
        'series_thk',
        'series_description',
        'orientation',
        'modality',
        'image_count',
        'protocol_name',
        'body_part_examined',
        'manufacturer',
        'institution_name',
        'main_thumbnail',
        'thumbnail_path',
        'series_path',
    ]
    if row:
        dic = dict(zip(keys, row))
        # del dic['patient_fk']
        return dic

    return


def get_instances_by_series_pk(series_pk: int, group_id: int) -> list[dict]:
    conn = get_connection_database()
    cur = conn.cursor()

    cur.execute("SELECT * FROM instances WHERE series_fk = ? AND group_id = ? ORDER BY instance_number",
                (series_pk, group_id))
    rows = cur.fetchall()

    keys = [
        'instance_pk',
        'sop_uid',
        'series_fk',
        'instance_path',
        'instance_number',
        'rows',
        'columns',
        'window_width',
        'window_center',
        'is_rgb',
        'group_id',
        'image_position_patient',
        'image_orientation_patient',
        'pixel_spacing',
        'direction'
    ]

    # print('rows:', rows)
    # idx = 0
    # type_series = rows[0][-1]  # flag is_rgb for first instance
    # for i in range(1, len(rows)):
    #     if rows[i][-1] != type_series:  # is not same color channel
    #         idx = i
    #         break

    if rows:
        # return [dict(zip(keys, row)) for row in rows]
        result = []
        for row in rows:
            d = dict(zip(keys, row))
            # Deserialize JSON fields (changed from ast.literal_eval to json.loads)
            for field in ('image_position_patient', 'image_orientation_patient', 'pixel_spacing', 'direction'):
                if d[field] is not None and isinstance(d[field], str):
                    try:
                        import json
                        d[field] = json.loads(d[field])  # JSON string to list
                    except (json.JSONDecodeError, ValueError):
                        # Fallback to ast.literal_eval for backward compatibility
                        try:
                            d[field] = ast.literal_eval(d[field])
                        except:
                            d[field] = None
            result.append(d)
        return result
    return


def update_series_thumbnail_path(series_pk: int, thumbnail_path: str) -> bool:
    conn = get_connection_database()
    cur = conn.cursor()

    cur.execute("""
        UPDATE series
        SET thumbnail_path = ?
        WHERE series_pk = ?
    """, (thumbnail_path, series_pk))
    conn.commit()
    return cur.rowcount > 0


def get_series_thumbnail_path(series_pk: int):
    conn = get_connection_database()
    cur = conn.cursor()

    cur.execute("""
        SELECT thumbnail_path
        FROM series
        WHERE series_pk = ?
    """, (series_pk,))
    row = cur.fetchone()
    return row[0] if row else None


def get_count_instances_in_study(study_uid: str) -> int:
    conn = get_connection_database()
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
    conn.close()
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

    conn = get_connection_database()
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
      col = CASE WHEN (col IS NULL OR col='' OR col='N/A') THEN ? ELSE col END   -- برای رشته‌ها
      col = CASE WHEN (col IS NULL) THEN ? ELSE col END                         -- برای عددی/غیررشته‌ای
    """
    sets = []
    params = []
    for col, val in fields.items():
        if val is None:
            # اگر مقدار جدید نداریم، از آپدیت آن ستون صرف‌نظر کن
            continue
        if _is_textlike(val):
            sets.append(f"{col} = CASE WHEN {col} IS NULL OR {col}='' OR {col}='N/A' THEN ? ELSE {col} END")
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
    conn = get_connection_database()
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
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute(f"UPDATE studies SET {set_sql} WHERE study_pk = ?", (*params, study_pk))
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
    conn = get_connection_database()
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
    conn = get_connection_database()
    cur = conn.cursor()
    cur.execute(f"UPDATE instances SET {set_sql} WHERE instance_pk = ?", (*params, instance_pk))
    conn.commit()
    return cur.rowcount


# =============================
# AI Chat passthroughs
# =============================
from . import database as _db_ai


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

    conn = get_connection_database()
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
    conn = get_connection_database()
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
    conn = get_connection_database()
    cur = conn.cursor()
    # در بعضی DBها series_number ممکن است TEXT باشد؛ برای اطمینان cast می‌کنیم
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
# Visit Status Management
# ============================================================================

def ensure_visit_status_column():
    """
    اطمینان از وجود ستون visit_status در جدول studies.
    اگر وجود نداشته باشد، اضافه می‌شود.
    """
    conn = get_connection_database()
    cur = conn.cursor()
    try:
        # Check if column exists
        cur.execute("PRAGMA table_info(studies)")
        columns = [info[1] for info in cur.fetchall()]
        
        if 'visit_status' not in columns:
            cur.execute("ALTER TABLE studies ADD COLUMN visit_status TEXT DEFAULT NULL")
            conn.commit()
            print("✅ [DB] Added visit_status column to studies table")
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
    
    conn = get_connection_database()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT visit_status FROM studies WHERE study_uid = ?",
            (study_uid,)
        )
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        # Column might not exist yet
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
    
    conn = get_connection_database()
    cur = conn.cursor()
    try:
        # Ensure column exists
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
        conn = get_connection_database()
        cur = conn.cursor()
        
        # First get the study_pk using study_uid
        cur.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (study_uid,))
        study_row = cur.fetchone()
        
        if not study_row:
            return []
            
        study_pk = study_row[0]
        
        # Then get all series for this study_fk
        cur.execute("SELECT * FROM series WHERE study_fk = ? ORDER BY series_number", (study_pk,))
        rows = cur.fetchall()
        
        # Convert rows to dictionaries
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