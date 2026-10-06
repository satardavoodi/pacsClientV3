"""Bounded, authenticated text workflows on the Eagle Eye server listener."""
from pathlib import Path
import threading
import sqlite3
from uuid import uuid4

from pydantic import ValidationError

from . import service
from .runtime import configuration
from ..text_history import History, validate_context, request_id

MAX_REQUEST_BYTES = 2 * 1024 * 1024
WORKFLOWS = tuple(service.ProcessRequest.model_fields['workflow'].annotation.__args__)


class RequestFailed(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class EchoMind:
    def __init__(self, config, clients):
        directory = Path(config.get('config_dir', ''))
        if not directory.is_absolute() or not (directory / 'settings.json').is_file():
            raise ValueError('Configure the private EchoMind server settings directory.')
        self.directory = directory
        history_dir = config.get('history_dir')
        if history_dir is None:
            from aipacs_runtime import user_data_root
            history_dir = user_data_root() / 'echomind' / 'remote_history'
        self.history = History(history_dir)
        self.case_events = None
        self.verify_case = None
        count = config.get('max_requests', 4)
        per_client = config.get('max_requests_per_client', 1)
        if not isinstance(count, int) or not 1 <= count <= 8 or not isinstance(per_client, int) or not 1 <= per_client <= count:
            raise ValueError('Invalid EchoMind request limits.')
        self.slots = threading.BoundedSemaphore(count)
        self.clients = {owner: threading.BoundedSemaphore(per_client) for owner in clients}
        self.capabilities = {'protocol': 1, 'input_mode': 'text',
            'workflows': list(WORKFLOWS), 'server_owned_prompts': True,
            'features': ['turbo_correction', 'cited_web_search', 'private_request_history']}

    def process(self, owner, body):
        # Client tokens select access; callers cannot select keys, prompts or destinations.
        allowed = {'text', 'provider', 'workflow', 'response_format', 'modality',
                   'normal_template', 'correction_note', 'target_section',
                   'study_profile', 'turbo_correction', 'request_id', 'case_context'}
        if not isinstance(body, dict) or set(body) - allowed or body.get('provider', 'company') not in ('company', 'aipacs'):
            raise RequestFailed(422, 'Invalid EchoMind request fields.')
        try:
            rid = request_id(body.get('request_id', str(uuid4())))
            context = validate_context(body.get('case_context', {}))
            payload = {k: v for k, v in body.items() if k not in ('request_id', 'case_context')}
            request = service.ProcessRequest.model_validate(payload)
        except (ValidationError, ValueError):
            raise RequestFailed(422, 'Invalid EchoMind request fields.') from None
        if self.verify_case and context.get('study_uid'):
            try:
                self.verify_case(owner, context['study_uid'])
            except Exception:
                raise RequestFailed(403, 'EchoMind case access could not be verified.') from None
        client_slot = self.clients[owner]
        if not client_slot.acquire(blocking=False):
            raise RequestFailed(429, 'EchoMind is busy for this client. Try again later.')
        acquired = self.slots.acquire(blocking=False)
        try:
            if not acquired:
                raise RequestFailed(429, 'EchoMind server is busy. Try again later.')
            try:
                self.history.begin(rid, owner, context, payload)
            except sqlite3.IntegrityError:
                raise RequestFailed(409, 'This EchoMind request identifier already exists. No repeat was sent.') from None
            except (OSError, sqlite3.Error):
                raise RequestFailed(503, 'EchoMind private history is unavailable. No provider request was sent.') from None
            with configuration(self.directory):
                try:
                    result = dict(service.process(request), request_id=rid)
                except Exception:
                    self.history.finish(rid, owner, failed=True)
                    raise
            try:
                self.history.finish(rid, owner, result)
            except (OSError, sqlite3.Error):
                raise RequestFailed(503, 'EchoMind completed processing but could not save its response. Do not resubmit automatically.') from None
            if self.case_events is not None and context.get('study_uid'):
                self.case_events.publish(context['study_uid'], 'echomind')
            return result
        except RequestFailed:
            raise
        except service.WorkflowError:
            raise RequestFailed(422, 'EchoMind does not support this workflow or its fields.') from None
        except Exception:
            raise RequestFailed(502, 'EchoMind could not complete the provider request. Check server configuration.') from None
        finally:
            if acquired:
                self.slots.release()
            client_slot.release()
