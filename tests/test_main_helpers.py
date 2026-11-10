from main import _parse_test_numbers


def test_parse_comma(temp_env):
    assert _parse_test_numbers("1,3,5", 5) == ([1, 3, 5], [])


def test_parse_space(temp_env):
    assert _parse_test_numbers("1 3 5", 5) == ([1, 3, 5], [])


def test_parse_semicolon(temp_env):
    assert _parse_test_numbers("1;3;5", 5) == ([1, 3, 5], [])


def test_parse_mixed_separators(temp_env):
    assert _parse_test_numbers("1, 3; 5", 5) == ([1, 3, 5], [])


def test_parse_invalid_values(temp_env):
    valid, invalid = _parse_test_numbers("1, 3, x, 10", 5)
    assert valid == [1, 3]
    assert invalid == ["x", "10"]


def test_parse_empty_string(temp_env):
    assert _parse_test_numbers("", 5) == ([], [])


def test_parse_duplicates_kept(temp_env):
    # Дубли не схлопываются - это ответственность вызывающего кода
    assert _parse_test_numbers("1,1,2", 5) == ([1, 1, 2], [])
