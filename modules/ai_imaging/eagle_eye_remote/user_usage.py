"""Version-2 human access audits, distinct from legacy token accounting."""
import math


def validate_user_usage(value):
    if (not isinstance(value, dict) or value.get('version') != 2
            or value.get('scope') != 'this_user'):
        raise ValueError('The server does not support human-scoped usage version 2.')
    counts, events = value.get('counts'), value.get('events')
    if (not isinstance(counts, list) or len(counts) > 4096
            or not isinstance(events, list) or len(events) > 100):
        raise ValueError('Invalid human usage audit.')
    for row in counts + events:
        if not isinstance(row, dict):
            raise ValueError('Invalid human usage row.')
        if any(not isinstance(row.get(k), str) or not 0 < len(row[k]) <= limit
               for k, limit in (('operation', 128), ('outcome', 4096))):
            raise ValueError('Invalid human usage labels.')
    if any(type(row.get('requests')) is not int or row['requests'] < 0 for row in counts):
        raise ValueError('Invalid human usage counts.')
    if any(type(row.get('occurred_at')) not in (int, float)
           or not math.isfinite(row['occurred_at']) or row['occurred_at'] < 0 for row in events):
        raise ValueError('Invalid human usage timestamps.')
    return value
