from unittest.mock import patch
from config import _action_change_threshold


def test_change_threshold(temp_env):
    config = {"threshold": 65}

    with patch("config.ask_int", return_value=80):
        changed = _action_change_threshold(config)

    assert changed is True
    assert config["threshold"] == 80


def test_change_threshold_cancel(temp_env):
    config = {"threshold": 65}

    with patch("config.ask_int", return_value=None):
        changed = _action_change_threshold(config)

    assert changed is False
    assert config["threshold"] == 65
