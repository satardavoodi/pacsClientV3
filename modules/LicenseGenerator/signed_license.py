"""Bounded signed entitlement and renewal-request codecs; verification only."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PRODUCTS = ('client', 'eagle-eye-server')
MAX_CODE = 32768
TOKEN_FIELDS = {'version', 'key_id', 'license_id', 'revision', 'hardware_id',
                'product', 'issued_at', 'expires_at', 'added_days', 'request_id',
                'previous_digest'}
REQUEST_FIELDS = {'version', 'request_id', 'hardware_id', 'product', 'created_at',
                  'previous_license', 'previous_hardware_id'}


class LicenseError(ValueError):
    """Safe public licensing error; never include raw codes or identifiers."""


def utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise LicenseError('Licensing requires a timezone-aware clock.')
    return value.astimezone(timezone.utc).replace(microsecond=0)


def timestamp(value):
    return utc(value).isoformat().replace('+00:00', 'Z')


def parse_time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value):
        raise LicenseError('Invalid license timestamp.')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise LicenseError('Invalid license timestamp.') from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def encode64(raw):
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def decode64(value):
    if not isinstance(value, str) or not value or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise LicenseError('Invalid license encoding.')
    try:
        raw = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        if encode64(raw) != value:
            raise ValueError
        return raw
    except ValueError:
        raise LicenseError('Invalid license encoding.') from None


def normalize(code):
    if not isinstance(code, str) or len(code) > MAX_CODE:
        raise LicenseError('License code is too large or invalid.')
    return ''.join(code.split())


def code_digest(code):
    return hashlib.sha256(normalize(code).encode('ascii')).hexdigest() if code else ''


def key_id(public):
    return hashlib.sha256(public).hexdigest()[:16]


def _hex(value, length, label):
    if not isinstance(value, str) or not re.fullmatch(f'[a-fA-F0-9]{{{length}}}', value):
        raise LicenseError(f'Invalid {label}.')


def _json(raw):
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or canonical(value) != raw:
            raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise LicenseError('Invalid license payload.') from None


def validate_claim(claim):
    if set(claim) != TOKEN_FIELDS or claim['version'] != 3 or type(claim['version']) is not int:
        raise LicenseError('Unsupported signed license format.')
    for name, size in (('key_id', 16), ('license_id', 32), ('request_id', 32), ('hardware_id', 32)):
        _hex(claim[name], size, name)
    if not isinstance(claim['previous_digest'], str):
        raise LicenseError('Invalid previous license reference.')
    if claim['previous_digest']:
        _hex(claim['previous_digest'], 64, 'previous license reference')
    if claim['product'] not in PRODUCTS:
        raise LicenseError('Unsupported license product.')
    if type(claim['revision']) is not int or not 1 <= claim['revision'] <= 1000000:
        raise LicenseError('Invalid license revision.')
    if type(claim['added_days']) is not int or not 1 <= claim['added_days'] <= 36500:
        raise LicenseError('Invalid additional days.')
    if parse_time(claim['expires_at']) <= parse_time(claim['issued_at']):
        raise LicenseError('Invalid license validity interval.')


def decode_token(code, trusted_keys, *, hardware_id=None, product=None):
    parts = normalize(code).split('.')
    if len(parts) != 3 or parts[0] != 'AIP3':
        raise LicenseError('Invalid signed license format.')
    raw, signature = decode64(parts[1]), decode64(parts[2])
    claim = _json(raw)
    validate_claim(claim)
    try:
        public = bytes.fromhex(trusted_keys[claim['key_id']])
        if key_id(public) != claim['key_id']:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(public).verify(signature, b'AIPACS-LICENSE-V3\0' + raw)
    except (KeyError, ValueError, TypeError, InvalidSignature):
        raise LicenseError('License signature is invalid or its issuer is not trusted.') from None
    if hardware_id is not None and claim['hardware_id'] != hardware_id:
        raise LicenseError('This license belongs to another device.')
    if product is not None and claim['product'] != product:
        raise LicenseError('This license belongs to another product.')
    return claim


def encode_request(request):
    return 'AIR3.' + encode64(canonical(request))


def decode_request(code):
    parts = normalize(code).split('.')
    if len(parts) != 2 or parts[0] != 'AIR3':
        raise LicenseError('Invalid renewal request format.')
    request = _json(decode64(parts[1]))
    if set(request) != REQUEST_FIELDS or type(request['version']) is not int or request['version'] != 3:
        raise LicenseError('Unsupported renewal request.')
    for name in ('request_id', 'hardware_id', 'previous_hardware_id'):
        _hex(request[name], 32, name)
    if request['product'] not in PRODUCTS or not isinstance(request['previous_license'], str):
        raise LicenseError('Invalid renewal product or previous license.')
    parse_time(request['created_at'])
    return request
