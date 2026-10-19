"""Local checkpoint profiles exercised through startup and the HTTP interface."""
import io
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
import yaml

from apps import openai_speech as api


class LocalSpeechModel:
    backend = "pytorch"

    def __init__(self, *, backbone_repo, model_subfolder, **kwargs):
        root = Path(backbone_repo)
        config = json.loads((root / model_subfolder / "config.json").read_text())
        voices = json.loads((root / "voices_v3_turbo.json").read_text())
        self._preset_voices = {"unrelated-base-voice": {}, **voices["presets"]}
        self._default_voice = voices["default_voice"]
        self._voice_aliases = {}
        self.frequency = config["test_frequency"]

    def resolve_voice_name(self, name):
        return name if name in self._preset_voices else self._voice_aliases.get(name)

    def _get_stream_scheduler(self):
        raise AssertionError("A nonstreaming profile must not initialize a stream scheduler")

    def infer_stream(self, *args, **kwargs):
        raise AssertionError("A nonstreaming profile must use complete inference")

    def infer(self, text, **kwargs):
        return (0.1 * np.sin(2 * np.pi * self.frequency * np.arange(48_000) / 48_000)).astype(np.float32)


@pytest.fixture
def local_profile(monkeypatch, tmp_path):
    checkpoint = tmp_path / "models" / "alan" / "merged"
    weights = checkpoint / "update"
    weights.mkdir(parents=True)
    (weights / "model.safetensors").write_bytes(b"stand-in model")
    (weights / "config.json").write_text(json.dumps({"test_frequency": 440}))
    (weights / "tokenizer.json").write_text("{}")
    (checkpoint / "voices_v3_turbo.json").write_text(json.dumps({
        "default_voice": "Alan", "presets": {"Alan": {"speaker_emb": [0.1] * 192, "codes": None}}
    }))
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"backbone_configs": {"Local Alan": {
        "mode": "v3turbo", "repo": "models/alan/merged", "local": True,
        "backend": "pytorch", "model_subfolder": "update", "requires_cuda": True,
        "supports_streaming": False,
    }}}))
    monkeypatch.setenv("VIENEU_MODEL_PROFILE", "Local Alan")
    monkeypatch.setenv("VIENEU_CONFIG_PATH", str(config))
    monkeypatch.setenv("VIENEU_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("VIENEU_VOICE_PRO_ENABLED", "1")
    monkeypatch.setenv("VIENEU_API_KEY", "local-test-key")
    monkeypatch.setenv("VIENEU_BACKEND", "auto")
    monkeypatch.setenv("VIENEU_DEVICE", "auto")
    monkeypatch.setattr(api, "Vieneu", lambda **kwargs: LocalSpeechModel(**kwargs))
    monkeypatch.setattr(api, "ENGINE", None)
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    other = tmp_path / "other-cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    return config, checkpoint


def test_local_profile_loads_relative_to_config_and_serves_complete_audio(local_profile):
    with TestClient(api.app, headers={"Authorization": "Bearer local-test-key"}) as client:
        capability = client.get("/v1/tts/capabilities").json()
        assert capability["model_profile"] == "Local Alan"
        assert capability["supports_streaming"] is False
        assert capability["max_streams"] == 1
        assert [v["id"] for v in client.get("/v1/voices").json()["data"]] == ["unrelated-base-voice", "Alan"]
        response = client.post("/v1/tts", json={"text": "Xin chào", "voice": "Alan", "format": "wav"})
        assert response.status_code == 200
        audio, rate = sf.read(io.BytesIO(response.content))
        assert rate == 48_000 and len(audio) == 48_000
        assert client.post("/v1/audio/speech", json={"input": "Xin chào", "stream": False}).status_code == 200
        assert client.post("/v1/audio/speech", json={"input": "Xin chào"}).status_code == 400
        cloning = client.post("/v1/voices", data={"name": "Other voice"}, files={"file": ("clip.wav", b"RIFF")})
        assert cloning.status_code == 400 and cloning.json()["error"]["code"] == "unsupported_parameter"


@pytest.mark.parametrize("setting,value,error", [
    ("VIENEU_MODEL_PROFILE", "missing profile", "VIENEU_MODEL_PROFILE"),
    ("VIENEU_BACKEND", "onnx", "Local PyTorch profiles"),
    ("VIENEU_DEVICE", "cpu", "requires CUDA"),
])
def test_invalid_profile_configuration_fails_instead_of_using_base_model(local_profile, monkeypatch, setting, value, error):
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=error):
        with TestClient(api.app):
            pass


def test_missing_checkpoint_is_rejected_before_startup(local_profile):
    _, checkpoint = local_profile
    (checkpoint / "update" / "model.safetensors").unlink()
    with pytest.raises(ValueError, match="missing model.safetensors"):
        with TestClient(api.app):
            pass


def test_profile_requiring_cuda_rejects_unavailable_gpu(local_profile, monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(ValueError, match="requires PyTorch CUDA"):
        with TestClient(api.app):
            pass


def test_complete_profile_checks_audio_limits_between_text_chunks(local_profile, monkeypatch):
    monkeypatch.setenv("VIENEU_MAX_AUDIO_SECONDS", "2")
    with TestClient(api.app, headers={"Authorization": "Bearer local-test-key"}) as client:
        response = client.post("/v1/tts", json={
            "text": "Đây là một câu đủ dài để kiểm tra chia đoạn văn bản. " * 8,
            "voice": "Alan", "format": "wav", "max_chars": 64,
        })
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "audio_too_large"


def test_switching_local_checkpoints_does_not_reuse_the_previous_voice_registry(local_profile, monkeypatch):
    config, checkpoint = local_profile
    with TestClient(api.app, headers={"Authorization": "Bearer local-test-key"}) as client:
        first_id = client.get("/v1/models").json()["data"][0]["id"]
    import shutil
    second = checkpoint.parent / "second-merged"
    shutil.copytree(checkpoint, second)
    manifest = json.loads((second / "voices_v3_turbo.json").read_text())
    manifest["presets"]["Beta"] = manifest["presets"].pop("Alan")
    manifest["default_voice"] = "Beta"
    (second / "voices_v3_turbo.json").write_text(json.dumps(manifest))
    data = yaml.safe_load(config.read_text())
    data["backbone_configs"]["Local Beta"] = {
        **data["backbone_configs"]["Local Alan"], "repo": "models/alan/second-merged"
    }
    config.write_text(yaml.safe_dump(data))
    monkeypatch.setenv("VIENEU_MODEL_PROFILE", "Local Beta")
    monkeypatch.setattr(api, "ENGINE", None)
    with TestClient(api.app, headers={"Authorization": "Bearer local-test-key"}) as client:
        assert [v["id"] for v in client.get("/v1/voices").json()["data"]] == ["unrelated-base-voice", "Beta"]
        assert client.get("/v1/models").json()["data"][0]["id"] != first_id
