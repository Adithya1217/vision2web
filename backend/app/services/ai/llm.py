"""Optional Claude-backed intent extraction.

Enabled only when ``MSME_ANTHROPIC_API_KEY`` is set. The model returns a ``ParsedIntent`` via structured
outputs; any error, refusal or invalid output falls back to the deterministic rule parser. The model never
sees database contents and never performs actions.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.ai.parser import ParsedIntent

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
    if not settings.anthropic_api_key:
        return None
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
