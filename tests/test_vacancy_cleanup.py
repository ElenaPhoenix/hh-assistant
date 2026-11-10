from datetime import datetime

from vacancy_cleanup import (
    _safe_int,
    _parse_period_input,
    _action_clear_period,
)
from utils import save_vacancies, load_vacancies

# --- _safe_int ---


def test_safe_int_from_int():
    assert _safe_int(42) == 42


def test_safe_int_from_str_int():
    assert _safe_int("42") == 42


def test_safe_int_from_str_non_int():
    assert _safe_int("abc") is None


def test_safe_int_from_none():
    assert _safe_int(None) is None


def test_safe_int_from_float():
    assert _safe_int(42.9) == 42


# --- _parse_period_input ---


def test_parse_period_one_date_returns_none_to():
    """Одна дата -> d2 = None (значит, надо спросить вид периода)."""
    status, d1, d2 = _parse_period_input("2026-01-15")
    assert status == "ok"
    assert d1 == datetime(2026, 1, 15)
    assert d2 is None


def test_parse_period_two_dates_space():
    status, d1, d2 = _parse_period_input("2026-01-15 2026-02-20")
    assert status == "ok"
    assert d1 == datetime(2026, 1, 15)
    assert d2 == datetime(2026, 2, 20)


def test_parse_period_two_dates_reversed():
    status, d1, d2 = _parse_period_input("2026-02-20 2026-01-15")
    assert status == "ok"
    assert d1 == datetime(2026, 1, 15)
    assert d2 == datetime(2026, 2, 20)


def test_parse_period_two_dates_comma():
    status, d1, d2 = _parse_period_input("2026-01-15, 2026-02-20")
    assert status == "ok"
    assert d1 == datetime(2026, 1, 15)
    assert d2 == datetime(2026, 2, 20)


def test_parse_period_two_dates_comma_no_space():
    status, d1, d2 = _parse_period_input("2026-01-15,2026-02-20")
    assert status == "ok"
    assert d1 == datetime(2026, 1, 15)
    assert d2 == datetime(2026, 2, 20)


def test_parse_period_single_digit_month_day():
    status, d1, d2 = _parse_period_input("2026-1-5")
    assert status == "ok"
    assert d1 == datetime(2026, 1, 5)
    assert d2 is None


def test_parse_period_cancel():
    status, d1, d2 = _parse_period_input("0")
    assert status == "cancel"
    assert d1 is None
    assert d2 is None


def test_parse_period_empty():
    status, d1, d2 = _parse_period_input("")
    assert status == "error"


def test_parse_period_no_dates():
    status, d1, d2 = _parse_period_input("вчера сегодня")
    assert status == "error"


def test_parse_period_too_many_dates():
    status, d1, d2 = _parse_period_input("2026-01-01 2026-01-02 2026-01-03")
    assert status == "error"


def test_parse_period_invalid_date():
    status, d1, d2 = _parse_period_input("2026-13-45")
    assert status == "error"


# --- _action_clear_period: две даты ---


def test_action_clear_period_removes_in_range(temp_env, monkeypatch):
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2026-01-10T12:00:00+00:00"},
            2: {"id": 2, "published_at": "2026-02-15T12:00:00+00:00"},
            3: {"id": 3, "published_at": "2026-03-20T12:00:00+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2026-01-01 2026-02-28")
    monkeypatch.setattr("vacancy_cleanup.ask_yes_no", lambda *a, **kw: True)

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 not in remaining
    assert 2 not in remaining
    assert 3 in remaining


def test_action_clear_period_two_dates_inclusive_boundaries(temp_env, monkeypatch):
    """Обе даты включительно: вакансия ровно в день from и ровно в день to."""
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2026-01-15T00:00:00+00:00"},
            2: {"id": 2, "published_at": "2026-02-20T23:59:59+00:00"},
            3: {"id": 3, "published_at": "2026-01-14T23:59:59+00:00"},
            4: {"id": 4, "published_at": "2026-02-21T00:00:00+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2026-01-15 2026-02-20")
    monkeypatch.setattr("vacancy_cleanup.ask_yes_no", lambda *a, **kw: True)

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 not in remaining  # ровно from
    assert 2 not in remaining  # ровно to
    assert 3 in remaining  # на день раньше
    assert 4 in remaining  # на день позже


def test_action_clear_period_cancel_keeps_vacancies(temp_env, monkeypatch):
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2026-01-10T12:00:00+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "0")

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 in remaining


def test_action_clear_period_empty_db(temp_env, monkeypatch):
    save_vacancies({})
    _action_clear_period()
    assert load_vacancies() == {}


# --- _action_clear_period: одна дата, выбор варианта ---


def test_action_clear_period_single_day(temp_env, monkeypatch):
    """Одна дата + "только этот день" - удаляется только этот день."""
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2026-01-15T10:00:00+00:00"},
            2: {"id": 2, "published_at": "2026-01-15T23:59:59+00:00"},
            3: {"id": 3, "published_at": "2026-01-16T00:00:00+00:00"},
            4: {"id": 4, "published_at": "2026-01-14T23:59:59+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2026-01-15")
    monkeypatch.setattr("vacancy_cleanup.ask_choice", lambda *a, **kw: "day")
    monkeypatch.setattr("vacancy_cleanup.ask_yes_no", lambda *a, **kw: True)

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 not in remaining
    assert 2 not in remaining
    assert 3 in remaining
    assert 4 in remaining


def test_action_clear_period_until_new(temp_env, monkeypatch):
    """Одна дата + "по самый новый" - с этой даты до максимальной в базе."""
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2026-01-10T12:00:00+00:00"},
            2: {"id": 2, "published_at": "2026-01-15T12:00:00+00:00"},
            3: {"id": 3, "published_at": "2026-03-20T12:00:00+00:00"},
            4: {"id": 4, "published_at": "2026-05-01T12:00:00+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2026-01-15")
    monkeypatch.setattr("vacancy_cleanup.ask_choice", lambda *a, **kw: "until_new")
    monkeypatch.setattr("vacancy_cleanup.ask_yes_no", lambda *a, **kw: True)

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 in remaining  # до from_d
    assert 2 not in remaining  # ровно from_d
    assert 3 not in remaining
    assert 4 not in remaining  # ровно max


def test_action_clear_period_until_old(temp_env, monkeypatch):
    """Одна дата + "с самого старого" - от минимальной в базе до этой."""
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2025-06-01T12:00:00+00:00"},
            2: {"id": 2, "published_at": "2025-12-31T12:00:00+00:00"},
            3: {"id": 3, "published_at": "2026-01-15T12:00:00+00:00"},
            4: {"id": 4, "published_at": "2026-02-20T12:00:00+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2026-01-15")
    monkeypatch.setattr("vacancy_cleanup.ask_choice", lambda *a, **kw: "until_old")
    monkeypatch.setattr("vacancy_cleanup.ask_yes_no", lambda *a, **kw: True)

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 not in remaining  # ровно min
    assert 2 not in remaining
    assert 3 not in remaining  # ровно to_d
    assert 4 in remaining


def test_action_clear_period_single_date_cancel(temp_env, monkeypatch):
    """Одна дата, но пользователь отменил подменю 0."""
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2026-01-15T12:00:00+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2026-01-15")
    monkeypatch.setattr("vacancy_cleanup.ask_choice", lambda *a, **kw: None)

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 in remaining


def test_action_clear_period_until_new_no_overlap(temp_env, monkeypatch):
    """Дата из будущего + "по самый новый" -> ничего не удалится."""
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2026-01-15T12:00:00+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2030-01-01")
    monkeypatch.setattr("vacancy_cleanup.ask_choice", lambda *a, **kw: "until_new")

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 in remaining


def test_action_clear_period_until_old_no_overlap(temp_env, monkeypatch):
    """Дата из прошлого + "с самого старого" -> ничего не удалится."""
    save_vacancies(
        {
            1: {"id": 1, "published_at": "2026-01-15T12:00:00+00:00"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2020-01-01")
    monkeypatch.setattr("vacancy_cleanup.ask_choice", lambda *a, **kw: "until_old")

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 in remaining


def test_action_clear_period_no_dates_in_db(temp_env, monkeypatch):
    """В базе нет вакансий с датами - функция выходит без изменений."""
    save_vacancies(
        {
            1: {"id": 1, "published_at": None},
            2: {"id": 2, "published_at": "мусор"},
        }
    )

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2026-01-15")
    monkeypatch.setattr("vacancy_cleanup.ask_choice", lambda *a, **kw: "until_new")

    _action_clear_period()

    remaining = load_vacancies()
    assert 1 in remaining
    assert 2 in remaining
