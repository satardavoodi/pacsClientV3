"""Build a source-traced UI inventory without importing workstation UI modules."""
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WIDGETS = {'QLineEdit','QComboBox','QCheckBox','QRadioButton','QSpinBox','QDoubleSpinBox',
           'QDateEdit','QTimeEdit','QPushButton','QToolButton','QAction','QSlider'}
CUSTOM_WIDGETS = {'LoginLineField':'QLineEdit','LoginComboField':'QComboBox',
                  'LoginDateField':'QDateEdit','LoginNumberField':'NumericField',
                  'CustomCheckbox':'QCheckBox'}
SENSITIVE = re.compile(r'password|credential|api.?key|secret|token|license.?key', re.I)


def text(node):
    value=node.value.strip()[:240] if isinstance(node, ast.Constant) and isinstance(node.value,str) else ''
    return '' if not value.isascii() or re.search(r'sk-[A-Za-z0-9]|gsk_|AIza|Bearer\s',value) else value


def inventory(path):
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    out=[]
    for owner in [n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]:
        records={}
        # Attribute names are descriptive source references, not executable locators.
        for node in ast.walk(owner):
            if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call):
                kind=ast.unparse(node.value.func).split('.')[-1]
                if kind not in WIDGETS and kind not in CUSTOM_WIDGETS: continue
                name=ast.unparse(node.targets[0])
                label=text(node.value.args[0]) if node.value.args else ''
                records[name]={'source':path.relative_to(ROOT).as_posix(),'line':node.lineno,
                    'function':owner.name,'name':name,'kind':CUSTOM_WIDGETS.get(kind,kind),'source_widget':kind,'label':label,
                    'options':[], 'constraints':{}, 'callbacks':[], 'sensitive':bool(SENSITIVE.search(name+' '+label))}
        for node in ast.walk(owner):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute): continue
            receiver=ast.unparse(node.func.value)
            method=node.func.attr
            rec=records.get(receiver)
            if rec is not None:
                numeric=[arg.value for arg in node.args if isinstance(arg,ast.Constant) and type(arg.value) in (int,float)]
                if method=='setRange' and len(numeric)==2:
                    rec['constraints'].update(minimum=numeric[0],maximum=numeric[1])
                elif method in ('setMinimum','setMaximum','setMaxLength','setDecimals') and len(numeric)==1:
                    rec['constraints'][{'setMinimum':'minimum','setMaximum':'maximum',
                        'setMaxLength':'maxLength','setDecimals':'decimals'}[method]]=numeric[0]
                if method in ('setToolTip','setPlaceholderText','setAccessibleName','setText') and node.args:
                    if method=='setText' and rec['kind'] not in ('QPushButton','QToolButton','QCheckBox','QAction'):
                        continue
                    value=text(node.args[0])
                    if value:rec[method]=value
                if method=='addItem' and node.args and text(node.args[0]):rec['options'].append(text(node.args[0]))
                if method=='addItems' and node.args and isinstance(node.args[0],(ast.List,ast.Tuple)):
                    rec['options'].extend(text(item) for item in node.args[0].elts if text(item))
            if method=='addRow' and len(node.args)>1:
                field=records.get(ast.unparse(node.args[1]))
                if field is not None and text(node.args[0]):field['label']=text(node.args[0])
            if method=='connect' and node.args and isinstance(node.func.value,ast.Attribute):
                field=records.get(ast.unparse(node.func.value.value))
                if field is not None:
                    callback=node.args[0]
                    field['callbacks'].append(ast.unparse(callback)[:160] if isinstance(callback,(ast.Name,ast.Attribute)) else 'Dynamic callback')
        for rec in records.values():
            joined=' '.join(str(rec.get(k,'')) for k in ('name','label','setToolTip','setPlaceholderText','setAccessibleName'))
            rec['sensitive']=bool(SENSITIVE.search(joined))
            rec['options']=list(dict.fromkeys(rec['options']))[:100]
            if rec['sensitive']:
                rec['options']=[]
            out.append(rec)
    return out


def source_paths():
    paths=set()
    for directory in ('PacsClient/pacs/workstation_ui/home_ui','PacsClient/pacs/workstation_ui/settings_ui',
                      'PacsClient/pacs/patient_tab/ui','modules/viewer/advanced','modules/advanced_analysis',
                      'modules/ai_imaging','modules/data_analysis','modules/mpr'):
        folder=ROOT/directory
        if folder.exists():
            paths.update(p for p in folder.rglob('*.py') if not {
                'vendor','echomind','__pycache__','build','dist','python-install',
                'site-packages','ThirdParty','.venv'} & set(p.parts))
    return sorted(paths)


def build():
    controls=[];errors=[]
    for path in source_paths():
        try:controls.extend(inventory(path))
        except (SyntaxError,UnicodeError) as exc:
            errors.append({'source':path.relative_to(ROOT).as_posix(),'error':type(exc).__name__})
    # Deduplicate nested function scans by canonical source location.
    controls=list({(r['source'],r['line'],r['name']):r for r in controls}.values())
    controls.sort(key=lambda r:(r['source'],r['line'],r['name']))
    return {'version':1,'controls':controls,'parse_errors':errors}


def main():
    result=build()
    target=ROOT/'PacsClient/utils/secretary_ui_source_catalog.py'
    target.write_text('"""Generated source inventory; regenerate with tools/dev/build_secretary_ui_catalog.py.\n'
        'Discovery is not execution availability. No live values are retained.\n"""\n'
        +'SOURCE_CATALOG = '+repr(result)+'\n',encoding='utf-8')
    doc=ROOT/'docs/agent_control/SECRETARY_UI_SOURCE_INVENTORY.md'
    lines=['# Secretary UI source inventory','',
        'Generated from static Qt declarations. Source references and callbacks are documentation, never executable commands.',
        'Dynamic factories, computed options and absent labels require live inspection. Discovered controls are not automatically MCP actions.',
        'Sensitive controls remain local-only. Actual execution is defined by registered typed CommandBus capabilities.','',
        '| Source / line | Field or action | Widget | Label / purpose | Static dropdown options | Constraints | Callback |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    def cell(value):return str(value).replace('|','/').replace('\n',' ')[:260]
    for r in result['controls']:
        label='LOCAL ONLY' if r['sensitive'] else (r['label'] or r.get('setAccessibleName') or r.get('setToolTip') or r.get('setPlaceholderText') or 'Live inspection required')
        lines.append('| '+ ' | '.join(cell(v) for v in (r['source']+':'+str(r['line']),r['name'],r['kind'],label,', '.join(r['options']),json.dumps(r['constraints']),', '.join(r['callbacks'])))+' |')
    lines.extend(['','Parse gaps: '+json.dumps(result['parse_errors'])])
    doc.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'controls':len(result['controls']),'source_files':len(source_paths()),'parse_errors':result['parse_errors']}))


if __name__=='__main__':main()
