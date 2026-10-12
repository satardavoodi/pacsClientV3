"""Public verification roots shipped with the application, never private keys.

Initial root provisioned on 2026-10-07 in a company-only Windows DPAPI store.
Additional authorized issuer roots must be provisioned separately and distributed
through reviewed application updates. Do not load roots from customer settings.
"""
TRUSTED_KEYS: dict[str, str] = {'f3f539a9abc96ef0': '1d0e48863d8fbde21c7d4c01adc473c5799ea7c5ba902e4f2057905152b54c5f'}
