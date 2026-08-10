import os
import tempfile
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.web.app import app
from src.database import init_db, get_setting, get_monitored_countries

@pytest.fixture
def client_and_db():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_netplex.db")
        init_db(db_path)
        log_path = os.path.join(tmp_dir, "netplex.log")
        
        # Write sample log file (150 lines)
        with open(log_path, "w", encoding="utf-8") as f:
            for i in range(1, 151):
                f.write(f"2026-08-11 00:00:{i:02d} [INFO] Test log line {i}\n")

        app.state.db_path = db_path
        app.state.log_path = log_path
        app.state.config_dir = tmp_dir
        
        client = TestClient(app)
        yield client, db_path, log_path, tmp_dir

def test_get_settings_page(client_and_db):
    client, _, _, _ = client_and_db
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Settings & Control Panel" in resp.text

def test_post_settings_json(client_and_db):
    client, db_path, _, _ = client_and_db
    payload = {
        "plex_url": "http://192.168.1.100:32400",
        "plex_token": "secret_token_123",
        "update_interval_hours": "48",
        "trailer_subtitles": True,
        "subtitle_languages": "en,de,tr",
        "log_level": "DEBUG",
        "monitored_countries": [
            {"country_code": "US", "formats": "movie,tv"},
            {"country_code": "DE", "formats": "movie"}
        ]
    }
    
    resp = client.post("/api/settings", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    
    assert get_setting(db_path, "plex_url") == "http://192.168.1.100:32400"
    assert get_setting(db_path, "plex_token") == "secret_token_123"
    assert get_setting(db_path, "update_interval_hours") == "48"
    assert get_setting(db_path, "trailer_subtitles") == "true"
    assert get_setting(db_path, "subtitle_languages") == "en,de,tr"
    assert get_setting(db_path, "log_level") == "DEBUG"
    
    monitored = get_monitored_countries(db_path)
    codes = [m["country_code"] for m in monitored]
    assert "US" in codes
    assert "DE" in codes

def test_post_settings_form(client_and_db):
    client, db_path, _, _ = client_and_db
    form_data = {
        "plex_url": "http://localhost:32400",
        "plex_token": "form_token",
        "update_interval_hours": "24",
        "trailer_subtitles": "true",
        "subtitle_languages": "en",
        "log_level": "INFO",
        "country_code": ["US", "GB"],
        "format_movie_US": "movie",
        "format_tv_US": "tv",
        "format_movie_GB": "movie"
    }
    
    resp = client.post("/settings", data=form_data, follow_redirects=False)
    assert resp.status_code == 303
    
    assert get_setting(db_path, "plex_token") == "form_token"
    assert get_setting(db_path, "update_interval_hours") == "24"

def test_plex_pin_initiation(client_and_db):
    client, db_path, _, _ = client_and_db
    
    mock_pin_data = {
        "id": 12345,
        "code": "ABCD",
        "auth_url": "https://app.plex.tv/auth#?code=ABCD"
    }
    
    with patch("src.web.routes_settings.request_plex_pin", return_value=mock_pin_data):
        resp = client.post("/api/auth/plex/pin")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 12345
        assert data["code"] == "ABCD"
        assert "auth_url" in data

def test_plex_pin_status(client_and_db):
    client, db_path, _, _ = client_and_db
    
    with patch("src.web.routes_settings.poll_plex_pin", return_value=None):
        resp = client.get("/api/auth/plex/status/12345")
        assert resp.status_code == 200
        assert resp.json() == {"authorized": False}
        
    with patch("src.web.routes_settings.poll_plex_pin", return_value="my_new_auth_token"):
        resp = client.get("/api/auth/plex/status/12345")
        assert resp.status_code == 200
        assert resp.json() == {"authorized": True, "token": "my_new_auth_token"}

def test_access_logs(client_and_db):
    client, db_path, log_path, tmp_dir = client_and_db
    
    # Valid logs request - returns last 100 lines
    resp = client.get("/api/logs?max_lines=100")
    assert resp.status_code == 200
    data = resp.json()
    assert "lines" in data
    assert len(data["lines"]) == 100
    assert "Test log line 150" in data["lines"][-1]
    
    # Directory traversal test: attempt to read file outside allowed config_dir
    app.state.log_path = "/etc/passwd"
    resp_forbidden = client.get("/api/logs")
    assert resp_forbidden.status_code == 403

def test_crawl_endpoint(client_and_db):
    client, db_path, _, _ = client_and_db
    
    with patch("src.web.routes_settings.crawl_netflix_top10") as mock_crawl, \
         patch("src.web.routes_settings.download_pending_trailers") as mock_download, \
         patch("src.web.routes_settings.run_plex_sync") as mock_sync, \
         patch("src.web.routes_settings.run_cleanup_cycle") as mock_cleanup:
        
        resp = client.post("/api/crawl")
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        
        status_resp = client.get("/api/crawl/status")
        assert status_resp.status_code == 200
