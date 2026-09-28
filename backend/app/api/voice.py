"""Sarvam speech-to-text and text-to-speech, proxied so the API key never reaches the browser.

When MSME_SARVAM_API_KEY is unset, /voice/status says so and the frontend uses the browser's built-in speech.
Any Sarvam failure is reported as 502, and the frontend falls back the same way.
"""

import base64
import logging

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.deps import Ctx, require
from app.core.errors import AppError, ValidationFailed
from app.core.permissions import P

log = logging.getLogger(__name__)
router = APIRouter()

MAX_AUDIO_BYTES = 3 * 1024 * 1024  # roughly a minute of compressed speech; commands are a few seconds
# Browser recorder formats → Sarvam codec names.
_CODECS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav",
           "audio/x-wav": "wav", "audio/aac": "aac", "audio/flac": "flac"}


class VoiceUnavailable(AppError):
    status_code = 503
    code = "voice_unavailable"


class VoiceFailed(AppError):
    status_code = 502
    code = "voice_failed"


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


def _client():
    settings = get_settings()
    if not settings.sarvam_api_key:
        raise VoiceUnavailable("Sarvam speech is not configured")
    from sarvamai import SarvamAI

    return SarvamAI(api_subscription_key=settings.sarvam_api_key)


_OPTS = {"timeout_in_seconds": 15, "max_retries": 1}


@router.get("/voice/status", tags=["voice"])
def status(ctx: Ctx = Depends(require(P.ai_use))):
    return {"sarvam": bool(get_settings().sarvam_api_key)}


@router.post("/voice/transcribe", tags=["voice"])
async def transcribe(request: Request, ctx: Ctx = Depends(require(P.ai_use))):
    """Raw recorded audio in the body (Content-Type e.g. audio/webm) → romanised text for the assistant."""
    audio = await request.body()
    if not audio:
        raise ValidationFailed("no audio received", code="empty_audio")
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValidationFailed("recording is too long; keep commands short", code="audio_too_long")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    codec = _CODECS.get(content_type)
    if codec is None:
        raise ValidationFailed(f"unsupported audio type '{content_type}'", code="unsupported_audio")
    client = _client()
    try:
        result = client.speech_to_text.transcribe(
            file=(f"command.{codec}", audio, content_type),
            model=get_settings().sarvam_stt_model,
            # Roman script: "ramesh ko do sabun" is what the parser and LLMs read best.
            mode="translit",
            language_code="unknown",
            input_audio_codec=codec,
            request_options=_OPTS,
        )
    except Exception as exc:
        log.warning("Sarvam transcription failed (%s)", exc.__class__.__name__)
        raise VoiceFailed("speech service failed; try again or type the command") from exc
    return {"text": (result.transcript or "").strip(), "language": result.language_code}


@router.post("/voice/speak", tags=["voice"])
def speak(data: SpeakIn, ctx: Ctx = Depends(require(P.ai_use))):
    """Text → MP3 audio."""
    settings = get_settings()
    client = _client()
    options = {"speaker": settings.sarvam_tts_speaker} if settings.sarvam_tts_speaker else {}
    try:
        result = client.text_to_speech.convert(
            text=data.text,
            language_code=settings.sarvam_tts_language,
            model=settings.sarvam_tts_model,
            output_audio_codec="mp3",
            request_options=_OPTS,
            **options,
        )
        # Long text comes back as several clips; decode each (joining base64 strings would corrupt padding).
        audio = b"".join(base64.b64decode(clip) for clip in result.audios)
    except Exception as exc:
        log.warning("Sarvam speech synthesis failed (%s)", exc.__class__.__name__)
        raise VoiceFailed("speech service failed") from exc
    return Response(content=audio, media_type="audio/mpeg")
