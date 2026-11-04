from unittest.mock import patch
from vacancy_search import _load_missing_details, MAX_DETAILS_CONSECUTIVE_FAILURES
from utils import save_vacancies, load_vacancies


@patch("vacancy_search.call_api", return_value=("timeout", "timeout"))
def test_load_missing_details_stops_after_limit_failures(mock_api, temp_env):
    # Создаем столько вакансий, сколько нужно для срабатывания лимита
    num_vacancies = MAX_DETAILS_CONSECUTIVE_FAILURES + 1
    save_vacancies({i: {"id": i} for i in range(1, num_vacancies + 1)})

    merged = {i: {"id": i} for i in range(1, num_vacancies + 1)}
    need_details = list(range(1, num_vacancies + 1))

    interrupted = _load_missing_details(merged, need_details)

    assert interrupted is True
    assert mock_api.call_count == MAX_DETAILS_CONSECUTIVE_FAILURES


@patch("vacancy_search.call_api")
def test_load_missing_details_success(mock_api, temp_env):
    mock_api.return_value = ("ok", {"description": "new desc"})
    save_vacancies({1: {"id": 1}, 2: {"id": 2}})

    merged = {1: {"id": 1}, 2: {"id": 2}}

    interrupted = _load_missing_details(merged, [1, 2])

    assert interrupted is False
    assert merged[1]["full_description"] == "new desc"
    assert merged[2]["full_description"] == "new desc"
