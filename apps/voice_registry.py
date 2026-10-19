"""Persistent API voice identities, metadata, and immutable synthesis snapshots."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any
import uuid

import numpy as np

from apps.tts_contract import TtsError


class VoiceRegistry:
    def __init__(self, tts: Any, home: Path):
        self.tts = tts
        self.path = home / "api-voices-v1.json"
        self.lock = threading.RLock()
        home.mkdir(parents=True, exist_ok=True)
        self.builtins: dict[str, str] = {}
        self.users: dict[str, dict] = {}
        if self.path.exists():
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("version") != 1:
                raise ValueError("Unsupported API voice registry version")
            for voice_id in document["builtins"]:
                target = tts.resolve_voice_name(voice_id)
                if target is None:
                    raise ValueError(f"Built-in voice ID needs an explicit migration: {voice_id}")
                self.builtins[voice_id] = target
            # Newly introduced presets get new IDs; previously published IDs stay fixed.
            for name in tts._preset_voices:
                if name not in self.builtins.values():
                    self.builtins[name] = name
            self.users = document["users"]
        else:
            self.builtins = {name: name for name in tts._preset_voices}
        for voice_id, entry in self.users.items():
            if not voice_id.startswith("usr_") or tts.resolve_voice_name(voice_id) is not None:
                raise ValueError("Conflicting API voice ID")
            if tts.resolve_voice_name(entry["name"]) is not None:
                raise ValueError("Conflicting API voice alias")
            tts._preset_voices[voice_id] = self._decode(entry["data"])
            tts._voice_aliases[entry["name"]] = voice_id
        for voice_id, target in self.builtins.items():
            if voice_id != target:
                tts._voice_aliases[voice_id] = target
        self._commit(self.users)
        self._publish()

    @staticmethod
    def _encode(entry: dict) -> dict:
        return {"speaker_emb": None if entry.get("speaker_emb") is None else np.asarray(entry["speaker_emb"]).tolist(),
                "codes": None if entry.get("codes") is None else np.asarray(entry["codes"]).tolist(),
                "style": entry.get("style", "tu_nhien"),
                "description": entry.get("description", ""), "gender": entry.get("gender", "unknown")}

    @staticmethod
    def _decode(entry: dict) -> dict:
        result = dict(entry)
        if entry.get("speaker_emb") is not None:
            result["speaker_emb"] = np.asarray(entry["speaker_emb"], dtype=np.float32)
        if entry.get("codes") is not None:
            result["codes"] = np.asarray(entry["codes"], dtype=np.int64)
        return result

    def _commit(self, users: dict) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix="voices-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "builtins": list(self.builtins), "users": users}, stream,
                          ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _publish(self) -> None:
        """Replace immutable read views only after a durable enrollment commit."""
        snapshots, metadata = {}, []
        for voice_id, target in self.builtins.items():
            entry = dict(self.tts._preset_voices[target])
            aliases = [a for a, name in self.tts._voice_aliases.items() if name == target and a != voice_id]
            for alias in [voice_id, target, *aliases]:
                snapshots[alias] = entry
            metadata.append(self._metadata(voice_id, target, entry, aliases))
        for voice_id, entry in self.users.items():
            snapshot = dict(self.tts._preset_voices[voice_id])
            snapshots[voice_id] = snapshots[entry["name"]] = snapshot
            metadata.append(self._metadata(voice_id, entry["name"], entry, [entry["name"]]))
        self._published = snapshots
        self._published_metadata = metadata

    def list_voices(self) -> list[dict]:
        # Same featured ordering as the Web preset dropdown; ties keep SDK order.
        metadata = sorted(self._published_metadata,
                          key=lambda entry: (entry.get("featured") is None, entry.get("featured") or 0))
        return [dict(entry, aliases=list(entry["aliases"])) for entry in metadata]

    @staticmethod
    def _metadata(voice_id: str, name: str, entry: dict, aliases: list) -> dict:
        gender = entry.get("gender", "unknown")
        return {"id": voice_id, "name": name, "locale": entry.get("locale", "vi-VN"),
                "gender": gender if gender in ("male", "female") else "unknown",
                "formats": ["mp3", "wav", "flac"], "aliases": aliases,
                "description": entry.get("description", ""), "featured": entry.get("featured")}

    def snapshot(self, voice_id: str) -> dict:
        entry = self._published.get(voice_id)
        if entry is None:
            raise TtsError(404, "voice_not_found", "The requested voice does not exist.", "voice")
        return dict(entry)

    def enroll(self, name: str, path: str, *, denoise: bool, description: str,
               locale: str, gender: str) -> dict:
        with self.lock:
            existing = self.tts.resolve_voice_name(name)
            if existing is not None and existing not in self.users:
                raise TtsError(409, "invalid_request", "A built-in voice or alias cannot be replaced.", "name")
            voice_id = existing or "usr_" + uuid.uuid4().hex
            previous = self.tts._preset_voices.get(voice_id)
            try:
                self.tts.add_voice(voice_id, path, denoise=denoise, description=description, gender=gender)
                data = self._encode(self.tts._preset_voices[voice_id])
                entry = {"name": name, "locale": locale, "gender": gender,
                         "description": description, "data": data}
                updated = {**self.users, voice_id: entry}
                self._commit(updated)
            except BaseException:
                if previous is None:
                    self.tts._preset_voices.pop(voice_id, None)
                else:
                    self.tts._preset_voices[voice_id] = previous
                raise
            self.users = updated
            self.tts._voice_aliases[name] = voice_id
            self._publish()
            return self._metadata(voice_id, name, entry, [name])
