import unittest

from dictator.recorder import SAMPLE_RATE, _open_attempts


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


if __name__ == "__main__":
    unittest.main()
