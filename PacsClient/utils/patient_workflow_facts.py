"""Cached workflow observations; never infer remote absence from local files."""
import time

WORKFLOW_ROLE_OFFSET = 30
MAX_SNAPSHOT_AGE = 60.0


def voice_fact(snapshot, study_uid, patient_id, local_flags=None, *, now=None):
    local_present = (local_flags or {}).get('voice') is True
    fresh = (isinstance(snapshot, dict) and snapshot.get('study_uid') == study_uid
             and snapshot.get('patient_id') == patient_id
             and type(snapshot.get('audio_count')) is int
             and 0 <= snapshot['audio_count'] <= 100000
             and type(snapshot.get('observed_at')) in (int, float)
             and 0 <= (time.monotonic() if now is None else now) - snapshot['observed_at'] <= MAX_SNAPSHOT_AGE)
    count = snapshot['audio_count'] if fresh else None
    presence = 'present' if local_present or (count is not None and count > 0) else (
        'absent' if count == 0 else 'unknown')
    return {'voice_presence':presence, 'server_audio_count':count,
            'voice_evidence':'server_snapshot_and_local_cache' if fresh else 'local_cache_only',
            'voice_author_known':False}
