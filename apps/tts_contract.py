"""Voice-Pro request contract and effective server settings."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TtsError(Exception):
    def __init__(self, status: int, code: str, message: str, param: str | None = None):
        super().__init__(message)
        self.status, self.code, self.param = status, code, param


class SynthesisRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=20_000)
    voice: str = Field(min_length=1)
    rate: float = Field(default=0, ge=-90, le=200)
    volume: float = Field(default=0, ge=-100, le=100)
    pitch: float = Field(default=0, ge=-400, le=400)
    format: Literal["mp3", "wav", "flac"] = "mp3"
    temperature: float = Field(default=0.8, ge=0, le=2)
    max_chars: int = Field(default=256, ge=64, le=512)


class RenderContext:
    def __init__(self, timeout: float):
        self.deadline = time.monotonic() + timeout
        self.cancelled = threading.Event()

    def check(self) -> None:
        if self.cancelled.is_set() or time.monotonic() >= self.deadline:
            raise TtsError(504, "synthesis_timeout", "Synthesis was cancelled or timed out.")

    def remaining(self) -> float:
        self.check()
        return self.deadline - time.monotonic()


@dataclass(frozen=True)
class TtsSettings:
    home: Path
    timeout: float = 300
    max_text_chars: int = 20_000
    max_request_bytes: int = 262_144
    max_audio_seconds: float = 600
    max_output_bytes: int = 67_108_864
    encoding_workers: int = 2
    max_complete_requests: int = 1
    ffmpeg: str = "ffmpeg"

    @classmethod
    def from_env(cls, max_streams: int) -> TtsSettings:
        def positive(name: str, default: int) -> int:
            value = int(os.environ.get(name, default))
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            return value

        chars = positive("VIENEU_MAX_TEXT_CHARS", 20_000)
        if chars > 20_000:
            raise ValueError("VIENEU_MAX_TEXT_CHARS cannot exceed 20000")
        return cls(
            home=Path(os.environ.get("VIENEU_HOME") or Path.home() / ".vieneu"),
            timeout=positive("VIENEU_TTS_TIMEOUT", 300),
            max_text_chars=chars,
            max_request_bytes=positive("VIENEU_MAX_REQUEST_BYTES", 262_144),
            max_audio_seconds=positive("VIENEU_MAX_AUDIO_SECONDS", 600),
            max_output_bytes=positive("VIENEU_MAX_OUTPUT_BYTES", 67_108_864),
            encoding_workers=positive("VIENEU_ENCODING_WORKERS", 2),
            max_complete_requests=positive("VIENEU_MAX_COMPLETE_REQUESTS", max_streams),
            ffmpeg=os.environ.get("VIENEU_FFMPEG_PATH", "ffmpeg"),
        )

    def capabilities(self, engine) -> dict:
        return {
            "api_version": "1.0", "model": "vieneu-v3-turbo", "backbone": engine.backbone,
            "formats": ["mp3", "wav", "flac"], "sample_rate": 48_000,
            "channels": 1, "response_mode": "file", "ssml": False,
            "max_text_chars": self.max_text_chars, "text_length_unit": "unicode_code_points",
            "max_request_bytes": self.max_request_bytes,
            "controls": {
                "rate": {"min": -90, "max": 200, "default": 0, "unit": "percent"},
                "volume": {"min": -100, "max": 100, "default": 0, "unit": "percent_amplitude"},
                "pitch": {"min": -400, "max": 400, "default": 0, "unit": "cent"},
                "temperature": {"min": 0, "max": 2, "default": 0.8, "unit": "sampling_temperature"},
                "max_chars": {"min": 64, "max": 512, "default": 256, "unit": "unicode_code_points"},
            },
            "request_timeout_seconds": self.timeout, "queue_timeout_seconds": engine.queue_timeout,
            "max_audio_seconds": self.max_audio_seconds, "max_output_bytes": self.max_output_bytes,
            "max_streams": engine.max_streams, "max_queue": engine.max_queue,
            "max_complete_requests": self.max_complete_requests, "encoding_workers": self.encoding_workers,
            "rate_limit": {"requests_per_minute": None, "policy": "concurrency_and_bounded_queue"},
            "result_url_ttl_seconds": None,
        }
