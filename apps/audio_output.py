"""Keep original float waveforms and create separate playback copies."""

from pathlib import Path
import tempfile
import numpy as np
import soundfile as sf


def peak_attenuation_gain(peak):
    """Use one gain for a whole recording, leaving quiet audio unchanged."""
    return 0.98 / peak if peak > 0.98 else 1.0


def write_generated_audio(path, waveform, sample_rate):
    """Save original float32 samples, including peaks outside +/-1."""
    audio = np.asarray(waveform, dtype=np.float32)
    if not audio.size or not np.isfinite(audio).all():
        raise ValueError("Audio rỗng hoặc có dữ liệu không hợp lệ.")
    sf.write(path, audio, sample_rate, subtype="FLOAT")


def balance_audio(audio_path):
    """Attenuate only when needed, saving a separate PCM24 WAV for playback.

    One constant gain preserves timing, pitch, channels and relative dynamics.
    Quiet clips and silence keep their volume. Never overwrite the original.
    """
    if not audio_path or not Path(audio_path).is_file():
        raise ValueError("Hãy tạo audio trước khi cân biên độ.")
    audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
    if not audio.size or not np.isfinite(audio).all():
        raise ValueError("Audio rỗng hoặc có dữ liệu không hợp lệ.")
    peak = float(np.max(np.abs(audio)))
    audio = audio * peak_attenuation_gain(peak)
    with tempfile.NamedTemporaryFile(suffix="_balanced.wav", delete=False) as output:
        path = output.name
    try:
        sf.write(path, audio, sample_rate, subtype="PCM_24")
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise
    return path
