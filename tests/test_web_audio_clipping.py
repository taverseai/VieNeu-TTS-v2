"""Exercise the web's actual export path with an over-range codec waveform."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from apps import gradio_main as web
from apps.audio_output import balance_audio, write_generated_audio
import tempfile


class WebAudioClippingTests(unittest.TestCase):
    def export(self, amplitude):
        sr = 48_000
        waveform = (amplitude * np.sin(2 * np.pi * 220 * np.arange(sr // 5) / sr)).astype(np.float32)
        tts = SimpleNamespace(
            sample_rate=sr,
            engine=SimpleNamespace(device=None, infer=lambda **kwargs: waveform.copy()),
            get_preset_voice=lambda voice: {"speaker_emb": np.zeros(192), "codes": None},
        )
        with patch.multiple(
            web, tts=tts, model_loaded=True, current_backbone="v3-test",
            current_codec="test", CODEC_CONFIGS={"test": {"use_preencoded": False}},
            resolve_voice_id=lambda value: value,
            normalize_to_chunks_v3_with_gaps=lambda *args, **kwargs: (["test"], []),
            cleanup_gpu_memory=lambda: None,
        ), patch("vieneu_utils.phonemize_text.phonemize_text_with_emotions", return_value="test"):
            results = list(web.synthesize_speech(
                "test", "test", None, "", "preset_mode", "Standard (Một lần)",
                False, 1, 0.8, 256,
            ))
        output = next((path for path, status in results if path), None)
        self.assertIsNotNone(output, results)
        try:
            self.assertEqual(sf.info(output).subtype, "FLOAT")
            saved, saved_sr = sf.read(output, dtype="float32")
            balanced_path = balance_audio(output)
            try:
                self.assertEqual(sf.info(balanced_path).subtype, "PCM_24")
                balanced, balanced_sr = sf.read(balanced_path)
                self.assertEqual(balanced_sr, sr)
                self.assertEqual(len(balanced), len(waveform))
                np.testing.assert_array_equal(sf.read(output, dtype="float32")[0], waveform)
            finally:
                Path(balanced_path).unlink(missing_ok=True)
        finally:
            Path(output).unlink(missing_ok=True)
        self.assertEqual(saved_sr, sr)
        self.assertEqual(len(saved), len(waveform))
        return waveform, saved, balanced

    def test_over_range_codec_output_keeps_wave_shape_without_clipping(self):
        source, saved, balanced = self.export(1.4)
        np.testing.assert_array_equal(saved, source)
        self.assertGreater(float(np.abs(saved).max()), 1)
        self.assertLessEqual(float(np.abs(balanced).max()), 0.981)
        expected = source * (0.98 / np.abs(source).max())
        np.testing.assert_allclose(balanced, expected, atol=1 / 8388608)

    def test_quiet_codec_output_keeps_its_volume(self):
        source, saved, balanced = self.export(0.3)
        np.testing.assert_array_equal(saved, source)
        np.testing.assert_allclose(balanced, source, atol=1 / 8388608)

    def test_balance_preserves_stereo_and_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.wav"
            for samples in [np.zeros((100, 2), dtype=np.float32),
                            np.array([[1.5, -0.5], [0.25, -1.2]], dtype=np.float32)]:
                write_generated_audio(path, samples, 24000)
                output = balance_audio(path)
                try:
                    balanced, sr = sf.read(output, always_2d=True)
                    self.assertEqual(sr, 24000)
                    self.assertEqual(balanced.shape, samples.shape)
                    peak = float(np.abs(samples).max())
                    expected = samples * (0.98 / peak) if peak > 0.98 else samples
                    np.testing.assert_allclose(balanced, expected, atol=1 / 8388608)
                finally:
                    Path(output).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
