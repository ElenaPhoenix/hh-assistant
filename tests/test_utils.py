import pytest
import random
import string
from conftest import random_string
from utils import normalize, clean_text, encode_url


def test_normalize_random():
    """Проверяет, что normalize корректно обрабатывает ЛЮБЫЕ строки."""
    for _ in range(50):
        text = random_string()
        # normalize приводит к нижнему регистру
        assert normalize(text) == text.lower()
        # normalize убирает лишние пробелы
        assert normalize(f"  {text}  ") == text.lower()
        # normalize заменяет спецсимволы на пробел
        special = "/- _|\\"
        test_str = "a" + random.choice(special) + "b"
        assert normalize(test_str) == "a b"


def test_clean_text_random():
    """Проверяет, что clean_text убирает лишние переносы и пробелы."""
    for _ in range(50):
        word = random_string()
        text = f"{word}\n\n\n{word}\t\t{word}"
        result = clean_text(text)
        # Не должно быть двойных пробелов и переносов
        assert "\n" not in result
        assert "  " not in result
        assert result.startswith(word)


def test_encode_url_random():
    """Проверяет, что кодирование URL работает для любых символов."""
    for _ in range(50):
        text = random_string()
        encoded = encode_url(text)
        # Латиница и цифры не кодируются
        if all(c in string.ascii_letters + string.digits for c in text):
            assert encoded == text
    # Спецсимволы кодируются
    assert encode_url("/") == "%2F"
    assert encode_url(" ") == "%20"
