"""Bounded server-owned speech continuation after client Google recognition."""
import base64
import binascii
import threading
from uuid import UUID

from .echomind.hosting import RequestFailed
from .echomind.runtime import configuration, request_context, company_identity
from .echomind.core import echomind_http

MAX_AUDIO_BYTES = 8 * 1024 * 1024


class Speech:
    capabilities = {'protocol': 1, 'continuation': ['whisper', 'company_1', 'company_2'],
                    'max_audio_bytes': MAX_AUDIO_BYTES, 'formats': ['wav', 'm4a', 'mp3']}

    def __init__(self, directory):
        self.directory = directory
        self.slots = threading.BoundedSemaphore(2)

    def process(self, body):
        fields = {'protocol', 'request_id', 'feature', 'audio_base64', 'format', 'quality_mode'}
        try:
            if (not isinstance(body, dict) or set(body) != fields or type(body['protocol']) is not int or body['protocol'] != 1
                    or body['feature'] not in ('echomind', 'secretary', 'crm')
                    or body['format'] not in self.capabilities['formats']
                    or body['quality_mode'] not in ('clear', 'noisy')
                    or not isinstance(body['audio_base64'], str)
                    or len(body['audio_base64']) > (MAX_AUDIO_BYTES + 2) // 3 * 4):
                raise ValueError()
            UUID(body['request_id'])
            audio = base64.b64decode(body['audio_base64'], validate=True)
            if not 0 < len(audio) <= MAX_AUDIO_BYTES:
                raise ValueError()
        except (ValueError, TypeError, KeyError, binascii.Error, AttributeError):
            raise RequestFailed(422, 'Invalid speech request.') from None
        if not self.slots.acquire(blocking=False):
            raise RequestFailed(429, 'Speech service is busy.')
        try:
            try:
                with configuration(self.directory), request_context():
                    _center, key = company_identity()
            except Exception:
                raise RequestFailed(503, 'Speech credentials are unavailable.') from None
            if not key:
                raise RequestFailed(503, 'Speech credentials are unavailable.')
            attempts = []
            for provider in ('whisper', 'company_1', 'company_2'):
                try:
                    with configuration(self.directory), request_context():
                        result = self._attempt(provider, key, audio, body)
                except Exception:
                    result = None
                ok = bool(result and result.get('transcript'))
                attempts.append({'provider': provider, 'ok': ok})
                if ok:
                    return {**result, 'ok': True, 'route_used': provider, 'attempts': attempts}
            raise RequestFailed(503, 'Speech providers are unavailable.')
        finally:
            self.slots.release()

    @staticmethod
    def _attempt(provider, key, audio, body):
        filename = 'recording.' + body['format']
        mime = {'wav': 'audio/wav', 'm4a': 'audio/mp4', 'mp3': 'audio/mpeg'}[body['format']]
        headers = {'Authorization': 'Bearer ' + key}
        if provider == 'whisper':
            url = 'https://api.gapgpt.app/v1/audio/transcriptions'
            files = {'file': (filename, audio, mime)}
            data = {'model': 'gapgpt/whisper-1'}
        else:
            base = {'company_1': 'http://81.16.117.196:8082',
                    'company_2': 'http://80.210.31.214:8085'}[provider]
            url = base + '/generate_transcript'
            files = [('audio_files', (filename, audio, mime))]
            data = {'quality_mode': body['quality_mode']}
        response = echomind_http.post(url, headers=headers, files=files, data=data, timeout=45)
        try:
            response.raise_for_status()
            value = response.json()
            transcript = value.get('text') if provider == 'whisper' else value.get('transcript')
            if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 100000:
                return None
            return {'transcript': transcript.strip(), 'accepted': value.get('accepted') is not False}
        finally:
            response.close()
