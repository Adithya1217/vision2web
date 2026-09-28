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
        self.models_tried = [*getattr(self, "models_tried", []), model]
        reply = self.reply(model) if callable(self.reply) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return type("Response", (), {"text": reply})()


@pytest.fixture
def gemini(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    def use(reply):
        fake = _FakeModels(reply)
        monkeypatch.setattr(genai, "Client", lambda **_: type("C", (), {"models": fake})())
        return fake

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


class _Busy(Exception):
    code = 503


def test_busy_model_retries_backup_model(gemini):
    ok = json.dumps({"intent": "report_summary", "entities": {"report": "sales", "period": "today"}})
    fake = gemini(lambda model: _Busy("high demand") if model == get_settings().gemini_model else ok)
    parsed = llm.parse_with_llm("aaj kitna becha")
    assert parsed.intent == "report_summary"
    assert fake.models_tried == [get_settings().gemini_model, llm.GEMINI_BACKUP_MODEL]


def test_non_busy_error_does_not_retry(gemini):
    fake = gemini(ValueError("bad request"))
    assert llm.parse_with_llm("anything") is None and len(fake.models_tried) == 1
