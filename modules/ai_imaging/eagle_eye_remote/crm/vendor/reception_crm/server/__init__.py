"""Production server packaging for the Reception CRM mobile endpoint.

This subpackage contains only deployment concerns — configuration loading,
process lifecycle, logging, and the Windows service wrapper. It deliberately
holds no CRM knowledge and no tool logic; those live in ``reception_crm.core``
and are reached through the existing HTTP adapter.
"""

from .config import ServerConfig, load_server_config

__all__ = ["ServerConfig", "load_server_config"]
