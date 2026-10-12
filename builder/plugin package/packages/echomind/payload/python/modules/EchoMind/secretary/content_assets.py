"""Worker services for receiving server artifacts and attaching verified media."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .session_files import SessionFiles, worker_only


def receive_asset(session_id, value, *, files=None):
    worker_only()
    files = files or SessionFiles()
    folder = files.folder(session_id)
    name = value.get('name', '')
    if Path(name).name != name or Path(name).suffix.lower() not in ('.png', '.jpg', '.pdf'):
        raise ValueError('Invalid delivered asset')
    raw = base64.b64decode(value['data'], validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    if not 0 < len(raw) <= 8*1024*1024 or digest != value['sha256'] or len(raw) != value['bytes']:
        raise ValueError('Delivered asset checksum mismatch')
    # Recheck magic/decodability at the receiving boundary.
    if name.endswith('.pdf'):
        if not raw.startswith(b'%PDF-'):
            raise ValueError('Invalid PDF')
    else:
        from modules.ai_imaging.eagle_eye_remote.secretary.web_assets import image_type
        if image_type(raw) != Path(name).suffix:
            raise ValueError('Invalid image type')
    name = digest + Path(name).suffix.lower()
    existing = files.snapshot(session_id)
    if not any(s['sha256'] == digest for s in existing):
        if len(existing) >= 12 or sum(len(base64.b64decode(s['data'])) for s in existing) + len(raw) > 8*1024*1024:
            raise ValueError('Session file limits reached')
        temporary = folder / ('.'+uuid4().hex+'.partial')
        try:
            temporary.write_bytes(raw)
            temporary.replace(folder/name)
        finally:
            temporary.unlink(missing_ok=True)
    # Provenance is outside files/, so source snapshots remain supported.
    provenance = folder.parent / 'asset_receipts'
    provenance.mkdir(exist_ok=True)
    (provenance/(digest+'.json')).write_text(json.dumps({k:v for k,v in value.items() if k!='data'}), encoding='utf-8')
    return {'session_id':session_id,'name':name,'sha256':digest,'bytes':len(raw),
            'source_url':value.get('source_url'),'origin':value.get('origin'),'delivered':True}


def inspect_course(course_pk):
    worker_only()
    from PacsClient.utils.database import get_db_connection
    from modules.education.course_authoring import _snapshot, _digest
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        course = _snapshot(conn, course_pk)
    return {'course_pk':course_pk,'content_digest':_digest(course),
            'course_name':course['course_name'],'author_name':course.get('author_name',''),'slides':[
                {'slide_pk':s['slide_pk'],'slide_order':s['slide_order'],'slide_title':s['slide_title'],
                 'slide_notes':s.get('slide_notes',''),
                 'content':[{'content_pk':i['content_pk'],'content_type':i['content_type'],
                             'fields':{k:v for k,v in i['content_data'].items() if k in
                                       ('name','text','rich_text','layout','background','foreground')}} for i in s['content']]}
                for s in course['slides']]}


def attach_asset(session_id, request, *, files=None):
    worker_only()
    files = files or SessionFiles()
    sources = [s for s in files.snapshot(session_id) if s['sha256']==request.sha256]
    if len(sources)!=1:
        raise ValueError('Session asset missing or ambiguous')
    source = files.folder(session_id)/sources[0]['name']
    image = source.suffix.lower() in ('.png','.jpg','.jpeg')
    if request.purpose != 'pdf' and not image or request.purpose=='pdf' and source.suffix.lower()!='.pdf':
        raise ValueError('Asset type does not match the requested use')
    from PacsClient.utils.database import get_db_connection
    from modules.education.course_database import _require_editable, save_course_asset
    from modules.education.course_authoring import _snapshot, _digest
    # Asset copy remains on this worker; optimistic DB check is repeated afterward.
    with get_db_connection() as conn:
        conn.row_factory=sqlite3.Row
        before=_snapshot(conn,request.course_pk)
        if _digest(before)!=request.expected_digest:
            raise ValueError('Course changed; inspect again')
        _require_editable(conn,course_pk=request.course_pk)
    stored=save_course_asset(str(source), request.course_pk)
    with get_db_connection() as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        try:
            _require_editable(conn,course_pk=request.course_pk)
            if _digest(_snapshot(conn,request.course_pk))!=request.expected_digest:
                raise ValueError('Course changed; inspect again')
            if request.purpose=='course_cover':
                if request.slide_pk or request.content_pk:
                    raise ValueError('Course cover cannot target a slide')
                conn.execute('UPDATE courses SET thumbnail_path=? WHERE course_pk=?',(stored,request.course_pk))
            else:
                slide=next((s for s in before['slides'] if s['slide_pk']==request.slide_pk),None)
                if slide is None:
                    raise ValueError('Select an actual slide in this course')
                if request.purpose=='slide_thumbnail':
                    if request.content_pk:
                        raise ValueError('Slide thumbnail cannot target content')
                    conn.execute('UPDATE slides SET thumbnail_path=? WHERE slide_pk=?',(stored,request.slide_pk))
                else:
                    old=next((i for i in slide['content'] if i['content_pk']==request.content_pk),None)
                    if request.content_pk and old is None:
                        raise ValueError('Content does not belong to the selected slide')
                    if old and old['content_type'] not in ('text','multimedia','image','pdf'):
                        raise ValueError('Do not replace DICOM or unsupported content with media')
                    data=dict(old['content_data']) if old else {}
                    data.update(path=stored,name=request.name or data.get('name') or slide['slide_title'])
                    if request.purpose=='image':
                        data.update(media_type='image',layout=data.get('layout') or 'right')
                        kind='multimedia'
                    else:
                        # Explicit PDF content is full width in the existing renderer.
                        if old and old['content_type']!='pdf':
                            raise ValueError('Add PDF as a separate full-width resource')
                        kind='pdf'
                    if old:
                        conn.execute('UPDATE slide_content SET content_type=?,content_data=? WHERE content_pk=?',
                                     (kind,json.dumps(data),old['content_pk']))
                    else:
                        if len(slide['content'])>=5:
                            raise ValueError('Slide resource limit reached')
                        order=max((i['content_order'] for i in slide['content']),default=0)+1
                        conn.execute('INSERT INTO slide_content(slide_fk,content_type,content_order,content_data) VALUES(?,?,?,?)',
                                     (request.slide_pk,kind,order,json.dumps(data)))
            conn.execute('UPDATE courses SET updated_at=CURRENT_TIMESTAMP WHERE course_pk=?',(request.course_pk,))
            after=_snapshot(conn,request.course_pk)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {'course_pk':request.course_pk,'content_digest':_digest(after),'asset_sha256':request.sha256,
            'purpose':request.purpose,'content_verified':True,'render_review':'pending'}


def organize_course(request):
    """Explicit full ordering preserves every existing slide, resource and unknown field."""
    worker_only()
    from PacsClient.utils.database import get_db_connection
    from modules.education.course_database import _require_editable
    from modules.education.course_authoring import _snapshot, _digest
    with get_db_connection() as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        try:
            _require_editable(conn,course_pk=request.course_pk)
            before=_snapshot(conn,request.course_pk)
            if _digest(before)!=request.expected_digest:
                raise ValueError('Course changed; inspect again')
            existing={s['slide_pk']:s for s in before['slides']}
            supplied=[s.slide_pk for s in request.slides if s.slide_pk is not None]
            if len(supplied)!=len(set(supplied)) or set(supplied)!=set(existing):
                raise ValueError('Ordering must preserve every existing slide exactly once')
            # Temporary negative order avoids collisions with existing positions.
            for index,pk in enumerate(existing,1):
                conn.execute('UPDATE slides SET slide_order=? WHERE slide_pk=?',(-index,pk))
            for order,edit in enumerate(request.slides,1):
                if edit.slide_pk is None:
                    pk=conn.execute('INSERT INTO slides(course_fk,slide_order,slide_title,slide_notes) VALUES(?,?,?,?)',
                        (request.course_pk,order,edit.slide_title,edit.slide_notes or '')).lastrowid
                    content=[]
                else:
                    pk=edit.slide_pk;content=existing[pk]['content']
                    conn.execute('UPDATE slides SET slide_order=?,slide_title=? WHERE slide_pk=?',(order,edit.slide_title,pk))
                    if edit.slide_notes is not None:
                        conn.execute('UPDATE slides SET slide_notes=? WHERE slide_pk=?',(edit.slide_notes,pk))
                if any(v is not None for v in (edit.text,edit.layout,edit.rich_text,edit.background,edit.foreground)):
                    item=next((i for i in content if i['content_type'] in ('text','multimedia')),None)
                    if item is None and len(content)>=5:
                        raise ValueError('Slide resource limit reached')
                    data=dict(item['content_data']) if item else {}
                    if edit.text is not None:
                        data['text']=edit.text
                        data.pop('rich_text',None)
                    if edit.layout is not None:
                        data['layout']=edit.layout
                    if edit.rich_text is not None:
                        from modules.education.slide_content import safe_rich_text
                        data['rich_text']=safe_rich_text(edit.rich_text)
                    if edit.background is not None:
                        data['background']=edit.background
                    if edit.foreground is not None:
                        data['foreground']=edit.foreground
                    data['name']=edit.slide_title
                    if item:
                        conn.execute("UPDATE slide_content SET content_type='multimedia',content_data=? WHERE content_pk=?",(json.dumps(data),item['content_pk']))
                    else:
                        next_order=max((i['content_order'] for i in content),default=0)+1
                        conn.execute('INSERT INTO slide_content(slide_fk,content_type,content_order,content_data) VALUES(?,?,?,?)',(pk,'multimedia',next_order,json.dumps(data)))
            if request.author_name is not None:
                conn.execute('UPDATE courses SET author_name=? WHERE course_pk=?',(request.author_name,request.course_pk))
            if request.course_name is not None:
                conn.execute('UPDATE courses SET course_name=? WHERE course_pk=?',(request.course_name,request.course_pk))
            conn.execute('UPDATE courses SET updated_at=CURRENT_TIMESTAMP WHERE course_pk=?',(request.course_pk,))
            after=_snapshot(conn,request.course_pk)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {'course_pk':request.course_pk,'content_digest':_digest(after),'slide_count':len(after['slides']),
            'content_verified':True,'render_review':'pending'}
