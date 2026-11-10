from unittest.mock import patch

from ui_helper import ask_yes_no, plural


def test_plural_one():
    assert plural(1, "вакансия", "вакансии", "вакансий") == "вакансия"
    assert plural(21, "вакансия", "вакансии", "вакансий") == "вакансия"


def test_plural_few():
    assert plural(2, "вакансия", "вакансии", "вакансий") == "вакансии"
    assert plural(3, "вакансия", "вакансии", "вакансий") == "вакансии"
    assert plural(22, "вакансия", "вакансии", "вакансий") == "вакансии"


def test_plural_many():
    assert plural(5, "вакансия", "вакансии", "вакансий") == "вакансий"
    assert plural(11, "вакансия", "вакансии", "вакансий") == "вакансий"
    assert plural(111, "вакансия", "вакансии", "вакансий") == "вакансий"


def test_ask_yes_no_russian():
    with patch("builtins.input", return_value="д"):
        assert ask_yes_no("?") is True
    with patch("builtins.input", return_value="да"):
        assert ask_yes_no("?") is True
    with patch("builtins.input", return_value="н"):
        assert ask_yes_no("?") is False
    with patch("builtins.input", return_value="нет"):
        assert ask_yes_no("?") is False


def test_ask_yes_no_english_layout():
    # В английской раскладке "д" дает "l", "н" дает "y"
    with patch("builtins.input", return_value="l"):
        assert ask_yes_no("?") is True
    with patch("builtins.input", return_value="lf"):
        assert ask_yes_no("?") is True
    with patch("builtins.input", return_value="y"):
        assert ask_yes_no("?") is False
    with patch("builtins.input", return_value="ytn"):
        assert ask_yes_no("?") is False


def test_ask_yes_no_cancel():
    with patch("builtins.input", return_value="0"):
        assert ask_yes_no("?", allow_cancel=True) is None


def test_ask_yes_no_retries_on_bad_input():
    """После двух некорректных вводов - два сообщения об ошибке."""
    with patch("builtins.input", side_effect=["xyz", "garbage", "д"]):
        with patch("ui_helper.print_error") as mock_err:
            assert ask_yes_no("?") is True
    assert mock_err.call_count == 2
