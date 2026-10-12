"""Bounded worker-only Home compatibility reads using existing socket endpoints."""


class CompatibilityReadError(ValueError):
    """Safe diagnostic category; never retain server payloads or identifiers."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def patient_metadata(request, pid):
    """Reuse only the existing Mongo compatibility contract, with exact filters."""
    from .socket_client import _PL_FALLBACK_MODES
    for _, flags, _ in _PL_FALLBACK_MODES:
        try:
            return request('GetPatientList', {'patient_id': pid, 'limit': 1, 'offset': 0, **flags})
        except CompatibilityReadError as error:
            if error.reason != 'mongo_sortarray':
                raise
    raise CompatibilityReadError('mongo_sortarray')


def read_rows(request, watched, *, stopped=lambda: False, failed=lambda endpoint, error: None, inventory_only=False):
    states = []
    grouped = {}
    for uid, pid in watched.items():
        if isinstance(uid, str) and isinstance(pid, str) and uid and pid:
            grouped.setdefault(pid, set()).add(uid)
    for pid, uids in grouped.items():
        if stopped():
            break
        try:
            data = request('GetPatientStatus', {'patient_id': pid})
        except (OSError, ValueError, TypeError) as error:
            if isinstance(error, CompatibilityReadError) and error.reason == 'authorization':
                raise
            failed('GetPatientStatus', error)
            continue
        if data.get('patient_id') != pid:
            continue
        studies = data.get('studies')
        if not isinstance(studies, list) or len(studies) > 1000:
            continue
        try:
            metadata = {} if inventory_only else patient_metadata(request, pid)
        except (OSError, ValueError, TypeError) as error:
            if isinstance(error, CompatibilityReadError) and error.reason == 'authorization':
                raise
            failed('GetPatientList', error)
            metadata = {}
        patients = metadata.get('patients', [])
        patient = patients[0] if isinstance(patients, list) and len(patients) == 1 and isinstance(patients[0], dict) and patients[0].get('patient_id') == pid else {}
        for row in studies:
            if not isinstance(row, dict):
                continue
            uid = row.get('study_uid')
            if uid not in uids:
                continue
            exact = patient.get('latest_study_uid') == uid
            state = dict(study_uid=uid, patient_id=pid, report_status=row.get('report_status'),
                         audio_count=row.get('voice_count', 0), assignment={}, assignment_known=False)
            latest = data.get('latest_study')
            if isinstance(latest, dict) and isinstance(latest.get('study_uid'), str):
                state['latest_study_uid'] = latest['study_uid']
            # Legacy radiologist metadata identifies a report participant, not
            # proof of an active internal assignment. Keep the existing Assign
            # state unless this exact study supplies the assignment contract.
            if isinstance(row.get('assignment'), dict):
                state.update(assignment=row['assignment'], assignment_known=True)
            author = row.get('reporting_physician')
            if author is None and exact:
                author = patient.get('reporting_physician')
            if isinstance(author, str):
                state['reporting_physician'] = author[:240]
            states.append(state)
    return states


def local_source():
    """Resolve the active source on a worker; no profile file reads on Qt."""
    from PacsClient.utils.server_profiles import server_profiles_enabled, get_active_profile
    from .socket_config import get_socket_server_settings
    if server_profiles_enabled():
        profile = get_active_profile()
        if not profile or not profile.host:
            return None
        return profile.host, profile.socket_port, profile.display_name
    config = get_socket_server_settings()
    if not config.get('host'):
        return None
    return config['host'], int(config['port']), 'Configured PACS'


class ReceptionOverlay:
    """Worker-owned reception authority, scoped to a verified current study."""
    def __init__(self, fetch, author, status, latest, *, resolve=None, is_actor=None, assignment=None):
        self.fetch, self.author, self.status, self.latest = fetch, author, status, latest
        self.resolve, self.is_actor = resolve, is_actor
        self.assignment = assignment

    def __call__(self, states):
        from .workflow_realtime import prepare_display
        seen = {}
        for state in states:
            # A missing/failed optional read is unknown, never an empty update.
            state['_report_status_known'] = False
            state['_reporting_physician_known'] = False
            pid, uid = state['patient_id'], state['study_uid']
            if pid not in seen:
                try:
                    inventory = ({'patient_id':pid, 'latest_study':{'study_uid':state['latest_study_uid']}}
                        if 'latest_study_uid' in state else self.latest(pid))
                    seen[pid] = (self.fetch(pid), inventory)
                except Exception:
                    seen[pid] = ({}, {})
            payload, inventory = seen[pid]
            if not isinstance(payload, dict) or not isinstance(inventory, dict):
                continue
            if str(payload.get('patient_id') or pid) != pid or inventory.get('patient_id') != pid:
                continue
            explicit = payload.get('study_uid') or payload.get('study_instance_uid')
            latest_uid = (inventory.get('latest_study') or {}).get('study_uid')
            if (explicit and str(explicit) != uid) or (not explicit and latest_uid != uid):
                continue
            if self.assignment:
                try:
                    assigned = self.assignment(pid)
                    if isinstance(assigned, dict) and assigned.get('ok') is True and isinstance(assigned.get('assignment'), dict):
                        from .ino_assignment_refresh import parse_assignment
                        record = assigned['assignment']
                        if not record.get('study_uid') or record['study_uid'] == uid:
                            # The REST shape includes RIS reporters with no actual assigner.
                            state.update(assignment=record if parse_assignment(record)['assigned'] else {},
                                         assignment_known=True)
                except Exception:
                    pass
            author = self.author(payload)
            if self.is_actor and self.is_actor(author):
                author = self.resolve(author) if self.resolve else ""
            status = self.status(payload)
            if isinstance(author, str) and author:
                state['reporting_physician'] = author[:240]
                state['_reporting_physician_known'] = True
            if isinstance(status, str) and status:
                state['report_status'] = status[:80]
                state['_report_status_known'] = True
        return prepare_display(states)
