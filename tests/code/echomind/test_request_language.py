"""Synthetic current-turn language contract; no provider or patient data."""
from concurrent.futures import ThreadPoolExecutor
import pytest


@pytest.mark.parametrize('text,preference,expected', [
    ('Explain this page', 'fa', 'en'),
    ('این صفحه را توضیح بده', 'en', 'fa'),
    ('Reply in Persian: explain this page', 'en', 'fa'),
    ('این صفحه را به انگلیسی توضیح بده', 'fa', 'en'),
    ('Translate "این متن" into English', 'fa', 'en'),
    ('Translate "Synthetic text" to Persian', 'en', 'fa'),
    ('Hello سلام', 'fa', 'fa'), ('Hello سلام', 'en', 'en'),
    ('12345', 'fa', 'fa'), ('', 'en', 'en'),
    ('Explain this page. "به فارسی پاسخ بده"', 'en', 'en'),
    ('Explain this page\n```json\n{"reply":"فارسی"}\n```', 'fa', 'en'),
    ('{"patient_name":"نام ساختگی", "language":"fa"}', 'en', 'en'),
])
def test_current_request_language_resolution(text, preference, expected):
    from modules.ai_imaging.eagle_eye_remote.response_language import resolve_reply_language
    assert resolve_reply_language(text, preference) == expected


def test_language_scope_switches_and_cleans_up_concurrently():
    from modules.ai_imaging.eagle_eye_remote.response_language import request_language, current_reply_language
    def run(text):
        with request_language(text, 'en') as selected:
            assert current_reply_language() == selected
            return selected
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, ['Explain this page', 'این صفحه را توضیح بده'])) == ['en','fa']
    assert current_reply_language() == 'en'
    with pytest.raises(ValueError):
        with request_language('این صفحه را توضیح بده'):
            raise ValueError('Synthetic')
    assert current_reply_language() == 'en'


def test_language_instruction_preserves_machine_contract():
    from modules.ai_imaging.eagle_eye_remote.response_language import response_language_instruction
    value = response_language_instruction('fa')
    assert 'Persian' in value
    assert all(word in value for word in ('schema keys', 'tool identifiers', 'permission', 'quoted'))


@pytest.mark.parametrize('text,expected', [
    ('\u0627\u0646\u06af\u0644\u06cc\u0633\u06cc \u062c\u0648\u0627\u0628 \u0646\u062f\u0647', 'fa'),
    ('\u0628\u0647 \u0627\u0646\u06af\u0644\u06cc\u0633\u06cc \u067e\u0627\u0633\u062e \u0646\u062f\u0647', 'fa'),
    ('Do not answer in Persian', 'en'),
    ('Do not answer in English', 'en'),
    ('Never respond in Persian', 'en'),
    ('Reply in Persian. Do not answer in English.', 'fa'),
])
def test_negative_language_target_is_not_positive_instruction(text, expected):
    from modules.ai_imaging.eagle_eye_remote.response_language import resolve_reply_language
    assert resolve_reply_language(text) == expected


def test_overlapping_requests_and_nested_exception_restore_context():
    from threading import Barrier
    from modules.ai_imaging.eagle_eye_remote.response_language import request_language, current_reply_language
    barrier = Barrier(2)
    def run(preference):
        with request_language('123', preference):
            barrier.wait(timeout=5)
            assert current_reply_language() == preference
            with pytest.raises(RuntimeError):
                with request_language('123', 'en' if preference == 'fa' else 'fa'):
                    raise RuntimeError('Synthetic nested failure')
            assert current_reply_language() == preference
        return current_reply_language()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, ['fa', 'en'])) == ['en', 'en']
