"""Private hosted-only delegation from freshly admitted Eagle identities."""
import base64
from contextvars import ContextVar

CURRENT = ContextVar('eagle_crm_principal', default=None)
HEADER = 'X-Eagle-CRM-Subject'

def encode_subject(subject):
    if not isinstance(subject,str) or not subject or len(subject.encode('utf-8'))>1024 or any(ord(c)<32 for c in subject):
        raise ValueError('Invalid delegated identity.')
    return base64.urlsafe_b64encode(subject.encode('utf-8')).decode('ascii').rstrip('=')

def decode_subject(value):
    try:
        subject=base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True).decode('utf-8')
        if encode_subject(subject)!=value: raise ValueError()
        return subject
    except Exception:
        raise ValueError('Invalid delegated identity.') from None

def principal_for(subject,center):
    encode_subject(subject)
    from reception_crm.core.types import Principal
    return Principal(user='eagle:'+subject,center=center,roles=['eagle_crm_readonly'],auth_method='eagle_session')

class DelegatedPolicy:
    def __init__(self,principal): self.principal=principal
    def check(self,user,center,operation,action,safety):
        from reception_crm.permissions import PermissionDecision
        p=self.principal
        allowed=bool(p and user==p.user and center==p.center and safety=='read' and action in ('read','plan'))
        return PermissionDecision(allowed,'Eagle CRM read-only delegation' if allowed else 'Hosted CRM permission denied',user,center,list(p.roles) if p else [])

def install_policy():
    # Core guards are the single actual tool admission boundary. Standalone policy
    # and identity implementations are unchanged outside this private worker.
    from reception_crm.core import guards
    from reception_crm import permissions
    loader=lambda: DelegatedPolicy(CURRENT.get())
    permissions.load_permissions=loader
    guards.load_permissions=loader
