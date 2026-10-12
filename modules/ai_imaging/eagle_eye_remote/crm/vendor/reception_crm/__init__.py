"""Reception CRM data collection and analytics package."""

__all__ = ["__version__"]

#: The one place the version is written.
#:
#: It had drifted to three answers — `0.1.0` here and in `pyproject.toml`,
#: `1.22.0` in the server installer — while `/api/health` published no version
#: at all. So the running server could not say which build it was, and every
#: "1.22.0 is deployed" in this project's notes rested on the filename of the
#: installer that had been copied over, not on anything the server itself said.
#:
#: That matters most exactly when it is least visible: a benchmark scores a
#: build, a defect is fixed in a build, and both records name a version that
#: nothing verified. `tests/test_version_identity.py` now refuses any commit
#: where this string, `pyproject.toml` and `installer/ReceptionCrmServer.iss`
#: disagree, and `/api/health` reports it.
#:
#: The desktop Agent installer is a separate product line with its own version
#: and is deliberately not tied to this one.
__version__ = "1.32.6"
