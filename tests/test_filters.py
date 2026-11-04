from filters import check_vacancy_relevance


def test_exact_match():
    # Точное совпадение target_title в названии
    assert check_vacancy_relevance("Python developer", "", "python", [], []) is True


def test_short_word_exact():
    # "sql" (3 символа) - только точное совпадение в core_keywords
    assert check_vacancy_relevance("", "Requires SQL", "", [], ["sql"]) is True
    assert check_vacancy_relevance("", "Requires MySQL", "", [], ["sql"]) is False


def test_long_word_levenshtein():
    # "python" (6 символов) - 1-2 ошибки разрешены в core_keywords
    assert check_vacancy_relevance("", "Requires pyton", "", [], ["python"]) is True
    assert check_vacancy_relevance("", "Requires pythom", "", [], ["python"]) is True
    assert check_vacancy_relevance("", "Requires pitone", "", [], ["python"]) is False


def test_special_chars_exact():
    # c#, c++ - только точное совпадение в core_keywords
    assert check_vacancy_relevance("", "C# developer", "", [], ["c#"]) is True
    assert check_vacancy_relevance("", "C developer", "", [], ["c#"]) is False
    assert check_vacancy_relevance("", "C++ developer", "", [], ["c++"]) is True
    assert check_vacancy_relevance("", "Cpp developer", "", [], ["c++"]) is False


def test_target_phrase_match():
    # Фраза (слова рядом в том же порядке) в target_title
    assert (
        check_vacancy_relevance(
            "Senior Python developer", "", "python developer", [], []
        )
        is True
    )
    assert (
        check_vacancy_relevance(
            "Python senior developer", "", "python developer", [], []
        )
        is False
    )


def test_target_phrase_with_error():
    # Опечатка в target_title (1-2 символа)
    assert (
        check_vacancy_relevance(
            "Senior Pythom developer", "", "python developer", [], []
        )
        is True
    )


def test_keyword_phrase_match():
    # Фраза в core_keywords
    assert (
        check_vacancy_relevance(
            "", "Требуется менеджер по продажам", "", [], ["менеджер по продажам"]
        )
        is True
    )
    assert (
        check_vacancy_relevance(
            "", "Требуется менеджер по продаже", "", [], ["менеджер по продажам"]
        )
        is True
    )


def test_exclude_priority():
    # Слово-исключение перекрывает target_title
    assert (
        check_vacancy_relevance("Junior Python", "", "python", ["junior"], []) is False
    )
    # Слово-исключение с опечаткой (fuzzy)
    assert (
        check_vacancy_relevance("Junoir Python", "", "python", ["junior"], []) is False
    )


def test_none_and_empty():
    assert check_vacancy_relevance("Any", None, "", [], []) is True
