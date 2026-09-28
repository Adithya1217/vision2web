import base64

import pytest

from app.api import voice
from app.config import get_settings


class _Fake:
    """Stands in for the Sarvam client; records calls, or fails when told to."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail
        self.speech_to_text, self.text_to_speech = self, self

    def transcribe(self, **kw):
        self.calls.append(("stt", kw))
        if self.fail:
            raise RuntimeError("sarvam down")
        return type("R", (), {"transcript": " ramesh ko do sabun ", "language_code": "hi-IN"})()

    def convert(self, **kw):
        self.calls.append(("tts", kw))
        if self.fail:
            raise RuntimeError("sarvam down")
        clips = [base64.b64encode(b"ID3-part1").decode(), base64.b64encode(b"-part2").decode()]
        return type("R", (), {"audios": clips})()


@pytest.fixture
def sarvam(monkeypatch):
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "test-key")

    def use(fake):
        monkeypatch.setattr(voice, "_client", lambda: fake)
        return fake

    return use


def _post_audio(api, body: bytes, content_type="audio/webm;codecs=opus"):
    headers = {"Content-Type": content_type, **api._headers()}
    return api.client.post("/api/v1/voice/transcribe", content=body, headers=headers)


def test_status_reflects_configuration(owner, monkeypatch):
    monkeypatch.setattr(get_settings(), "sarvam_api_key", None)
    assert owner.ok(owner.get("/voice/status")) == {"sarvam": False}
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "k")
    assert owner.ok(owner.get("/voice/status")) == {"sarvam": True}


def test_transcribe_returns_romanised_text(owner, sarvam):
    fake = sarvam(_Fake())
    r = _post_audio(owner, b"\x1aE\xdf\xa3fake-webm")
    assert r.status_code == 200 and r.json() == {"text": "ramesh ko do sabun", "language": "hi-IN"}
    kw = fake.calls[0][1]
    assert kw["mode"] == "translit" and kw["input_audio_codec"] == "webm" and kw["file"][1].startswith(b"\x1aE")


def test_speak_returns_mp3_from_all_clips(owner, sarvam):
    sarvam(_Fake())
    r = owner.client.post("/api/v1/voice/speak", json={"text": "New sale. Total ₹294.00."}, headers=owner._headers())
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3-part1-part2"


def test_bad_input_rejected_before_calling_sarvam(owner, sarvam):
    fake = sarvam(_Fake())
    assert _post_audio(owner, b"").status_code == 422
    assert _post_audio(owner, b"x" * (voice.MAX_AUDIO_BYTES + 1)).status_code == 422
    assert _post_audio(owner, b"abc", "video/avi").status_code == 422
    assert fake.calls == []


def test_sarvam_failure_reports_502_so_the_browser_falls_back(owner, sarvam):
    sarvam(_Fake(fail=True))
    assert _post_audio(owner, b"abc").status_code == 502
    assert owner.client.post("/api/v1/voice/speak", json={"text": "hi"}, headers=owner._headers()).status_code == 502


def test_missing_key_reports_503(owner, monkeypatch):
    monkeypatch.setattr(get_settings(), "sarvam_api_key", None)
    assert _post_audio(owner, b"abc").status_code == 503


def test_voice_requires_login(client):
    assert client.get("/api/v1/voice/status").status_code == 401
