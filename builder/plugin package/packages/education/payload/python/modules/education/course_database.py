"""Database operations for educational courses."""

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from PacsClient.utils.database import get_db_connection

RESOURCE_TYPES = {"Course", "Book", "Video"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm", ".m4v"}
BOOK_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw", ".txt", ".doc", ".docx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}
MEDIA_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".aac", ".m4a"}
PPT_EXTENSIONS = {".ppt", ".pptx"}


def _normalize_resource_type(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    if text == "book":
        return "Book"
    if text == "video":
        return "Video"
    return "Course"


def _safe_json_dumps(value) -> str:
    try:
        return json.dumps(value if value is not None else [], ensure_ascii=True)
    except Exception:
        return "[]"


def _safe_json_loads(value, default):
    try:
        return json.loads(value)
    except Exception:
        return default


def insert_course(name: str, description: str = "", author: str = "", 
                  outline: str = "", thumbnail_path: str = None,
                  tags: list = None, modality: str = "", body_regions: list = None,
                  level: str = "Intermediate", is_my_course: bool = True,
                  is_downloaded: bool = False, resource_type: str = "Course",
                  content_origin: str = "local", validation_status: str = "ok",
                  needs_attention: bool = False, import_source_path: str = "",
                  import_manifest_path: str = "") -> int:
    """
    Insert a new course into the database.
    
    Args:
        name: Course name
        description: Course description
        author: Author name
        outline: Course outline/template
        thumbnail_path: Path to thumbnail image
        tags: List of tags
        modality: CT/MRI/US/XRay, etc.
        body_regions: List of body regions
        level: Basic/Intermediate/Advanced
        is_my_course: If True, course is in "My Courses"
        is_downloaded: If True, course is downloaded
        
    Returns:
        course_pk: Primary key of inserted course
    """
    tags_json = _safe_json_dumps(tags or [])
    regions_json = _safe_json_dumps(body_regions or [])
    normalized_type = _normalize_resource_type(resource_type)
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO courses (course_name, course_description, author_name,
                               outline, thumbnail_path, tags, modality, body_regions,
                               level, is_my_course, is_downloaded, resource_type,
                               content_origin, validation_status, needs_attention,
                               import_source_path, import_manifest_path, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (name, description, author, outline, thumbnail_path,
              tags_json, modality, regions_json, level,
              1 if is_my_course else 0, 1 if is_downloaded else 0, normalized_type,
              content_origin or "local", validation_status or "ok",
              1 if needs_attention else 0, import_source_path or "",
              import_manifest_path or ""))
        new_pk = cur.lastrowid
        # The pool rolls back uncommitted writes on return (see
        # database/_pool.py::_return_to_pool). Without this explicit commit,
        # the INSERT vanishes the moment this `with` block exits.
        conn.commit()
        return new_pk


def update_course(course_pk: int, name: str = None, description: str = None, 
                  author: str = None, outline: str = None, thumbnail_path: str = None,
                  tags: List[str] = None, modality: str = None,
                  body_regions: List[str] = None, level: str = None,
                  resource_type: str = None, content_origin: str = None,
                  validation_status: str = None, needs_attention: bool = None,
                  import_source_path: str = None, import_manifest_path: str = None,
                  is_my_course: bool = None, is_downloaded: bool = None):
    """Update an existing course."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Build dynamic update query based on provided fields
        updates = []
        params = []
        
        if name is not None:
            updates.append("course_name = ?")
            params.append(name)
        if description is not None:
            updates.append("course_description = ?")
            params.append(description)
        if author is not None:
            updates.append("author_name = ?")
            params.append(author)
        if outline is not None:
            updates.append("outline = ?")
            params.append(outline)
        if thumbnail_path is not None:
            updates.append("thumbnail_path = ?")
            params.append(thumbnail_path)
        if tags is not None:
            updates.append("tags = ?")
            params.append(_safe_json_dumps(tags))
        if modality is not None:
            updates.append("modality = ?")
            params.append(modality)
        if body_regions is not None:
            updates.append("body_regions = ?")
            params.append(_safe_json_dumps(body_regions))
        if level is not None:
            updates.append("level = ?")
            params.append(level)
        if resource_type is not None:
            updates.append("resource_type = ?")
            params.append(_normalize_resource_type(resource_type))
        if content_origin is not None:
            updates.append("content_origin = ?")
            params.append(content_origin)
        if validation_status is not None:
            updates.append("validation_status = ?")
            params.append(validation_status)
        if needs_attention is not None:
            updates.append("needs_attention = ?")
            params.append(1 if needs_attention else 0)
        if import_source_path is not None:
            updates.append("import_source_path = ?")
            params.append(import_source_path)
        if import_manifest_path is not None:
            updates.append("import_manifest_path = ?")
            params.append(import_manifest_path)
        if is_my_course is not None:
            updates.append("is_my_course = ?")
            params.append(1 if is_my_course else 0)
        if is_downloaded is not None:
            updates.append("is_downloaded = ?")
            params.append(1 if is_downloaded else 0)
        
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(course_pk)
            query = f"UPDATE courses SET {', '.join(updates)} WHERE course_pk = ?"
            cur.execute(query, params)
            conn.commit()  # pool rolls back uncommitted writes


def delete_course(course_pk: int):
    """Delete a course and all associated slides (cascade)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM courses WHERE course_pk = ?", (course_pk,))
        conn.commit()  # pool rolls back uncommitted writes


def get_all_courses() -> List[Dict[str, Any]]:
    """Retrieve all courses ordered by update time."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM courses ORDER BY updated_at DESC")
        courses = [dict(row) for row in cur.fetchall()]
        
        # Parse JSON fields
        for course in courses:
            course['tags'] = _safe_json_loads(course.get('tags', '[]'), [])
            course['body_regions'] = _safe_json_loads(course.get('body_regions', '[]'), [])
            course['resource_type'] = _normalize_resource_type(course.get('resource_type'))
            course['content_origin'] = str(course.get('content_origin') or "local")
            course['validation_status'] = str(course.get('validation_status') or "ok")
            course['needs_attention'] = bool(course.get('needs_attention', 0))
        
        return courses


def search_and_filter_courses(query: str = "", modality: List[str] = None,
                              body_regions: List[str] = None, level: str = None,
                              tags: List[str] = None, is_my_course: bool = None,
                              resource_types: List[str] = None) -> List[Dict[str, Any]]:
    """
    Search and filter courses.
    
    Args:
        query: Search string (matches title, description, author, tags)
        modality: List of modalities to filter
        body_regions: List of body regions to filter
        level: Difficulty level to filter
        tags: List of tags to filter
        is_my_course: Filter by my courses (True/False/None for all)
        
    Returns:
        List of matching courses
    """
    courses = get_all_courses()
    
    # Apply filters
    filtered = []
    for course in courses:
        # My courses filter
        if is_my_course is not None and course.get('is_my_course') != is_my_course:
            continue

        if resource_types:
            normalized_allowed = {_normalize_resource_type(value) for value in resource_types}
            if _normalize_resource_type(course.get('resource_type')) not in normalized_allowed:
                continue
            
        # Query filter (case-insensitive search)
        if query:
            query_lower = query.lower()
            search_text = (
                f"{course.get('course_name', '')} "
                f"{course.get('course_description', '')} "
                f"{course.get('author_name', '')} "
                f"{course.get('resource_type', '')} "
                f"{course.get('content_origin', '')}"
            ).lower()
            course_tags = ' '.join(course.get('tags', [])).lower()
            
            if query_lower not in search_text and query_lower not in course_tags:
                continue
        
        # Modality filter
        if modality:
            if course.get('modality') not in modality:
                continue
        
        # Body regions filter
        if body_regions:
            course_regions = course.get('body_regions', [])
            if not any(region in course_regions for region in body_regions):
                continue
        
        # Level filter
        if level and course.get('level') != level:
            continue
        
        # Tags filter
        if tags:
            course_tags = course.get('tags', [])
            if not any(tag in course_tags for tag in tags):
                continue
        
        filtered.append(course)
    
    return filtered


def get_course_by_pk(course_pk: int) -> Optional[Dict[str, Any]]:
    """Retrieve a single course by primary key."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM courses WHERE course_pk = ?", (course_pk,))
        row = cur.fetchone()
        return dict(row) if row else None


def insert_slide(course_fk: int, slide_order: int, title: str = "", 
                 notes: str = "") -> int:
    """
    Insert a new slide into a course.
    
    Args:
        course_fk: Foreign key to course
        slide_order: Position in sequence (1, 2, 3...)
        title: Slide title
        notes: Speaker notes
        
    Returns:
        slide_pk: Primary key of inserted slide
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO slides (course_fk, slide_order, slide_title, slide_notes)
            VALUES (?, ?, ?, ?)
        """, (course_fk, slide_order, title, notes))
        new_pk = cur.lastrowid
        conn.commit()  # pool rolls back uncommitted writes
        return new_pk


def update_slide(slide_pk: int, slide_order: int = None, title: str = None,
                 notes: str = None):
    """Update an existing slide."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        updates = []
        params = []

        if slide_order is not None:
            updates.append("slide_order = ?")
            params.append(slide_order)
        if title is not None:
            updates.append("slide_title = ?")
            params.append(title)
        if notes is not None:
            updates.append("slide_notes = ?")
            params.append(notes)

        if updates:
            params.append(slide_pk)
            query = f"UPDATE slides SET {', '.join(updates)} WHERE slide_pk = ?"
            cur.execute(query, params)
            conn.commit()  # pool rolls back uncommitted writes


def delete_slide(slide_pk: int):
    """Delete a slide and all associated content (cascade)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM slides WHERE slide_pk = ?", (slide_pk,))
        conn.commit()  # pool rolls back uncommitted writes


def get_slides_for_course(course_pk: int) -> List[Dict[str, Any]]:
    """Retrieve all slides for a course, ordered by slide_order."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM slides 
            WHERE course_fk = ? 
            ORDER BY slide_order ASC
        """, (course_pk,))
        return [dict(row) for row in cur.fetchall()]


def get_slide_by_pk(slide_pk: int) -> Optional[Dict[str, Any]]:
    """Retrieve a single slide by primary key."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM slides WHERE slide_pk = ?", (slide_pk,))
        row = cur.fetchone()
        return dict(row) if row else None


def insert_slide_content(slide_fk: int, content_type: str, content_order: int,
                         content_data: Dict[str, Any], layout_position: Dict[str, Any] = None) -> int:
    """
    Insert content into a slide.
    
    Args:
        slide_fk: Foreign key to slide
        content_type: 'text', 'image', 'video', 'dicom_study', 'dicom_series'
        content_order: Position within slide
        content_data: Dictionary with type-specific data
        layout_position: Dictionary with position/size info
        
    Returns:
        content_pk: Primary key of inserted content
    """
    with get_db_connection() as conn:
        cur = conn.cursor()

        content_data_json = json.dumps(content_data)
        layout_json = json.dumps(layout_position) if layout_position else None

        cur.execute("""
            INSERT INTO slide_content (slide_fk, content_type, content_order,
                                      content_data, layout_position)
            VALUES (?, ?, ?, ?, ?)
        """, (slide_fk, content_type, content_order, content_data_json, layout_json))
        new_pk = cur.lastrowid
        conn.commit()  # pool rolls back uncommitted writes
        return new_pk


def update_slide_content(content_pk: int, content_type: str = None,
                        content_order: int = None, content_data: Dict[str, Any] = None,
                        layout_position: Dict[str, Any] = None):
    """Update existing slide content."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        updates = []
        params = []

        if content_type is not None:
            updates.append("content_type = ?")
            params.append(content_type)
        if content_order is not None:
            updates.append("content_order = ?")
            params.append(content_order)
        if content_data is not None:
            updates.append("content_data = ?")
            params.append(json.dumps(content_data))
        if layout_position is not None:
            updates.append("layout_position = ?")
            params.append(json.dumps(layout_position))

        if updates:
            params.append(content_pk)
            query = f"UPDATE slide_content SET {', '.join(updates)} WHERE content_pk = ?"
            cur.execute(query, params)
            conn.commit()  # pool rolls back uncommitted writes


def delete_slide_content(content_pk: int):
    """Delete slide content."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM slide_content WHERE content_pk = ?", (content_pk,))
        conn.commit()  # pool rolls back uncommitted writes


def get_content_for_slide(slide_pk: int) -> List[Dict[str, Any]]:
    """Retrieve all content for a slide, ordered by content_order."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM slide_content 
            WHERE slide_fk = ? 
            ORDER BY content_order ASC
        """, (slide_pk,))
        
        results = []
        for row in cur.fetchall():
            item = dict(row)
            # Parse JSON fields
            if item.get('content_data'):
                try:
                    item['content_data'] = json.loads(item['content_data'])
                except Exception:
                    item['content_data'] = {}
            if item.get('layout_position'):
                try:
                    item['layout_position'] = json.loads(item['layout_position'])
                except Exception:
                    item['layout_position'] = {}
            results.append(item)
        
        return results


def get_course_with_slides(course_pk: int) -> Optional[Dict[str, Any]]:
    """
    Retrieve a complete course with all slides and their content.
    
    Returns:
        Dictionary with course info, slides list, and each slide's content
    """
    course = get_course_by_pk(course_pk)
    if not course:
        return None
    
    slides = get_slides_for_course(course_pk)
    
    # Get content for each slide
    for slide in slides:
        slide['content'] = get_content_for_slide(slide['slide_pk'])
    
    course['slides'] = slides
    return course


def reorder_slides(course_pk: int, slide_pks_in_order: List[int]):
    """
    Reorder slides in a course.
    
    Args:
        course_pk: Course primary key
        slide_pks_in_order: List of slide_pk values in desired order
    """
    with get_db_connection() as conn:
        cur = conn.cursor()

        for order, slide_pk in enumerate(slide_pks_in_order, start=1):
            cur.execute("""
                UPDATE slides
                SET slide_order = ?
                WHERE slide_pk = ? AND course_fk = ?
            """, (order, slide_pk, course_pk))
        conn.commit()  # pool rolls back uncommitted writes


def save_course_asset(file_path: str, course_pk: int) -> str:
    """
    Copy an asset file to the education assets folder.
    
    Args:
        file_path: Source file path
        course_pk: Course primary key
        
    Returns:
        Destination path of copied file
    """
    from PacsClient.utils.config import EDUCATION_STORAGE_PATH
    
    course_folder = EDUCATION_STORAGE_PATH / f"course_{course_pk}" / "assets"
    course_folder.mkdir(parents=True, exist_ok=True)
    
    source = Path(file_path)
    dest_path = course_folder / source.name
    
    # Handle duplicate filenames
    counter = 1
    while dest_path.exists():
        dest_path = course_folder / f"{source.stem}_{counter}{source.suffix}"
        counter += 1
    
    shutil.copy2(file_path, dest_path)
    return str(dest_path)


def save_course_asset_tree(folder_path: str, course_pk: int, dest_name: str = None) -> str:
    """
    Copy a folder tree into the education assets directory for a course.

    Args:
        folder_path: Source directory
        course_pk: Course primary key
        dest_name: Optional destination folder name

    Returns:
        Destination folder path as string
    """
    from PacsClient.utils.config import EDUCATION_STORAGE_PATH

    source = Path(folder_path)
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Asset folder not found: {folder_path}")

    course_folder = EDUCATION_STORAGE_PATH / f"course_{course_pk}" / "assets"
    course_folder.mkdir(parents=True, exist_ok=True)

    base_name = dest_name or source.name
    dest_path = course_folder / base_name
    counter = 1
    while dest_path.exists():
        dest_path = course_folder / f"{base_name}_{counter}"
        counter += 1

    shutil.copytree(source, dest_path, dirs_exist_ok=True)
    return str(dest_path)


def _ensure_course_storage(course_pk: int) -> Path:
    from PacsClient.utils.config import EDUCATION_STORAGE_PATH
    course_root = EDUCATION_STORAGE_PATH / f"course_{course_pk}"
    course_root.mkdir(parents=True, exist_ok=True)
    return course_root


def _normalize_slide_item(item: Dict[str, Any], warnings: List[str], index: int) -> Dict[str, Any]:
    if not isinstance(item, dict):
        warnings.append(f"Slide item #{index}: invalid structure. Replaced with placeholder.")
        return {
            "content_type": "text",
            "content_data": {"text": "need to be imported", "name": "need to be corrected"},
            "content_order": index,
        }

    content_type = str(item.get("content_type") or "").strip().lower()
    content_data = item.get("content_data") if isinstance(item.get("content_data"), dict) else {}
    content_order = int(item.get("content_order") or index)

    if not content_type:
        warnings.append(f"Slide item #{index}: missing content_type (set to text).")
        content_type = "text"
        content_data.setdefault("text", "need to be imported")

    if not content_data:
        warnings.append(f"Slide item #{index}: missing content_data.")
        content_data = {"text": "need to be imported"}

    if not content_data.get("name"):
        content_data["name"] = "need to be corrected"

    return {
        "content_type": content_type,
        "content_data": content_data,
        "content_order": content_order,
    }


def _normalize_slide(slide: Dict[str, Any], warnings: List[str], index: int) -> Dict[str, Any]:
    if not isinstance(slide, dict):
        warnings.append(f"Slide #{index}: invalid format (placeholder inserted).")
        return {
            "slide_order": index,
            "slide_title": "need to be corrected",
            "slide_notes": "need to be imported",
            "content": [_normalize_slide_item({}, warnings, 1)],
        }

    slide_title = str(slide.get("slide_title") or "").strip() or "need to be corrected"
    if slide_title == "need to be corrected":
        warnings.append(f"Slide #{index}: missing slide_title.")

    slide_notes = str(slide.get("slide_notes") or "").strip()
    if not slide_notes:
        slide_notes = "need to be imported"
        warnings.append(f"Slide #{index}: missing slide_notes.")

    content = slide.get("content")
    if not isinstance(content, list) or not content:
        warnings.append(f"Slide #{index}: empty content list. Placeholder item added.")
        content = [_normalize_slide_item({}, warnings, 1)]
    else:
        content = [_normalize_slide_item(item, warnings, i + 1) for i, item in enumerate(content)]

    return {
        "slide_order": int(slide.get("slide_order") or index),
        "slide_title": slide_title,
        "slide_notes": slide_notes,
        "content": content,
    }


def _normalize_import_payload(payload: Dict[str, Any], source_path: Path) -> Dict[str, Any]:
    warnings: List[str] = []
    if not isinstance(payload, dict):
        payload = {}
        warnings.append("Invalid JSON root. Created placeholder course.")

    raw_name = str(payload.get("course_name") or "").strip()
    course_name = raw_name or f"Imported Resource - {source_path.stem}"
    if not raw_name:
        warnings.append("Missing course_name.")

    description = str(payload.get("course_description") or "").strip() or "need to be imported"
    if description == "need to be imported":
        warnings.append("Missing course_description.")

    author = str(payload.get("author_name") or "").strip() or "need to be corrected"
    if author == "need to be corrected":
        warnings.append("Missing author_name.")

    resource_type = _normalize_resource_type(payload.get("resource_type"))
    modality = str(payload.get("modality") or "").strip()
    level = str(payload.get("level") or "Intermediate").strip() or "Intermediate"
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    body_regions = payload.get("body_regions") if isinstance(payload.get("body_regions"), list) else []

    raw_slides = payload.get("slides")
    if not isinstance(raw_slides, list) or not raw_slides:
        warnings.append("No slides found in imported payload. Placeholder slide created.")
        slides = [_normalize_slide({}, warnings, 1)]
    else:
        slides = [_normalize_slide(slide, warnings, i + 1) for i, slide in enumerate(raw_slides)]

    return {
        "course_name": course_name,
        "course_description": description,
        "author_name": author,
        "resource_type": resource_type,
        "modality": modality,
        "level": level,
        "tags": tags,
        "body_regions": body_regions,
        "slides": slides,
        "warnings": warnings,
    }


def _infer_resource_type_from_file(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "Video"
    if suffix in BOOK_EXTENSIONS:
        return "Book"
    return "Course"


def _build_single_resource_payload(file_path: Path, resource_type: str) -> Dict[str, Any]:
    normalized = _normalize_resource_type(resource_type)
    name = file_path.stem.replace("_", " ").strip() or "Imported Resource"
    item_type = "pdf"
    if normalized == "Video":
        item_type = "video"
    elif file_path.suffix.lower() in IMAGE_EXTENSIONS:
        item_type = "image"
    elif file_path.suffix.lower() in MEDIA_AUDIO_EXTENSIONS:
        item_type = "audio"
    elif file_path.suffix.lower() in BOOK_EXTENSIONS:
        item_type = "pdf"

    return {
        "course_name": name,
        "course_description": "Imported resource",
        "author_name": "Imported",
        "resource_type": normalized,
        "modality": "",
        "level": "Intermediate",
        "tags": ["Imported"],
        "body_regions": [],
        "slides": [
            {
                "slide_order": 1,
                "slide_title": name,
                "slide_notes": "Imported as single resource item",
                "content": [
                    {
                        "content_type": item_type,
                        "content_order": 1,
                        "content_data": {
                            "name": name,
                            "description": "Imported item",
                        },
                    }
                ],
            }
        ],
        "warnings": [],
    }


def import_resource_to_my_courses(file_path: str, desired_resource_type: str = None) -> Dict[str, Any]:
    """
    Import a course/book/video into My Courses with structure normalization.

    Supported input:
    - JSON with course/slides/content structure
    - Media/document files (book/video/image/audio/pdf) as one-item imported resource
    """
    source = Path(file_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Import file not found: {file_path}")

    warnings: List[str] = []

    if source.suffix.lower() == ".json":
        with open(source, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        normalized = _normalize_import_payload(payload, source)
    else:
        resource_type = _normalize_resource_type(desired_resource_type or _infer_resource_type_from_file(source))
        normalized = _build_single_resource_payload(source, resource_type)

    warnings.extend(normalized.get("warnings") or [])
    needs_attention = len(warnings) > 0

    course_pk = insert_course(
        name=normalized["course_name"],
        description=normalized["course_description"],
        author=normalized["author_name"],
        tags=normalized["tags"],
        modality=normalized.get("modality", ""),
        body_regions=normalized.get("body_regions", []),
        level=normalized.get("level", "Intermediate"),
        is_my_course=True,
        is_downloaded=False,
        resource_type=normalized.get("resource_type", "Course"),
        content_origin="imported",
        validation_status="needs_correction" if needs_attention else "ok",
        needs_attention=needs_attention,
        import_source_path=str(source),
        import_manifest_path="",
    )

    course_root = _ensure_course_storage(course_pk)
    manifest_path = course_root / "import_manifest.json"

    # Insert slides/items and copy local file references into course assets
    for slide in normalized["slides"]:
        slide_pk = insert_slide(
            course_fk=course_pk,
            slide_order=int(slide.get("slide_order") or 1),
            title=slide.get("slide_title") or "need to be corrected",
            notes=slide.get("slide_notes") or "need to be imported",
        )

        for idx, item in enumerate(slide.get("content") or [], start=1):
            content_data = dict(item.get("content_data") or {})

            path_value = content_data.get("path")
            if isinstance(path_value, str) and path_value.strip():
                candidate = Path(path_value)
                if not candidate.is_absolute():
                    candidate = (source.parent / candidate).resolve()
                if candidate.exists() and candidate.is_file():
                    content_data["path"] = save_course_asset(str(candidate), course_pk)
                else:
                    warnings.append(f"Missing item file: {path_value}")
                    content_data["path"] = "need to be imported"
                    if not content_data.get("description"):
                        content_data["description"] = "need to be corrected"
            elif source.suffix.lower() != ".json" and idx == 1:
                # Single media import path
                content_data["path"] = save_course_asset(str(source), course_pk)

            if not content_data.get("name"):
                content_data["name"] = "need to be corrected"

            insert_slide_content(
                slide_fk=slide_pk,
                content_type=str(item.get("content_type") or "text"),
                content_order=int(item.get("content_order") or idx),
                content_data=content_data,
            )

    # Store normalized manifest for future synchronization with server
    manifest_payload = {
        "schema": "education-import-v1",
        "source_file": str(source),
        "course_pk": course_pk,
        "resource_type": normalized.get("resource_type", "Course"),
        "warnings": warnings,
        "normalized_course": {
            "course_name": normalized["course_name"],
            "course_description": normalized["course_description"],
            "author_name": normalized["author_name"],
            "modality": normalized.get("modality", ""),
            "level": normalized.get("level", "Intermediate"),
            "tags": normalized.get("tags", []),
            "body_regions": normalized.get("body_regions", []),
            "slides": normalized["slides"],
        },
    }
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest_payload, fp, ensure_ascii=True, indent=2)

    update_course(
        course_pk=course_pk,
        validation_status="needs_correction" if warnings else "ok",
        needs_attention=bool(warnings),
        import_manifest_path=str(manifest_path),
    )

    return {
        "course_pk": course_pk,
        "course_name": normalized["course_name"],
        "warnings": warnings,
        "needs_attention": bool(warnings),
        "resource_type": normalized.get("resource_type", "Course"),
    }


def _contains_dicom_files(folder: Path) -> bool:
    try:
        for entry in folder.rglob("*.dcm"):
            if entry.is_file():
                return True
    except Exception:
        return False
    return False


def _sort_item_dirs(paths: List[Path]) -> List[Path]:
    def _key(path: Path):
        name = path.name
        digits = "".join(ch for ch in name if ch.isdigit())
        return (name.rstrip(digits).lower(), int(digits) if digits else 0, name.lower())

    return sorted(paths, key=_key)


def import_course_folder_to_my_courses(folder_path: str,
                                       course_name: str = None,
                                       author: str = "Imported",
                                       copy_assets: bool = True) -> Dict[str, Any]:
    """
    Import a course folder from external storage into My Courses.

    This importer expects a structure like:
    Course-XXXX/
        Item-XXXX/
            Dicom####/ (may contain .dcm files)
            *.IPcryp / *.IPdcom (encrypted placeholders)

    Each Item folder becomes a slide. DICOM folders become "dicom" items.
    Image and media files are added when possible (up to 5 items per slide).
    """
    source = Path(folder_path)
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Course folder not found: {folder_path}")

    warnings: List[str] = []
    course_title = course_name or source.name.replace("_", " ").strip()
    description = f"Imported from folder: {source}"

    course_pk = insert_course(
        name=course_title,
        description=description,
        author=author,
        tags=["Imported"],
        modality="",
        body_regions=[],
        level="Intermediate",
        is_my_course=True,
        is_downloaded=False,
        resource_type="Course",
        content_origin="imported",
        validation_status="ok",
        needs_attention=False,
        import_source_path=str(source),
        import_manifest_path="",
    )

    course_root = _ensure_course_storage(course_pk)
    manifest_path = course_root / "import_manifest.json"

    item_dirs = [entry for entry in source.iterdir() if entry.is_dir()]
    item_dirs = _sort_item_dirs(item_dirs)

    if not item_dirs:
        warnings.append("No item folders found. Created placeholder slide.")
        slide_pk = insert_slide(course_fk=course_pk, slide_order=1,
                                title="need to be corrected",
                                notes="need to be imported")
        insert_slide_content(
            slide_fk=slide_pk,
            content_type="text",
            content_order=1,
            content_data={"name": "need to be corrected", "text": "need to be imported"},
        )
    else:
        for slide_index, item_dir in enumerate(item_dirs, start=1):
            slide_title = item_dir.name
            slide_notes = f"Imported from {item_dir.name}"
            slide_pk = insert_slide(
                course_fk=course_pk,
                slide_order=slide_index,
                title=slide_title,
                notes=slide_notes,
            )

            content_order = 1
            content_limit = 5

            dicom_dirs = [
                entry for entry in item_dir.iterdir()
                if entry.is_dir() and _contains_dicom_files(entry)
            ]
            dicom_dirs = sorted(dicom_dirs, key=lambda p: p.name.lower())

            for dicom_dir in dicom_dirs:
                if content_order > content_limit:
                    warnings.append(
                        f"{item_dir.name}: more than {content_limit} items found; extra items skipped."
                    )
                    break
                try:
                    path_value = str(dicom_dir)
                    if copy_assets:
                        path_value = save_course_asset_tree(str(dicom_dir), course_pk)
                    insert_slide_content(
                        slide_fk=slide_pk,
                        content_type="dicom",
                        content_order=content_order,
                        content_data={
                            "name": dicom_dir.name,
                            "path": path_value,
                            "description": "DICOM image set",
                        },
                    )
                    content_order += 1
                except Exception as exc:
                    warnings.append(f"{item_dir.name}: failed to import DICOM folder {dicom_dir}: {exc}")

            if content_order <= content_limit:
                image_files = [
                    entry for entry in item_dir.rglob("*")
                    if entry.is_file()
                    and entry.suffix.lower() in IMAGE_EXTENSIONS
                    and "cachefile" not in {p.lower() for p in entry.parts}
                ]
                for image_file in sorted(image_files, key=lambda p: p.name.lower()):
                    if content_order > content_limit:
                        warnings.append(
                            f"{item_dir.name}: more than {content_limit} items found; extra images skipped."
                        )
                        break
                    try:
                        stored_path = save_course_asset(str(image_file), course_pk)
                        insert_slide_content(
                            slide_fk=slide_pk,
                            content_type="image",
                            content_order=content_order,
                            content_data={
                                "name": image_file.stem,
                                "path": stored_path,
                                "description": "Imported image",
                            },
                        )
                        content_order += 1
                    except Exception as exc:
                        warnings.append(f"{item_dir.name}: failed to import image {image_file}: {exc}")

            if content_order <= content_limit:
                other_files = [
                    entry for entry in item_dir.rglob("*")
                    if entry.is_file() and entry.suffix.lower() in (BOOK_EXTENSIONS | VIDEO_EXTENSIONS | MEDIA_AUDIO_EXTENSIONS | PPT_EXTENSIONS)
                ]
                for other_file in sorted(other_files, key=lambda p: p.name.lower()):
                    if other_file.suffix.lower() in PPT_EXTENSIONS:
                        warnings.append(
                            f"{item_dir.name}: PowerPoint detected ({other_file.name}); convert to PDF before import."
                        )
                        continue
                    if content_order > content_limit:
                        warnings.append(
                            f"{item_dir.name}: more than {content_limit} items found; extra files skipped."
                        )
                        break

                    try:
                        stored_path = save_course_asset(str(other_file), course_pk)
                        if other_file.suffix.lower() in VIDEO_EXTENSIONS:
                            content_type = "video"
                        elif other_file.suffix.lower() in MEDIA_AUDIO_EXTENSIONS:
                            content_type = "audio"
                        else:
                            content_type = "pdf"

                        insert_slide_content(
                            slide_fk=slide_pk,
                            content_type=content_type,
                            content_order=content_order,
                            content_data={
                                "name": other_file.stem,
                                "path": stored_path,
                                "description": "Imported file",
                            },
                        )
                        content_order += 1
                    except Exception as exc:
                        warnings.append(f"{item_dir.name}: failed to import file {other_file}: {exc}")

            encrypted_files = [
                entry for entry in item_dir.iterdir()
                if entry.is_file() and entry.suffix.lower() in {".ipcryp", ".ipdcom"}
            ]
            if encrypted_files and content_order <= content_limit:
                insert_slide_content(
                    slide_fk=slide_pk,
                    content_type="text",
                    content_order=content_order,
                    content_data={
                        "name": "Encrypted content",
                        "text": "Encrypted item(s) detected (.IPcryp/.IPdcom). Manual review needed.",
                    },
                )
                content_order += 1
            if encrypted_files:
                warnings.append(
                    f"{item_dir.name}: encrypted items detected ({len(encrypted_files)} files)."
                )

            if content_order == 1:
                warnings.append(f"{item_dir.name}: no importable content found.")
                insert_slide_content(
                    slide_fk=slide_pk,
                    content_type="text",
                    content_order=1,
                    content_data={"name": "need to be corrected", "text": "need to be imported"},
                )

    manifest_payload = {
        "schema": "education-folder-import-v1",
        "source_folder": str(source),
        "course_pk": course_pk,
        "warnings": warnings,
    }
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest_payload, fp, ensure_ascii=True, indent=2)

    update_course(
        course_pk=course_pk,
        validation_status="needs_correction" if warnings else "ok",
        needs_attention=bool(warnings),
        import_manifest_path=str(manifest_path),
    )

    return {
        "course_pk": course_pk,
        "course_name": course_title,
        "warnings": warnings,
        "needs_attention": bool(warnings),
        "resource_type": "Course",
    }
