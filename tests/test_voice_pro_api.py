"""Voice-Pro's HTTP contract with real file encoding and a stand-in speech model."""
import io
import wave
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from apps import openai_speech as api


class SpeechModel:
    backend = "onnx"

    def __init__(self):
        self._preset_voices = {"Trúc Ly": {"gender": "female"}}
        self._voice_aliases = {}

    def resolve_voice_name(self, name):
        return name if name in self._preset_voices else self._voice_aliases.get(name)

    def infer_stream(self, text, **kwargs):
        if text == "fail":
            raise RuntimeError("private model failure")
        if text == "empty":
            return
        samples = np.arange(48_000) / 48_000
        yield (0.1 * np.sin(2 * np.pi * 440 * samples)).astype(np.float32)

    def add_voice(self, name, path, **kwargs):
        self._preset_voices[name] = {"speaker_emb": np.ones(192), "codes": np.ones((2, 16), dtype=int)}


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("VIENEU_VOICE_PRO_ENABLED", "1")
    monkeypatch.setenv("VIENEU_API_KEY", "test-key")
    monkeypatch.setenv("VIENEU_HOME", str(tmp_path))
    monkeypatch.setattr(api, "Vieneu", lambda **kwargs: SpeechModel())
    monkeypatch.setattr(api, "ENGINE", None)
    return tmp_path


@pytest.fixture
def client(configured):
    with TestClient(api.app, headers={"Authorization": "Bearer test-key"}) as client:
        yield client


def test_voice_pro_can_discover_controls_and_stable_voice_ids(client):
    response = client.get("/v1/tts/capabilities")
    assert response.status_code == 200
    capability = response.json()
    assert capability["formats"] == ["mp3", "wav", "flac"]
    assert capability["controls"]["pitch"]["unit"] == "cent"
    assert capability["max_text_chars"] == 20_000
    voice = client.get("/v1/voices").json()["data"][0]
    assert (voice["id"], voice["locale"]) == ("Trúc Ly", "vi-VN")


def test_synthesis_returns_a_complete_decodable_file(client):
    response = client.post("/v1/tts", json={"text": "Xin chào", "voice": "Trúc Ly", "format": "wav"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert int(response.headers["content-length"]) == len(response.content)
    with wave.open(io.BytesIO(response.content)) as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getnframes()) == (48_000, 1, 48_000)


def test_enrolled_voice_id_survives_restart_and_name_remains_an_alias(configured, monkeypatch):
    with TestClient(api.app, headers={"Authorization": "Bearer test-key"}) as client:
        response = client.post("/v1/voices", data={"name": "My voice"},
                               files={"file": ("reference.wav", b"RIFF", "audio/wav")})
        assert response.status_code == 200
        voice_id = response.json()["id"]
    assert voice_id.startswith("usr_")
    monkeypatch.setattr(api, "ENGINE", None)
    with TestClient(api.app, headers={"Authorization": "Bearer test-key"}) as restarted:
        voices = restarted.get("/v1/voices").json()["data"]
        assert any(v["id"] == voice_id and v["name"] == "My voice" for v in voices)
        for voice in (voice_id, "My voice"):
            result = restarted.post("/v1/tts", json={"text": "Xin chào", "voice": voice, "format": "wav"})
            assert result.status_code == 200


def test_openai_client_can_request_a_finalized_wav(client):
    response = client.post("/v1/audio/speech", json={"input": "Xin chào", "stream": False})
    assert response.status_code == 200
    with wave.open(io.BytesIO(response.content)) as audio:
        assert audio.getnframes() == 48_000


@pytest.mark.parametrize("fmt,mime", [("mp3", "audio/mpeg"), ("flac", "audio/flac")])
def test_compressed_formats_decode_to_standard_audio(client, fmt, mime):
    response = client.post("/v1/tts", json={"text": "Xin chào", "voice": "Trúc Ly", "format": fmt})
    assert response.status_code == 200
    assert response.headers["content-type"] == mime
    audio, sample_rate = sf.read(io.BytesIO(response.content))
    assert sample_rate == 48_000 and len(audio) > 40_000


def test_controls_change_audio_without_relabeling_pitch_as_hz(client):
    def synthesize(**controls):
        response = client.post("/v1/tts", json={"text": "Xin chào", "voice": "Trúc Ly", "format": "wav", **controls})
        assert response.status_code == 200
        return sf.read(io.BytesIO(response.content))[0]

    fast = synthesize(rate=100)
    assert abs(len(fast) / 48_000 - 0.5) < 0.05
    shifted = synthesize(pitch=400)
    assert abs(len(shifted) / 48_000 - 1) < 0.05
    frequencies = np.fft.rfftfreq(len(shifted), 1 / 48_000)
    peak = frequencies[np.argmax(np.abs(np.fft.rfft(shifted)))]
    assert abs(peak - 554.37) < 5
    muted = synthesize(volume=-100)
    assert len(muted) == 48_000 and np.max(np.abs(muted)) == 0


@pytest.mark.parametrize("extra", [
    {"rate": -100}, {"rate": "10"}, {"rate": True}, {"pitch": 401},
    {"format": "MP3"}, {"volume": None}, {"max_chars": 63}, {"temperature": float("nan")},
    {"text": "   "}, {"ssml": True}, {"voice": None},
])
def test_invalid_controls_are_json_errors_before_any_audio(client, extra):
    body = json.dumps({"text": "Xin chào", "voice": "Trúc Ly", **extra})
    response = client.post("/v1/tts", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/json"
    assert isinstance(response.json()["error"]["code"], str)
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize("text,code", [("fail", "synthesis_failed"), ("empty", "invalid_audio")])
def test_model_failures_return_json_and_leave_capacity_available(client, text, code):
    response = client.post("/v1/tts", json={"text": text, "voice": "Trúc Ly"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == code
    assert "private model failure" not in response.text
    assert client.post("/v1/tts", json={"text": "Xin chào", "voice": "Trúc Ly"}).status_code == 200


def test_voice_pro_requires_bearer_key(client):
    for endpoint in ("/v1/tts/capabilities", "/v1/voices"):
        response = client.get(endpoint, headers={"Authorization": "Bearer incorrect"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_api_key"


def test_character_and_body_limits_are_distinct(configured, monkeypatch):
    monkeypatch.setenv("VIENEU_MAX_TEXT_CHARS", "3")
    monkeypatch.setenv("VIENEU_MAX_REQUEST_BYTES", "256")
    with TestClient(api.app, headers={"Authorization": "Bearer test-key"}) as client:
        assert client.post("/v1/tts", json={"text": "Việt", "voice": "Trúc Ly"}).json()["error"]["code"] == "text_too_long"
        assert client.post("/v1/tts", json={"text": "Việ", "voice": "Trúc Ly"}).status_code == 200
        response = client.post("/v1/tts", content=b" " * 257, headers={"Content-Type": "application/json"})
        assert response.status_code == 413 and response.json()["error"]["code"] == "request_too_large"


def test_accept_and_media_type_are_enforced(client):
    body = {"text": "Xin chào", "voice": "Trúc Ly"}
    assert client.post("/v1/tts", json=body, headers={"Accept": "audio/wav"}).status_code == 406
    assert client.post("/v1/tts", json=body, headers={"Accept": "audio/mpeg;q=0,*/*;q=1"}).status_code == 406
    assert client.post("/v1/tts", content="text", headers={"Content-Type": "text/plain"}).status_code == 415


def test_audio_limit_failure_releases_capacity(configured, monkeypatch):
    monkeypatch.setenv("VIENEU_MAX_OUTPUT_BYTES", "100000")
    with TestClient(api.app, headers={"Authorization": "Bearer test-key"}) as client:
        body = {"text": "Xin chào", "voice": "Trúc Ly", "format": "wav", "rate": -50}
        response = client.post("/v1/tts", json=body)
        assert response.status_code == 413
        assert client.post("/v1/tts", json={**body, "rate": 0}).status_code == 200


def test_busy_requests_get_retry_after_and_do_not_stall_streaming(configured, monkeypatch):
    monkeypatch.setenv("VIENEU_QUEUE", "0")
    started, release = threading.Event(), threading.Event()
    original = SpeechModel.infer_stream

    def blocked(self, text, **kwargs):
        if text == "blocked":
            started.set()
            release.wait(5)
        yield from original(self, text, **kwargs)

    monkeypatch.setattr(SpeechModel, "infer_stream", blocked)
    with TestClient(api.app, headers={"Authorization": "Bearer test-key"}) as client:
        with ThreadPoolExecutor() as executor:
            pending = executor.submit(client.post, "/v1/tts", json={"text": "blocked", "voice": "Trúc Ly"})
            try:
                assert started.wait(3)
                response = client.post("/v1/tts", json={"text": "Xin chào", "voice": "Trúc Ly"})
                assert response.status_code == 429 and response.headers["retry-after"] == "2"
            finally:
                release.set()
            assert pending.result().status_code == 200
        assert client.post("/v1/audio/speech", json={"input": "Xin chào"}).status_code == 200


def test_deadline_retains_busy_slot_until_native_work_stops(configured, monkeypatch):
    monkeypatch.setenv("VIENEU_QUEUE", "0")
    monkeypatch.setenv("VIENEU_TTS_TIMEOUT", "1")
    release = threading.Event()
    original = SpeechModel.infer_stream

    def blocked(self, text, **kwargs):
        if text == "blocked":
            release.wait(5)
        yield from original(self, text, **kwargs)

    monkeypatch.setattr(SpeechModel, "infer_stream", blocked)
    with TestClient(api.app, headers={"Authorization": "Bearer test-key"}) as client:
        try:
            response = client.post("/v1/tts", json={"text": "blocked", "voice": "Trúc Ly"})
            assert response.status_code == 504
            assert client.post("/v1/tts", json={"text": "Xin chào", "voice": "Trúc Ly"}).status_code == 429
        finally:
            release.set()
        end = time.monotonic() + 3
        while client.get("/health").json()["active"] and time.monotonic() < end:
            time.sleep(0.02)
        assert client.post("/v1/tts", json={"text": "Xin chào", "voice": "Trúc Ly"}).status_code == 200


def test_unknown_voice_pro_route_still_returns_a_structured_error(client):
    response = client.get("/v1/tts/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_voice_enrollment_does_not_freeze_other_http_requests(client, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = SpeechModel.add_voice

    def blocked(self, *args, **kwargs):
        started.set()
        release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SpeechModel, "add_voice", blocked)
    with ThreadPoolExecutor(max_workers=3) as executor:
        upload = executor.submit(client.post, "/v1/voices", data={"name": "Concurrent"},
                                 files={"file": ("reference.wav", b"RIFF", "audio/wav")})
        try:
            assert started.wait(3)
            synthesis = executor.submit(client.post, "/v1/tts", json={"text": "Xin chào", "voice": "Trúc Ly"})
            time.sleep(0.1)
            discovery = executor.submit(client.get, "/v1/tts/capabilities")
            assert discovery.result(timeout=1).status_code == 200
            unknown = executor.submit(client.post, "/v1/tts", json={"text": "Xin chào", "voice": "missing"})
            assert unknown.result(timeout=1).status_code == 404
        finally:
            release.set()
        assert upload.result().status_code == 200
        assert synthesis.result().status_code == 200
