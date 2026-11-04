import pytest
from unittest.mock import patch
from apply_via_api import process_vacancy
from state_helper import load_state, get_resume_state, add_needs_test, save_state


@patch("apply_via_api.check_vacancy_status")
@patch("apply_via_api.send_negotiation")
def test_process_vacancy_archived(mock_send, mock_status, mock_vacancy_data, temp_env):
    state = load_state()
    add_needs_test(state, "test_rid", {"id": 123456})
    save_state(state)

    mock_status.return_value = "archived"

    status, remove = process_vacancy(
        mock_vacancy_data, "test_rid", "text", None, state, False, "q1", "Q1", "Name"
    )

    assert status == "denied"
    assert remove is True
    rs = get_resume_state(state, "test_rid")
    assert 123456 in rs["denied_vacancy_ids"]
    assert len(rs["needs_test"]) == 0
    mock_send.assert_not_called()


@patch("apply_via_api.check_vacancy_status")
def test_process_vacancy_test_required(mock_status, mock_vacancy_data, temp_env):
    state = load_state()
    mock_status.return_value = "test_required"

    status, remove = process_vacancy(
        mock_vacancy_data, "test_rid", "text", None, state, False, "q1", "Q1", "Name"
    )

    assert status == "test_required"
    assert remove is False
    rs = get_resume_state(state, "test_rid")
    assert len(rs["needs_test"]) == 1
    assert rs["needs_test"][0]["id"] == 123456


@patch("apply_via_api.check_vacancy_status")
@patch("apply_via_api.send_negotiation")
def test_process_vacancy_unknown(mock_send, mock_status, mock_vacancy_data, temp_env):
    state = load_state()
    mock_status.return_value = "unknown"

    status, remove = process_vacancy(
        mock_vacancy_data, "test_rid", "text", None, state, False, "q1", "Q1", "Name"
    )

    assert status == "failed"
    assert remove is False
    mock_send.assert_not_called()


@patch("apply_via_api.check_vacancy_status")
@patch("apply_via_api.send_negotiation")
def test_process_vacancy_captcha(mock_send, mock_status, mock_vacancy_data, temp_env):
    state = load_state()
    mock_status.return_value = "captcha"

    status, remove = process_vacancy(
        mock_vacancy_data, "test_rid", "text", None, state, False, "q1", "Q1", "Name"
    )

    assert status == "captcha"
    assert remove is False
    mock_send.assert_not_called()


@patch("apply_via_api.check_vacancy_status")
@patch("apply_via_api.send_negotiation")
def test_process_vacancy_already(mock_send, mock_status, mock_vacancy_data, temp_env):
    state = load_state()
    mock_status.return_value = "already_applied"

    status, remove = process_vacancy(
        mock_vacancy_data, "test_rid", "text", None, state, False, "q1", "Q1", "Name"
    )

    assert status == "already"
    rs = get_resume_state(state, "test_rid")
    assert 123456 in rs["applied_vacancy_ids"]
    mock_send.assert_not_called()


@patch("apply_via_api.check_vacancy_status")
@patch("apply_via_api.generate_letter")
@patch("apply_via_api.send_negotiation")
def test_process_vacancy_limit_exceeded(
    mock_send, mock_gen, mock_status, mock_vacancy_data, temp_env
):
    state = load_state()
    mock_status.return_value = "ok"
    mock_gen.return_value = ("Letter", None)
    mock_send.return_value = ("limit_exceeded", "limit")

    status, remove = process_vacancy(
        mock_vacancy_data, "test_rid", "text", None, state, False, "q1", "Q1", "Name"
    )

    assert status == "limit_exceeded"
    assert remove is False


@patch("apply_via_api.check_vacancy_status")
@patch("apply_via_api.generate_letter")
@patch("apply_via_api.send_negotiation")
def test_process_vacancy_auth_required(
    mock_send, mock_gen, mock_status, mock_vacancy_data, temp_env
):
    state = load_state()
    mock_status.return_value = "ok"
    mock_gen.return_value = ("Letter", None)
    mock_send.return_value = ("auth_required", "auth")

    status, remove = process_vacancy(
        mock_vacancy_data, "test_rid", "text", None, state, False, "q1", "Q1", "Name"
    )

    assert status == "auth_required"
    assert remove is False


@patch("apply_via_api.check_vacancy_status")
@patch("apply_via_api.generate_letter")
@patch("apply_via_api.send_negotiation")
def test_process_vacancy_sent_ok(
    mock_send, mock_gen, mock_status, mock_vacancy_data, temp_env
):
    state = load_state()
    mock_status.return_value = "ok"
    mock_gen.return_value = ("Letter text", None)
    mock_send.return_value = ("ok", "ok")

    status, remove = process_vacancy(
        mock_vacancy_data, "test_rid", "text", None, state, False, "q1", "Q1", "Name"
    )

    assert status == "sent"
    rs = get_resume_state(state, "test_rid")
    assert 123456 in rs["applied_vacancy_ids"]
