import json

import pytest
from google import genai

from app.config import get_settings
from app.services.ai import llm


class _FakeModels:
    def __init__(self, reply):
        self.reply = reply

    def generate_content(self, *, model, contents, config):
        # The real SDK objects must accept what we send, so a bad schema or config fails here too.
        assert config.response_mime_type == "application/json" and config.response_schema is not None
        if isinstance(self.reply, Exception):
            raise self.reply
        return type("Response", (), {"text": self.reply})()


@pytest.fixture
def gemini(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    def use(reply):
        monkeypatch.setattr(genai, "Client", lambda **_: type("C", (), {"models": _FakeModels(reply)})())

    return use


def test_gemini_reply_is_used(gemini):
    gemini(json.dumps({"intent": "invoice_draft",
                       "entities": {"items": [{"query": "sabun", "quantity": 2}], "customer_query": "ramesh"}}))
    parsed = llm.parse_with_llm("ramesh ko do sabun")
    assert parsed.source == "llm" and parsed.intent == "invoice_draft"
    assert [(i.query, i.quantity) for i in parsed.entities.items] == [("sabun", 2)]


def test_gemini_reply_breaking_our_rules_falls_back(gemini):
    gemini(json.dumps({"intent": "invoice_draft", "entities": {"items": [{"query": "sabun", "quantity": 0}]}}))
    assert llm.parse_with_llm("anything") is None  # caller then uses the rule parser


def test_gemini_outage_falls_back_to_rules(gemini, owner):
    gemini(RuntimeError("429 quota exceeded"))
    out = owner.ok(owner.post("/ai/interpret", {"text": "received 20 atta"}))
    assert out["source"] == "rules" and out["intent"] == "stock_receipt"
