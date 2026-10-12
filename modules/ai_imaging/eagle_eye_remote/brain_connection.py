"""Private selected-Brain transport accounting, independent of provider model."""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from pathlib import Path
import sqlite3
import uuid

_source = ContextVar('eagle_ai_brain_source', default='echomind')
LABELS = {'echomind': 'EchoMind', 'secretary': 'Secretary EchoMind',
          'agent': 'Agent', 'crm': 'CRM', 'eagle_eye': 'Eagle Eye', 'other': 'Other'}

@contextmanager
def source(category):
    token = _source.set(category if category in LABELS else 'other')
    try:
        yield
    finally:
        _source.reset(token)

def _database(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'brain-usage.sqlite3', timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, category TEXT NOT NULL, state TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER)')
    db.execute('BEGIN IMMEDIATE')
    if 'provider' not in {row[1] for row in db.execute('PRAGMA table_info(calls)')}:
        db.execute("ALTER TABLE calls ADD COLUMN provider TEXT NOT NULL DEFAULT 'server_1'")
    db.commit()
    return db

def begin(directory, provider="server_1"):
    identifier = uuid.uuid4().hex
    with closing(_database(directory)) as db, db:
        db.execute('INSERT INTO calls(id,category,state,provider) VALUES (?,?,?,?)',
                   (identifier, _source.get(), 'pending', provider))
    return identifier

def _count(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None

def finish(directory, identifier, usage, *, failed=False):
    usage = usage if isinstance(usage, dict) else {}
    incoming = _count(usage.get('input_tokens', usage.get('prompt_tokens')))
    outgoing = _count(usage.get('output_tokens', usage.get('completion_tokens')))
    total = _count(usage.get('total_tokens'))
    if total is None and incoming is not None and outgoing is not None:
        total = incoming + outgoing
    with closing(_database(directory)) as db, db:
        db.execute('UPDATE calls SET state=?,input_tokens=?,output_tokens=?,total_tokens=? WHERE id=? AND state=?',
                   ('failed' if failed else 'completed', incoming, outgoing, total, identifier, 'pending'))

def summary(directory, provider="server_1"):
    path = Path(directory) / 'brain-usage.sqlite3'
    rows = {key: dict(label=label, calls=0, failed=0, pending=0, input_tokens=None,
                     output_tokens=None, total_tokens=None, missing_usage=0) for key,label in LABELS.items()}
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
            has_provider = 'provider' in {r[1] for r in db.execute('PRAGMA table_info(calls)')}
            query = 'SELECT category,state,input_tokens,output_tokens,total_tokens FROM calls'
            if has_provider:
                query += ' WHERE provider=?'
            elif provider != 'server_1':
                query += ' WHERE 0'
            for category,state,incoming,outgoing,total in db.execute(query, (provider,) if has_provider else ()):
                row = rows.get(category, rows['other'])
                row['calls'] += 1
                row['failed'] += int(state == 'failed')
                row['pending'] += int(state == 'pending')
                row['missing_usage'] += int(incoming is None or outgoing is None)
                for key,value in [('input_tokens',incoming),('output_tokens',outgoing),('total_tokens',total)]:
                    if value is not None:
                        row[key] = (row[key] or 0) + value
    return {'server': provider, 'scope': 'provider_calls_since_accounting_enabled', 'groups': list(rows.values())}

def send(url, operation, *, options=None):
    """Account selected Brain and approved company calls; exclude personal/audio calls."""
    from urllib.parse import urlsplit
    from .echomind import runtime
    from .echomind.core.ai_chat_config import GAPGPT_API_URL, AI_BASE, ASSIST_BASE, URL_GEN_TRANSCRIPT
    target = urlsplit(url)
    is_gapgpt = target.hostname == urlsplit(GAPGPT_API_URL).hostname
    try:
        settings = runtime.current_settings()
    except RuntimeError:
        if is_gapgpt:
            raise ValueError('Eagle AI Brain requires the shared server connection context.') from None
        return operation()
    if settings.get('llm_backend', 'company') != 'company':
        return operation()
    if '/audio/' in target.path or url == URL_GEN_TRANSCRIPT:
        return operation()
    from .brain_profiles import route, custom_options
    selected = route(settings)
    from .brain_administration import proxy_settings
    proxy = proxy_settings(settings)
    if options is None and proxy['connection_type'] == 'socks5':
        raise ValueError('Shared Brain proxy requires authoritative transport options.')
    proxy_url = f"socks5://127.0.0.1:{proxy['proxy_port']}"
    if options is not None:
        options['proxies'] = ({'http': proxy_url, 'https': proxy_url}
                              if proxy['connection_type'] == 'socks5' else {})
    if options is not None:
        options.pop('_brain_url', None)
    if selected == 'custom':
        if options is None:
            raise ValueError('Custom API requires the shared Brain transport.')
        custom_options(settings, options, _source.get())
        is_gapgpt = False
    if not is_gapgpt and selected != 'custom':
        allowed = {urlsplit(AI_BASE).netloc, urlsplit(ASSIST_BASE).netloc}
        if target.netloc not in allowed:
            raise ValueError('Company AI destination is not registered in Eagle AI Brain.')
    if '/audio/' in target.path:
        return operation()
    if selected == 'server_1':
        try:
            _center, provider_key = runtime.company_identity()
        except Exception:
            raise ValueError('Authenticate LLM G in AI > Connection.') from None
        if is_gapgpt and (target.scheme != 'https' or target.username or target.password):
            raise ValueError('LLM G requires the configured secure provider connection.')
    if options is not None and selected == 'server_1' and is_gapgpt:
        headers = {key: value for key,value in options.get('headers', {}).items()
                   if key.lower() != 'authorization'}
        headers['Authorization'] = 'Bearer ' + provider_key
        options['headers'] = headers
    directory = Path(settings.get("brain_usage_dir") or runtime.private_dir())
    identifier = begin(directory, selected)
    try:
        response = operation()
    except Exception:
        finish(directory, identifier, None, failed=True)
        raise
    try:
        body = response.json()
        usage = body.get('usage') if isinstance(body, dict) else None
    except (AttributeError, ValueError, TypeError):
        usage = None
    finish(directory, identifier, usage, failed=getattr(response, 'status_code', 200) >= 300)
    return response
