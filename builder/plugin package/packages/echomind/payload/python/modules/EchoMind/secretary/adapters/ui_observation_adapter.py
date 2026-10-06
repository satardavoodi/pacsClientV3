"""Shared UI observation contracts. Discovery never grants arbitrary widget writes."""
from concurrent.futures import ThreadPoolExecutor
import time
from ..command_envelope import CommandResult

UI_ACTIONS={name:name for name in ('get_ui_control_catalog','inspect_ui_controls',
                                   'capture_ui_context','ui_context_status')}


def area(source):
    if 'settings_ui' in source:return 'settings'
    if 'home_ui' in source:return 'home'
    if 'modules/viewer/advanced' in source:return 'advanced_viewer'
    if 'advanced_analysis' in source or 'data_analysis' in source or 'modules/mpr/' in source:return 'advanced_analysis'
    if 'ai_imaging' in source:return 'eagle_eye'
    return 'patient_viewer'


class UiObservationAdapter:
    def __init__(self,root_getter,bus_getter):
        self.root_getter=root_getter
        self.bus_getter=bus_getter
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='secretary-ui-image')
        self.pending=None

    def get_ui_control_catalog(self,plan,state):
        from PacsClient.utils.secretary_ui_source_catalog import SOURCE_CATALOG
        bus=self.bus_getter()
        contracts=bus.capabilities()['actions'] if bus else []
        wanted=plan.entities.get('area','all');offset=plan.entities.get('offset',0);limit=plan.entities.get('limit',50)
        records=[r for r in SOURCE_CATALOG['controls'] if wanted=='all' or area(r['source'])==wanted]
        # No free-form current values, callback bodies or source literals are published.
        fields=[{key:r[key] for key in ('source','line','function','name','kind','label','options','constraints','sensitive')}
                for r in records[offset:offset+limit]]
        for field,record in zip(fields,records[offset:offset+limit]):
            field['label']='Local-only control' if record['sensitive'] else next(
                (record.get(key) for key in ('label','setAccessibleName','setToolTip','setPlaceholderText','setText')
                 if record.get(key)), 'Live inspection required')
        return CommandResult(ok=True,action=plan.action,data={'version':1,'controls':fields,
            'total':len(records),'offset':offset,'truncated':offset+limit<len(records),
            'executable_contracts':contracts,'parse_errors':SOURCE_CATALOG['parse_errors'],
            'limits':['discovery_is_not_execution','source_callbacks_are_not_commands',
                      'dynamic_options_require_live_inspection','credentials_local_only',
                      'advanced_and_fast_tools_are_separate_domains']})

    def inspect_ui_controls(self,plan,state):
        from PacsClient.utils.secretary_ui_observation import collect
        try:
            metadata,_=collect(self.root_getter())
        except (ValueError,RuntimeError):
            return CommandResult(ok=False,action=plan.action,error_code='UI_SURFACE_UNAVAILABLE',
                                 message='Open the intended page before inspecting its controls.')
        return CommandResult(ok=True,action=plan.action,data=metadata)

    def capture_ui_context(self,plan,state):
        from PacsClient.utils.secretary_ui_observation import capture,encode
        if self.pending and not self.pending['future'].done():
            return CommandResult(ok=False,action=plan.action,error_code='UI_CAPTURE_BUSY')
        try:
            metadata,image=capture(self.root_getter())
        except (ValueError,RuntimeError):
            return CommandResult(ok=False,action=plan.action,error_code='UI_SURFACE_UNAVAILABLE')
        self.pending={'metadata':metadata,'created':time.monotonic(),'future':self.pool.submit(encode,metadata,image)}
        return CommandResult(ok=True,action=plan.action,data={'state':'encoding',
            'snapshot_id':metadata['snapshot_id'],'context_digest':metadata['context_digest']})

    def is_current(self,metadata):
        from PacsClient.utils.secretary_ui_observation import collect
        try:return collect(self.root_getter())[0]['context_digest']==metadata['context_digest']
        except (ValueError,RuntimeError):return False

    def ui_context_status(self,plan,state):
        item=self.pending
        if not item or plan.entities['snapshot_id']!=item['metadata']['snapshot_id']:
            return CommandResult(ok=False,action=plan.action,error_code='UI_CAPTURE_UNKNOWN')
        if time.monotonic()-item['created']>90 or not self.is_current(item['metadata']):
            self.pending=None
            return CommandResult(ok=False,action=plan.action,error_code='UI_CONTEXT_STALE',
                                 message='The page changed or capture expired. Capture it again.')
        if not item['future'].done():return CommandResult(ok=True,action=plan.action,data={'state':'encoding'})
        try:image=item['future'].result()
        except Exception:return CommandResult(ok=False,action=plan.action,error_code='UI_CAPTURE_FAILED')
        return CommandResult(ok=True,action=plan.action,data={'state':'ready','ui_image':image,
            'ui_controls':item['metadata']})
