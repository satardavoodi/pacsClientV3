"""Bounded text-course drafts and atomic worker persistence for shared commands.

No inference, GUI, clinical search, arbitrary filesystem paths or media import.
Existing media and unknown metadata survive text corrections.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import sqlite3
import threading
import uuid

from modules.ai_imaging.eagle_eye_remote.secretary.validation.course_authoring import (
    PrepareCourse, UpdateCourse,
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _snapshot(conn, pk):
    row = conn.execute('SELECT * FROM courses WHERE course_pk=?', (pk,)).fetchone()
    if row is None:
        raise ValueError('COURSE_NOT_FOUND')
    course = dict(row)
    course['slides'] = []
    for row in conn.execute('SELECT * FROM slides WHERE course_fk=? ORDER BY slide_order,slide_pk', (pk,)):
        slide = dict(row)
        slide['content'] = []
        for item in conn.execute('SELECT * FROM slide_content WHERE slide_fk=? ORDER BY content_order,content_pk', (slide['slide_pk'],)):
            item = dict(item)
            item['content_data'] = json.loads(item['content_data'])
            slide['content'].append(item)
        course['slides'].append(slide)
    return course


class CourseAuthoringService:
    MAX_DRAFTS = 32
    MAX_OPERATIONS = 128

    def __init__(self):
        self._lock = threading.RLock()
        self._drafts = {}
        self._operations = {}
        self._saves = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='education-authoring')

    def close(self):
        self._pool.shutdown(wait=True)

    def _bound(self, value):
        if len(json.dumps(value, ensure_ascii=True).encode()) > 100000:
            raise ValueError('COURSE_TOO_LARGE')

    def _require(self, handle):
        draft = self._drafts.get(handle)
        if draft is None:
            raise ValueError('DRAFT_NOT_FOUND')
        if draft.get('loading'):
            raise ValueError('DRAFT_LOADING')
        if draft.get('failed'):
            raise ValueError(draft['failed'])
        return draft

    def _summary(self, handle, draft):
        value = draft['value']
        missing = [key for key in ('course_name','author_name','slides') if not value.get(key) or (isinstance(value.get(key),str) and not value[key].strip())]
        return {'draft_id':handle, 'revision':draft['revision'], 'course_pk':draft.get('course_pk'),
                'course_name':value['course_name'], 'author_name':value['author_name'],
                'slide_count':len(value['slides']), 'missing_fields':missing,
                'duration_seconds':sum(s.get('duration_seconds',0) for s in value['slides']),
                'saved':draft.get('saved_revision') == draft['revision'],
                'review_status':'instructor_review_required'}

    def prepare(self, values):
        value = PrepareCourse.model_validate(values).model_dump()
        self._bound(value)
        with self._lock:
            if len(self._drafts) >= self.MAX_DRAFTS:
                raise ValueError('DRAFT_LIMIT')
            handle = uuid.uuid4().hex
            draft = {'value':value, 'revision':1, 'course_pk':None, 'base_digest':None}
            self._drafts[handle] = draft
            return self._summary(handle, draft)

    def get(self, handle):
        with self._lock:
            draft = self._require(handle)
            return dict(self._summary(handle,draft), **deepcopy(draft['value']))

    def update(self, handle, revision, fields, slides):
        request = UpdateCourse.model_validate({'draft_id':handle,'expected_revision':revision,'fields':fields,'slides':slides})
        with self._lock:
            draft = self._require(handle)
            if draft.get('saving'):
                raise ValueError('DRAFT_BUSY')
            if draft['revision'] != revision:
                raise ValueError('REVISION_CONFLICT')
            value = deepcopy(draft['value'])
            value.update(request.fields.model_dump(exclude_unset=True))
            touched = set()
            for patch in request.slides:
                index = patch.slide_order - 1
                if index in touched or index > len(value['slides']):
                    raise ValueError('INVALID_SLIDE_ORDER')
                touched.add(index)
                changes = patch.model_dump(exclude_unset=True, exclude={'slide_order'})
                if any(v is None for v in changes.values()):
                    raise ValueError('INVALID_SLIDE_VALUE')
                if index == len(value['slides']):
                    from modules.ai_imaging.eagle_eye_remote.secretary.validation.course_authoring import CourseSlide
                    value['slides'].append(CourseSlide.model_validate(changes).model_dump())
                else:
                    value['slides'][index].update(changes)
            self._bound(value)
            draft['value'] = value
            draft['revision'] += 1
            return self._summary(handle,draft)

    def _submit(self, fn, handle):
        if len(self._operations) >= self.MAX_OPERATIONS:
            completed = [key for key,value in self._operations.items() if value.done()]
            for key in completed[:32]:
                del self._operations[key]
            if len(self._operations) >= self.MAX_OPERATIONS:
                raise ValueError('AUTHORING_BUSY')
        operation = uuid.uuid4().hex
        self._operations[operation] = self._pool.submit(fn)
        return {'operation_id':operation,'draft_id':handle,'state':'pending'}

    def status(self, operation):
        with self._lock:
            task = self._operations.get(operation)
        if task is None:
            raise ValueError('OPERATION_NOT_FOUND')
        if not task.done():
            return {'operation_id':operation,'state':'pending'}
        return dict(task.result(), operation_id=operation)

    def load(self, pk):
        with self._lock:
            if len(self._drafts) >= self.MAX_DRAFTS:
                raise ValueError('DRAFT_LIMIT')
            handle = uuid.uuid4().hex
            self._drafts[handle] = {'loading':True}
            def work():
                try:
                    from PacsClient.utils.database import get_db_connection
                    with get_db_connection() as conn:
                        conn.row_factory = sqlite3.Row
                        course = _snapshot(conn,pk)
                    if not course.get('is_editable',1):
                        raise ValueError('COURSE_READ_ONLY')
                    value = {key:course.get(key,'') for key in ('course_name','author_name','course_description','modality','level')}
                    for key in ('tags','body_regions'):
                        value[key] = json.loads(course.get(key) or '[]')
                    outline = json.loads(course.get('outline') or '{}')
                    value['visibility'] = outline.get('visibility','Private') if isinstance(outline,dict) else 'Private'
                    value['slides'] = []
                    for slide in course['slides']:
                        item = next((i for i in slide['content'] if i['content_type']=='multimedia' or (i['content_type']=='text' and not i['content_data'].get('path'))),None)
                        data = item['content_data'] if item else {}
                        value['slides'].append({'slide_title':slide['slide_title'] or '', 'slide_notes':slide['slide_notes'] or '',
                            'text':data.get('text',''), 'duration_seconds':data.get('duration_seconds',0),
                            '_slide_pk':slide['slide_pk'], '_content_pk':item['content_pk'] if item else None})
                    self._bound(value)
                    with self._lock:
                        self._drafts[handle] = {'value':value, 'revision':1,'course_pk':pk,'base_digest':_digest(course),
                            'saved_revision':1, 'saved_course':course}
                        return dict(self._summary(handle,self._drafts[handle]),state='succeeded')
                except Exception as exc:
                    code = str(exc) if str(exc) in {'COURSE_READ_ONLY','COURSE_NOT_FOUND','COURSE_TOO_LARGE'} else 'COURSE_LOAD_FAILED'
                    with self._lock:
                        self._drafts[handle] = {'failed':code}
                    return {'state':'failed','error_code':code}
            return self._submit(work,handle)

    def save(self, handle, revision):
        with self._lock:
            draft = self._require(handle)
            if draft['revision'] != revision:
                raise ValueError('REVISION_CONFLICT')
            if self._summary(handle,draft)['missing_fields']:
                raise ValueError('INCOMPLETE_DRAFT')
            key = (handle,revision)
            if key in self._saves and self._saves[key]['operation_id'] in self._operations:
                previous = self._operations[self._saves[key]['operation_id']]
                if not previous.done() or previous.result().get('state') == 'succeeded':
                    return dict(self._saves[key])
            snapshot = deepcopy(draft)
            draft['saving'] = True
            def work():
                try:
                    result, course = self._persist(handle,revision,snapshot)
                    with self._lock:
                        draft.update(course_pk=result['course_pk'],base_digest=_digest(course),
                                     saved_revision=revision,saved_course=course)
                        for slide,stored in zip(draft['value']['slides'],course['slides']):
                            slide['_slide_pk'] = stored['slide_pk']
                            item = next((i for i in stored['content'] if i['content_type']=='multimedia' or (i['content_type']=='text' and not i['content_data'].get('path'))),None)
                            slide['_content_pk'] = item['content_pk'] if item else None
                    return dict(result,state='succeeded')
                except Exception as exc:
                    code = str(exc) if str(exc) in {'COURSE_CHANGED','COURSE_READ_ONLY','COURSE_NOT_FOUND'} else 'COURSE_SAVE_FAILED'
                    return {'state':'failed','error_code':code}
                finally:
                    with self._lock:
                        draft['saving'] = False
            try:
                operation = self._submit(work,handle)
            except Exception:
                draft['saving'] = False
                raise
            self._saves[key] = operation
            return dict(operation)

    def saved_course(self, handle):
        with self._lock:
            draft = self._require(handle)
            if draft.get('saving') or draft.get('saved_revision') != draft['revision']:
                raise ValueError('UNSAVED_DRAFT')
            return deepcopy(draft['saved_course'])

    def check_saved(self, handle):
        """Recheck database identity on a worker before opening cached GUI content."""
        with self._lock:
            course = self.saved_course(handle)
            expected = _digest(course)
            def work():
                try:
                    from PacsClient.utils.database import get_db_connection
                    with get_db_connection() as conn:
                        conn.row_factory = sqlite3.Row
                        current = _snapshot(conn,course['course_pk'])
                    if _digest(current) != expected:
                        return {'state':'failed','error_code':'COURSE_CHANGED'}
                    return {'state':'succeeded','draft_id':handle,'course_pk':course['course_pk'],'content_verified':True}
                except Exception:
                    return {'state':'failed','error_code':'COURSE_LOAD_FAILED'}
            return self._submit(work,handle)

    @staticmethod
    def _write_slide(conn, pk, order, slide):
        slide_pk = slide.get('_slide_pk')
        if slide_pk:
            conn.execute('UPDATE slides SET slide_title=?,slide_notes=? WHERE slide_pk=? AND course_fk=?',
                         (slide['slide_title'],slide['slide_notes'],slide_pk,pk))
        else:
            slide_pk = conn.execute('INSERT INTO slides(course_fk,slide_order,slide_title,slide_notes) VALUES(?,?,?,?)',
                                    (pk,order,slide['slide_title'],slide['slide_notes'])).lastrowid
        item_pk = slide.get('_content_pk')
        data = {}
        if item_pk:
            row = conn.execute("SELECT content_data FROM slide_content WHERE content_pk=? AND slide_fk=? AND content_type IN ('text','multimedia')",
                               (item_pk,slide_pk)).fetchone()
            if row is None:
                raise ValueError('COURSE_CHANGED')
            data = json.loads(row[0])
        if data.get('text') != slide['text']:
            data.pop('rich_text',None)
        data.update(name=slide['slide_title'],description='Teaching text',text=slide['text'],duration_seconds=slide['duration_seconds'])
        if item_pk:
            conn.execute('UPDATE slide_content SET content_data=? WHERE content_pk=?',(json.dumps(data),item_pk))
        elif slide['text'] or not slide.get('_slide_pk'):
            order = conn.execute('SELECT COALESCE(MAX(content_order),0)+1 FROM slide_content WHERE slide_fk=?',(slide_pk,)).fetchone()[0]
            conn.execute('INSERT INTO slide_content(slide_fk,content_type,content_order,content_data) VALUES(?,?,?,?)',
                         (slide_pk,'multimedia',order,json.dumps(dict(layout='right', **data))))

    def _persist(self, handle, revision, draft):
        from PacsClient.utils.database import get_db_connection
        value = draft['value']
        key = f'{handle}:{revision}'
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            try:
                conn.execute('CREATE TABLE IF NOT EXISTS education_command_receipts (request_key TEXT PRIMARY KEY, course_pk INTEGER NOT NULL, receipt TEXT NOT NULL)')
                old = conn.execute('SELECT receipt FROM education_command_receipts WHERE request_key=?',(key,)).fetchone()
                if old:
                    receipt = json.loads(old[0])
                    return receipt,_snapshot(conn,receipt['course_pk'])
                pk = draft.get('course_pk')
                outline = {}
                if pk:
                    current = _snapshot(conn,pk)
                    if not current.get('is_editable',1):
                        raise ValueError('COURSE_READ_ONLY')
                    if _digest(current) != draft['base_digest']:
                        raise ValueError('COURSE_CHANGED')
                    try:
                        outline = json.loads(current.get('outline') or '{}')
                    except (ValueError,TypeError):
                        outline = {'legacy_outline':current.get('outline')}
                    if not isinstance(outline,dict):
                        outline = {'legacy_outline':outline}
                outline['visibility'] = value['visibility']
                params = (value['course_name'],value['course_description'],value['author_name'],json.dumps(outline),
                          value['modality'],value['level'],json.dumps(value['tags']),json.dumps(value['body_regions']))
                if pk:
                    conn.execute('UPDATE courses SET course_name=?,course_description=?,author_name=?,outline=?,modality=?,level=?,tags=?,body_regions=?,updated_at=CURRENT_TIMESTAMP WHERE course_pk=?',params+(pk,))
                else:
                    pk = conn.execute('INSERT INTO courses(course_name,course_description,author_name,outline,modality,level,tags,body_regions,is_my_course,content_origin) VALUES(?,?,?,?,?,?,?,?,1,?)',params+('local',)).lastrowid
                for order,slide in enumerate(value['slides'],1):
                    self._write_slide(conn,pk,order,slide)
                course = _snapshot(conn,pk)
                assert course['author_name'] == value['author_name'] and len(course['slides']) == len(value['slides'])
                for wanted,actual in zip(value['slides'],course['slides']):
                    assert actual['slide_title'] == wanted['slide_title'] and actual['slide_notes'] == wanted['slide_notes']
                    if wanted['text']:
                        assert any(i['content_type'] in {'text','multimedia'} and i['content_data'].get('text')==wanted['text'] for i in actual['content'])
                receipt = {'draft_id':handle,'revision':revision,'course_pk':pk,'slide_count':len(course['slides']),
                           'duration_seconds':sum(s['duration_seconds'] for s in value['slides']),
                           'content_digest':_digest(course),'content_verified':True,'review_status':'instructor_review_required'}
                conn.execute('INSERT INTO education_command_receipts VALUES(?,?,?)',(key,pk,json.dumps(receipt)))
                conn.commit()
                return receipt,course
            except Exception:
                conn.rollback()
                raise
