"""PySide6 only. No HTTP, no threads, no dataclass construction.

Widgets talk to ``qt.repository.ChatRepository`` and to nothing else. If a
widget needs something from the server, the repository grows a slot and a
signal — it does not grow an import of ``requests``.
"""
