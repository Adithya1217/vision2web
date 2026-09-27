from fastapi import APIRouter, Depends

from app.core.deps import Ctx, require
from app.core.permissions import P
from app.schemas.ai import InterpretIn, InterpretOut
from app.services.ai import actions
from app.services.ai.llm import parse_with_llm
from app.services.ai.parser import ParsedIntent, parse

router = APIRouter()


@router.post("/ai/parse", response_model=ParsedIntent, tags=["ai"])
def parse_intent(data: InterpretIn, ctx: Ctx = Depends(require(P.ai_use))):
    """Parse text into an intent and entities only. Nothing is looked up or changed."""
    return (parse_with_llm(data.text) if data.use_llm else None) or parse(data.text)


@router.post("/ai/interpret", response_model=InterpretOut, tags=["ai"])
def interpret(data: InterpretIn, ctx: Ctx = Depends(require(P.ai_use))):
    """Read intents run immediately and return a result. Write intents return a proposal describing the
    normal API call(s) to make after the user confirms; this endpoint never modifies data."""
    return actions.interpret(ctx, data.text, data.use_llm)
