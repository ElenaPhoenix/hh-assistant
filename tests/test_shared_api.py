from unittest.mock import patch

from shared_api import fetch_all_negotiations


@patch("shared_api.call_api")
def test_fetch_all_negotiations_success(mock_api):
    mock_api.return_value = ("ok", {"items": [{"id": 1}], "pages": 1})
    items, status = fetch_all_negotiations(per_page=100, pause=0)
    assert status == "ok"
    assert len(items) == 1
    assert items[0]["id"] == 1


@patch("shared_api.call_api")
def test_fetch_all_negotiations_captcha(mock_api):
    mock_api.return_value = ("captcha", "captcha data")
    items, status = fetch_all_negotiations(per_page=100, pause=0)
    assert status == "captcha"
    assert items == []


@patch("shared_api.call_api")
def test_fetch_all_negotiations_auth_required(mock_api):
    mock_api.return_value = ("auth_required", "auth data")
    items, status = fetch_all_negotiations(per_page=100, pause=0)
    assert status == "auth_required"
    assert items == []


@patch("shared_api.call_api")
def test_fetch_all_negotiations_empty(mock_api):
    mock_api.return_value = ("ok", {"items": [], "pages": 0})
    items, status = fetch_all_negotiations(per_page=100, pause=0)
    assert status == "ok"
    assert items == []


@patch("shared_api.call_api")
def test_fetch_all_negotiations_paginated(mock_api):
    mock_api.side_effect = [
        ("ok", {"items": [{"id": 1}, {"id": 2}], "pages": 2}),
        ("ok", {"items": [{"id": 3}], "pages": 2}),
    ]
    items, status = fetch_all_negotiations(per_page=100, pause=0)
    assert status == "ok"
    assert len(items) == 3
