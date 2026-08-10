import json
import os
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock
import pytest

from src.database import init_db, get_setting, set_setting
from src.plex.auth import request_plex_pin, poll_plex_pin, verify_plex_connection

@pytest.fixture
def db_path(tmp_path):
    db_file = tmp_path / "netplex.db"
    init_db(str(db_file))
    return str(db_file)

def test_request_plex_pin(db_path):
    client_id = get_setting(db_path, "plex_client_id")
    assert client_id is not None

    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "plex_pin_response.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture_data = json.load(f)

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(fixture_data).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = request_plex_pin(db_path)
        
        assert result["id"] == 12345678
        assert result["code"] == "H9RX"
        assert f"code=H9RX" in result["auth_url"]
        assert f"clientID={client_id}" in result["auth_url"]

        # Verify request parameters
        called_req = mock_urlopen.call_args[0][0]
        assert called_req.get_full_url() == "https://plex.tv/api/v2/pins"
        assert called_req.headers["X-plex-product"] == "NetPlex"
        assert called_req.headers["X-plex-client-identifier"] == client_id

def test_request_plex_pin_missing_client_id(tmp_path):
    # DB without init_db seeding
    db_file = tmp_path / "empty.db"
    conn = init_db(str(db_file))
    # Explicitly clear plex_client_id
    import sqlite3
    c = sqlite3.connect(str(db_file))
    c.execute("DELETE FROM settings WHERE key = 'plex_client_id'")
    c.commit()
    c.close()

    with pytest.raises(ValueError, match="plex_client_id setting is missing"):
        request_plex_pin(str(db_file))

def test_poll_plex_pin_unauthorized(db_path):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"id": 12345, "code": "H9RX", "authToken": None}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        token = poll_plex_pin(db_path, 12345)
        assert token is None
        assert get_setting(db_path, "plex_token") is None

def test_poll_plex_pin_authorized(db_path):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"id": 12345, "code": "H9RX", "authToken": "valid_plex_token_999"}).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        token = poll_plex_pin(db_path, 12345)
        assert token == "valid_plex_token_999"
        assert get_setting(db_path, "plex_token") == "valid_plex_token_999"

def test_poll_plex_pin_network_error(db_path):
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        token = poll_plex_pin(db_path, 12345)
        assert token is None

def test_verify_plex_connection_no_token(db_path):
    assert verify_plex_connection(db_path) is False

def test_verify_plex_connection_success(db_path):
    set_setting(db_path, "plex_token", "test_token_abc")
    set_setting(db_path, "plex_url", "http://127.0.0.1:32400")

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        is_connected = verify_plex_connection(db_path)
        assert is_connected is True

        called_req = mock_urlopen.call_args[0][0]
        assert called_req.get_full_url() == "http://127.0.0.1:32400/identity"
        assert called_req.headers["X-plex-token"] == "test_token_abc"

def test_verify_plex_connection_failure(db_path):
    set_setting(db_path, "plex_token", "invalid_token")
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("http://127.0.0.1:32400/identity", 401, "Unauthorized", {}, None)):
        is_connected = verify_plex_connection(db_path)
        assert is_connected is False
