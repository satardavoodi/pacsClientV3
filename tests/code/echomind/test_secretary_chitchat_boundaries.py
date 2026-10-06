"""Conversation shortcuts must never consume operational instructions."""
import pytest
from modules.EchoMind.secretary.parser_rules import is_chitchat

@pytest.mark.parametrize("text", [
    "Filter brain MRI studies and sort by image quantity",
    "Hello, select the first and third patients",
    "Thanks, open the CD configuration",
    "Show image quality settings",
    "Check system capabilities and errors",
])
def test_operational_text_is_not_conversation(text):
    assert is_chitchat(text) == (False, "")

@pytest.mark.parametrize("text", ["Hello!", "thank you", "okay", "good morning", "what can you do?"])
def test_standalone_conversation_remains_supported(text):
    assert is_chitchat(text)[0]
