"""Protect generated waveforms before converting them to integer PCM."""

import numpy as np
import soundfile as sf


def write_generated_audio(path, waveform, sample_rate):
    """Keep headroom by scaling the whole clip, preserving its wave shape.

    Codec output can exceed +/-1. Writing those floats directly as PCM16
    permanently clips their peaks; denoising the resulting file cannot undo it.
    """
    audio = np.asarray(waveform, dtype=np.float32)
    if not audio.size or not np.isfinite(audio).all():
        raise ValueError("Audio rỗng hoặc có dữ liệu không hợp lệ.")
    peak = float(np.max(np.abs(audio)))
    if peak > 0.98:
        audio = audio * (0.98 / peak)
    sf.write(path, audio, sample_rate, subtype="PCM_16")
