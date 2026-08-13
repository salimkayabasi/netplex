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
from src.web.app import app

@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "netplex.db")
        config_dir = os.path.join(tmpdir, "config")
        init_db(db_path)
        
        # Configure app state
        app.state.db_path = db_path
        app.state.config_dir = config_dir
        
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

    # Test /tv endpoint directly
    response = client.get("/tv")
    assert response.status_code == 200
    assert "Stranger Things" in response.text
    assert "NetPlex" in response.text
    assert 'class="rank-badge">01</div>' in response.text or '01' in response.text
    assert 'badge-status status-pending' in response.text
    assert 'href="/movies"' in response.text
    assert 'href="/tv"' in response.text

    # Test legacy query param redirect /?category=TV
    response_redirect = client.get("/?category=TV", follow_redirects=False)
    assert response_redirect.status_code == 307
    assert response_redirect.headers["location"] == "/tv"

    # Test root / redirecting to /movies
    response_root = client.get("/", follow_redirects=False)
    assert response_root.status_code == 307
    assert response_root.headers["location"] == "/movies"

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

    response = client.get("/movies")
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


def test_dummy_media_mode_ui_and_stream(test_env, monkeypatch):
    client = test_env["client"]
    db_path = test_env["db_path"]
    tmpdir = test_env["tmpdir"]

    from src.database import set_setting, update_media_item_status

    data_dir = os.path.join(tmpdir, "media")
    os.makedirs(data_dir, exist_ok=True)
    monkeypatch.setenv("NETPLEX_DATA_DIR", data_dir)

    set_monitored_country(db_path, "US", "movie")
    item_id = upsert_media_item(db_path, "Stub Movie", "movie", 2026, None, "Stub Movie (2026)")
    insert_ranking(db_path, "US", "Movies", 1, "2026-08-01", item_id)

    # Create a 0-byte video stub file
    stub_file = os.path.join(data_dir, "stub.mp4")
    open(stub_file, "wb").close()
    update_media_item_status(db_path, item_id, "downloaded", file_path=stub_file)

    # 1. When dummy_media_mode is false (default)
    set_setting(db_path, "dummy_media_mode", "false")
    resp_normal = client.get("/movies")
    assert resp_normal.status_code == 200
    assert "window.DUMMY_MEDIA_MODE = false;" in resp_normal.text
    assert f'href="/movie/{item_id}?country=US"' in resp_normal.text
    assert 'class="play-overlay"' in resp_normal.text

    # 2. When dummy_media_mode is true
    set_setting(db_path, "dummy_media_mode", "true")
    resp_dummy = client.get("/movies")
    assert resp_dummy.status_code == 200
    assert "window.DUMMY_MEDIA_MODE = true;" in resp_dummy.text
    assert 'class="media-card dummy-mode"' in resp_dummy.text
    assert 'class="play-overlay"' not in resp_dummy.text

    # 3. Stream endpoint when dummy_media_mode is true or file size is 0
    resp_stream = client.get(f"/stream/video/{item_id}")
    assert resp_stream.status_code == 400
    assert "Dummy media mode" in resp_stream.json()["detail"]


def test_youtube_button_in_player_modal(test_env):
    client = test_env["client"]
    db_path = test_env["db_path"]

    set_monitored_country(db_path, "US", "movie")
    yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    item_id = upsert_media_item(
        db_path,
        title="Rick Roll Movie",
        type="movie",
        release_year=2024,
        season_name=None,
        folder_name="Rick Roll Movie (2024)",
        youtube_url=yt_url,
        netflix_id=999888
    )
    insert_ranking(db_path, "US", "Movies", 1, "2026-08-01", item_id)

    response = client.get("/movies")
    assert response.status_code == 200
    assert 'id="modal-yt-btn"' in response.text
    assert 'href="/movie/999888?country=US"' in response.text
    assert f'data-youtube-url="{yt_url}"' in response.text

    # Test detail page YouTube button
    resp_detail = client.get("/movie/999888")
    assert resp_detail.status_code == 200
    assert yt_url in resp_detail.text
    assert 'Watch Trailer on YouTube' in resp_detail.text


def test_detail_page_movie_and_tv(test_env, monkeypatch):
    client = test_env["client"]
    db_path = test_env["db_path"]
    tmpdir = test_env["tmpdir"]

    data_dir = os.path.join(tmpdir, "media")
    os.makedirs(data_dir, exist_ok=True)
    monkeypatch.setenv("NETPLEX_DATA_DIR", data_dir)

    movie_dir = os.path.join(data_dir, "movies", "72 HOURS (2026)")
    os.makedirs(movie_dir, exist_ok=True)
    
    nfo_content = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<movie>
    <title>72 HOURS</title>
    <year>2026</year>
    <plot>To save his career, a 40-year-old ad exec joins a crew of twentysomethings.</plot>
    <tagline>Wild Miami Bachelor Party</tagline>
    <mpaa>TV-MA</mpaa>
    <runtime>105</runtime>
    <genre>Comedy</genre>
    <director>John Smith</director>
    <actor><name>Actor Alpha</name></actor>
    <uniqueid type="netflix" default="true">81715790</uniqueid>
</movie>"""
    with open(os.path.join(movie_dir, "movie.nfo"), "w") as f:
        f.write(nfo_content)

    video_file = os.path.join(movie_dir, "72 HOURS (2026).mp4")
    with open(video_file, "wb") as f:
        f.write(b"0" * 1024)

    item_id = upsert_media_item(
        db_path,
        title="72 HOURS",
        type="movie",
        release_year=2026,
        season_name=None,
        folder_name="72 HOURS (2026)",
        netflix_id=81715790
    )
    from src.database import update_media_item_status
    update_media_item_status(db_path, item_id, "downloaded", file_path=video_file)

    resp = client.get("/movie/81715790")
    assert resp.status_code == 200
    assert "72 HOURS" in resp.text
    assert "To save his career" in resp.text
    assert "Wild Miami Bachelor Party" in resp.text
    assert "Comedy" in resp.text
    assert "John Smith" in resp.text
    assert "Actor Alpha" in resp.text
    assert "https://www.netflix.com/title/81715790" in resp.text

    # Test 404 when non-existent item is requested
    resp_404 = client.get("/movie/999999999")
    assert resp_404.status_code == 404

def test_detail_page_prev_next_navigation(test_env):
    client = test_env["client"]
    db_path = test_env["db_path"]

    set_monitored_country(db_path, "US", "movie,tv")
    set_monitored_country(db_path, "TR", "movie,tv")

    item1 = upsert_media_item(db_path, title="Movie One", type="movie", release_year=2024, season_name=None, folder_name="Movie One (2024)", netflix_id=101)
    item2 = upsert_media_item(db_path, title="Movie Two", type="movie", release_year=2024, season_name=None, folder_name="Movie Two (2024)", netflix_id=102)
    item3 = upsert_media_item(db_path, title="Movie Three", type="movie", release_year=2024, season_name=None, folder_name="Movie Three (2024)", netflix_id=103)

    insert_ranking(db_path, "US", "Movies", 1, "2026-08-01", item1)
    insert_ranking(db_path, "US", "Movies", 10, "2026-08-01", item2)
    insert_ranking(db_path, "TR", "Movies", 1, "2026-08-01", item3)

    # 1. View US Rank 1 (Movie One): Prev HIDDEN, Next is Movie Two in US
    resp_1 = client.get("/movie/101?country=US")
    assert resp_1.status_code == 200
    assert "Movie One" in resp_1.text
    assert 'US' in resp_1.text
    assert '#01' in resp_1.text
    assert 'id="detail-prev-link"' not in resp_1.text
    assert 'id="detail-next-link"' in resp_1.text
    assert '/movie/102?country=US' in resp_1.text

    # 2. View US Rank 10 (Movie Two): Prev is Movie One in US, Next transitions across region to Movie Three in TR (#01/10)
    resp_2 = client.get("/movie/102?country=US")
    assert resp_2.status_code == 200
    assert "Movie Two" in resp_2.text
    assert '#10' in resp_2.text
    assert 'id="detail-prev-link"' in resp_2.text
    assert '/movie/101?country=US' in resp_2.text
    assert 'id="detail-next-link"' in resp_2.text
    assert '/movie/103?country=TR' in resp_2.text

    # 3. View TR Rank 1 (Movie Three): Prev goes back across region to Movie Two in US (#10/10), Next HIDDEN (last item of sequence)
    resp_3 = client.get("/movie/103?country=TR")
    assert resp_3.status_code == 200
    assert "Movie Three" in resp_3.text
    assert 'TR' in resp_3.text
    assert '#01' in resp_3.text
    assert 'id="detail-prev-link"' in resp_3.text
    assert '/movie/102?country=US' in resp_3.text
    assert 'id="detail-next-link"' not in resp_3.text




