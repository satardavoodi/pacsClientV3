"""Database operations for educational courses."""

import sqlite3
import json
from typing import List, Dict, Optional, Any
from PacsClient.utils.database import get_db_connection


def insert_course(name: str, description: str = "", author: str = "", 
                  outline: str = "", thumbnail_path: str = None,
                  tags: list = None, modality: str = "", body_regions: list = None,
                  level: str = "Intermediate", is_my_course: bool = True,
                  is_downloaded: bool = False) -> int:
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
    tags_json = json.dumps(tags or [])
    regions_json = json.dumps(body_regions or [])
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO courses (course_name, course_description, author_name, 
                               outline, thumbnail_path, tags, modality, body_regions,
                               level, is_my_course, is_downloaded, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (name, description, author, outline, thumbnail_path,
              tags_json, modality, regions_json, level, 
              1 if is_my_course else 0, 1 if is_downloaded else 0))
        return cur.lastrowid


def update_course(course_pk: int, name: str = None, description: str = None, 
                  author: str = None, outline: str = None, thumbnail_path: str = None):
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
        
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(course_pk)
            query = f"UPDATE courses SET {', '.join(updates)} WHERE course_pk = ?"
            cur.execute(query, params)


def delete_course(course_pk: int):
    """Delete a course and all associated slides (cascade)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM courses WHERE course_pk = ?", (course_pk,))


def get_all_courses() -> List[Dict[str, Any]]:
    """Retrieve all courses ordered by update time."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM courses ORDER BY updated_at DESC")
        courses = [dict(row) for row in cur.fetchall()]
        
        # Parse JSON fields
        for course in courses:
            try:
                course['tags'] = json.loads(course.get('tags', '[]'))
                course['body_regions'] = json.loads(course.get('body_regions', '[]'))
            except:
                course['tags'] = []
                course['body_regions'] = []
        
        return courses


def search_and_filter_courses(query: str = "", modality: List[str] = None,
                              body_regions: List[str] = None, level: str = None,
                              tags: List[str] = None, is_my_course: bool = None) -> List[Dict[str, Any]]:
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
            
        # Query filter (case-insensitive search)
        if query:
            query_lower = query.lower()
            search_text = f"{course.get('course_name', '')} {course.get('course_description', '')} {course.get('author_name', '')}".lower()
            course_tags = ' '.join(course.get('tags', [])).lower()
            
            if query_lower not in search_text and query_lower not in course_tags:
                continue
        
        # Modality filter
        if modality and course.get('modality'):
            if course['modality'] not in modality:
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
        return cur.lastrowid


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


def delete_slide(slide_pk: int):
    """Delete a slide and all associated content (cascade)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM slides WHERE slide_pk = ?", (slide_pk,))


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
        return cur.lastrowid


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


def delete_slide_content(content_pk: int):
    """Delete slide content."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM slide_content WHERE content_pk = ?", (content_pk,))


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
                except:
                    pass
            if item.get('layout_position'):
                try:
                    item['layout_position'] = json.loads(item['layout_position'])
                except:
                    pass
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


def save_course_asset(file_path: str, course_pk: int) -> str:
    """
    Copy an asset file to the education assets folder.
    
    Args:
        file_path: Source file path
        course_pk: Course primary key
        
    Returns:
        Destination path of copied file
    """
    import shutil
    from pathlib import Path
    from PacsClient.utils.config import EDUCATION_ASSETS_PATH
    
    course_folder = EDUCATION_ASSETS_PATH / f"course_{course_pk}"
    course_folder.mkdir(exist_ok=True)
    
    source = Path(file_path)
    dest_path = course_folder / source.name
    
    # Handle duplicate filenames
    counter = 1
    while dest_path.exists():
        dest_path = course_folder / f"{source.stem}_{counter}{source.suffix}"
        counter += 1
    
    shutil.copy2(file_path, dest_path)
    return str(dest_path)
