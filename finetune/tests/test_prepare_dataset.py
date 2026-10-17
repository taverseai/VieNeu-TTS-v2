"""Regression checks for the issue #198 dataset guard (no model download)."""
import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "prepare_dataset.py"
spec = importlib.util.spec_from_file_location("prepare_dataset", SCRIPT)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def rows(code, count):
    return [{"codes": [[code] * 16]} for _ in range(count)]


class EncoderGuardTests(unittest.TestCase):
    def test_reported_silence_endings_are_allowed(self):
        prepare.check_encoder_pad_frames(rows(482, 951) + rows(10, 2))

    def test_other_common_endings_are_allowed(self):
        prepare.check_encoder_pad_frames(rows(100, 30))

    def test_known_artifact_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "codebook-0 = 455"):
            prepare.check_encoder_pad_frames(rows(455, 951) + rows(482, 2))

    def test_original_thresholds_are_preserved(self):
        prepare.check_encoder_pad_frames([])
        prepare.check_encoder_pad_frames(rows(455, 19))
        prepare.check_encoder_pad_frames(rows(455, 10) + rows(482, 10))
        with self.assertRaises(SystemExit):
            prepare.check_encoder_pad_frames(rows(455, 11) + rows(482, 9))


if __name__ == "__main__":
    unittest.main()
