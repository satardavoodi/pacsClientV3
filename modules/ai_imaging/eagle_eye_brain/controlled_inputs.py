"""Explicit MCP series selection; never infer clinical input verification."""
def select_brain_inputs(rows, inputs, *, lesions=False):
    if inputs.get('inputs_verified') is not True:
        raise ValueError('Explicit full-brain T1/FLAIR input verification is required.')
    def resolve(uid):
        found=[r for r in rows if r['series_uid']==uid and r['available']]
        if len(found)!=1:
            raise ValueError('Each requested series must be uniquely available in this examination.')
        return dict(found[0])
    first=resolve(str(inputs.get('t1_series_uid') or ''))
    flair_uid=str(inputs.get('flair_series_uid') or '')
    if lesions and not flair_uid:
        raise ValueError('Lesion analysis requires a distinct 3D FLAIR series.')
    second=resolve(flair_uid) if flair_uid else None
    if second and first['series_uid']==second['series_uid']:
        raise ValueError('T1 and FLAIR must be distinct series.')
    return first,second
