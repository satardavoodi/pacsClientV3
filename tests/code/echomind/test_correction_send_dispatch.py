"""Correction Send must reach its worker after the Turbo UI was removed."""
import ast
from pathlib import Path
from types import SimpleNamespace
from modules.EchoMind import remote_backend

def test_correction_send_reaches_server_worker(monkeypatch):
    tree=ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8'))
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_send_report_correction')
    scope={'get_active_backend_display_name':lambda:'Eagle Eye Server',
        '_resolve_active_ai_identity':lambda:('server','Synthetic',None),
        '_ai_identity_ready':lambda *a:True}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<correction-send>','exec'),scope)
    sent=[]; bubbles=[]; workers=[]
    monkeypatch.setattr(remote_backend,'selected',lambda:True)
    monkeypatch.setattr(remote_backend,'correction',lambda report,note:sent.append((report,note)))
    def run(work,*callbacks,**options):
        workers.append(options)
        work()
    page=SimpleNamespace(composer=SimpleNamespace(get_selected_correction_report_text=lambda:'Synthetic original report',btn_send=object()),
        controller=SimpleNamespace(bubble=lambda *a:bubbles.append(a)),
        _resolve_corrected_msg_id=lambda report:None,_run_async=run)
    scope['_send_report_correction'](page,'Synthetic correction note')
    assert sent==[('Synthetic original report','Synthetic correction note')]
    assert len(workers)==1 and bubbles[0][0]=='You (Correction)'
