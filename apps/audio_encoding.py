"""Bounded FFmpeg encoding and validation of complete speech files."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import time

import numpy as np

from apps.audio_output import peak_attenuation_gain
from apps.tts_contract import RenderContext, TtsError, TtsSettings


FORMATS = {
    "mp3": ("libmp3lame", "audio/mpeg"),
    "wav": ("pcm_s16le", "audio/wav"),
    "flac": ("flac", "audio/flac"),
    "pcm": ("pcm_s16le", "audio/pcm"),
}


class AudioEncoder:
    def __init__(self, settings: TtsSettings):
        self.settings = settings
        for option, required in (
            ("-encoders", ("libmp3lame", "pcm_s16le", "pcm_f32le", "flac")),
            ("-decoders", ("pcm_s16le", "pcm_f32le", "flac")),
            ("-filters", ("rubberband", "volume")),
        ):
            result = subprocess.run([settings.ffmpeg, "-hide_banner", option],
                                    capture_output=True, timeout=10, check=True)
            available = {line.split()[1] for line in result.stdout.decode(errors="replace").splitlines()
                         if len(line.split()) >= 2}
            missing = set(required) - available
            if option == "-decoders" and not available.intersection({"mp3", "mp3float"}):
                missing.add("MP3 decoder")
            if missing:
                raise ValueError(f"FFmpeg missing required capabilities: {sorted(missing)}")

    def _run(self, args: list[str], context: RenderContext, output: Path, max_bytes: int) -> None:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                [self.settings.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
            )
            try:
                while process.poll() is None:
                    context.check()
                    if output.exists() and output.stat().st_size > max_bytes:
                        raise TtsError(413, "audio_too_large", "Audio exceeds the configured limit.")
                    time.sleep(0.02)
                context.check()
                if output.exists() and output.stat().st_size > max_bytes:
                    raise TtsError(413, "audio_too_large", "Audio exceeds the configured limit.")
                if process.returncode:
                    raise TtsError(500, "encoding_failed", "Audio encoding or validation failed.")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def encode(self, raw: Path, output: Path, context: RenderContext, *, fmt: str,
               rate: float, volume: float, pitch: float, sample_rate: int = 48_000) -> float:
        codec, _ = FORMATS[fmt]
        filters = []
        if rate or pitch:
            filters.append(f"rubberband=tempo={1 + rate / 100}:pitch={2 ** (pitch / 1200)}:formant=preserved")
        filters.append(f"volume={1 + volume / 100}")
        # Keep samples floating point until tempo, pitch, gain and resampling have
        # finished. Measure the whole result before applying the same attenuation
        # as Web playback, without normalizing individual model chunks.
        max_decoded = int(self.settings.max_audio_seconds * sample_rate * 4)
        with tempfile.TemporaryDirectory(prefix="balance-", dir=output.parent) as directory:
            transformed = Path(directory) / "transformed.f32"
            self._run([
                "-threads", "1", "-f", "f32le", "-ar", "48000", "-ac", "1", "-i", str(raw),
                "-filter_threads", "1", "-af", ",".join(filters), "-ac", "1", "-ar", str(sample_rate),
                "-c:a", "pcm_f32le", "-threads", "1", "-f", "f32le", str(transformed),
            ], context, transformed, max_decoded)
            peak = 0.0
            with transformed.open("rb") as source:
                while block := source.read(65536 * 4):
                    context.check()
                    samples = np.frombuffer(block, dtype="<f4")
                    if not np.isfinite(samples).all():
                        raise TtsError(500, "invalid_audio", "Audio processing produced invalid samples.")
                    peak = max(peak, float(np.max(np.abs(samples))))
            gain = peak_attenuation_gain(peak)
            args = ["-threads", "1", "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", str(transformed),
                    "-filter_threads", "1", "-af", f"volume={gain:.17g}:precision=double",
                    "-ac", "1", "-ar", str(sample_rate), "-c:a", codec, "-threads", "1"]
            self._encode_output(args, fmt, output, context)
        if not output.exists() or output.stat().st_size == 0:
            raise TtsError(500, "invalid_audio", "No audio was encoded.")
        return self._validate_output(output, context, fmt, sample_rate, max_decoded)

    def _encode_output(self, args: list[str], fmt: str, output: Path, context: RenderContext) -> None:
        if fmt == "mp3":
            args += ["-b:a", "192k"]
        if fmt == "flac":
            args += ["-sample_fmt", "s16"]
        if fmt == "pcm":
            args += ["-f", "s16le"]
        self._run([*args, str(output)], context, output, self.settings.max_output_bytes)

    def _validate_output(self, output: Path, context: RenderContext, fmt: str,
                         sample_rate: int, max_decoded: int) -> float:
        decoded = output.with_name("validated.f32")
        decode_args = ["-threads", "1", "-xerror"]
        if fmt == "pcm":
            decode_args += ["-f", "s16le", "-ar", str(sample_rate), "-ac", "1"]
        decode_args += ["-i", str(output), "-map", "0:a:0", "-ac", "1", "-ar", str(sample_rate),
                        "-threads", "1", "-f", "f32le", str(decoded)]
        self._run(decode_args, context, decoded, max_decoded)
        samples = decoded.stat().st_size // 4
        decoded.unlink()
        if samples == 0:
            raise TtsError(500, "invalid_audio", "Encoded file contains no audio samples.")
        return samples / sample_rate
