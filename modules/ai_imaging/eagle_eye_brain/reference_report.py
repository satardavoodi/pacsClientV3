"""Only the active published reference can add report pages."""


def pages(reference):
    if reference.get('reference_id') == 'volbrain' and reference.get('status') == 'published_intervals':
        from .volbrain_reference import pages as published_pages
        return published_pages(reference)
    return []
