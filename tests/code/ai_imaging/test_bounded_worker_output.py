"""Worker output must remain bounded and drained even after a log-write error."""
import io
import pytest


def test_verbose_worker_log_keeps_a_bounded_latest_window(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.worker_output import WorkerOutput
    stream=io.BytesIO(b'A'*8192+b'FINAL-SYNTHETIC-ERROR')
    output=WorkerOutput(tmp_path/'worker.log',max_bytes=1024)
    output.start(stream)
    output.finish()
    content=(tmp_path/'worker.log').read_bytes()
    assert 0<len(content)<=1024
    assert content.endswith(b'FINAL-SYNTHETIC-ERROR')
    assert stream.tell()==8213


def test_logging_failure_still_drains_the_worker_pipe(tmp_path,monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.worker_output import WorkerOutput
    output=WorkerOutput(tmp_path/'missing'/'worker.log',max_bytes=1024)
    stream=io.BytesIO(b'SYNTHETIC'*4096)
    output.start(stream)
    with pytest.raises(OSError,match='Worker output'):
        output.finish()
    assert stream.tell()==len(b'SYNTHETIC'*4096)


def test_real_owned_verbose_worker_completes_without_pipe_deadlock(tmp_path,monkeypatch):
    import json,subprocess,sys,threading
    from modules.ai_imaging.eagle_eye_remote import server
    popen=subprocess.Popen
    script="import sys,json;from pathlib import Path;sys.stdout.buffer.write(b'SYNTHETIC'*600000);sys.stdout.flush();Path(sys.argv[1]).write_text(json.dumps({'synthetic':True}))"
    monkeypatch.setattr(server.subprocess,'Popen',lambda command,**options:
        popen([sys.executable,'-c',script,str(tmp_path/'worker-result.json')],**options))
    assert server.run_worker(tmp_path,threading.Event())=={'synthetic':True}
    assert (tmp_path/'worker.log').stat().st_size<=1024*1024


def test_uncertain_process_cleanup_is_not_hidden_by_log_failure(tmp_path,monkeypatch):
    import json,threading
    from modules.ai_imaging.eagle_eye_remote import server,process_owner,worker_output
    from modules.ai_imaging.eagle_eye_remote.admission import CompletionUncertain
    class Owner:
        def assign(self,process):pass
        def close(self):raise OSError('Synthetic ownership uncertainty')
    class Process:
        stdout=io.BytesIO(b'')
        returncode=0
        def poll(self):return 0
        def wait(self,timeout):return 0
    monkeypatch.setattr(process_owner,'ProcessJob',Owner)
    monkeypatch.setattr(server.subprocess,'Popen',lambda *a,**kw:Process())
    def log_failure(self):raise OSError('Synthetic log failure')
    monkeypatch.setattr(worker_output.WorkerOutput,'finish',log_failure)
    (tmp_path/'worker-result.json').write_text(json.dumps({'synthetic':True}))
    with pytest.raises(CompletionUncertain):server.run_worker(tmp_path,threading.Event())
