import pytest
import random
from conftest import random_string, random_vacancy_name
from filters import check_name_filters


def test_exclude_word_random():
    """Проверяет, что ЛЮБОЕ слово-исключение работает."""
    for _ in range(50):
        exclude_word = random_string("exclude_")
        # Название содержит слово-исключение
        name = f"Vacancy {exclude_word}"
        assert check_name_filters(name, "", [exclude_word]) is False
        # Название не содержит слово-исключение
        name = f"Vacancy {random_string()}"
        assert check_name_filters(name, "", [exclude_word]) is True


def test_target_title_random():
    """Проверяет, что ЛЮБОЕ целевое слово работает."""
    for _ in range(50):
        target = random_string("target_")
        # Название содержит target
        name = f"Vacancy {target} additional"
        assert check_name_filters(name, target, []) is True
        # Название не содержит target
        name = f"Vacancy {random_string()}"
        assert check_name_filters(name, target, []) is False


def test_or_logic_random():
    """Проверяет, что ЛЮБАЯ из фраз через | срабатывает."""
    for _ in range(50):
        t1 = random_string("t1_")
        t2 = random_string("t2_")
        t3 = random_string("t3_")
        target = f"{t1}|{t2}|{t3}"
        # Проверяем каждое слово
        assert check_name_filters(f"Vacancy {t1}", target, []) is True
        assert check_name_filters(f"Vacancy {t2}", target, []) is True
        assert check_name_filters(f"Vacancy {t3}", target, []) is True
        # Не содержит ни одного
        assert check_name_filters(f"Vacancy {random_string()}", target, []) is False


def test_none_and_empty_inputs():
    """Пустые/None значения не ломают логику."""
    # Используем случайные строки для target_title
    assert check_name_filters(None, random_string(), []) is False
    assert check_name_filters("", random_string(), []) is False
    assert check_name_filters(random_string(), "", []) is True
    assert check_name_filters(random_string(), None, []) is True
    assert check_name_filters(random_string(), "", [None]) is True
    assert check_name_filters(random_string(), "", [""]) is True
    assert check_name_filters(random_string(), "", ["  "]) is True
