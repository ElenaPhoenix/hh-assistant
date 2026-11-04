import os
import json
from utils import (
    normalize,
    clean_text,
    clear_query_hash,
    encode_url,
    load_config,
    save_config,
    load_vacancies,
    save_vacancies,
    remove_vacancies_from_cache,
)


def test_normalize(random_string):
    part1, part2 = random_string(), random_string()
    s = f"{part1}_{part2}"
    expected = s.replace("_", " ").lower().strip()
    assert normalize(s) == expected


def test_clean_text(random_string):
    s = f"{random_string()}_{random_string()}"
    assert clean_text(s) == s


def test_clear_query_hash(temp_env):
    """Проверяет, что хэш удаляется из matches.json."""
    # Создаем фейковый matches.json
    matches_dir = temp_env / "matches"
    matches_dir.mkdir()
    file_path = matches_dir / "test_resume.json"

    data = {"query_hashes": {"q1": "hash1", "q2": "hash2"}, "all": [], "passed": []}
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    clear_query_hash("test_resume", "q1")

    with open(file_path, "r", encoding="utf-8") as f:
        updated_data = json.load(f)

    assert "q1" not in updated_data["query_hashes"]
    assert "q2" in updated_data["query_hashes"]


def test_encode_url(random_string):
    s = random_string()
    assert encode_url(s) == s


def test_vacancies_cache(temp_env):
    v1 = {"id": 1, "name": "A"}
    v2 = {"id": 2, "name": "B"}

    save_vacancies({1: v1, 2: v2})
    loaded = load_vacancies()
    assert len(loaded) == 2

    removed = remove_vacancies_from_cache([1])
    assert removed == 1
    assert len(load_vacancies()) == 1
