"""Server authentication never inherits the workstation offline bypass."""
import ast
from pathlib import Path
from types import SimpleNamespace


def method(name):
    tree = ast.parse(Path('PacsClient/app_handler.py').read_text(encoding='utf-8-sig'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'AppHandler')
    node = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = {'settings_role': lambda: 'server'}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<login-policy>', 'exec'), namespace)
    return namespace[name]


def test_server_offline_toggle_cannot_reach_main_window():
    errors = []
    fake = SimpleNamespace(_set_loading_state=lambda _: None,
        btn_local_login=SimpleNamespace(isChecked=lambda: True),
        _show_error=errors.append)
    method('_complete_login')(fake, 'synthetic', 'synthetic')
    assert errors and 'offline' in errors[0].lower()


def test_server_main_window_requires_server_session_even_with_pacs_token():
    errors = []
    fake = SimpleNamespace(auth_token='synthetic-pacs-token',
        btn_local_login=SimpleNamespace(isChecked=lambda: True),
        _show_error=errors.append, _server_session=None)
    method('_open_main_window')(fake)
    assert errors and 'authentication' in errors[0].lower()


def test_server_demo_and_remembered_credentials_are_disabled():
    assert method('_authenticate_user')(SimpleNamespace(), '', '') is False
    assert method('_load_saved_credentials')(SimpleNamespace()) is None
    assert method('_save_credentials')(SimpleNamespace(), 'synthetic', 'synthetic') is None


def test_current_upstream_console_completion_publishes_only_memory_context(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import user_session, admin_auth
    monkeypatch.setattr(user_session,'identity',lambda:((1,user_session._epoch),None))
    monkeypatch.setattr(admin_auth,'valid_session',lambda value:True)
    context=user_session.ConsoleLoginContext()
    operation=context.begin('synthetic-user','synthetic-password')
    opened=[]
    fake=SimpleNamespace(_server_login_context=context,_set_loading_state=lambda value:None,
        line_edit_password=SimpleNamespace(clear=lambda:None),_open_main_window=lambda:opened.append(True),
        _server_login_failed=lambda value:(_ for _ in ()).throw(AssertionError('Unexpected failure')))
    ready=method('_server_login_ready')
    ready.__globals__['QApplication']=SimpleNamespace(instance=lambda:SimpleNamespace(setProperty=lambda *args:None))
    result={'session':'synthetic-console','user':{'auth_source':'pacs','provider':'pacs','subject':'synthetic-subject'}}
    try:
        ready(fake,operation,result)
        assert opened==[True] and fake.auth_token is None
        assert user_session._login_credentials[3:]==('pacs','synthetic-subject')
    finally:
        user_session.clear()


def test_stale_server_completion_does_not_clear_new_attempt(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import user_session, admin_auth
    monkeypatch.setattr(user_session,'identity',lambda:((1,user_session._epoch),None))
    context=user_session.ConsoleLoginContext()
    old=context.begin('synthetic-old','synthetic-password')
    fresh=context.begin('synthetic-fresh','synthetic-password')
    fake=SimpleNamespace(_server_login_context=context)
    try:
        method('_server_login_ready')(fake,old,{'session':'synthetic-old-console'})
        assert context.is_current(fresh)
    finally:
        context.cancel()


def test_busy_server_login_rejects_new_attempt_before_context_invalidation(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import admin_auth
    tree=ast.parse(Path('PacsClient/app_handler.py').read_text(encoding='utf-8-sig'))
    branch=next(node for node in ast.walk(tree) if isinstance(node,ast.If)
        and any(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                and call.func.attr=='begin' for call in ast.walk(node))
        and 'settings_role' in ast.unparse(node.test))
    # Execute the actual Server branch inside a function so its early return is valid.
    function=ast.FunctionDef(name='server_branch',args=ast.arguments(posonlyargs=[],
        args=[ast.arg(arg='self')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[branch],decorator_list=[])
    scope={'settings_role':lambda:'server'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'<busy-server>','exec'),scope)
    monkeypatch.setattr(admin_auth,'invalidate_session',lambda value:(_ for _ in ()).throw(AssertionError('Old callback/context must remain owned')))
    fake=SimpleNamespace(_server_auth_operation=SimpleNamespace(future=object()))
    assert scope['server_branch'](fake) is None
