"""Company-only offline issuer. Never import this module from customer runtime.

The order ledger serializes issuance and prevents duplicate credit or stale-base
requests. Legacy migration requires an operator-approved expiry from company
records because a customer-distributed symmetric secret is not an authority.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

from modules.LicenseGenerator.protection import protect, unprotect
from modules.LicenseGenerator.legacy_proof import legacy_claim
from modules.LicenseGenerator.signed_license import (LicenseError, canonical, code_digest,
    decode_request, decode_token, encode64, key_id, normalize, parse_time, timestamp, utc,
    validate_claim)


class Issuer:
    def __init__(self, private_key, ledger_path, *, trusted_keys=None):
        self.private = private_key
        public = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.key_id = key_id(public)
        self.trusted = dict(trusted_keys or {})
        self.trusted[self.key_id] = public.hex()
        self.ledger_path = Path(ledger_path)

    def inspect_request(self, code, *, expected_product):
        request = decode_request(code)
        if request['product'] != expected_product:
            raise LicenseError('The customer request does not match the purchased company product.')
        previous = request['previous_license']
        if previous.startswith('AIP3.'):
            claim = decode_token(previous, self.trusted, hardware_id=request['hardware_id'], product=expected_product)
        elif previous:
            if expected_product != 'client':
                raise LicenseError('Legacy licenses cannot activate Eagle Eye Server.')
            claim = legacy_claim(previous, request['previous_hardware_id'])
        else:
            claim = None
        return {'product': request['product'], 'request_id': request['request_id'],
                'expires_at': claim['expires_at'] if claim else None,
                'legacy': bool(claim and claim.get('legacy')), 'initial': claim is None}

    def issue(self, request_code, *, days, order_id, now=None, approved_legacy_expiry=None):
        if type(days) is not int or not 1 <= days <= 36500:
            raise LicenseError('Additional days must be between 1 and 36500.')
        if not isinstance(order_id, str) or not order_id.strip() or len(order_id) > 128:
            raise LicenseError('A unique company order reference is required.')
        order_id = order_id.strip()
        request = decode_request(request_code)
        now = utc(now or datetime.now(timezone.utc))
        previous = request['previous_license']
        base = None
        if previous.startswith('AIP3.'):
            base = decode_token(previous, self.trusted,
                                hardware_id=request['hardware_id'], product=request['product'])
            if request['previous_hardware_id'] != request['hardware_id']:
                raise LicenseError('Device transfers require a separate company process.')
        elif previous:
            if request['product'] != 'client' or approved_legacy_expiry is None:
                raise LicenseError('Company-approved legacy expiry is required for migration.')
            base = legacy_claim(previous, request['previous_hardware_id'])
            approved = parse_time(approved_legacy_expiry)
            if approved > parse_time(base['expires_at']):
                raise LicenseError('Approved legacy expiry exceeds the verified previous expiry.')
            base['expires_at'] = timestamp(approved)
        elif approved_legacy_expiry is not None:
            raise LicenseError('Legacy approval is only valid for a legacy migration request.')
        request_hash = code_digest(request_code)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.ledger_path, timeout=10) as db:
            db.execute('CREATE TABLE IF NOT EXISTS issued (order_id TEXT PRIMARY KEY, request_id TEXT UNIQUE, '
                       'request_hash TEXT, days INTEGER, approved_expiry TEXT, token TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS devices (product TEXT, hardware_id TEXT, token TEXT, '
                       'PRIMARY KEY(product, hardware_id))')
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT request_hash, days, approved_expiry, token FROM issued WHERE order_id=?',
                                  (order_id,)).fetchone()
            if existing:
                if existing[:3] != (request_hash, days, approved_legacy_expiry):
                    raise LicenseError('This order reference was already used for different inputs.')
                return existing[3]
            if db.execute('SELECT 1 FROM issued WHERE request_id=?', (request['request_id'],)).fetchone():
                raise LicenseError('This request already received a license. Reuse the original order reference.')
            created = parse_time(request['created_at'])
            if created > now + timedelta(minutes=5) or now - created >= timedelta(days=30):
                raise LicenseError('Request is stale or its device clock is incorrect. Generate a fresh request.')
            active = db.execute('SELECT token FROM devices WHERE product=? AND hardware_id=?',
                                (request['product'], request['hardware_id'])).fetchone()
            if active and normalize(previous) != active[0]:
                raise LicenseError('This device has a newer issued license. Apply it before requesting another extension.')
            if base and not base.get('legacy') and parse_time(base['issued_at']) > now + timedelta(minutes=5):
                raise LicenseError('Previous license is newer than the company clock.')
            expiry = max(now, parse_time(base['expires_at'])) if base else now
            claim = {'version': 3, 'key_id': self.key_id,
                'license_id': base['license_id'] if base and not base.get('legacy') else uuid.uuid4().hex,
                'revision': base['revision'] + 1 if base else 1,
                'hardware_id': request['hardware_id'], 'product': request['product'],
                'issued_at': timestamp(now), 'expires_at': timestamp(expiry + timedelta(days=days)),
                'added_days': days, 'request_id': request['request_id'], 'previous_digest': code_digest(previous)}
            validate_claim(claim)
            raw = canonical(claim)
            token = 'AIP3.' + encode64(raw) + '.' + encode64(self.private.sign(b'AIPACS-LICENSE-V3\0' + raw))
            db.execute('INSERT INTO issued VALUES (?,?,?,?,?,?)',
                       (order_id, request['request_id'], request_hash, days, approved_legacy_expiry, token))
            db.execute('INSERT OR REPLACE INTO devices VALUES (?,?,?)',
                       (request['product'], request['hardware_id'], token))
            return token


def external_private_path(path):
    if not Path(path).is_absolute():
        raise LicenseError('Company private storage requires an absolute path.')
    path = Path(path).resolve()
    repo = Path(__file__).resolve().parents[2]
    if path == repo or repo in path.parents or not path.is_absolute():
        raise LicenseError('Company private storage must be outside the application repository.')
    return path


def restrict_company_directory(directory):
    """A dedicated new directory belongs only to this Windows user and SYSTEM."""
    identity = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'],
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), text=True)
    sid = next(csv.reader(identity.splitlines()))[1]
    if not sid.startswith('S-1-'):
        raise LicenseError('Could not identify the company Windows account.')
    subprocess.run(['icacls', str(directory), '/inheritance:r', '/grant:r',
        f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def provision(private_path, public_output):
    if os.name != 'nt':
        raise LicenseError('Company signing-key provisioning requires Windows DPAPI.')
    private_path = external_private_path(private_path)
    public_output = Path(public_output).resolve()
    if private_path == public_output or private_path.exists() or public_output.exists():
        raise LicenseError('Use distinct new private-store and public-output paths; existing keys are never overwritten.')
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    data = {'version': 3, 'key_id': key_id(public), 'private': private.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()}
    if private_path.parent.exists() and any(private_path.parent.iterdir()):
        raise LicenseError('Provision into a dedicated new or empty company directory.')
    private_path.parent.mkdir(parents=True, exist_ok=True)
    restrict_company_directory(private_path.parent)
    public_output.parent.mkdir(parents=True, exist_ok=True)
    # Persist only a DPAPI-protected private key; never print it or write a PEM.
    with private_path.open('xb') as output:
        output.write(protect(canonical(data)))
        output.flush()
        os.fsync(output.fileno())
    with public_output.open('x', encoding='utf-8') as output:
        output.write('"""Company public verification roots; no private key material."""\n')
        output.write(f'TRUSTED_KEYS = {repr({key_id(public): public.hex()})}\n')
    return key_id(public)


def load_issuer(private_path, ledger_path=None):
    if os.name != 'nt':
        raise LicenseError('The company issuer requires Windows DPAPI.')
    private_path = external_private_path(private_path)
    try:
        raw = private_path.read_bytes()
        if len(raw) > 8192 or not raw.startswith(b'DPAPI3\0'):
            raise ValueError
        data = json.loads(unprotect(raw))
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(data['private']))
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if data['version'] != 3 or key_id(public) != data['key_id']:
            raise ValueError
    except (OSError, KeyError, ValueError, TypeError):
        raise LicenseError('The signing store could not be unlocked by this Windows account.') from None
    from modules.LicenseGenerator.signing_trust import TRUSTED_KEYS
    # The issuing root must be pinned before real licenses can be activated.
    if TRUSTED_KEYS.get(key_id(public)) != public.hex():
        raise LicenseError('Install this issuer public root in signing_trust.py before issuing licenses.')
    ledger = external_private_path(ledger_path or private_path.with_suffix('.sqlite'))
    if ledger.parent != private_path.parent:
        raise LicenseError('Keep the issuance ledger in the protected signing-store directory.')
    return Issuer(private, ledger, trusted_keys=TRUSTED_KEYS)


def main():
    parser = argparse.ArgumentParser(description='Company-only AI-PACS signed license issuer')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('provision')
    init.add_argument('--private-store', required=True, type=Path)
    init.add_argument('--public-output', required=True, type=Path)
    issue = commands.add_parser('issue')
    issue.add_argument('--private-store', required=True, type=Path)
    issue.add_argument('--request-file', required=True, type=Path)
    issue.add_argument('--output', required=True, type=Path)
    issue.add_argument('--days', required=True, type=int)
    issue.add_argument('--order-id', required=True)
    issue.add_argument('--product', required=True, choices=('client', 'eagle-eye-server'))
    issue.add_argument('--approved-legacy-expiry')
    args = parser.parse_args()
    try:
        if args.command == 'provision':
            provision(args.private_store, args.public_output)
            print('Protected signing store and public verification file created. No private key was displayed.')
        else:
            private_store = external_private_path(args.private_store)
            if args.output.resolve() in (private_store, private_store.with_suffix('.sqlite'), args.request_file.resolve()):
                raise LicenseError('License output must not overwrite the signing store, ledger or request.')
            if args.output.exists():
                raise LicenseError('Use a new license output file. Existing files are never overwritten.')
            if args.request_file.stat().st_size > 32768:
                raise LicenseError('Request file is too large.')
            issuer = load_issuer(args.private_store)
            request_code = args.request_file.read_text(encoding='utf-8')
            issuer.inspect_request(request_code, expected_product=args.product)
            token = issuer.issue(request_code,
                days=args.days, order_id=args.order_id, approved_legacy_expiry=args.approved_legacy_expiry)
            with args.output.open('x', encoding='utf-8') as output:
                output.write(token)
            print('Signed license saved. Reuse the same order reference to recover the same response.')
    except (LicenseError, OSError, subprocess.SubprocessError):
        raise SystemExit('Issuance failed. Check protected store access, public root, request and company order details.') from None


if __name__ == '__main__':
    main()
