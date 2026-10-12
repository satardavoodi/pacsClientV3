"""The adapter's transport edge: what happens to a request we cannot read.

There is one property here, and it is not about JSON. A request that cannot be
parsed must produce a REPLY. When `read_json` raised, `BaseHTTPRequestHandler`
wrote no response and `log_message` is deliberately a no-op, so the caller saw
the socket close and the service log said nothing at all — which is exactly what
a crashed server looks like from the outside. It cost a real debugging session
looking through a log that had nothing wrong in it.

The second property: a body we could not read must never come back as an empty
dict. The endpoint would then run on arguments the caller never sent and answer
as though it had been asked something.
"""

from __future__ import annotations

import io

import pytest

from reception_crm.adapters.http_api import BadRequest, HttpApiHandler, MAX_JSON_BODY_BYTES


class Body:
    """A handler stand-in carrying just a body — what `read_json` reads."""

    def __init__(self, raw: bytes, *, content_length: str | None = None):
        self.rfile = io.BytesIO(raw)
        length = str(len(raw)) if content_length is None else content_length
        self.headers = {"Content-Length": length}

    def read(self):
        return HttpApiHandler.read_json(self)


def test_a_well_formed_body_is_read():
    assert Body('{"text": "سلام"}'.encode("utf-8")).read() == {"text": "سلام"}


def test_an_empty_body_is_an_empty_object():
    """Several endpoints take no arguments. Sending nothing is legitimate."""
    assert Body(b"").read() == {}


def test_a_body_that_is_not_utf8_is_a_client_error():
    """The failure that started this: Windows PowerShell sent Persian as
    mangled bytes, the decode raised, and the connection simply closed."""
    # Persian encoded in a single-byte Windows codepage: every letter becomes
    # one byte in 0xC8-0xEC, and 0xC8 then starts a UTF-8 sequence whose
    # "continuation" byte is another letter. Written as literal bytes rather
    # than via .encode() so the test does not depend on a codec table.
    with pytest.raises(BadRequest) as caught:
        Body(b'{"title": "\xc8\xd1\xd1\xd3\xed"}').read()
    assert "UTF-8" in str(caught.value)


def test_a_body_that_is_not_json_is_a_client_error():
    with pytest.raises(BadRequest):
        Body(b"not json at all").read()


def test_a_json_body_that_is_not_an_object_is_a_client_error():
    for raw in (b"[1, 2, 3]", b'"just a string"', b"42"):
        with pytest.raises(BadRequest):
            Body(raw).read()


def test_a_nonsense_content_length_is_a_client_error():
    with pytest.raises(BadRequest):
        Body(b"{}", content_length="banana").read()


def test_a_negative_content_length_does_not_raise_from_the_socket():
    """`rfile.read(-1)` reads to EOF, which on a live socket blocks until the
    client goes away. Clamp rather than pass it through."""
    assert Body(b"", content_length="-5").read() == {}


def test_an_oversized_body_is_rejected_before_it_is_read():
    with pytest.raises(BadRequest, match="24 MB"):
        Body(b"", content_length=str(MAX_JSON_BODY_BYTES + 1)).read()


def test_the_error_never_quotes_the_body():
    """A malformed body can still carry a national code, and this message is
    written into a response."""
    with pytest.raises(BadRequest) as caught:
        Body(b'{"nationalCode": "0079123456"').read()
    assert "0079123456" not in str(caught.value)


def test_the_router_answers_400_instead_of_dropping_the_connection():
    """The whole point: `do_POST` catches it and replies."""

    class Handler:
        path = "/api/agent/command"
        sent: list = []

        def route_post(self):
            raise BadRequest("Body is not valid UTF-8.")

        def respond_json(self, body, status=None):
            self.sent.append((status, body))

    handler = Handler()
    HttpApiHandler.do_POST(handler)

    status, body = handler.sent[0]
    assert status.value == 400
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION"


def test_a_real_fault_is_still_a_real_fault():
    """Only BadRequest is turned into a 400. A genuine server error must NOT be
    quietly relabelled as the caller's mistake."""

    class Handler:
        def route_post(self):
            raise RuntimeError("something is actually broken")

        def respond_json(self, body, status=None):  # pragma: no cover - not reached
            raise AssertionError("a server fault was reported as a client error")

    with pytest.raises(RuntimeError):
        HttpApiHandler.do_POST(Handler())
