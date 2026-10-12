"""Report Send preserves the existing Turbo study gate in the worker."""
import ast
from pathlib import Path
from types import SimpleNamespace

def test_send_worker_forwards_study_gate_and_template():
    tree=ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8'))
    work=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='work' and any(
        isinstance(c,ast.Call) and isinstance(c.func,ast.Attribute) and isinstance(c.func.value,ast.Name)
        and c.func.value.id=='remote_backend' and c.func.attr=='reporter'
        and c.args and isinstance(c.args[0],ast.Name) and c.args[0].id=='sent_text' for c in ast.walk(n)))
    profile={'regions':['brain'],'contrast':'none'}
    observed={}
    def gate(text):
        observed['gate_text']=text
        return profile
    def reporter(*args,**kwargs):
        observed.update(args=args,kwargs=kwargs)
        return {'content':'Synthetic result'}
    scope=dict(self=SimpleNamespace(_build_gate_profile=gate),remote_route=True,
        remote_backend=SimpleNamespace(reporter=reporter),sent_text='Synthetic brain dictation',
        modality='MRI',remote_template='Synthetic normal template',report_files=())
    exec(compile(ast.Module(body=[work],type_ignores=[]),'<report-worker>','exec'),scope)
    scope['work']()
    assert observed.get('gate_text')=='Synthetic brain dictation'
    assert observed['kwargs']['study_profile']==profile
    assert observed['args']==('Synthetic brain dictation','MRI','Synthetic normal template')
