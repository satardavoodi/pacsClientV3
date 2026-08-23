"""The bridge between the Qt-free services and the widgets.

Exactly two things live here: the worker that runs a blocking call off the GUI
thread, and the repository that owns those workers and turns their results into
signals. Nothing else in the module knows that threads exist — the services do
not import Qt, and the widgets never see an HTTP call or a QThread.

Import-cheap by contract: this package pulls PySide6, so nothing on the startup
path may import it. Only the tab factory does, and only when the operator
clicks.
"""
