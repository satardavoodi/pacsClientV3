"""Synthetic installed package identity and transactional activation boundaries."""
import json
from pathlib import Path
import pytest


def test_package_detects_stale_core_and_keeps_private_state_out(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.release_package import stamp, verify
    core=tmp_path/'core';core.mkdir();(core/'AIPacs.exe').write_bytes(b'new executable')
    (core/'worker.dll').write_bytes(b'worker')
    private=tmp_path/'private';private.mkdir();(private/'secret.json').write_text('not package content')
    identity=stamp(core, '3.7.1')
    assert verify(core)==identity
    assert 'private' not in json.dumps(identity)
    (core/'worker.dll').write_bytes(b'old worker')
    with pytest.raises(ValueError):verify(core)


def test_package_refuses_traversal(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.release_package import verify
    (tmp_path/'eagle-eye-release.json').write_text(json.dumps({'schema':1,'version':'3.7.1','files':{'../outside':'0'*64}}))
    with pytest.raises(ValueError):verify(tmp_path)


def test_transition_commits_only_after_health_and_rolls_back():
    from modules.ai_imaging.eagle_eye_remote.release_package import transition
    class Host:
        def __init__(self):self.events=[];self.selected='old'
        def quiesce(self):
            from contextlib import contextmanager
            @contextmanager
            def locked():
                self.events.append('lock')
                try:yield
                finally:self.events.append('unlock')
            return locked()
        def snapshot(self):return self.selected
        def verify(self, release):self.events.append('verify-'+release)
        def drain(self):self.events.append('drain')
        def stop(self):self.events.append('stop')
        def select_service(self, release):self.events.append('service-'+release)
        def start(self):self.events.append('start')
        def healthy(self, release):self.events.append('health-'+release);return release=='old'
        def publish(self, release):self.events.append('publish-'+release);self.selected=release
        def journal(self, state, **fields):self.events.append(state)
    h=Host()
    with pytest.raises(RuntimeError):transition(h,'new')
    assert h.selected=='old'
    assert 'publish-new' not in h.events
    assert 'service-old' in h.events
    assert h.events.index('drain')<h.events.index('stop')
    assert h.events[-1]=='unlock'


@pytest.mark.parametrize('qualified,release', [(False,'same'),(True,'old')])
def test_gui_rejects_stale_or_unqualified_server(qualified,release):
    from modules.ai_imaging.eagle_eye_remote.release_package import require_same_release
    with pytest.raises(ValueError):
        require_same_release({'qualified':True,'release_id':'same'}, {'qualified':qualified,'release_id':release})


def test_frozen_identity_reads_installed_package(tmp_path,monkeypatch):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye_remote.release_package import stamp,runtime_identity
    (tmp_path/'AIPacs.exe').write_bytes(b'fixed package')
    identity=stamp(tmp_path,'3.7.1')
    monkeypatch.setattr(aipacs_runtime,'is_frozen',lambda:True)
    monkeypatch.setattr(aipacs_runtime,'install_root',lambda:tmp_path)
    assert runtime_identity()['release_id']==identity['release_id']
    (tmp_path/'AIPacs.exe').write_bytes(b'old package')
    with pytest.raises(ValueError):runtime_identity()


@pytest.mark.parametrize('failure', ['none','drain','new-health','rollback-health','publish'])
def test_atomic_selection_and_failure_receipt(failure):
    from contextlib import contextmanager
    from modules.ai_imaging.eagle_eye_remote.release_package import transition
    class Host:
        def __init__(self):self.selected='old';self.service='old';self.records=[];self.locked=False;self.stops=0
        @contextmanager
        def quiesce(self):
            self.locked=True
            try:yield
            finally:self.locked=False
        def snapshot(self):return self.selected
        def verify(self,r):assert self.locked
        def drain(self):
            if failure=='drain':raise ValueError('Synthetic busy work')
        def journal(self,state,**fields):self.records.append(state)
        def stop(self):assert self.locked;self.stops+=1
        def start(self):assert self.locked
        def select_service(self,r):self.service=r
        def healthy(self,r):
            assert self.locked and self.service==r
            return failure not in ('new-health','rollback-health') if r=='new' else failure!='rollback-health'
        def publish(self,r):
            if r=='new' and failure=='publish':raise OSError('Synthetic pointer write failure')
            self.selected=r
    h=Host()
    if failure=='none':
        transition(h,'new');assert h.selected==h.service=='new';assert h.records[-1]=='committed'
    else:
        with pytest.raises((RuntimeError,ValueError)):transition(h,'new')
        assert h.selected=='old'
        if failure=='drain':assert h.stops==0 and not h.records
        else:assert h.records[-1]==('recovery_required' if failure=='rollback-health' else 'rolled_back')
    assert not h.locked
