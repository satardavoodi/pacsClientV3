"""Read-only legacy proof parsing shared by runtime migration and company issuance."""
from datetime import datetime, timezone
import hashlib
import hmac

from .signed_license import LicenseError, normalize, timestamp


def legacy_claim(code, hardware_id):
    """Read-only legacy proof. Its symmetric authenticity is a migration gap."""
    from .license_manager import SECRET_KEY
    value = normalize(code).replace('-', '').upper()
    if len(value) != 32:
        raise LicenseError('Invalid legacy license format.')
    try:
        expiry = datetime.strptime(value[:8], '%Y%m%d').astimezone(timezone.utc)
    except ValueError:
        raise LicenseError('Invalid legacy license expiry.') from None
    expected = hashlib.sha256(f'{hardware_id}|{value[:8]}|{SECRET_KEY}'.encode()).hexdigest()[:24].upper()
    if not hmac.compare_digest(expected, value[8:]):
        raise LicenseError('Legacy license does not match this device.')
    return {'expires_at': timestamp(expiry), 'revision': 0, 'license_id': '',
            'product': 'client', 'hardware_id': hardware_id, 'legacy': True}
