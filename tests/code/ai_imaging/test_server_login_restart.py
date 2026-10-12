import pytest
from modules.ai_imaging.eagle_eye_remote.login_restart import LoginRestart

class Adapter:
    def __init__(self, owned=True, stopped=True):
        self.owned, self.stopped = owned, stopped
        self.calls=[]; self.generation=1
    def inspect(self):
        self.calls.append("inspect")
        return {"owned":self.owned,"running":True,"generation":self.generation}
    def stop(self): self.calls.append("stop")
    def wait_stopped(self, deadline):
        self.calls.append("wait_stopped")
        if not self.stopped: raise TimeoutError()
    def start(self): self.calls.append("start"); self.generation=2
    def wait_ready(self, deadline): self.calls.append("ready")


def test_successful_login_consumed_once_and_new_generation_required():
    a=Adapter(); c=LoginRestart(a)
    assert c.run("login-1")["generation"]==2
    with pytest.raises(RuntimeError): c.run("login-1")
    assert a.calls.count("stop")==a.calls.count("start")==1


def test_foreign_service_is_never_stopped():
    a=Adapter(owned=False)
    with pytest.raises(RuntimeError): LoginRestart(a).run("login-1")
    assert "stop" not in a.calls


def test_stop_timeout_never_starts_or_kills_and_no_retry():
    a=Adapter(stopped=False); c=LoginRestart(a)
    with pytest.raises(TimeoutError): c.run("login-1")
    with pytest.raises(RuntimeError): c.run("login-1")
    assert "start" not in a.calls and a.calls.count("stop")==1


def test_same_generation_is_not_recovered():
    a=Adapter(); a.start=lambda:a.calls.append("start")
    with pytest.raises(RuntimeError): LoginRestart(a).run("login-1")


def test_operator_rights_are_service_specific_and_never_configuration_write():
    from modules.ai_imaging.eagle_eye_remote.service_admin import LOGIN_OPERATOR_RIGHTS, validate_login_operator_sid
    assert LOGIN_OPERATOR_RIGHTS == 0x35
    assert LOGIN_OPERATOR_RIGHTS & (0x2 | 0x10000 | 0x40000 | 0x80000) == 0
    assert validate_login_operator_sid("S-1-5-21-1-2-3-1001")
    for sid in ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "invalid"):
        with pytest.raises(ValueError): validate_login_operator_sid(sid)


def test_worker_entry_is_once_even_on_failure(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import login_restart as module
    calls=[]
    monkeypatch.setenv("AIPACS_EAGLE_EYE_ROLE", "server")
    monkeypatch.setenv("AIPACS_EAGLE_EYE_SERVER_CONFIG", "synthetic")
    monkeypatch.setattr(module,"_ENTRY_CONSUMED",set())
    def refuse(path): calls.append(path); raise PermissionError()
    monkeypatch.setattr(module,"WindowsService",refuse)
    assert module.recover_after_login("once")["service_restarted"] is False
    assert module.recover_after_login("once")["service_restarted"] is False
    assert calls==["synthetic"]


def test_gui_hook_defers_native_window_until_success_and_consumes_operation():
    import ast
    from pathlib import Path
    tree=ast.parse(Path("PacsClient/app_handler.py").read_text(encoding="utf-8"))
    methods={n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    login=ast.unparse(methods["_server_login_ready"])
    recovered=ast.unparse(methods["_server_recovery_ready"])
    assert "_open_main_window" not in login
    assert "_server_recovery_consumed.add(operation)" in login
    assert "_server_recovery_operation.start" in login
    assert "valid_session" in recovered and "service_restarted" in recovered and "_open_main_window" in recovered


def test_windows_adapter_uses_fixed_service_only_and_minimum_rights(monkeypatch):
    import sys, types
    from modules.ai_imaging.eagle_eye_remote import login_restart as module
    from modules.ai_imaging.eagle_eye_remote import service_host, secretary_native_connector
    import aipacs_runtime
    calls=[]
    fake=types.SimpleNamespace(SC_MANAGER_CONNECT=1,SERVICE_QUERY_CONFIG=1,SERVICE_QUERY_STATUS=4,SERVICE_START=16,SERVICE_STOP=32,
        OpenSCManager=lambda *a:"manager",OpenService=lambda *a:calls.append(a) or "service",CloseServiceHandle=lambda h:None)
    monkeypatch.setitem(sys.modules,"win32service",fake)
    monkeypatch.setattr(service_host,"service_config",lambda p:{"service_managed":True})
    monkeypatch.setattr(secretary_native_connector,"read_source_target",lambda *a:{"runtime_executable":"synthetic-python"})
    monkeypatch.setattr(aipacs_runtime,"is_frozen",lambda:False)
    adapter=module.WindowsService("synthetic-config")
    adapter.close()
    assert calls==[("manager","AIPacsEagleEye",0x35)]


def test_failed_entry_does_not_replay_any_business_request(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import login_restart as module
    monkeypatch.setattr(module,"_ENTRY_CONSUMED",set())
    monkeypatch.setenv("AIPACS_EAGLE_EYE_ROLE","client")
    assert module.recover_after_login("foreign-role")=={"service_restarted":False,"error_code":"EAGLE_LOGIN_RECOVERY_FAILED"}


def _gui_recovery(monkeypatch):
    import ast, types
    from pathlib import Path
    from modules.ai_imaging.eagle_eye_remote import admin_auth
    tree=ast.parse(Path("PacsClient/app_handler.py").read_text(encoding="utf-8"))
    methods=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in {"_server_recovery_ready","_server_recovery_failed"}]
    namespace={};exec(compile(ast.Module(body=methods,type_ignores=[]),"synthetic_gui","exec"),namespace)
    calls=[]
    monkeypatch.setattr(admin_auth,"valid_session",lambda session:session=="current")
    monkeypatch.setattr(admin_auth,"invalidate_session",lambda session:calls.append(("invalidate",session)))
    view=types.SimpleNamespace(_server_session="current",_server_recovery_pending=("operation","current"),
        _set_loading_state=lambda value:calls.append(("loading",value)),_open_main_window=lambda:calls.append("home"),
        _show_error=lambda message:calls.append("error"),_server_login_context=types.SimpleNamespace(cancel=lambda:calls.append("cancel")))
    for name,func in namespace.items():
        if callable(func):setattr(view,name,types.MethodType(func,view))
    return view,calls


def test_gui_stale_and_duplicate_completions_never_open_home(monkeypatch):
    view,calls=_gui_recovery(monkeypatch)
    view._server_recovery_ready("stale",{"service_restarted":True})
    assert calls==[]
    view._server_recovery_ready("operation",{"service_restarted":True})
    view._server_recovery_ready("operation",{"service_restarted":True})
    assert calls.count("home")==1


def test_gui_failed_recovery_invalidates_only_matching_session(monkeypatch):
    view,calls=_gui_recovery(monkeypatch)
    view._server_recovery_failed("stale","")
    assert calls==[]
    view._server_recovery_ready("operation",{"service_restarted":False})
    assert ("invalidate","current") in calls and "home" not in calls
    assert view._server_session is None


def test_changed_session_completion_cannot_open_home(monkeypatch):
    view,calls=_gui_recovery(monkeypatch)
    view._server_session="new-context"
    view._server_recovery_ready("operation",{"service_restarted":True})
    assert calls==[]
