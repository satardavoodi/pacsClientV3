"""Qt-free half of AiPacs Chat.

NOTHING IN THIS PACKAGE MAY IMPORT PySide6. That is the whole point of it
being a package: the cursor arithmetic, the cadence curve, the cold-resync
rule and the request-ordering guard are the parts most likely to be wrong and
most expensive to debug through a GUI, so they are written where a plain
pytest run can exercise them.

The web console's own split between ``Services\\CaseSync`` (protocol) and its
views is what kept that codebase maintainable for a year. This mirrors it.
"""
