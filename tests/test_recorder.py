import unittest

import numpy as np

from dictator.recorder import SAMPLE_RATE, _capture_block, _open_attempts


class OpenAttemptTests(unittest.TestCase):
    def test_16k_mono_is_first_when_device_differs(self) -> None:
        attempts = _open_attempts(48000, 2, None)
        self.assertEqual(attempts[0], (SAMPLE_RATE, 1, None))
        self.assertIn((48000, 2, None), attempts)

    def test_wasapi_conversion_is_tried_before_plain_16k(self) -> None:
        marker = object()
        attempts = _open_attempts(16000, 1, marker)  # type: ignore[arg-type]
        self.assertEqual(attempts[0][0], SAMPLE_RATE)
        self.assertIs(attempts[0][2], marker)
        self.assertEqual(attempts[1], (SAMPLE_RATE, 1, None))


class CaptureBlockTests(unittest.TestCase):
    def test_mono_block_survives_reuse_of_portaudio_buffer(self) -> None:
        buffer = np.zeros((512, 1), np.float32)
        buffer[:] = 0.25
        copied = _capture_block(buffer, 1)
        buffer[:] = 0
        self.assertEqual(float(copied[0]), 0.25)
        self.assertFalse(np.shares_memory(copied, buffer))


if __name__ == "__main__":
    unittest.main()
