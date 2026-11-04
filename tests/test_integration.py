import json
import os
from unittest.mock import patch
from matcher import _matches_any_query


def test_first_query_processed(random_string, random_vacancy_name):
    t = random_string()
    queries = [{"target_title": t, "exclude_words": [], "core_keywords": []}]
    assert (
        _matches_any_query(f"{random_vacancy_name()} {t}", random_string(), queries)
        is True
    )


def test_multiple_queries_processed_independently(random_string, random_vacancy_name):
    t1, t2 = random_string(), random_string()
    queries = [
        {"target_title": t1, "exclude_words": [], "core_keywords": []},
        {"target_title": t2, "exclude_words": [], "core_keywords": []},
    ]
    assert (
        _matches_any_query(f"{random_vacancy_name()} {t2}", random_string(), queries)
        is True
    )
    assert (
        _matches_any_query(f"{random_vacancy_name()} {t1}", random_string(), queries)
        is True
    )


def test_config_threshold_passed_to_matcher(tmp_path, monkeypatch):
    # Создаем фейковый config.json
    config_file = tmp_path / "config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump({"threshold": 90, "resumes": []}, f)

    monkeypatch.setattr("utils.CONFIG_FILE", str(config_file))

    from utils import load_config

    cfg = load_config()
    assert cfg["threshold"] == 90
