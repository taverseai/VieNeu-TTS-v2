"""Post-process generated speech with the bundled Resemble ONNX denoiser."""

from functools import lru_cache
from pathlib import Path
import os
import tempfile

import numpy as np
import soundfile as sf
import soxr


@lru_cache(maxsize=1)
def _load_denoiser():
    from huggingface_hub import hf_hub_download
    import onnxruntime as ort
    from vieneu._v3_turbo_engine.onnx_denoiser import OnnxDenoiser

    model_path = hf_hub_download(
        "pnnbao-ump/VieNeu-TTS-v3-Turbo", "denoiser.onnx"
    )
    options = ort.SessionOptions()
    options.intra_op_num_threads = min(4, os.cpu_count() or 1)
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return OnnxDenoiser(model_path, sess_options=options)


def enhance_audio(audio_path, strength=0.65, progress=None):
    """Return a separate WAV; bound inference memory using overlapping chunks.

    This uses Resemble's denoise core, not its generative enhancer. Blend with
    the original waveform to control suppression without changing speech timing.
    Preserve the input sample rate and duration, including for long SRT audio.
    """
    if not audio_path or not Path(audio_path).is_file():
        raise ValueError("Hãy tạo audio trước khi cải thiện giọng nói.")
    strength = float(strength)
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("Mức khử nhiễu phải nằm trong khoảng 0–1.")

    audio, sample_rate = sf.read(audio_path, dtype="float32", always_2d=True)
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Audio rỗng hoặc có dữ liệu không hợp lệ.")
    original = audio.mean(axis=1)
    if progress:
        progress(0, desc="Đang chuẩn bị bộ khử nhiễu…")

    # Skip silence: there is no speech to restore, and neural output could add noise.
    if strength == 0 or np.max(np.abs(original)) < 1e-7:
        result = original
    else:
        denoiser = _load_denoiser()
        rate = 44_100
        source = (soxr.resample(original, sample_rate, rate)
                  if sample_rate != rate else original)
        source = np.asarray(source, dtype=np.float32)
        chunk_size, overlap = rate * 4, rate // 4
        step = chunk_size - overlap
        clean = np.zeros(len(source), dtype=np.float32)
        weights = np.zeros(len(source), dtype=np.float32)
        for start in range(0, len(source), step):
            end = min(start + chunk_size, len(source))
            chunk = source[start:end]
            # Very short clips still need enough samples for the model's STFT.
            padded = np.pad(chunk, (0, max(0, 1680 - len(chunk))))
            processed = denoiser.denoise(padded, rate)[:len(chunk)]
            if len(processed) != len(chunk) or not np.isfinite(processed).all():
                raise RuntimeError("Bộ khử nhiễu trả về audio không hợp lệ.")
            window = np.ones(len(chunk), dtype=np.float32)
            if start:
                window[:overlap] = np.linspace(0, 1, overlap, endpoint=False)
            if end < len(source):
                window[-overlap:] = np.linspace(1, 0, overlap, endpoint=False)
            clean[start:end] += processed * window
            weights[start:end] += window
            if progress:
                progress(end / len(source), desc="Đang giảm rè và nhiễu…")
            if end == len(source):
                break
        clean /= np.maximum(weights, 1e-7)
        if sample_rate != rate:
            clean = soxr.resample(clean, rate, sample_rate)
        clean = np.pad(clean, (0, max(0, len(original) - len(clean))))[:len(original)]
        result = (1 - strength) * original + strength * clean

    # Attenuate only when necessary; do not amplify quiet noise or hard-clip peaks.
    peak = float(np.max(np.abs(result)))
    if peak > 0.98:
        result = result * (0.98 / peak)
    with tempfile.NamedTemporaryFile(suffix="_enhanced.wav", delete=False) as output:
        output_path = output.name
    try:
        sf.write(output_path, result, sample_rate, subtype="PCM_16")
    except Exception:
        Path(output_path).unlink(missing_ok=True)
        raise
    return output_path
