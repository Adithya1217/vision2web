"""Optional LLM-backed intent extraction: Claude if ``MSME_ANTHROPIC_API_KEY`` is set, otherwise Gemini if
``MSME_GEMINI_API_KEY`` is set.

The model returns a ``ParsedIntent`` via structured output; any error, refusal or invalid output falls back
to the deterministic rule parser. The model only sees the command text, never database contents, and never
performs actions.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.config import get_settings
from app.services.ai.parser import Entities, Intent, ParsedIntent

log = logging.getLogger(__name__)

SYSTEM = """You convert a shopkeeper's short command (English or Hinglish) into a structured intent for an
Indian MSME shop dashboard. Extract only what the user said; never invent products, customers, amounts or
quantities. Product and customer names go into *_query fields exactly as spoken. Amounts are decimal strings
with two places. Intents: product_lookup, stock_receipt, stock_adjustment (manual_increase, manual_decrease,
damage, correction with counted_quantity), invoice_draft (items + optional customer), payment_record (amount,
method, customer or invoice number), khata_lookup (customer balance), report_summary (sales, top_products,
low_stock, out_of_stock, khata with a period), or unknown."""


def parse_with_llm(text: str) -> ParsedIntent | None:
    settings = get_settings()
    if settings.anthropic_api_key:
        return _parse_with_claude(text)
    if settings.gemini_api_key:
        return _parse_with_gemini(text)
    return None


def _parse_with_gemini(text: str) -> ParsedIntent | None:
    settings = get_settings()
    try:
        from google import genai
        from google.genai import types
    except ImportError:  # pragma: no cover - optional dependency
        log.warning("google-genai package not installed; using rule parser")
        return None
    # Gemini rejects deadlines under 10s (400 "deadline is too short"), so this is the minimum, in ms.
    client = genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(timeout=10_000))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_schema=_gemini_schema(),
        temperature=0,
    )
    # The free tier often answers "busy" (429/503) for one model while another is free, so try a second one.
    models = [settings.gemini_model, *([GEMINI_BACKUP_MODEL] if settings.gemini_model != GEMINI_BACKUP_MODEL else [])]
    for model in models:
        try:
            response = client.models.generate_content(model=model, contents=text, config=config)
            # Re-validate against our own model rather than trusting the provider's parsing.
            parsed = ParsedIntent.model_validate_json(response.text or "")
            parsed.source, parsed.confidence = "llm", 0.9
            return parsed
        except Exception as exc:  # quota, timeout, network, bad JSON: the rule parser is the fallback
            busy = getattr(exc, "code", None) in (429, 500, 502, 503, 504) or "Timeout" in exc.__class__.__name__
            log.warning("Gemini %s failed (%s %s)", model, exc.__class__.__name__, getattr(exc, "code", ""))
            if not busy:
                break
    log.warning("Gemini unavailable; using rule parser")
    return None


GEMINI_BACKUP_MODEL = "gemini-flash-latest"


class _GeminiIntent(BaseModel):
    """What Gemini fills in; confidence and source are ours to set."""

    intent: Intent
    entities: Entities


def _gemini_schema() -> dict:
    """Our JSON schema minus keywords Gemini rejects ("quantity > 0"); ParsedIntent re-checks them on the reply."""
    def strip(node: object) -> object:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "exclusiveMinimum"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(_GeminiIntent.model_json_schema())


def _parse_with_claude(text: str) -> ParsedIntent | None:
    settings = get_settings()
    try:
        import anthropic
    except ImportError:  # pragma: no cover - optional dependency
        log.warning("anthropic package not installed; using rule parser")
        return None
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=15.0, max_retries=1)
        response = client.messages.parse(
            model=settings.anthropic_model,
            max_tokens=2048,
            system=SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": text}],
            output_format=ParsedIntent,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return None
        parsed = response.parsed_output
        parsed.source = "llm"
        return parsed
    except anthropic.APIError as exc:
        log.warning("LLM intent parsing failed (%s); using rule parser", exc.__class__.__name__)
        return None
    except ValueError:
        return None
