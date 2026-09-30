import requests


class UpstreamError(requests.RequestException):
    """Safe machine-readable failure; never stores upstream bodies or credentials."""
    def __init__(self, status):
        self.status = status
        super().__init__("EchoMind provider rejected the request")
