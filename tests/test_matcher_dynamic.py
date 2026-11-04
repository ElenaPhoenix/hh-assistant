from matcher import (
    _matches_any_query,
    _get_aggregated_skills,
    _cleanup_stale_processed,
    _check_vacancy_area,
)


def test_matches_any_query_filter1_target_in_name(random_string, random_vacancy_name):
    t = random_string()
    queries = [{"target_title": t, "exclude_words": [], "core_keywords": []}]
    assert (
        _matches_any_query(f"{random_vacancy_name()} {t}", random_string(), queries)
        is True
    )


def test_matches_any_query_filter2_keyword_in_description(
    random_string, random_vacancy_name
):
    k = random_string()
    queries = [{"target_title": "", "exclude_words": [], "core_keywords": [k]}]
    assert (
        _matches_any_query(random_vacancy_name(), f"{random_string()} {k}", queries)
        is True
    )


def test_matches_any_query_exclude_in_name(random_string, random_vacancy_name):
    t, e = random_string(), random_string()
    queries = [{"target_title": t, "exclude_words": [e], "core_keywords": []}]
    assert (
        _matches_any_query(f"{random_vacancy_name()} {e} {t}", random_string(), queries)
        is False
    )


def test_aggregated_skills_random(random_string):
    k = random_string()
    resume_data = {"key_skills": [k]}
    queries = [{"target_title": "", "exclude_words": [], "core_keywords": []}]
    assert k in _get_aggregated_skills(resume_data, queries)


def test_cleanup_stale_processed(mock_vacancy_data, temp_env):
    mock_vacancy_data["full_description"] = ""
    vacancies = {123456: mock_vacancy_data}
    processed_ids = {123456, 999}

    state = {"resumes": {"test_rid": {"processed_vacancy_ids": {"q1": [123456, 999]}}}}

    removed = _cleanup_stale_processed(
        state, "test_rid", "q1", processed_ids, vacancies
    )

    assert removed == 1
    assert 123456 not in processed_ids
    assert 999 in processed_ids
    # Проверяем, что в state обновилось
    assert state["resumes"]["test_rid"]["processed_vacancy_ids"]["q1"] == [999]


def test_check_vacancy_area_remote():
    query = {"work_formats": ["remote"]}
    resume_data = {"city_id": "1"}

    # Удаленка из любого города подходит
    vacancy = {"area_id": "2", "work_formats": ["REMOTE"]}
    assert _check_vacancy_area(vacancy, query, resume_data) is True


def test_check_vacancy_area_office_moscow():
    query = {"work_formats": ["office", "hybrid"]}
    resume_data = {"city_id": "1"}  # Москва

    # Офис в Москве - подходит
    v_ok = {"area_id": "1", "work_formats": ["ON_SITE"]}
    assert _check_vacancy_area(v_ok, query, resume_data) is True

    # Офис в Питере - НЕ подходит
    v_bad = {"area_id": "2", "work_formats": ["ON_SITE"]}
    assert _check_vacancy_area(v_bad, query, resume_data) is False


def test_check_vacancy_area_unknown_format():
    query = {"work_formats": ["office"]}
    resume_data = {"city_id": "1"}

    # Старая вакансия без формата - принимается
    vacancy = {"area_id": "2", "work_formats": []}
    assert _check_vacancy_area(vacancy, query, resume_data) is True
