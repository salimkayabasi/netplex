import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from src.database import (
    init_db,
    set_monitored_country,
    upsert_media_item,
    insert_ranking
)
from src.web.app import (
    app,
    download_and_cache_tudum_css,
    ensure_config_www_mounted
)

@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "netplex.db")
        config_dir = os.path.join(tmpdir, "config")
        init_db(db_path)
        
        # Configure app state
        app.state.db_path = db_path
        app.state.config_dir = config_dir
        ensure_config_www_mounted(config_dir)
        
        client = TestClient(app)
        yield {
            "client": client,
            "db_path": db_path,
            "config_dir": config_dir,
            "tmpdir": tmpdir
        }

def test_landing_page_endpoint(test_env):
    client = test_env["client"]
    db_path = test_env["db_path"]

    # Setup DB data
    set_monitored_country(db_path, "US", "Films,TV")
    item_id = upsert_media_item(
        db_path,
        title="Stranger Things",
        type="tv",
        release_year=2016,
        season_name="Season 4",
        folder_name="Stranger Things (2016)"
    )
    insert_ranking(
        db_path,
        country_code="US",
        category="TV",
        rank=1,
        week="2026-08-01",
        media_item_id=item_id
    )

    response = client.get("/?country=US&category=TV")
    assert response.status_code == 200
    assert "Stranger Things" in response.text
    assert "NetPlex" in response.text
    assert 'class="rank-badge">01</div>' in response.text or '01' in response.text

def test_sequential_country_sections(test_env):
    client = test_env["client"]
    db_path = test_env["db_path"]

    # Configure tracked countries in specific order: GLOBAL, TR, US
    set_monitored_country(db_path, "GLOBAL", "movie,tv")
    set_monitored_country(db_path, "TR", "movie,tv")
    set_monitored_country(db_path, "US", "movie,tv")

    item1 = upsert_media_item(db_path, "Global Movie", "movie", 2024, None, "Global Movie (2024)")
    item2 = upsert_media_item(db_path, "Turkey Movie", "movie", 2024, None, "Turkey Movie (2024)")
    item3 = upsert_media_item(db_path, "US Movie", "movie", 2024, None, "US Movie (2024)")

    insert_ranking(db_path, "GLOBAL", "Movies", 1, "2026-08-01", item1)
    insert_ranking(db_path, "TR", "Movies", 1, "2026-08-01", item2)
    insert_ranking(db_path, "US", "Movies", 1, "2026-08-01", item3)

    response = client.get("/")
    assert response.status_code == 200
    text = response.text
    # Verify sequential order: Global appears before Turkey, Turkey appears before United States
    pos_global = text.find("Global Top 10 Movies")
    pos_tr = text.find("Turkey Top 10 Movies")
    pos_us = text.find("United States Top 10 Movies")

    assert pos_global != -1
    assert pos_tr != -1
    assert pos_us != -1
    assert pos_global < pos_tr < pos_us

def test_download_and_cache_tudum_css(test_env):
    config_dir = test_env["config_dir"]
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    
    html_fixture_path = os.path.join(fixtures_dir, "sample_tudum.html")
    css_fixture_path = os.path.join(fixtures_dir, "sample_tudum_style.css")

    with open(html_fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    with open(css_fixture_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    cached_file = download_and_cache_tudum_css(
        config_dir=config_dir,
        html_content=html_content,
        css_content=css_content
    )

    assert os.path.exists(cached_file)
    assert cached_file.endswith("tudum.css")

    with open(cached_file, "r", encoding="utf-8") as f:
        saved_css = f.read()
    assert "--tudum-brand-red" in saved_css

def test_stream_video_endpoint(test_env, monkeypatch):
    client = test_env["client"]
    db_path = test_env["db_path"]
    tmpdir = test_env["tmpdir"]

    # Configure data dir to tmpdir
    data_dir = os.path.join(tmpdir, "media")
    os.makedirs(data_dir, exist_ok=True)
    monkeypatch.setenv("NETPLEX_DATA_DIR", data_dir)

    # Create dummy 1024-byte video file inside data_dir
    video_file_path = os.path.join(data_dir, "sample_trailer.mp4")
    dummy_data = b"0" * 1024
    with open(video_file_path, "wb") as f:
        f.write(dummy_data)

    item_id = upsert_media_item(
        db_path,
        title="Test Movie",
        type="movie",
        release_year=2024,
        season_name=None,
        folder_name="Test Movie (2024)"
    )

    # Set status and file_path in media_items table
    from src.database import update_media_item_status
    update_media_item_status(db_path, item_id, "downloaded", file_path=video_file_path)

    # Test full video request (no range header)
    resp_full = client.get(f"/stream/video/{item_id}")
    assert resp_full.status_code == 200
    assert len(resp_full.content) == 1024

    # Test range request
    headers = {"Range": "bytes=0-499"}
    resp_range = client.get(f"/stream/video/{item_id}", headers=headers)
    assert resp_range.status_code == 206
    assert resp_range.headers["Content-Range"] == "bytes 0-499/1024"
    assert resp_range.headers["Content-Length"] == "500"
    assert len(resp_range.content) == 500

    # Test path traversal security check (file outside data_dir)
    outside_file = os.path.join(tmpdir, "sensitive.txt")
    with open(outside_file, "w") as f:
        f.write("secret data")
    
    bad_item_id = upsert_media_item(
        db_path, title="Malicious", type="movie", release_year=2024, season_name=None, folder_name="Bad"
    )
    update_media_item_status(db_path, bad_item_id, "downloaded", file_path=outside_file)
    
    resp_traversal = client.get(f"/stream/video/{bad_item_id}")
    assert resp_traversal.status_code == 403

    # Test non-existent media_item
    resp_404 = client.get("/stream/video/99999")
    assert resp_404.status_code == 404

