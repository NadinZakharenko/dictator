import unittest

from dictator.recorder import FRAME_SAMPLES, SAMPLE_RATE, SilenceTracker


class SilenceTrackerTests(unittest.TestCase):
    def test_leading_silence_does_not_stop(self) -> None:
        tracker = SilenceTracker(1.5)
        self.assertFalse(tracker.feed(False, SAMPLE_RATE * 5))
        self.assertFalse(tracker.heard_speech)

    def test_stops_after_silence_following_speech(self) -> None:
        tracker = SilenceTracker(1.5)
        self.assertFalse(tracker.feed(True, FRAME_SAMPLES))
        self.assertFalse(tracker.feed(False, SAMPLE_RATE))
        self.assertTrue(tracker.feed(False, SAMPLE_RATE))
        self.assertTrue(tracker.heard_speech)

    def test_speech_resets_silence_run(self) -> None:
        tracker = SilenceTracker(1.0)
        tracker.feed(True, FRAME_SAMPLES)
        tracker.feed(False, SAMPLE_RATE - 1)
        tracker.feed(True, FRAME_SAMPLES)
        self.assertFalse(tracker.feed(False, SAMPLE_RATE - 1))
        self.assertTrue(tracker.feed(False, 1))

    def test_rejects_non_positive_timeout(self) -> None:
        with self.assertRaises(ValueError):
            SilenceTracker(0)


if __name__ == "__main__":
    unittest.main()
