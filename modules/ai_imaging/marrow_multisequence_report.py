"""Portable full-stack marrow signal report, shared by HTML and existing PDF export."""
import html
from pathlib import Path


def number(value):
    return 'Unavailable' if value is None else f'{value:,.1f}'


def report_html(result):
    rows=result.get('marrow_measurements',[])
    drop=result.get('map_kind')=='in_opposed_signal_drop'
    metric='Signal drop %' if drop else 'Signal FF %'
    prefix='signal_drop' if drop else 'signal_ff'
    table=''
    signals=''
    echoes=''
    sensitivity=''
    for r in rows:
        values=[r['level'],number(r['body_volume_mm3']/1000),str(r['spatial_slices']),
                number(r['sample_volume_mm3']/1000),number(r.get(prefix+'_median_percent')),
                number(r.get(prefix+'_p10_percent'))+'–'+number(r.get(prefix+'_p90_percent'))]
        table+='<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in values)+'</tr>'
        for role in ('t1','t2','stir'):
            measurement=r.get(role+'_signal')
            if measurement:
                vals=[r['level'],role.upper(),str(measurement['sample_voxels']),number(measurement['median_si']),number(measurement['mean_si'])]
                signals+='<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>'
        for e in r.get('echo_measurements',[]):
            ranges=e.get('predicted_dixon_signal_ranges')
            if ranges:
                vals=[r['level'],number(100*e['dixon_signal_percentiles'][1]),
                      '–'.join(number(100*x) for x in ranges[0]),'–'.join(number(100*x) for x in ranges[1]),
                      'Low-fat' if e.get('conditional_t1_supported_branch')==0 else 'High-fat' if e.get('conditional_t1_supported_branch')==1 else 'Unresolved']
                sensitivity+='<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>'
            for i,b in enumerate(e['branches']):
                supported=e.get('dixon_supported_branch')==i
                values=[r['level'],str(e['plane_index']+1),'Low-fat' if i==0 else 'High-fat',
                    number(100*b['fat_signal_fraction']),number(b['r2star_s_inverse']),number(b['t2star_ms']),
                    number(b['relative_rmse_percent']), 'Dixon-supported candidate' if supported else e['selection'].replace('_',' ')]
                echoes+='<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in values)+'</tr>'
    identity=result.get('patient_context',{})
    identification=' | '.join(str(identity[k]) for k in ('patient_name','patient_id','study_date') if identity.get(k)) or 'Identity pending authenticated job binding'
    page='<!--EAGLE_BRAIN_PAGE-->'
    def image(key,width=600):
        path=result.get(key)
        if not path or not Path(path).is_file():
            return ''
        from PIL import Image
        with Image.open(path) as source:
            height=round(width*source.height/source.width)
        return '<p style="line-height:100%;margin:0"><img width="'+str(width)+'" height="'+str(height)+'" src="'+html.escape(Path(path).as_uri())+'"></p>'
    acquisition=result.get('acquisition',{})
    roles=', '.join(result.get('input_roles',[]))
    optional=result.get('optional_inputs',{})
    content=('<html><head><meta name="brain-patient" content="'+html.escape(identification,quote=True)+'">'
        '<style>body{font-family:Arial;font-size:11pt;line-height:1.5}td,th{padding:8px;border:1px solid #c5ced8}th{background:#e2e8f0}table{border-collapse:collapse;width:100%}</style></head><body>'
        '<h1>Lumbar Bone Marrow</h1><h2>Full-stack T1 / T2 / Dixon signal evaluation</h2>'
        '<p>Inputs: '+html.escape(roles)+'. STIR: '+optional.get('stir','not recorded')+'; multi-echo: '+optional.get('multiecho','not recorded')+'.</p>'
        '<p>Research draft • Physician review required</p><p>'+html.escape(identification)+'</p>'
        '<p>Dixon spatial slices: '+str(acquisition.get('dixon_spatial_slices',''))+
        '; multi-echo acquired spatial planes: '+str(acquisition.get('multiecho_spatial_planes',''))+'.</p>'
        '<h3>Vertebral-body measurements</h3><table><tr><th>Level</th><th>Body cm³</th><th>Body slices</th><th>Interior ROI cm³</th><th>'+metric+'</th><th>P10–P90 %</th></tr>'+table+'</table>'
        '<p>Body masks combine MR body segmentation with per-level vertebra labels. Signal statistics use a 2 mm interior margin; all acquired slices contribute. Confirm boundaries, coverage and numbering. Volume represents sampled acquisition geometry; incomplete field of view is not a complete anatomical volume.</p>'
        '<h3>Color map</h3><p>'+('In/opposed-phase signed signal drop = 100 × (IP−OP)/IP; not fat fraction. Display colors saturate at 0 and 100%; table retains signed values. ' if drop else '')+'Purple → yellow: continuous low → high displayed signal metric (0–100%). Color is confined to the candidate vertebral bodies. It does not label red marrow, edema or tumor.</p>'+page+image('preview',400)+page+image('overview_preview')+page+
        '<h3>Multi-echo decay and competing fat solutions</h3><table><tr><th>Level</th><th>Plane</th><th>Branch</th><th>Fitted fat signal %</th><th>R2* s⁻¹</th><th>T2* ms</th><th>Error %</th><th>Dixon comparison</th></tr>'+echoes+'</table>'
        '<p>Both branches remain visible. Error = RMSE / maximum observed echo signal. Multi-echo measurements apply only to acquired planes.</p>'
        +page+'<h3>Can Dixon distinguish the two solutions?</h3><table><tr><th>Level</th><th>Observed Dixon % (echo plane)</th><th>Predicted Dixon %: low branch</th><th>Predicted Dixon %: high branch</th><th>Conditional support</th></tr>'+sensitivity+'</table>'
        '<p>Predictions use the actual TR/flip angles and an exploratory spoiled-GRE steady-state sensitivity calculation: fat T1 150–500 ms; water T1 400–2000 ms; water T1 at least fat T1. These are assumed ranges, not measured T1 values or normal-reference limits. Differential R2*, B1 and vendor reconstruction bias are not corrected. Iron-related water-T1 shortening can invalidate the assumption. A supported branch is therefore conditional, not a calibrated PDFF result. Alignment must be reviewed before the branch is selected.</p>'
        '<h3>Measurement meaning</h3><p>Signal FF = F/(F+W), not a fat-cell volume fraction or a PDFF map. Water signal includes multiple tissues. The six-peak magnitude fit uses a common R2*, Gaussian ROI-mean residuals and no T1/noise-floor correction. Neither output directly quantifies hematopoietic cells or iron concentration.</p>'
        '<h3>Native sequence signals</h3><table><tr><th>Level</th><th>Sequence</th><th>Sample voxels</th><th>Median SI</th><th>Mean SI</th></tr>'+signals+'</table><p>Arbitrary signal units; DICOM-coordinate mask transfer only. Inspect alignment. STIR signal is not an edema-volume classifier.</p>'
        '<h3>Physician notes</h3><p>'+html.escape(result.get('physician_notes','') or 'Not entered').replace('\n','<br>')+'</p></body></html>')

    if not echoes and result.get('parameters',{}).get('input_protocol') == 2:
        start=content.index('<h3>Multi-echo decay')
        end=content.index('<h3>Measurement meaning')
        content=content[:start]+'<p>Multi-echo was not acquired; core T1/T2/Dixon evaluation completed.</p>'+content[end:]
    elif echoes and not sensitivity:
        start=content.index('<h3>Can Dixon distinguish')
        end=content.index('<h3>Measurement meaning')
        content=content[:start]+'<p>No matched fat/water reconstruction prior; both echo solutions retained.</p>'+content[end:]
    return content
