import pytest
from unittest.mock import MagicMock, patch
from db import db_cursor


@patch("db.get_connection")
def test_db_cursor_success(mock_get_conn):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_get_conn.return_value = mock_conn

    with db_cursor() as cur:
        cur.execute("SELECT 1")

    mock_conn.commit.assert_called_once()
    mock_cur.close.assert_called_once()
    mock_conn.close.assert_called_once()


@patch("db.get_connection")
def test_db_cursor_rollback(mock_get_conn):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_get_conn.return_value = mock_conn

    with pytest.raises(ValueError):
        with db_cursor() as cur:
            raise ValueError("Test error")

    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()
