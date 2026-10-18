"""Exercise the web's actual export path with an over-range codec waveform."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from apps import gradio_main as web


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
            saved, saved_sr = sf.read(output)
        finally:
            Path(output).unlink(missing_ok=True)
        self.assertEqual(saved_sr, sr)
        self.assertEqual(len(saved), len(waveform))
        return waveform, saved

    def test_over_range_codec_output_keeps_wave_shape_without_clipping(self):
        source, saved = self.export(1.4)
        self.assertLessEqual(float(np.abs(saved).max()), 0.981)
        expected = source * (0.98 / np.abs(source).max())
        np.testing.assert_allclose(saved, expected, atol=1 / 32768)

    def test_quiet_codec_output_keeps_its_volume(self):
        source, saved = self.export(0.3)
        np.testing.assert_allclose(saved, source, atol=1 / 32768)


if __name__ == "__main__":
    unittest.main()
