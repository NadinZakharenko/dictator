import unittest

from dictator.polish import keep_dictation


class KeepDictationTests(unittest.TestCase):
    def test_accepts_a_cleanup_of_similar_length(self) -> None:
        source = "Требуется создать приложение g/n/d*.bd и список покупок"
        cleaned = "Требуется создать приложение и список покупок"
        self.assertEqual(keep_dictation(source, cleaned), cleaned)

    def test_unwraps_quotes_and_a_label(self) -> None:
        source = "Собрать меню навигации"
        self.assertEqual(
            keep_dictation(source, "Исправлено: «Собрать меню навигации»"),
            "Собрать меню навигации",
        )

    def test_rejects_an_empty_or_much_shorter_answer(self) -> None:
        source = "Требуется создать приложение и формировать список покупок для магазина"
        self.assertEqual(keep_dictation(source, "   "), source)
        self.assertEqual(keep_dictation(source, "Список"), source)

    def test_rejects_a_lecture_instead_of_the_phrase(self) -> None:
        source = "Требуется создать приложение и формировать список покупок для магазина"
        lecture = "Ваш запрос содержит ошибки и не является корректной русской диктовкой."
        self.assertEqual(keep_dictation(source, lecture), source)

    def test_rejects_a_long_rewrite(self) -> None:
        source = "Список покупок"
        essay = source + " " + ("пояснение " * 30)
        self.assertEqual(keep_dictation(source, essay), source)


if __name__ == "__main__":
    unittest.main()
