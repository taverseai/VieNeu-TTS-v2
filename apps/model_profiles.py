"""Resolve local v3 Turbo checkpoints from the same config used by the Web UI."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"


@dataclass(frozen=True)
class LocalModelProfile:
    name: str
    repo: Path
    model_subfolder: str
    requires_cuda: bool
    supports_streaming: bool
    voice_ids: tuple[str, ...]
    default_voice: str

    @property
    def storage_key(self) -> str:
        identity = f"{os.path.normcase(str(self.repo))}\n{self.model_subfolder}"
        return hashlib.sha256(identity.encode()).hexdigest()[:16]

    @classmethod
    def from_env(cls) -> LocalModelProfile | None:
        name = os.environ.get("VIENEU_MODEL_PROFILE", "")
        if not name:
            return None
        config_path = Path(os.environ.get("VIENEU_CONFIG_PATH") or Path(__file__).resolve().parents[1] / "config.yaml").resolve()
        with config_path.open(encoding="utf-8") as source:
            config = yaml.safe_load(source)
        profiles = config.get("backbone_configs", {}) if isinstance(config, dict) else {}
        if not isinstance(profiles, dict) or name not in profiles:
            raise ValueError(f"VIENEU_MODEL_PROFILE does not match a backbone_configs entry: {name}")
        entry = profiles[name]
        if not isinstance(entry, dict) or entry.get("mode") != "v3turbo" or entry.get("local") is not True:
            raise ValueError("API model profiles require mode: v3turbo and local: true")
        if entry.get("backend", "pytorch") != "pytorch":
            raise ValueError("Local model profiles currently require backend: pytorch")
        repo, subfolder = entry.get("repo"), entry.get("model_subfolder", "update")
        if not isinstance(repo, str) or not repo or not isinstance(subfolder, str):
            raise ValueError("Model profile requires a repo path and a string model_subfolder")
        root = (config_path.parent / repo).resolve()
        weights = (root / subfolder).resolve()
        if not weights.is_relative_to(root):
            raise ValueError("model_subfolder must stay within the checkpoint directory")
        for filename in ("model.safetensors", "config.json", "tokenizer.json"):
            if not (weights / filename).is_file():
                raise ValueError(f"Local checkpoint is incomplete: missing {filename}")
        with (root / "voices_v3_turbo.json").open(encoding="utf-8") as source:
            voices = json.load(source)
        presets = voices.get("presets") if isinstance(voices, dict) else None
        default_voice = voices.get("default_voice") if isinstance(voices, dict) else None
        if not isinstance(presets, dict) or not presets or not isinstance(default_voice, str) or default_voice not in presets:
            raise ValueError("Local checkpoint must declare presets and a valid default_voice")
        if any(not isinstance(key, str) or not isinstance(value, dict) or value.get("speaker_emb") is None
               for key, value in presets.items()):
            raise ValueError("Local checkpoint voices must contain speaker embeddings")
        for field in ("requires_cuda", "supports_streaming"):
            if field in entry and not isinstance(entry[field], bool):
                raise ValueError(f"{field} must be a YAML boolean")
        return cls(name, root, subfolder, entry.get("requires_cuda", False),
                   entry.get("supports_streaming", False), tuple(presets), default_voice)

    def runtime(self, backend: str, device: str, onnx_dir: str | None) -> tuple[str, str]:
        if backend not in ("auto", "pytorch") or onnx_dir:
            raise ValueError("Local PyTorch profiles cannot use VIENEU_BACKEND=onnx or VIENEU_ONNX_DIR")
        if self.requires_cuda:
            if device != "auto" and device != "cuda" and not device.startswith("cuda:"):
                raise ValueError("Selected model profile requires CUDA; set VIENEU_DEVICE=auto or cuda")
            try:
                import torch
                available = torch.cuda.is_available()
            except ImportError:
                available = False
            if not available:
                raise ValueError("Selected model profile requires PyTorch CUDA; install uv sync --extra cuda")
            device = "cuda" if device == "auto" else device
        return "pytorch", device

    def activate_voices(self, tts: Any) -> None:
        missing = set(self.voice_ids) - tts._preset_voices.keys()
        if missing:
            raise ValueError("SDK did not load all voices declared by the local checkpoint")
        tts._preset_voices = {key: tts._preset_voices[key] for key in self.voice_ids}
        tts._voice_aliases = {alias: target for alias, target in tts._voice_aliases.items() if target in self.voice_ids}
        tts._default_voice = self.default_voice
