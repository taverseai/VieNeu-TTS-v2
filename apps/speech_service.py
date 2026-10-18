"""Shared complete-audio rendering with bounded resources and explicit ownership."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import threading
import os
import sys
from typing import Any

import numpy as np

from apps.audio_encoding import AudioEncoder, FORMATS
from apps.tts_contract import RenderContext, TtsError, TtsSettings


class _InstanceLock:
    """Keep two API processes from sharing and cleaning the same job directory."""
    def __init__(self, home: Path):
        self.stream = (home / "api-instance.lock").open("a+b")
        try:
            if self.stream.tell() == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise ValueError("VIENEU_HOME is already in use by another API process") from exc

    def close(self) -> None:
        self.stream.close()


class RenderedAudio:
    def __init__(self, directory: Path, path: Path, duration: float, sample_rate: int,
                 media_type: str, release):
        self.directory, self.path, self.duration = directory, path, duration
        self.sample_rate, self.media_type = sample_rate, media_type
        self._release = release
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            shutil.rmtree(self.directory)
        finally:
            self._release()


class SpeechService:
    def __init__(self, engine: Any, settings: TtsSettings):
        self.engine, self.settings = engine, settings
        self.encoder = AudioEncoder(settings)
        self.complete_slots = threading.BoundedSemaphore(settings.max_complete_requests)
        self.encoding_slots = threading.BoundedSemaphore(settings.encoding_workers)
        self.spool = settings.home / "api-jobs"
        self.spool.mkdir(parents=True, exist_ok=True)
        self._instance = _InstanceLock(settings.home)
        self._condition = threading.Condition()
        self._contexts: set[RenderContext] = set()
        self._closed = False
        try:
            for old in self.spool.glob("job-*"):
                if old.is_dir() and not old.is_symlink() and old.resolve().is_relative_to(self.spool.resolve()):
                    shutil.rmtree(old)
        except BaseException:
            self._instance.close()
            raise

    def healthy(self) -> bool:
        try:
            with tempfile.TemporaryFile(dir=self.spool) as probe:
                probe.write(b"0")
                probe.flush()
            return not self._closed and shutil.which(self.settings.ffmpeg) is not None
        except OSError:
            return False

    def close(self) -> None:
        with self._condition:
            self._closed = True
            for context in self._contexts:
                context.cancelled.set()
            while self._contexts:
                self._condition.wait(0.05)
        self._instance.close()

    def render(self, context: RenderContext, *, text: str, voice: Any, fmt: str,
               rate: float = 0, volume: float = 0, pitch: float = 0,
               sample_rate: int = 48_000, **sampling: Any) -> RenderedAudio:
        """Caller holds a complete slot; result owns it until transfer cleanup."""
        directory = None
        try:
            with self._condition:
                if self._closed:
                    raise TtsError(503, "engine_unavailable", "Speech renderer is shutting down.")
                self._contexts.add(context)
            directory = Path(tempfile.mkdtemp(prefix="job-", dir=self.spool))
            raw = directory / "speech.f32"
            self.engine.acquire(context=context)
            try:
                chunks = self.engine.audio_chunks(text, context=context, voice=voice,
                                                     apply_watermark=self.engine.watermark, **sampling)
                try:
                    samples = 0
                    with raw.open("wb") as output:
                        for chunk in chunks:
                            context.check()
                            if chunk is None:
                                continue
                            audio = np.asarray(chunk, dtype=np.float32).reshape(-1)
                            if not np.isfinite(audio).all():
                                raise TtsError(500, "invalid_audio", "Model produced invalid samples.")
                            samples += audio.size
                            if samples / 48_000 > self.settings.max_audio_seconds:
                                raise TtsError(413, "audio_too_large", "Generated audio is too long.")
                            output.write(audio.astype("<f4").tobytes())
                    context.check()
                    if not samples:
                        raise TtsError(500, "invalid_audio", "Model produced no audio samples.")
                finally:
                    chunks.close()
            finally:
                self.engine.release()
            if samples / 48_000 / (1 + rate / 100) > self.settings.max_audio_seconds:
                raise TtsError(413, "audio_too_large", "Transformed audio is too long.")
            self.engine.acquire_capacity(self.encoding_slots, context)
            try:
                path = directory / f"speech.{fmt}"
                duration = self.encoder.encode(raw, path, context, fmt=fmt, rate=rate,
                                               volume=volume, pitch=pitch, sample_rate=sample_rate)
            finally:
                self.encoding_slots.release()
            raw.unlink()
            return RenderedAudio(directory, path, duration, sample_rate, FORMATS[fmt][1],
                                 self.complete_slots.release)
        except BaseException as exc:
            if directory is not None:
                shutil.rmtree(directory, ignore_errors=True)
            self.complete_slots.release()
            if isinstance(exc, (TtsError, KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, OSError):
                raise TtsError(503, "engine_unavailable", "Temporary audio storage is unavailable.") from exc
            raise TtsError(500, "synthesis_failed", "Speech synthesis failed.") from exc
        finally:
            with self._condition:
                self._contexts.discard(context)
                self._condition.notify_all()
