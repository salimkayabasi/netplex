import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from src.database import (
    init_db,
    _get_connection,
    set_setting,
    upsert_media_item,
    update_media_item_status,
    reset_stubs_and_failed_media_items
)
from src.scraper.tudum_downloader import (
    score_trailer_candidate,
    search_and_download_youtube_trailer,
    download_pending_trailers,
    extract_trailer_assets
)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_yt.db")


@pytest.fixture
def initialized_db(db_path):
    init_db(db_path)
    return db_path


def test_extract_trailer_assets_bypasses_video_scraping():
    # Verify extract_trailer_assets returns None for video_url and subtitle_url
    assets = extract_trailer_assets(None)
    assert assets["video_url"] is None
    assert assets["subtitle_url"] is None


@patch("yt_dlp.YoutubeDL")
def test_search_and_download_youtube_trailer_success(mock_ytdl_cls, tmp_path):
    # Setup mock YoutubeDL instance
    mock_ydl = MagicMock()
    mock_ytdl_cls.return_value.__enter__.return_value = mock_ydl

    mock_info = {
        "entries": [
            {
                "id": "abc123xyz",
                "webpage_url": "https://www.youtube.com/watch?v=abc123xyz"
            }
        ]
    }
    mock_ydl.extract_info.return_value = mock_info

    out_file = tmp_path / "movies" / "Test Movie (2026)" / "Test Movie (2026).mp4"
    yt_url = search_and_download_youtube_trailer(
        title="Test Movie",
        release_year=2026,
        output_path=str(out_file)
    )

    assert yt_url == "https://www.youtube.com/watch?v=abc123xyz"
    assert mock_ydl.download.call_count == 1
    mock_ydl.download.assert_called_once_with(["https://www.youtube.com/watch?v=abc123xyz"])


@patch("yt_dlp.YoutubeDL")
def test_search_and_download_youtube_trailer_fallback_query(mock_ytdl_cls, tmp_path):
    mock_ydl = MagicMock()
    mock_ytdl_cls.return_value.__enter__.return_value = mock_ydl

    # First search query fails (no entries), second search query succeeds
    mock_ydl.extract_info.side_effect = [
        {"entries": []},
        {"entries": [{"id": "fallback123", "webpage_url": "https://www.youtube.com/watch?v=fallback123", "title": "Fallback Film Official Trailer"}]},
        {"entries": []},
        {"entries": []}
    ]

    out_file = tmp_path / "trailer.mp4"
    yt_url = search_and_download_youtube_trailer(
        title="Fallback Film",
        release_year=2026,
        output_path=str(out_file)
    )

    assert yt_url == "https://www.youtube.com/watch?v=fallback123"
    assert mock_ydl.extract_info.call_count == 2


@patch("yt_dlp.YoutubeDL")
def test_search_and_download_youtube_trailer_failure(mock_ytdl_cls, tmp_path):
    mock_ydl = MagicMock()
    mock_ytdl_cls.return_value.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.return_value = {"entries": []}

    out_file = tmp_path / "trailer.mp4"
    yt_url = search_and_download_youtube_trailer(
        title="Nonexistent Movie",
        release_year=2026,
        output_path=str(out_file)
    )

    assert yt_url is None
    mock_ydl.download.assert_not_called()


@patch("src.scraper.tudum_downloader.search_and_download_youtube_trailer")
@patch("src.scraper.tudum_downloader.find_tudum_page")
@patch("src.scraper.tudum_downloader.extract_trailer_assets")
def test_download_pending_trailers_yt_download_success(mock_extract, mock_find, mock_yt_search, initialized_db, tmp_path):
    conn = _get_connection(initialized_db)
    with conn:
        conn.execute("""
            INSERT INTO media_items (title, type, release_year, season_name, folder_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Gladiator II", "movie", 2026, None, "Gladiator II (2026)", "pending"))

    mock_find.return_value = "https://www.netflix.com/tudum/gladiator-ii"
    mock_extract.return_value = {
        "video_url": None,
        "subtitle_url": None,
        "plot": "An epic sequel plot.",
        "netflix_id": "81902148",
        "poster_url": "https://example.com/poster.jpg",
        "logo_url": None,
        "maturity_rating": "16+",
        "runtime_seconds": 7200
    }
    mock_yt_search.return_value = "https://www.youtube.com/watch?v=gladiator2yt"

    media_dir = tmp_path / "media"
    download_pending_trailers(initialized_db, media_dir=str(media_dir))

    # Verify Youtube search downloader called
    mock_yt_search.assert_called_once()

    # Verify DB updated status and youtube_url
    conn = _get_connection(initialized_db)
    row = conn.execute("SELECT status, youtube_url, file_path FROM media_items WHERE title = 'Gladiator II'").fetchone()
    conn.close()

    assert row["status"] == "downloaded"
    assert row["youtube_url"] == "https://www.youtube.com/watch?v=gladiator2yt"
    assert "Gladiator II (2026).mp4" in row["file_path"]

    # Verify NFO file written
    nfo_path = media_dir / "movies" / "Gladiator II (2026)" / "movie.nfo"
    assert nfo_path.exists()
    assert "<title>Gladiator II</title>" in nfo_path.read_text()


@patch("src.scraper.tudum_downloader.search_and_download_youtube_trailer")
@patch("src.scraper.tudum_downloader.find_tudum_page")
@patch("src.scraper.tudum_downloader.extract_trailer_assets")
def test_download_pending_trailers_yt_download_failure_creates_stub(mock_extract, mock_find, mock_yt_search, initialized_db, tmp_path):
    conn = _get_connection(initialized_db)
    with conn:
        conn.execute("""
            INSERT INTO media_items (title, type, release_year, season_name, folder_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Failed Film", "movie", 2026, None, "Failed Film (2026)", "pending"))

    mock_find.return_value = None
    mock_extract.return_value = {"video_url": None, "subtitle_url": None, "plot": None, "netflix_id": None}
    mock_yt_search.return_value = None

    media_dir = tmp_path / "media"
    download_pending_trailers(initialized_db, media_dir=str(media_dir))

    # Verify zero-byte placeholder stub created
    stub_file = media_dir / "movies" / "Failed Film (2026)" / "Failed Film (2026).mp4"
    assert stub_file.exists()
    assert stub_file.stat().st_size == 0

    conn = _get_connection(initialized_db)
    row = conn.execute("SELECT status, file_path FROM media_items WHERE title = 'Failed Film'").fetchone()
    conn.close()

    assert row["status"] == "downloaded"
    assert row["file_path"] == str(stub_file)


def test_download_pending_trailers_dummy_mode_stub_creation(initialized_db, tmp_path):
    set_setting(initialized_db, "dummy_media_mode", "true")
    conn = _get_connection(initialized_db)
    with conn:
        conn.execute("""
            INSERT INTO media_items (title, type, release_year, season_name, folder_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Dummy Show", "tv", 2026, "Season 1", "Dummy Show (2026)", "pending"))

    media_dir = tmp_path / "media"
    download_pending_trailers(initialized_db, media_dir=str(media_dir))

    # Verify zero-byte stub created
    stub_file = media_dir / "tv" / "Dummy Show (2026)" / "Season 01" / "S01E00 - Trailer.mp4"
    assert stub_file.exists()
    assert stub_file.stat().st_size == 0

    # Verify NFO created
    nfo_file = media_dir / "tv" / "Dummy Show (2026)" / "tvshow.nfo"
    assert nfo_file.exists()

    conn = _get_connection(initialized_db)
    row = conn.execute("SELECT status, file_path FROM media_items WHERE title = 'Dummy Show'").fetchone()
    conn.close()

    assert row["status"] == "downloaded"
    assert row["file_path"] == str(stub_file)


def test_reset_stubs_and_failed_media_items(initialized_db, tmp_path):
    conn = _get_connection(initialized_db)
    
    # 1. Create a zero-byte stub file and item
    stub_file = tmp_path / "stub.mp4"
    stub_file.write_bytes(b"")
    id1 = upsert_media_item(initialized_db, "Stub Item", "movie", 2026, None, "Stub Item (2026)")
    update_media_item_status(initialized_db, id1, "downloaded", file_path=str(stub_file))

    # 2. Create a failed item
    id2 = upsert_media_item(initialized_db, "Failed Item", "movie", 2026, None, "Failed Item (2026)")
    update_media_item_status(initialized_db, id2, "failed")

    # 3. Create a downloaded item with real content (non-zero size)
    real_file = tmp_path / "real.mp4"
    real_file.write_bytes(b"video content data")
    id3 = upsert_media_item(initialized_db, "Real Item", "movie", 2026, None, "Real Item (2026)")
    update_media_item_status(initialized_db, id3, "downloaded", file_path=str(real_file))

    # Run reset_stubs_and_failed_media_items
    reset_ids = reset_stubs_and_failed_media_items(initialized_db)
    assert set(reset_ids) == {id1, id2}

    # Verify statuses in DB
    conn = _get_connection(initialized_db)
    rows = conn.execute("SELECT id, status FROM media_items").fetchall()
    status_map = {row["id"]: row["status"] for row in rows}
    conn.close()

    assert status_map[id1] == "pending"
    assert status_map[id2] == "pending"
    assert status_map[id3] == "downloaded"


def test_score_trailer_candidate_filters_iphone_max_promo():
    # Searching for movie "Max" (2015)
    iphone_promo = {
        "title": "iPhone 15 Pro Max Official Trailer",
        "uploader": "Apple",
        "duration": 180
    }
    real_trailer = {
        "title": "MAX | Official Trailer | Warner Bros. Entertainment",
        "uploader": "Warner Bros. Entertainment",
        "description": "Max movie official trailer 2015",
        "duration": 150
    }

    iphone_score = score_trailer_candidate(iphone_promo, "Max", 2015)
    real_score = score_trailer_candidate(real_trailer, "Max", 2015)

    assert iphone_score < 25.0
    assert real_score >= 50.0


def test_score_trailer_candidate_filters_generic_happy_content():
    # Searching for movie "Are We Happy?" (2024)
    vlog = {
        "title": "10 Ways To Be Happy in Life - Daily Vlog",
        "uploader": "Self Help Daily",
        "duration": 900
    }
    official_trailer = {
        "title": "Are We Happy? | Official Trailer | Netflix",
        "uploader": "Netflix",
        "description": "Watch Are We Happy? (2024) trailer on Netflix",
        "duration": 135
    }

    vlog_score = score_trailer_candidate(vlog, "Are We Happy?", 2024)
    trailer_score = score_trailer_candidate(official_trailer, "Are We Happy?", 2024)

    assert vlog_score < 25.0
    assert trailer_score >= 50.0

