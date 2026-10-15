"""Tests for the one part of the app that talks to a model.

No network, no API key: the Anthropic client is replaced with a stub that
returns a canned tool-use block. That proves everything around the model call
is right — the tool schema, turning its reply into a Netlist, and what happens
when it misbehaves. Whether the model can actually *read a schematic* is a
question only a real call can answer; see README, "Testing the model".
"""

from __future__ import annotations

import pytest

from app import llm
from app.models import ComponentKind, Netlist


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Response:
    def __init__(self, content):
        self.content = content


def _stub_client(response, recorder=None):
    class Messages:
        def create(self, **kwargs):
            if recorder is not None:
                recorder.update(kwargs)
            return response

    class Client:
        messages = Messages()

    return Client()


GOOD_NETLIST = {
    "title": "Divider",
    "nets": [{"name": "VIN", "role": "input"}, {"name": "GND", "role": "ground"}],
    "components": [
        {"ref": "R1", "kind": "resistor", "value": "10k", "pins": {"1": "VIN", "2": "MID"}},
        {"ref": "R2", "kind": "resistor", "value": "10k", "pins": {"1": "MID", "2": "GND"}},
    ],
    "warnings": ["R2's value was blurry"],
}


def test_a_tool_use_reply_becomes_a_netlist(monkeypatch):
    response = _Response([_Block(type="tool_use", name="emit_netlist", input=GOOD_NETLIST)])
    monkeypatch.setattr(llm, "_client", lambda: _stub_client(response))

    netlist = llm.extract_netlist(b"\x89PNG fake bytes", "image/png")

    assert isinstance(netlist, Netlist)
    assert [c.ref for c in netlist.components] == ["R1", "R2"]
    assert netlist.components[0].kind is ComponentKind.RESISTOR
    assert netlist.components[0].pins["2"] == "MID"
    assert netlist.warnings == ["R2's value was blurry"]


def test_the_image_and_the_hint_both_reach_the_model(monkeypatch):
    sent: dict = {}
    response = _Response([_Block(type="tool_use", name="emit_netlist", input=GOOD_NETLIST)])
    monkeypatch.setattr(llm, "_client", lambda: _stub_client(response, sent))

    llm.extract_netlist(b"bytes", "image/jpeg", hint="U1 is a TL072")

    content = sent["messages"][0]["content"]
    image = next(b for b in content if b["type"] == "image")
    text = next(b for b in content if b["type"] == "text")
    assert image["source"]["media_type"] == "image/jpeg"
    assert image["source"]["data"], "the image is sent base64-encoded"
    assert "TL072" in text["text"]
    assert sent["tool_choice"] == {"type": "tool", "name": "emit_netlist"}


def test_a_chatty_reply_with_no_netlist_is_an_error(monkeypatch):
    response = _Response([_Block(type="text", text="I can't quite make out this schematic.")])
    monkeypatch.setattr(llm, "_client", lambda: _stub_client(response))

    with pytest.raises(llm.LLMError, match="did not return a netlist"):
        llm.extract_netlist(b"bytes")


def test_a_malformed_netlist_is_rejected_rather_than_half_placed(monkeypatch):
    broken = {"title": "x", "nets": [], "components": [{"ref": "R1", "kind": "flux_capacitor", "pins": {}}]}
    response = _Response([_Block(type="tool_use", name="emit_netlist", input=broken)])
    monkeypatch.setattr(llm, "_client", lambda: _stub_client(response))

    with pytest.raises(Exception):  # pydantic ValidationError
        llm.extract_netlist(b"bytes")


def test_missing_api_key_says_so_in_plain_words(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
        llm._client()


def test_the_tool_schema_covers_every_component_kind():
    """If a kind is added to the models, the model has to be told about it."""
    schema = llm.NETLIST_TOOL["input_schema"]
    kinds = schema["properties"]["components"]["items"]["properties"]["kind"]["enum"]
    assert set(kinds) == {k.value for k in ComponentKind}
