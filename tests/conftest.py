import sys
import os
import random
import string

# Добавляем корень проекта в пути
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def random_string(prefix="", length=8):
    """Генерирует случайную строку из букв и цифр."""
    chars = string.ascii_letters + string.digits
    return prefix + "".join(random.choices(chars, k=length))


def random_vacancy_name(prefix=""):
    """Генерирует абсолютно случайное название вакансии (без статических слов)."""
    return f"Vacancy_{random_string(prefix, 12)}"


def random_id():
    """Генерирует случайный ID (для вакансий и откликов)."""
    return random.randint(1, 10_000_000)
