"""Deprecated compatibility helpers; ordinary Client login must not call these.

Owner correction 2026-10-09: use automatic current-login credential exchange.
Provider selection and separate Reception entry UI are superseded.
"""
import time


def authenticate_reception(username, password):
    from .client import Client
    from . import user_session
    client = Client()
    user = client.authenticate_user(None, username, password)
    admission = user_session.confirmed_admission(client)
    return {'user':user,'client':client,**admission,
            'admit_before':time.monotonic()+5}


def valid_reception_admission(receipt):
    """Immediate UI handoff only; each later API call revalidates upstream."""
    from . import user_session
    from .client import ServerHTTPError
    valid = (isinstance(receipt,dict) and isinstance(receipt.get('user'),dict)
        and receipt['user'].get('provider') in ('pacs', 'reception')
        and bool(receipt['user'].get('enabled'))
        and bool(receipt['user'].get('principal'))
        and receipt.get('generation')==user_session.identity()[0]
        and receipt.get('admit_before',0)>time.monotonic())
    if not valid or receipt.get('client') is None:
        return False
    try:
        current = user_session.confirmed_admission(receipt['client'])
        return (current['provider']==receipt['user']['provider']
            and current['principal']==receipt['user']['principal']
            and current['generation']==receipt['generation'])
    except ServerHTTPError:
        return False
