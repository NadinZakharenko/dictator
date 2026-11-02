import os
import unittest

from dictator.instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_in_the_same_session_is_rejected(self) -> None:
        name = f"Local\\DictatorTest{os.getpid()}"
        first = SingleInstance(name)
        self.addCleanup(first.close)
        self.assertFalse(first.already_running)
        second = SingleInstance(name)
        self.assertTrue(second.already_running)
        self.assertIsNone(second._handle)


if __name__ == "__main__":
    unittest.main()
