import pytest
import random
from conftest import random_string, random_id
from dedupe import dedupe_passed


def test_dedupe_random():
    """Проверяет дедупликацию для ЛЮБЫХ случайных наборов данных."""
    for _ in range(20):
        employer = random_string("emp_")
        name = random_string("name_")
        score = round(random.uniform(50, 100), 1)
        count = random.randint(1, 5)

        passed = [
            {
                "id": random_id(),
                "employer": employer,
                "name": name,
                "match_score": score,
            }
            for _ in range(count)
        ]

        result = dedupe_passed(passed)
        # Все элементы одинаковые, должен остаться ровно 1
        assert len(result) == 1
        # Остался первый
        assert result[0]["employer"] == employer
        assert result[0]["name"] == name
        assert result[0]["match_score"] == score


def test_dedupe_keeps_different():
    """Проверяет, что вакансии с разными полями НЕ схлопываются."""
    for _ in range(20):
        employer = random_string("emp_")
        name = random_string("name_")
        score = round(random.uniform(50, 100), 1)

        passed = [
            {
                "id": random_id(),
                "employer": employer,
                "name": name,
                "match_score": score,
            },
            {
                "id": random_id(),
                "employer": random_string(),
                "name": name,
                "match_score": score,
            },
            {
                "id": random_id(),
                "employer": employer,
                "name": random_string(),
                "match_score": score,
            },
            {
                "id": random_id(),
                "employer": employer,
                "name": name,
                "match_score": score + 1,
            },
        ]

        result = dedupe_passed(passed)
        assert len(result) == 4


def test_dedupe_case_and_whitespace():
    """Проверяет, что регистр и пробелы не влияют на дедупликацию."""
    for _ in range(20):
        base = random_string("case_")
        passed = [
            {
                "id": random_id(),
                "employer": " " + base.upper() + " ",
                "name": " " + base + " ",
                "match_score": 90,
            },
            {"id": random_id(), "employer": base, "name": base, "match_score": 90},
        ]
        result = dedupe_passed(passed)
        assert len(result) == 1
