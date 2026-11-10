from matcher import (
    _matches_any_query,
    _get_aggregated_skills,
    _cleanup_stale_processed,
    _check_vacancy_area,
    _compute_rules_score,
    TITLE_HIT_SCORE,
    KEYWORD_HIT_SCORE,
)

# ---------- базовые проверки ----------


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
    assert state["resumes"]["test_rid"]["processed_vacancy_ids"]["q1"] == [999]


def test_check_vacancy_area_remote():
    query = {"work_formats": ["remote"]}
    resume_data = {"city_id": "1"}

    vacancy = {"area_id": "2", "work_formats": ["REMOTE"]}
    assert _check_vacancy_area(vacancy, query, resume_data) is True


def test_check_vacancy_area_office_moscow():
    query = {"work_formats": ["office", "hybrid"]}
    resume_data = {"city_id": "1"}

    v_ok = {"area_id": "1", "work_formats": ["ON_SITE"]}
    assert _check_vacancy_area(v_ok, query, resume_data) is True

    v_bad = {"area_id": "2", "work_formats": ["ON_SITE"]}
    assert _check_vacancy_area(v_bad, query, resume_data) is False


def test_check_vacancy_area_unknown_format():
    query = {"work_formats": ["office"]}
    resume_data = {"city_id": "1"}

    vacancy = {"area_id": "2", "work_formats": []}
    assert _check_vacancy_area(vacancy, query, resume_data) is True


# ---------- _compute_rules_score: числа совпадений (вариативные данные) ----------
#
# Здесь входные строки генерируются через random_string: проверяется
# арифметика (TITLE_HIT_SCORE + kw_hits * KEYWORD_HIT_SCORE), а не конкретные
# строки или числа. Если константа изменится в matcher.py, тест адаптируется.
#
# target_title оставлен "аналитик" намеренно: random_string дает hex (только
# 0-9a-f), кириллица в нем не встречается - ложных совпадений быть не может.
# Это слово-сценарий, а не магическое значение.


def test_compute_score_keyword_in_description(random_string):
    tt = "аналитик"
    k1, k2 = random_string(), random_string()
    vacancy = {
        "name": f"{random_string()} {tt}",
        "full_description": f"Требуется {k1} и {k2}",
        "key_skills": "",
    }
    query = {"target_title": tt, "core_keywords": [k1, k2], "exclude_words": []}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["title_hits"] == 1
    assert meta["kw_hits"] == 2
    assert score == TITLE_HIT_SCORE + 2 * KEYWORD_HIT_SCORE


def test_compute_score_keyword_in_skills(random_string):
    tt = "аналитик"
    k1, k2, k3 = random_string(), random_string(), random_string()
    vacancy = {
        "name": f"{random_string()} {tt}",
        "full_description": random_string(),
        "key_skills": f"{k1}, {k2}, {k3}",
    }
    query = {"target_title": tt, "core_keywords": [k1, k2, k3], "exclude_words": []}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 3


def test_compute_score_keyword_in_both_no_double(random_string):
    """Одно и то же kw в описании и в навыках - считается один раз."""
    tt = "аналитик"
    k = random_string()
    vacancy = {
        "name": f"{random_string()} {tt}",
        "full_description": f"Нужен {k}",
        "key_skills": f"{k}, {random_string()}",
    }
    query = {"target_title": tt, "core_keywords": [k], "exclude_words": []}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 1


def test_compute_score_no_title(random_string):
    """Целевого слова нет в названии - 0 баллов, reason=no_title."""
    k = random_string()
    vacancy = {"name": random_string(), "full_description": k}
    query = {"target_title": "аналитик", "core_keywords": [k]}
    score, meta = _compute_rules_score(vacancy, query)
    assert score == 0
    assert meta["reason"] == "no_title"


def test_compute_score_no_kw(random_string):
    """Целевое слово есть в названии, но нет ни одного kw - 0 баллов."""
    tt = "аналитик"
    k = random_string()
    vacancy = {"name": f"{random_string()} {tt}", "full_description": random_string()}
    query = {"target_title": tt, "core_keywords": [k]}
    score, meta = _compute_rules_score(vacancy, query)
    assert score == 0
    assert meta["reason"] == "no_kw"


def test_compute_score_skills_as_list(random_string):
    """key_skills может быть списком (старый формат JSON)."""
    tt = "аналитик"
    k1, k2 = random_string(), random_string()
    vacancy = {
        "name": f"{random_string()} {tt}",
        "full_description": "",
        "key_skills": [k1, k2],
    }
    query = {"target_title": tt, "core_keywords": [k1, k2]}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 2


# ---------- _compute_rules_score: fuzzy-поиск (семантические данные) ----------
#
# Здесь нужны конкретные русские слова - без них не проверить расстояние
# Левенштейна и совпадение словоформ. Это контракт fuzzy-алгоритма,
# а не отсутствие вариативности. Числа (score) берутся из констант,
# а не пишутся вручную.


def test_compute_score_target_fuzzy_vs_substring():
    """target='аналитика' находит 'Аналитик' в названии (Левенштейн=1).

    Раньше предфильтр пропускал такую вакансию, а скоринг отсеивал:
    _compute_rules_score использовал простую подстроку 'in', а не fuzzy.
    """
    vacancy = {
        "name": "Аналитик данных",
        "full_description": "Работа с SQL",
        "key_skills": "SQL",
    }
    query = {
        "target_title": "аналитика",
        "core_keywords": ["sql"],
        "exclude_words": [],
    }
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["title_hits"] == 1
    assert score >= TITLE_HIT_SCORE


def test_compute_score_kw_forms_one_match():
    """'анализировать' в тексте + kw ['анализ','анализировать'] = 1.

    'анализ' не матчится на 'анализировать' (расстояние Левенштейна > 2),
    'анализировать' матчится на 'анализировать' один раз.
    """
    vacancy = {
        "name": "Аналитик",
        "full_description": "Умею анализировать данные",
        "key_skills": "",
    }
    query = {"target_title": "аналитик", "core_keywords": ["анализ", "анализировать"]}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 1


def test_compute_score_kw_forms_two_matches():
    """'анализу' и 'анализировать' в тексте, kw ['анализ','анализировать'] = 2."""
    vacancy = {
        "name": "Аналитик",
        "full_description": "Умею анализу данных и анализировать отчеты",
        "key_skills": "",
    }
    query = {"target_title": "аналитик", "core_keywords": ["анализ", "анализировать"]}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 2


def test_compute_score_kw_three_words_two_kws():
    """3 слова в тексте, 2 kw - 2 совпадения (жадно, не 3).

    Жадный алгоритм забирает первое подходящее слово для каждого kw.
    Одно слово не может быть засчитано дважды.
    """
    vacancy = {
        "name": "Аналитик",
        "full_description": "Анализу, анализ и анализировать",
        "key_skills": "",
    }
    query = {"target_title": "аналитик", "core_keywords": ["анализ", "анализировать"]}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 2


def test_compute_score_kw_in_skills_substring():
    """kw 'оптимизация' в навыке 'оптимизация процессов' = 1 совпадение."""
    vacancy = {
        "name": "Аналитик",
        "full_description": "",
        "key_skills": "оптимизация процессов",
    }
    query = {"target_title": "аналитик", "core_keywords": ["оптимизация"]}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 1


def test_compute_score_kw_in_desc_and_skills_no_double():
    """kw 'excel' в описании и в навыках - 1 совпадение, не 2."""
    vacancy = {
        "name": "Аналитик",
        "full_description": "Опыт работы с Excel",
        "key_skills": "Excel, Word",
    }
    query = {"target_title": "аналитик", "core_keywords": ["excel"]}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 1


def test_compute_score_multiword_kw_in_description():
    """Многословный kw 'power bi' в описании - 1 совпадение.

    Отдельная ветка в _score_keywords: для kw из 2+ слов используется
    _phrase_in_text (подряд идущие), не пул токенов.
    """
    vacancy = {
        "name": "Аналитик",
        "full_description": "Опыт работы с Power BI и Excel",
        "key_skills": "",
    }
    query = {"target_title": "аналитик", "core_keywords": ["power bi"]}
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["kw_hits"] == 1


def test_compute_score_multiple_targets_in_name():
    """Два разных target через | совпали в одном name - title_hits=2.

    Реальный сценарий: у Елены target_title содержит
    'аналитик|analyst|администратор|...'. В названии 'Аналитик, analyst'
    найдены два.
    """
    vacancy = {
        "name": "Аналитик analyst",
        "full_description": "SQL",
        "key_skills": "SQL",
    }
    query = {
        "target_title": "аналитик|analyst|администратор",
        "core_keywords": ["sql"],
    }
    score, meta = _compute_rules_score(vacancy, query)
    assert meta["reason"] == "ok"
    assert meta["title_hits"] == 2
    # Формула: TITLE_HIT_SCORE (один раз, не за каждый hit) + kw_hits * KEYWORD
    assert score == TITLE_HIT_SCORE + KEYWORD_HIT_SCORE
