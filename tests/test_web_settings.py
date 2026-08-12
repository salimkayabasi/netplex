import os
import tempfile
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.web.app import app
from src.database import init_db, get_setting, get_monitored_countries
from src.crawler_lock import release_crawl_lock

@pytest.fixture
def client_and_db():
    release_crawl_lock()
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
        try:
            yield client, db_path, log_path, tmp_dir
        finally:
            release_crawl_lock()


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
        "cron_expression": "0 12 * * 1",
        "dummy_media_mode": True,
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
    assert get_setting(db_path, "cron_expression") == "0 12 * * 1"
    assert get_setting(db_path, "dummy_media_mode") == "true"
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
        "cron_expression": "0 0 * * *",
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
    assert get_setting(db_path, "cron_expression") == "0 0 * * *"

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

def test_logs_endpoint_removed(client_and_db):
    client, _, _, _ = client_and_db
    resp = client.get("/api/logs")
    assert resp.status_code == 404

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

def test_crawl_endpoint_singleton_conflict(client_and_db):
    client, db_path, _, _ = client_and_db
    from src.crawler_lock import try_acquire_crawl_lock, release_crawl_lock

    assert try_acquire_crawl_lock() is True
    try:
        resp = client.post("/api/crawl")
        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"]

        status_resp = client.get("/api/crawl/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["is_crawling"] is True
    finally:
        release_crawl_lock()

    status_idle_resp = client.get("/api/crawl/status")
    assert status_idle_resp.status_code == 200
    assert status_idle_resp.json()["is_crawling"] is False

def test_auto_trigger_crawl_on_region_change(client_and_db):
    client, db_path, _, _ = client_and_db
    
    with patch("src.web.routes_settings.run_crawl_pipeline") as mock_pipeline:
        payload = {
            "monitored_countries": [
                {"country_code": "GLOBAL", "formats": "movie,tv"},
                {"country_code": "TR", "formats": "movie,tv"}
            ]
        }
        resp = client.post("/api/settings", json=payload)
        assert resp.status_code == 200
        assert resp.json()["crawl_triggered"] is True

def test_crawl_status_task_display(client_and_db):
    client, _, _, _ = client_and_db
    from src.crawler_lock import try_acquire_crawl_lock, release_crawl_lock, set_crawl_progress

    assert try_acquire_crawl_lock() is True
    try:
        set_crawl_progress(3, 14, "Downloading trailer: Are We Happy?")
        resp = client.get("/api/crawl/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_crawling"] is True
        assert data["current_task"] == 3
        assert data["total_tasks"] == 14
        assert data["task_display"] == "Crawling (3/14)"
        assert "Are We Happy?" in data["message"]
    finally:
        release_crawl_lock()


