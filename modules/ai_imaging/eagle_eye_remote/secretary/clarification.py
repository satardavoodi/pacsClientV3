"""Bounded display-only choices; never executable actions or permissions."""
def validate_clarification(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'question', 'options'}:
        raise ValueError('Invalid clarification fields.')
    question=value['question']
    options=value['options']
    if not isinstance(question,str) or not question.strip() or len(question)>2000:
        raise ValueError('Invalid clarification question.')
    if not isinstance(options,list) or not 1<=len(options)<=3:
        raise ValueError('Invalid clarification option count.')
    seen=set()
    for option in options:
        if not isinstance(option,dict) or set(option)!={'id','label'}:
            raise ValueError('Invalid clarification option.')
        key=option['id']; label=option['label']
        if not isinstance(key,str) or not key or len(key)>40 or key in seen:
            raise ValueError('Invalid clarification option id.')
        if not isinstance(label,str) or not label.strip() or len(label)>240:
            raise ValueError('Invalid clarification label.')
        seen.add(key)
    return {'question':question,'options':[dict(o) for o in options]}
