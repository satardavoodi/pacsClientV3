"""Physician-led text course authoring; synthetic data and isolated database."""
import threading
import time

import pytest

from tests.code.education.test_course_importer import temp_env
from modules.education import course_database as db
from tests.code.education.test_authoring_flow import builder


@pytest.fixture
def service(temp_env):
    from modules.education.course_authoring import CourseAuthoringService
    instance = CourseAuthoringService()
    yield instance
    instance.close()


def ready(service, operation):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = service.status(operation['operation_id'])
        if result['state'] != 'pending':
            return result
        time.sleep(.01)
    pytest.fail('Authoring operation did not finish')


def draft(service):
    return service.prepare({'course_name':'Synthetic conference', 'author_name':'Instructor A',
        'modality':'MRI', 'body_regions':['MSK'], 'slides':[
            {'slide_title':'Question', 'text':'Synthetic question', 'slide_notes':'Speak for two minutes', 'duration_seconds':120},
            {'slide_title':'Answer', 'text':'Synthetic explanation', 'duration_seconds':780}]})


def test_create_save_readback_and_retry_do_not_duplicate(service):
    prepared = draft(service)
    saved = ready(service, service.save(prepared['draft_id'], 1))
    assert saved['state'] == 'succeeded'
    assert saved['slide_count'] == 2 and saved['duration_seconds'] == 900
    assert saved['content_verified'] is True
    retried = ready(service, service.save(prepared['draft_id'], 1))
    assert retried['course_pk'] == saved['course_pk']
    assert len(db.get_all_courses()) == 1
    actual = db.get_course_with_slides(saved['course_pk'])
    assert actual['author_name'] == 'Instructor A'
    assert actual['slides'][0]['content'][0]['content_data']['text'] == 'Synthetic question'


def test_spoken_correction_changes_same_course_and_only_selected_slide(service):
    prepared = draft(service)
    first = ready(service, service.save(prepared['draft_id'], 1))
    changed = service.update(prepared['draft_id'], 1,
        {'author_name':'Instructor B'}, [{'slide_order':1,'text':'Corrected synthetic question'}])
    assert changed['revision'] == 2
    second = ready(service, service.save(prepared['draft_id'], 2))
    assert second['course_pk'] == first['course_pk']
    actual = db.get_course_with_slides(first['course_pk'])
    assert actual['author_name'] == 'Instructor B'
    assert actual['slides'][1]['content'][0]['content_data']['text'] == 'Synthetic explanation'
    assert len(db.get_all_courses()) == 1


def test_append_and_stale_revision_rejection(service):
    prepared = draft(service)
    service.update(prepared['draft_id'], 1, {}, [{'slide_order':3,'slide_title':'References','text':'Synthetic source'}])
    with pytest.raises(ValueError, match='REVISION_CONFLICT'):
        service.update(prepared['draft_id'], 1, {'author_name':'Stale'}, [])
    assert len(service.get(prepared['draft_id'])['slides']) == 3


def test_manual_edit_conflict_preserves_human_work(service):
    prepared = draft(service)
    first = ready(service, service.save(prepared['draft_id'], 1))
    db.update_course(first['course_pk'], author='Human edit')
    service.update(prepared['draft_id'], 1, {'author_name':'Assistant edit'}, [])
    result = ready(service, service.save(prepared['draft_id'], 2))
    assert result['state'] == 'failed' and result['error_code'] == 'COURSE_CHANGED'
    assert db.get_course_by_pk(first['course_pk'])['author_name'] == 'Human edit'


def test_load_existing_course_preserves_media_and_unknown_metadata(service):
    pk = db.insert_course('Existing synthetic course', author='Teacher', outline='{"visibility":"Private","custom":"keep"}')
    slide = db.insert_slide(pk,1,'Media slide','Notes')
    media = db.insert_slide_content(slide,'image',1,{'name':'Synthetic unavailable image','path':'synthetic.png','custom':7})
    loaded = service.load(pk)
    assert ready(service, loaded)['state'] == 'succeeded'
    service.update(loaded['draft_id'],1,{'author_name':'New teacher'},[{'slide_order':1,'text':'Added teaching text'}])
    result = ready(service,service.save(loaded['draft_id'],2))
    assert result['state'] == 'succeeded'
    actual = db.get_course_with_slides(pk)
    assert actual['slides'][0]['content'][0]['content_pk'] == media
    assert actual['slides'][0]['content'][0]['content_data']['custom'] == 7
    assert '"custom": "keep"' in actual['outline']


def test_failed_insert_rolls_back_entire_course(service, monkeypatch):
    prepared = draft(service)
    monkeypatch.setattr(service,'_write_slide',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic failure')))
    result = ready(service,service.save(prepared['draft_id'],1))
    assert result['state'] == 'failed'
    assert db.get_all_courses() == []


def test_database_save_runs_on_worker(service, monkeypatch):
    prepared = draft(service)
    original = service._persist
    threads = []
    def checked(*args):
        threads.append(threading.get_ident())
        return original(*args)
    monkeypatch.setattr(service,'_persist',checked)
    assert ready(service,service.save(prepared['draft_id'],1))['state'] == 'succeeded'
    assert threads and threads[0] != threading.get_ident()


def test_missing_fields_are_draft_warnings_and_block_save(service):
    prepared = service.prepare({})
    assert set(prepared['missing_fields']) == {'course_name','author_name','slides'}
    with pytest.raises(ValueError,match='INCOMPLETE_DRAFT'):
        service.save(prepared['draft_id'],1)


def test_readonly_course_cannot_be_loaded_for_writing(service):
    pk = db.insert_course('Locked synthetic course',author='Teacher')
    from PacsClient.utils.database import get_db_connection
    with get_db_connection() as conn:
        conn.execute('UPDATE courses SET is_editable=0 WHERE course_pk=?',(pk,))
        conn.commit()
    result = ready(service,service.load(pk))
    assert result['state'] == 'failed' and result['error_code'] == 'COURSE_READ_ONLY'


def test_build_course_loads_prepared_snapshot_without_gui_database_reads(service, builder, monkeypatch):
    page, namespace = builder
    prepared = draft(service)
    result = ready(service,service.save(prepared['draft_id'],1))
    course = service.saved_course(prepared['draft_id'])
    def forbidden(*args):
        raise AssertionError('Command editor loading must not read the database on the GUI thread')
    for name in ('get_course_with_slides','get_slides_for_course','get_content_for_slide'):
        monkeypatch.setitem(namespace,name,forbidden)
    assert page.load_course_for_edit(result['course_pk'],prepared_course=course)
    assert page.author_input.text()=='Instructor A'
    assert page.slides_list.count()==2
    assert page.items_cache[0]['content_data']['text']=='Synthetic question'


def test_changed_saved_course_is_not_opened_from_stale_cache(service):
    prepared = draft(service)
    result = ready(service,service.save(prepared['draft_id'],1))
    db.update_course(result['course_pk'],author='New human edit')
    assert ready(service,service.check_saved(prepared['draft_id']))['error_code']=='COURSE_CHANGED'


def test_whitespace_identity_is_incomplete(service):
    prepared = service.prepare({'course_name':'  ','author_name':'  ','slides':[{'text':'Synthetic'}]})
    assert {'course_name','author_name'} <= set(prepared['missing_fields'])
    with pytest.raises(ValueError,match='INCOMPLETE_DRAFT'):
        service.save(prepared['draft_id'],1)


def test_failed_save_can_retry_without_duplicate(service, monkeypatch):
    prepared = draft(service)
    original = service._persist
    def fail(*args):
        raise RuntimeError('Synthetic transient failure')
    monkeypatch.setattr(service,'_persist',fail)
    failed = ready(service,service.save(prepared['draft_id'],1))
    assert failed['state']=='failed'
    monkeypatch.setattr(service,'_persist',original)
    saved = ready(service,service.save(prepared['draft_id'],1))
    assert saved['state']=='succeeded' and len(db.get_all_courses())==1
