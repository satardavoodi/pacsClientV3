"""Named Brain routes. Infrastructure endpoints stay in private host settings."""
from urllib.parse import urlsplit

PROFILES = {'server_1':'LLM G', 'server_2':'LLM A', 'server_3':'LLM V', 'custom':'Custom API'}
MODALITY_PROMPTS = {'MRI':'prompt_report_mri', 'CT':'prompt_report_ct',
                    'Sonography':'prompt_report_sonography', 'Obstetrics':'prompt_report_obstetrics',
                    'Cardiology':'prompt_report_cardiology'}
CUSTOM_FIELDS = tuple(MODALITY_PROMPTS.values()) + ('openai_base_url','openai_org_id','openai_project_id','openai_text_model',
                 'openai_report_model','openai_vision_model','prompt_report_generation',
                 'prompt_breast_assistant','prompt_secretary_routing','prompt_secretary_action',
                 'prompt_transcript_cleanup','prompt_image_artifact','prompt_crm')

def route(settings):
    selected = settings.get('brain_server','server_1')
    if selected not in PROFILES:
        raise ValueError('Select a registered Eagle AI Brain route.')
    if settings.get('brain_enabled',True) is not True:
        raise ValueError('Eagle AI Brain is disabled.')
    if selected in ('server_2','server_3'):
        raise ValueError('This Brain route has no qualified model/API yet. Select another route explicitly.')
    return selected

def custom_options(settings, options, category):
    base = str(settings.get('openai_base_url') or '').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Custom API requires an HTTPS API base URL.')
    key = str(settings.get('openai_api_key') or '').strip()
    if not key:
        raise ValueError('Configure your own Custom API credential.')
    payload = dict(options.get('json') or {})
    workflow = settings.get('brain_workflow','report')
    prompt_key = ('prompt_secretary_routing' if workflow == 'route' else 'prompt_secretary_action') if category in ('agent','secretary') else 'prompt_crm' if category=='crm' else 'prompt_image_artifact' if category=='eagle_eye' else 'prompt_breast_assistant' if workflow=='breast' else 'prompt_report_generation'
    if category == 'echomind' and workflow in ('report', 'turbo', 'correction'):
        modality = settings.get('brain_modality')
        aliases = {'SONOGRAPHY':'Sonography', 'OBSTETRIC ULTRASOUND':'Obstetrics',
                   'ECHOCARDIOGRAPHY':'Cardiology'}
        prompt_key = MODALITY_PROMPTS.get(aliases.get(modality, modality))
        if prompt_key is None or not str(settings.get(prompt_key) or '').strip():
            raise ValueError('Define your own exact modality prompt for Custom reporting.')
    prompt = str(settings.get(prompt_key) or '').strip()
    if not prompt:
        raise ValueError('Define your own prompt for this Custom API workflow.')
    model_key = 'openai_report_model' if workflow in ('report','turbo','correction') and category=='echomind' else 'openai_text_model'
    model = str(settings.get(model_key) or '').strip()
    if not model:
        raise ValueError('Select your Custom API model.')
    if not isinstance(payload.get('messages'), list):
        raise ValueError('Custom API currently supports chat-completions workflows only.')
    payload['messages'] = [{'role':'system','content':prompt}] + [m for m in payload['messages'] if isinstance(m,dict) and m.get('role') not in ('system','developer')]
    payload['model'] = model
    options['json'] = payload
    options['_brain_url'] = base + '/chat/completions'
    headers = {'Content-Type':'application/json','Authorization':'Bearer '+key}
    for field,header in [('openai_org_id','OpenAI-Organization'),('openai_project_id','OpenAI-Project')]:
        if settings.get(field):headers[header]=str(settings[field])
    options['headers'] = headers
