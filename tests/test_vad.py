import unittest

import numpy as np

from dictator.recorder import FRAME_SAMPLES, StreamingVad


class StreamingVadTests(unittest.TestCase):
    def test_silence_is_not_speech(self) -> None:
        vad = StreamingVad()
        vad.reset(0.5)
        frame = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        self.assertFalse(vad.is_speech(frame))
        self.assertFalse(vad.is_speech(frame))


if __name__ == "__main__":
    unittest.main()
