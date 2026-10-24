import pytest
import random
from conftest import random_string, random_id, random_vacancy_name
from matcher import _matches_any_query, _get_aggregated_skills


def test_matches_any_query_random():
    """Проверяет, что вакансия проходит хотя бы по одному из случайных запросов."""
    for _ in range(50):
        query1_target = random_string("q1_")
        query2_target = random_string("q2_")
        query3_target = random_string("q3_")

        queries = [
            {"target_title": query1_target, "exclude_words": []},
            {"target_title": query2_target, "exclude_words": []},
            {"target_title": query3_target, "exclude_words": []},
        ]

        # Содержит первый
        name = f"Vacancy {query1_target}"
        assert _matches_any_query(name, queries) is True

        # Содержит третий
        name = f"Vacancy {query3_target}"
        assert _matches_any_query(name, queries) is True

        # Не содержит ни одного
        name = f"Vacancy {random_string()}"
        assert _matches_any_query(name, queries) is False


def test_aggregated_skills_random():
    """Проверяет объединение навыков из резюме и всех запросов."""
    for _ in range(50):
        resume_skills = [random_string("skill_") for _ in range(3)]
        query1_kw = random_string("kw1_")
        query2_kw = random_string("kw2_")

        queries = [
            {"core_keywords": [query1_kw]},
            {"core_keywords": [query2_kw]},
        ]

        resume_data = {"key_skills": resume_skills}
        result = set(_get_aggregated_skills(resume_data, queries))

        # Все навыки должны быть в результате
        for s in resume_skills:
            assert s in result
        assert query1_kw in result
        assert query2_kw in result
