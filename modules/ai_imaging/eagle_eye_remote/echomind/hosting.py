"""Bounded, authenticated text workflows on the Eagle Eye server listener."""
from pathlib import Path
import threading

from pydantic import ValidationError

from . import service
from .runtime import configuration

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
        count = config.get('max_requests', 4)
        per_client = config.get('max_requests_per_client', 1)
        if not isinstance(count, int) or not 1 <= count <= 8 or not isinstance(per_client, int) or not 1 <= per_client <= count:
            raise ValueError('Invalid EchoMind request limits.')
        self.slots = threading.BoundedSemaphore(count)
        self.clients = {owner: threading.BoundedSemaphore(per_client) for owner in clients}
        self.capabilities = {'protocol': 1, 'input_mode': 'text',
            'workflows': list(WORKFLOWS), 'server_owned_prompts': True,
            'features': ['turbo_correction', 'cited_web_search']}

    def process(self, owner, body):
        # Client tokens select access; callers cannot select keys, prompts or destinations.
        allowed = {'text', 'provider', 'workflow', 'response_format', 'modality',
                   'normal_template', 'correction_note', 'target_section',
                   'study_profile', 'turbo_correction'}
        if not isinstance(body, dict) or set(body) - allowed or body.get('provider', 'company') not in ('company', 'aipacs'):
            raise RequestFailed(422, 'Invalid EchoMind request fields.')
        try:
            request = service.ProcessRequest.model_validate(body)
        except (ValidationError, ValueError):
            raise RequestFailed(422, 'Invalid EchoMind request fields.') from None
        client_slot = self.clients[owner]
        if not client_slot.acquire(blocking=False):
            raise RequestFailed(429, 'EchoMind is busy for this client. Try again later.')
        acquired = self.slots.acquire(blocking=False)
        try:
            if not acquired:
                raise RequestFailed(429, 'EchoMind server is busy. Try again later.')
            with configuration(self.directory):
                return service.process(request)
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
