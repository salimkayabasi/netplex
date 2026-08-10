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
    assert 'class="rank-badge">1<' in response.text or 'rank-badge">1</div>' in response.text

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

def test_stream_video_endpoint(test_env):
    client = test_env["client"]
    db_path = test_env["db_path"]
    tmpdir = test_env["tmpdir"]

    # Create dummy 1024-byte video file
    video_file_path = os.path.join(tmpdir, "sample_trailer.mp4")
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

    # Test non-existent media_item
    resp_404 = client.get("/stream/video/99999")
    assert resp_404.status_code == 404
