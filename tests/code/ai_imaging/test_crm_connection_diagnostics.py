"""CRM connection diagnostics use fixed Mongo and do not replace settings state."""
import pytest
from modules.ai_imaging.eagle_eye_remote.crm import administration, diagnostics

def test_test_connection_uses_configured_private_directory(monkeypatch):
    monkeypatch.setattr(administration,'snapshot',lambda:{'editable':True,'config_dir':'synthetic-private'})
    seen=[]
    monkeypatch.setattr(diagnostics,'run',lambda path:seen.append(path) or {'diagnostic':True})
    assert administration.test_connection()=={'diagnostic':True}
    assert seen==['synthetic-private']

def test_worker_fixed_mongo_override(monkeypatch):
    monkeypatch.setenv('RECEPTION_MONGO_URI','mongodb://example.invalid:1/')
    diagnostics.configure_local_mongo()
    import os
    assert os.environ['RECEPTION_MONGO_URI']=='mongodb://127.0.0.1:27017/'

def test_folder_missing_and_readable_are_distinct(tmp_path):
    assert diagnostics.folder_status(tmp_path)=='OK'
    assert diagnostics.folder_status(tmp_path/'absent')=='MISSING_FOLDER'

def test_diagnostic_render_preserves_configuration_snapshot(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.crm_connections import CRMConnectionsWidget
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(CRMConnectionsWidget,'load',lambda self:None)
    widget=CRMConnectionsWidget();original={'editable':True,'revision':'synthetic','config_dir':'private'}
    widget.render(original)
    widget.render({'diagnostic':True,'api':{'status':'API_UNREACHABLE','port':8080},'mongo':{'status':'OK','port':27017},'folders':[]})
    assert widget.snapshot is original
    assert 'API_UNREACHABLE' in widget.status.text()
    widget.deleteLater();app.processEvents()

@pytest.mark.parametrize('status,body,expected',[(200,{'token':'synthetic'},'OK'),(200,{},'API_INVALID_RESPONSE'),(500,{'token':'synthetic'},'API_INVALID_RESPONSE'),(401,{},'AUTH_REJECTED')])
def test_api_requires_authenticated_success(status,body,expected):
    assert diagnostics.api_result(status,body)==expected

def test_subprocess_failure_has_fixed_sanitized_result(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: (_ for _ in ()).throw(subprocess.TimeoutExpired('synthetic',18)))
    value=diagnostics.run('synthetic-private')
    assert value=={'diagnostic':True,'api':{'status':'CHECK_UNAVAILABLE'},'mongo':{'status':'CHECK_UNAVAILABLE'},'folders':[]}

@pytest.mark.parametrize('frozen',[False,True])
def test_diagnostic_uses_existing_worker_dispatch(monkeypatch,frozen):
    import aipacs_runtime,subprocess,json,sys
    from types import SimpleNamespace
    monkeypatch.setattr(aipacs_runtime,'is_frozen',lambda:frozen)
    seen=[]
    def run(command,**kwargs):
        seen.append((command,kwargs))
        return SimpleNamespace(returncode=0,stdout=json.dumps({'diagnostic':True}))
    monkeypatch.setattr(subprocess,'run',run)
    assert diagnostics.run('C:/synthetic-private')=={'diagnostic':True}
    command,kwargs=seen[0]
    assert command==([sys.executable,'--eagle-eye-crm-worker','stdin'] if frozen else [sys.executable,'-m','modules.ai_imaging.eagle_eye_remote.crm.worker'])
    assert json.loads(kwargs['input'])=={'operation':'connection_diagnostic','config_dir':'C:/synthetic-private'}
    assert kwargs['timeout']==18

def test_worker_diagnostic_returns_before_host_start(monkeypatch,tmp_path):
    import io,json,sys
    from modules.ai_imaging.eagle_eye_remote.crm import worker
    seen=[]
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps({'operation':'connection_diagnostic','config_dir':str(tmp_path)})))
    monkeypatch.setattr(diagnostics,'check',lambda directory:seen.append(directory) or {'diagnostic':True})
    worker.main()
    assert seen==[tmp_path]
