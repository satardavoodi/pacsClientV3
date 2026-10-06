"""Worker-only settings persistence and DICOM verification with bounded receipts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from modules.ai_imaging.eagle_eye_remote.secretary.validation.settings_controls import SETTINGS_CONTROL_MODELS

_LOCK = threading.RLock()


class SettingsControlError(ValueError):
    """Safe, explicitly authored settings failure; contains no private values."""


def dicom_echo(host, port, ae_title):
    from pynetdicom import AE
    from pynetdicom.sop_class import Verification
    ae = AE()
    ae.add_requested_context(Verification)
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = 3
    association = ae.associate(host, port, ae_title=ae_title)
    connected = association.is_established
    try:
        status = association.send_c_echo() if connected else None
        code = int(status.Status) if status is not None and hasattr(status, 'Status') else None
        return {'connected':connected, 'echo_success':code == 0, 'status_code':code}
    finally:
        if association.is_established:
            association.release()


class SettingsRepository:
    def __init__(self, root=None, echo=None):
        if root is None:
            from PacsClient.utils.config import SOCKET_CONFIG_PATH
            root = SOCKET_CONFIG_PATH
        self.root = Path(root)
        self.echo = echo or dicom_echo
        self._observed = {}

    def _read(self, name):
        raw = (self.root / name).read_bytes()
        self._observed[name] = raw
        return json.loads(raw.decode('utf-8-sig'))

    def _save(self, documents):
        """Check for concurrent manual edits, replace, read back, roll back on failure."""
        originals = {name:(self.root/name).read_bytes() if (self.root/name).exists() else None for name in documents}
        if any(name in self._observed and self._observed[name] != old for name,old in originals.items()):
            raise SettingsControlError('Settings changed concurrently; retry after reviewing them')
        staged = {}
        replaced = []
        try:
            for name, data in documents.items():
                path = self.root / (name + '.' + str(uuid4()) + '.tmp')
                path.write_text(json.dumps(data, indent=2), encoding='utf-8')
                staged[name] = path
            for name, old in originals.items():
                path = self.root/name
                if (path.read_bytes() if path.exists() else None) != old:
                    raise SettingsControlError('Settings changed concurrently; retry after reviewing them')
            for name, path in staged.items():
                os.replace(path, self.root/name)
                replaced.append(name)
            for name, data in documents.items():
                if self._read(name) != data:
                    raise SettingsControlError('Settings readback failed')
        except Exception:
            for name in replaced:
                path = self.root/name
                if originals[name] is None:
                    path.unlink(missing_ok=True)
                else:
                    rollback = self.root/(name+'.'+str(uuid4())+'.rollback')
                    rollback.write_bytes(originals[name])
                    os.replace(rollback, path)
            raise
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)

    def execute(self, action, entities):
        values = SETTINGS_CONTROL_MODELS[action].model_validate(entities).model_dump(exclude_none=True)
        with _LOCK:
            return getattr(self, action)(**values)

    def get_settings_snapshot(self, section):
        if section == 'server':
            return {'section':section, 'servers':[{k:s.get(k) for k in ('name','host','port','ae_title')}
                                                  for s in self._read('servers.json')]}
        if section == 'modality_grid':
            doc = self._read('modality_grid.json')
            layouts = doc.get('modality_layouts', doc)
            return {'section':section, 'layouts':{k:v for k,v in layouts.items() if k.upper() != 'DEFAULT'}}
        if section == 'image_filter':
            return {'section':section, 'filters':self._read('filter_settings.json')}
        from PacsClient.pacs.patient_tab.utils.tools_settings import get_tools_settings
        return {'section':section, 'styles':get_tools_settings().get_settings().to_dict()}

    def verify_settings_server(self, server_name, ports):
        matching = [s for s in self._read('servers.json') if s['name'].casefold() == server_name.casefold()]
        if len(matching) != 1:
            raise SettingsControlError('Select one configured server by exact name')
        server = matching[0]
        results = []
        for port in ports:
            try:
                result = self.echo(server['host'], port, server['ae_title'])
            except Exception:
                result = {'connected':False, 'echo_success':False, 'error_code':'DICOM_VERIFY_FAILED'}
            results.append(dict(result, port=port))
        return {'server_name':server['name'], 'results':results, 'configuration_changed':False}

    def clone_settings_server(self, source_name, new_name):
        servers = self._read('servers.json')
        if any(s['name'].casefold() == new_name.casefold() for s in servers):
            raise SettingsControlError('The new server name already exists')
        matching = [s for s in servers if s['name'].casefold() == source_name.casefold()]
        if len(matching) != 1:
            raise SettingsControlError('Select one configured source server')
        source = matching[0]
        clone = deepcopy(source)
        clone['name'] = new_name
        documents = {'servers.json':servers+[clone]}
        profile_path = self.root/'server_profiles.json'
        if profile_path.exists():
            from PacsClient.utils.server_profiles import reconcile_profiles
            original = self._read('server_profiles.json')
            profiles = reconcile_profiles(original, documents['servers.json'])
            old = next((p for p in original['profiles'] if p['display_name'].casefold() == source_name.casefold()), None)
            new = next(p for p in profiles['profiles'] if p['display_name'] == new_name)
            if old:
                for key in ('socket_port','modules','poor_connectivity','enabled','server_type'):
                    if key in old:
                        new[key] = deepcopy(old[key])
            documents['server_profiles.json'] = profiles
        self._save(documents)
        return {'server_name':new_name,'saved':True,'active_server_changed':False,'restart_required':True}

    def remove_settings_modalities(self, modalities):
        doc = self._read('modality_grid.json')
        layouts = doc.get('modality_layouts', doc)
        available = {k for k in layouts if k.upper() != 'DEFAULT'}
        if set(modalities) - available:
            raise SettingsControlError('Requested modality is not configured')
        if not available - set(modalities):
            raise SettingsControlError('At least one modality must remain')
        for name in modalities:
            del layouts[name]
        self._save({'modality_grid.json':doc})
        return {'saved':True,'removed':modalities,'modalities':sorted(available-set(modalities)), 'restart_required':True}

    def set_settings_filter_parameter(self, modality, parameter, value):
        filters = self._read('filter_settings.json')
        presets = self._read('filter_presets.json')
        target = filters[modality]
        parts = parameter.split('.')
        for part in parts[:-1]:
            target = target[part]
        if parts[-1] not in target:
            raise SettingsControlError('Filter parameter is not configured')
        previous = target[parts[-1]]
        target[parts[-1]] = value
        active = presets['active']
        if active not in presets['presets']:
            raise SettingsControlError('The active filter preset is unavailable')
        presets['presets'][active] = deepcopy(filters)
        self._save({'filter_settings.json':filters, 'filter_presets.json':presets})
        return {'saved':True,'modality':modality,'parameter':parameter,'previous':previous,'value':value,
                'restart_required':True,'active_images_changed':False}

    def set_settings_tool_style(self, tool, color=None, line_width=None):
        from PacsClient.pacs.patient_tab.utils import tools_settings
        from PacsClient.utils.database import get_db_connection
        manager = tools_settings.get_tools_settings()
        requested = deepcopy(manager.get_settings())
        updates = {}
        if color is not None:
            updates['color'] = tuple(int(color[i:i+2],16)/255 for i in (1,3,5))
        if line_width is not None:
            updates['line_width'] = line_width
        for name, value in updates.items():
            setattr(getattr(requested, tool), name, value)
        expected = json.loads(json.dumps(requested.to_dict()))
        with get_db_connection() as connection:
            connection.execute('INSERT OR REPLACE INTO tools_settings (id,settings_json,updated_at) VALUES (1,?,CURRENT_TIMESTAMP)',
                               (json.dumps(expected),))
            connection.commit()
            row = connection.execute('SELECT settings_json FROM tools_settings WHERE id=1').fetchone()
        actual = json.loads(row[0]) if row else {}
        if actual != expected:
            raise SettingsControlError('Tool settings did not persist')
        with tools_settings._cache_lock:
            manager._settings = requested
            tools_settings._settings_cache = requested
        return {'saved':True,'tool':tool,'style':actual[tool], 'restart_required':True,'active_images_changed':False}

    def get_ai_settings(self):
        from modules.EchoMind import settings_store as store
        from modules.ai_imaging.eagle_eye_remote import administration as admin
        voice = store.get_stt_settings()
        personal = store.get_openai_settings()
        eagle = admin.load_settings()
        from urllib.parse import urlsplit
        address = eagle['value'].get('url','')
        parsed = urlsplit(address)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            address = ''
        return {'voice_to_text':{k:voice[k] for k in ('provider','timeout_seconds')},
                'voice_providers':['auto','v2t','aipacs_1','aipacs_2','aipacs_3','openai','custom'],
                'proxy':store.get_proxy_settings(), 'backend':store.get_llm_backend(),
                'personal':{k:v for k,v in personal.items() if k.endswith('_model') or k in
                            ('reasoning_effort','temperature','max_output_tokens','timeout_seconds')},
                'personal_key_configured':bool(personal.get('api_key')),
                'user_prompt_configured':any(store.get_prompt_settings().values()),
                'eagle_eye':{'role':eagle['role'],'url':address,
                             'credentials_configured':bool(eagle['value'].get('token_file'))},
                'company_prompts_models':'authenticated_eagle_eye_server_owned',
                'credential_and_prompt_entry':'local_only',
                'legacy_transcription_route':'shared_existing_service_not_a_server_audio_migration'}

    def set_voice_to_text_preferences(self, provider=None, timeout_seconds=None):
        from modules.EchoMind import settings_store as store
        before = store.get_stt_settings()
        requested = dict(before)
        if provider is not None:
            if provider == 'custom' and not before['custom_base_url']:
                raise SettingsControlError('Configure the custom transcription address and credentials in the local Voice to Text form first.')
            if provider == 'openai' and (not store.get_openai_settings().get('api_key') or not any(store.get_prompt_settings().values())):
                raise SettingsControlError('Personal OpenAI requires your own key and explicitly defined prompt in local Settings first.')
            requested['provider'] = provider
        if timeout_seconds is not None:
            requested['timeout_seconds'] = timeout_seconds
        store.save_stt_settings(requested)
        actual = store.get_stt_settings()
        if actual != requested:
            raise SettingsControlError('Voice to Text preferences did not persist.')
        return {'saved':True,'provider':actual['provider'],'timeout_seconds':actual['timeout_seconds'],
                'applies_to':['echomind_chat','secretary'],'applies_to_new_recordings':True,
                'restart_required':False,'settings_form_refresh_required':True}

    def set_ai_proxy_preferences(self, connection_type, proxy_port):
        from modules.EchoMind import settings_store as store
        store.save_proxy_settings({'connection_type':connection_type,'proxy_port':proxy_port})
        actual = store.get_proxy_settings()
        if actual['connection_type'] != connection_type or actual['proxy_port'] != proxy_port:
            raise SettingsControlError('AI proxy preferences did not persist.')
        return {'saved':True,'proxy':actual,'restart_required':False,'settings_form_refresh_required':True}

    def set_personal_ai_preferences(self, **changes):
        from modules.EchoMind import settings_store as store
        if store.get_llm_backend() != 'openai':
            raise SettingsControlError('Company AI models and prompts are owned by Eagle Eye Server. This control changes only an already configured personal OpenAI mode.')
        if not store.get_openai_settings().get('api_key') or not any(store.get_prompt_settings().values()):
            raise SettingsControlError('Configure your personal key and explicitly defined prompt in local Settings first.')
        # Patch exact fields; the legacy full-form saver supplies defaults for
        # omitted fields and would overwrite unrelated preferences or zero values.
        store.save_settings({'openai_'+key:value for key,value in changes.items()})
        actual = store.get_openai_settings()
        if any(actual[key] != value for key,value in changes.items()):
            raise SettingsControlError('Personal AI preferences did not persist.')
        return {'saved':True,'preferences':{key:actual[key] for key in changes},
                'scope':'personal_openai_only','restart_required':False,'settings_form_refresh_required':True}

    def verify_eagle_eye_connection(self):
        from modules.ai_imaging.eagle_eye_remote import administration as admin
        snapshot = admin.load_settings()
        try:
            capabilities = admin.probe_connection(snapshot['value'])
        except Exception:
            raise SettingsControlError('Eagle Eye authentication, TLS trust or capability verification failed. Review the local connection form; no settings were changed.') from None
        return {'authenticated':True,'compatible':True,'configuration_changed':False,
                'modules':capabilities['modules'],'protocol':capabilities['protocol']}

    def set_eagle_eye_connection(self, url):
        from modules.ai_imaging.eagle_eye_remote import administration as admin
        snapshot = admin.load_settings()
        if snapshot['role'] == 'server':
            raise SettingsControlError('This is the Eagle Eye Server role. Listener and credentials must be changed through the local server administration form.')
        requested = {**snapshot['value'],'url':url}
        # Validate identity, TLS and capabilities before committing the new target.
        try:
            admin.probe_connection(requested)
        except Exception:
            raise SettingsControlError('The new Eagle Eye address failed authentication, TLS trust or compatibility checks. The previous connection was preserved.') from None
        admin.save_connection(snapshot['path'],snapshot['revision'],{'url':url})
        actual = admin.load_settings()
        if actual['value'].get('url') != url.rstrip('/'):
            raise SettingsControlError('Eagle Eye connection did not persist.')
        return {'saved':True,'url':actual['value']['url'],'authenticated':True,
                'connection_revision':actual['revision'],
                'credentials_changed':False,'restart_required':False,'settings_form_refresh_required':True}
