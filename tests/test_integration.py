import json
import os
import random
import pytest
from unittest.mock import patch
from conftest import random_string, random_id, random_vacancy_name

from matcher import match_resume
from state_helper import load_state, get_processed_ids


@pytest.fixture
def dynamic_environment(tmp_path, monkeypatch):
    """Создает полностью случайное окружение, где вакансии ГАРАНТИРОВАННО содержат target_title."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    os.makedirs(data_dir / "matches", exist_ok=True)
    os.makedirs(data_dir / "resumes", exist_ok=True)

    # Изоляция путей
    monkeypatch.setattr("utils.CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr("utils.RESUMES_DIR", str(data_dir / "resumes"))
    monkeypatch.setattr("utils.MATCHES_DIR", str(data_dir / "matches"))
    monkeypatch.setattr(
        "matcher.VACANCIES_FILE", str(data_dir / "vacancies_detailed.json")
    )
    monkeypatch.setattr("matcher.MATCHES_DIR", str(data_dir / "matches"))
    monkeypatch.setattr("matcher.RESUMES_DIR", str(data_dir / "resumes"))
    monkeypatch.setattr("state_helper.STATE_FILE", str(tmp_path / "state.json"))

    # Генерируем 2 резюме, у каждого 3 запроса с уникальными target_title
    config = {"resumes": [], "threshold": 65, "auto_apply": False}
    resume_ids = []
    all_target_titles = []  # Собираем все target_title из всех запросов

    for _ in range(2):
        queries = []
        for _ in range(3):
            target = random_string("title_")
            all_target_titles.append(target)
            queries.append(
                {
                    "name": random_string("q_"),
                    "target_title": target,
                    "exclude_words": [],  # Пустые, чтобы ничего не отбрасывалось
                    "core_keywords": [random_string("kw_")],
                }
            )
        resume_id = random_string("res_", 10)
        resume_ids.append(resume_id)
        config["resumes"].append(
            {
                "url": f"https://hh.ru/resume/{resume_id}",
                "queries": queries,
            }
        )

    with open(tmp_path / "config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False)

    # Создаем 10 вакансий, в названиях которых ЦИКЛИЧЕСКИ распределены target_title
    # Это гарантирует, что каждый target_title встретится хотя бы раз
    vacancies = []
    for i in range(10):
        title = all_target_titles[i % len(all_target_titles)]
        vacancies.append(
            {
                "id": random_id(),
                "name": f"{title} {random_string('extra_')}",
                "employer": random_string("emp_"),
                "full_description": random_string("desc_"),
            }
        )

    with open(data_dir / "vacancies_detailed.json", "w", encoding="utf-8") as f:
        json.dump(vacancies, f, ensure_ascii=False)

    # Создаем файлы резюме
    for rid in resume_ids:
        with open(data_dir / "resumes" / f"{rid}.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "title": random_string("Title_"),
                    "full_text": random_string("Text_"),
                    "url": f"https://hh.ru/resume/{rid}",
                    "resume_id": rid,
                    "key_skills": [random_string("skill_") for _ in range(3)],
                },
                f,
                ensure_ascii=False,
            )

    return {
        "tmp_path": tmp_path,
        "resume_ids": resume_ids,
        "vacancies": vacancies,
        "config": config,
    }


@patch("matcher.CrossEncoder")
def test_all_queries_are_processed(mock_cross_encoder, dynamic_environment):
    """Проверяет, что ВСЕ запросы из конфига обрабатываются (а не только первый)."""
    env = dynamic_environment
    mock_instance = mock_cross_encoder.return_value
    mock_instance.predict.return_value = [0.90] * len(env["vacancies"])

    resume_id = env["resume_ids"][0]
    match_resume(resume_id, config_index=0)

    state = load_state()
    processed = get_processed_ids(state, resume_id)

    # Хотя бы одна вакансия обработана
    assert len(processed) > 0
    # Обработано не меньше вакансий, чем запросов (каждый запрос увидел хотя бы одну)
    assert len(processed) >= len(env["config"]["resumes"][0]["queries"])


@patch("matcher.CrossEncoder")
def test_resumes_are_isolated(mock_cross_encoder, dynamic_environment):
    """Проверяет, что при смене резюме результаты не пересекаются."""
    env = dynamic_environment
    mock_instance = mock_cross_encoder.return_value
    mock_instance.predict.return_value = [0.90] * len(env["vacancies"])

    rid1 = env["resume_ids"][0]
    rid2 = env["resume_ids"][1]

    match_resume(rid1, config_index=0)
    match_resume(rid2, config_index=1)

    state = load_state()
    processed1 = get_processed_ids(state, rid1)
    processed2 = get_processed_ids(state, rid2)

    # Оба резюме обработали хотя бы по одной вакансии
    assert len(processed1) > 0
    assert len(processed2) > 0

    # Множества не идентичны (уникальные target_title у каждого резюме)
    assert processed1 != processed2
