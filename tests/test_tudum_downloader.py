import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from src.database import init_db, _get_connection, set_setting
from src.scraper.tudum_downloader import (
    make_slug,
    find_tudum_page,
    extract_trailer_assets,
    download_file,
    convert_vtt_to_srt,
    extract_season_number,
    download_pending_trailers
)

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")

@pytest.fixture
def initialized_db(db_path):
    init_db(db_path)
    return db_path

def test_make_slug():
    assert make_slug("Stranger Things") == "stranger-things"
    assert make_slug("Inside Out 2 (2024)") == "inside-out-2-2024"
    assert make_slug("Squid Game: The Challenge") == "squid-game-the-challenge"
    assert make_slug("A Toxic Love Story: Where Are They Now?") == "a-toxic-love-story-where-are-they-now"
    assert make_slug("  Some Title! With Symbols...   ") == "some-title-with-symbols"

def test_extract_season_number():
    assert extract_season_number("Season 1") == "01"
    assert extract_season_number("Season 03") == "03"
    assert extract_season_number("Season 12") == "12"
    assert extract_season_number(None) == "01"
    assert extract_season_number("Stranger Things 4") == "04"
    assert extract_season_number("Special Season") == "01"

def test_convert_vtt_to_srt():
    vtt_content = """WEBVTT

00:00:01.000 --> 00:00:04.000 line:80%
Hello <c.red>World</c.red>

00:00:05.123 --> 00:00:08.456
Goodbye!
"""
    expected_srt = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "Hello World\n"
        "\n"
        "2\n"
        "00:00:05,123 --> 00:00:08,456\n"
        "Goodbye!\n"
    )
    assert convert_vtt_to_srt(vtt_content) == expected_srt

@patch('urllib.request.urlopen')
def test_find_tudum_page_direct_success(mock_urlopen):
    # Mock direct page success (200 status)
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    url = find_tudum_page("Stranger Things", "tv", 2026)
    assert url == "https://www.netflix.com/tudum/stranger-things"
    assert mock_urlopen.call_count == 1

@patch('urllib.request.urlopen')
def test_find_tudum_page_fallback_success(mock_urlopen):
    # First call (direct URL check) raises Exception
    # Second call (Top 10 list fetch) succeeds and returns mock HTML with matches
    mock_resp_direct = MagicMock()
    mock_resp_direct.status = 404
    
    mock_resp_top10 = MagicMock()
    mock_resp_top10.status = 200
    mock_resp_top10.read.return_value = b'<html><body><a href="/tudum/articles/stranger-things-behind-the-episode">ST</a></body></html>'
    mock_resp_top10.__enter__.return_value = mock_resp_top10
    
    mock_urlopen.side_effect = [Exception("Direct fails"), mock_resp_top10]

    url = find_tudum_page("Stranger Things", "tv", 2026)
    assert url == "https://www.netflix.com/tudum/articles/stranger-things-behind-the-episode"
    assert mock_urlopen.call_count == 2

@patch('urllib.request.urlopen')
def test_find_tudum_page_completely_fails(mock_urlopen):
    # Direct and fallback both fail, returns None to avoid 404 logs
    mock_urlopen.side_effect = Exception("All connections fail")
    url = find_tudum_page("Stranger Things", "tv", 2026)
    assert url is None

def test_extract_trailer_assets_with_fixture():
    # Use real fixture file to test extraction logic
    fixture_path = "tests/fixtures/tudum-stranger-things.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = html_content.encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        
        assets = extract_trailer_assets("https://www.netflix.com/tudum/stranger-things")
        
        assert assets["video_url"] is None
        assert assets["subtitle_url"] is None
        assert assets["plot"] is not None
        assert "When a young boy vanishes" in assets["plot"]
        assert assets["netflix_id"] == "80057281"

@patch('urllib.request.urlopen')
def test_extract_trailer_assets_custom_html(mock_urlopen):
    mock_html = "<html><body></body></html>"
    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_html.encode('utf-8')
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    assets = extract_trailer_assets("https://www.netflix.com/tudum/custom")
    assert assets["video_url"] is None
    assert assets["subtitle_url"] is None

@patch('urllib.request.urlopen')
def test_extract_trailer_assets_failure(mock_urlopen):
    mock_urlopen.side_effect = Exception("Network down")
    assets = extract_trailer_assets("https://www.netflix.com/tudum/fail")
    assert assets["video_url"] is None
    assert assets["subtitle_url"] is None

@patch('yt_dlp.YoutubeDL')
def test_download_file(mock_ytdl_cls, tmp_path):
    mock_ydl = MagicMock()
    mock_ytdl_cls.return_value.__enter__.return_value = mock_ydl

    out_file = tmp_path / "trailer.mp4"
    out_file.write_bytes(b"video_data")
    download_file("https://example.com/video.mp4", str(out_file))

    mock_ytdl_cls.assert_called_once()
    mock_ydl.download.assert_called_once_with(["https://example.com/video.mp4"])

@patch('urllib.request.urlopen')
@patch('yt_dlp.YoutubeDL')
def test_download_file_fallback(mock_ytdl_cls, mock_urlopen, tmp_path):
    mock_ytdl_cls.side_effect = Exception("yt-dlp error")
    mock_resp = MagicMock()
    mock_resp.read.side_effect = [b"chunk1", b"chunk2", b""]
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    out_file = tmp_path / "trailer.mp4"
    download_file("https://example.com/video.mp4", str(out_file))

    assert out_file.exists()
    assert out_file.read_bytes() == b"chunk1chunk2"


@patch('src.scraper.tudum_downloader.find_tudum_page')
@patch('src.scraper.tudum_downloader.extract_trailer_assets')
@patch('src.scraper.tudum_downloader.search_and_download_youtube_trailer')
def test_download_pending_trailers_success(mock_yt_search, mock_extract, mock_find, initialized_db, tmp_path):
    # Enable subtitle downloads
    set_setting(initialized_db, "trailer_subtitles", "true")
    set_setting(initialized_db, "subtitle_languages", "en")

    # Add pending movie and TV series to the DB
    conn = _get_connection(initialized_db)
    with conn:
        conn.execute("""
            INSERT INTO media_items (title, type, release_year, season_name, folder_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Stranger Things Movie", "movie", 2026, None, "Stranger Things Movie (2026)", "pending"))
        conn.execute("""
            INSERT INTO media_items (title, type, release_year, season_name, folder_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Stranger Things Show", "tv", 2026, "Season 5", "Stranger Things Show (2026)", "pending"))

    # Mock helpers
    mock_find.side_effect = lambda title, t, y: f"https://www.netflix.com/tudum/{make_slug(title)}"
    mock_extract.side_effect = [
        {"video_url": None, "subtitle_url": None, "plot": "Movie plot", "netflix_id": "111"},
        {"video_url": None, "subtitle_url": None, "plot": "Show plot", "netflix_id": "222"}
    ]
    mock_yt_search.side_effect = [
        "https://www.youtube.com/watch?v=movieyt123",
        "https://www.youtube.com/watch?v=showyt123"
    ]

    media_dir = tmp_path / "media"
    
    # Run the pipeline
    download_pending_trailers(initialized_db, media_dir=str(media_dir))

    # Verify movie paths created
    movie_video = media_dir / "movies" / "Stranger Things Movie (2026)" / "Stranger Things Movie (2026).mp4"
    movie_nfo = media_dir / "movies" / "Stranger Things Movie (2026)" / "movie.nfo"
    assert movie_nfo.exists()
    assert "<movie>" in movie_nfo.read_text()
    assert "<title>Stranger Things Movie</title>" in movie_nfo.read_text()
    assert "<uniqueid type=\"netflix\" default=\"true\">111</uniqueid>" in movie_nfo.read_text()

    # Verify TV paths created
    tv_video = media_dir / "tv" / "Stranger Things Show (2026)" / "Season 05" / "S05E00 - Trailer.mp4"
    tv_nfo = media_dir / "tv" / "Stranger Things Show (2026)" / "tvshow.nfo"
    assert tv_nfo.exists()
    assert "<tvshow>" in tv_nfo.read_text()
    assert "<title>Stranger Things Show</title>" in tv_nfo.read_text()
    assert "<uniqueid type=\"netflix\" default=\"true\">222</uniqueid>" in tv_nfo.read_text()

    # Verify DB statuses updated
    conn = _get_connection(initialized_db)
    cursor = conn.execute("SELECT title, status, file_path, youtube_url FROM media_items")
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()

    assert len(results) == 2
    for r in results:
        assert r["status"] == "downloaded"
        assert r["file_path"] is not None
        assert r["youtube_url"] is not None

@patch('src.scraper.tudum_downloader.find_tudum_page')
@patch('src.scraper.tudum_downloader.extract_trailer_assets')
@patch('src.scraper.tudum_downloader.search_and_download_youtube_trailer')
def test_download_pending_trailers_failure_fallback_stub(mock_yt_search, mock_extract, mock_find, initialized_db, tmp_path):
    conn = _get_connection(initialized_db)
    with conn:
        conn.execute("""
            INSERT INTO media_items (title, type, release_year, season_name, folder_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Failure Show", "tv", 2026, "Season 1", "Failure Show (2026)", "pending"))

    # Mock extract to return no video url (failed extraction)
    mock_find.return_value = "https://www.netflix.com/tudum/failure"
    mock_extract.return_value = {"video_url": None, "subtitle_url": None}
    mock_yt_search.return_value = None

    media_dir = tmp_path / "media"
    
    # Run the pipeline
    download_pending_trailers(initialized_db, media_dir=str(media_dir))

    # Verify zero-byte placeholder stub created
    stub_file = media_dir / "tv" / "Failure Show (2026)" / "Season 01" / "S01E00 - Trailer.mp4"
    assert stub_file.exists()
    assert stub_file.stat().st_size == 0

    # Verify status is marked as downloaded with stub file path
    conn = _get_connection(initialized_db)
    cursor = conn.execute("SELECT status, file_path FROM media_items WHERE title = 'Failure Show'")
    row = cursor.fetchone()
    conn.close()

    assert row["status"] == "downloaded"
    assert row["file_path"] == str(stub_file)

@patch('src.scraper.tudum_downloader.find_tudum_page')
@patch('src.scraper.tudum_downloader.extract_trailer_assets')
@patch('src.scraper.tudum_downloader.download_file')
def test_download_pending_trailers_dummy_mode(mock_download, mock_extract, mock_find, initialized_db, tmp_path):
    set_setting(initialized_db, "dummy_media_mode", "true")
    conn = _get_connection(initialized_db)
    with conn:
        conn.execute("""
            INSERT INTO media_items (title, type, release_year, season_name, folder_name, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Dummy Movie", "movie", 2026, None, "Dummy Movie (2026)", "pending"))

    mock_find.return_value = "https://www.netflix.com/tudum/dummy"
    mock_extract.return_value = {
        "video_url": "https://example.com/dummy.mp4",
        "subtitle_url": None,
        "plot": "Dummy Plot",
        "netflix_id": "999",
        "poster_url": None,
        "logo_url": None,
        "maturity_rating": None,
        "runtime_seconds": None
    }

    media_dir = tmp_path / "media"
    download_pending_trailers(initialized_db, media_dir=str(media_dir))

    # download_file should not be called in dummy mode
    mock_download.assert_not_called()

    # Zero-byte stub file should exist
    stub_file = media_dir / "movies" / "Dummy Movie (2026)" / "Dummy Movie (2026).mp4"
    assert stub_file.exists()
    assert stub_file.stat().st_size == 0

    # NFO should exist
    nfo_file = media_dir / "movies" / "Dummy Movie (2026)" / "movie.nfo"
    assert nfo_file.exists()

    # DB status should be downloaded
    conn = _get_connection(initialized_db)
    cursor = conn.execute("SELECT status, file_path FROM media_items WHERE title = 'Dummy Movie'")
    row = cursor.fetchone()
    conn.close()
    assert row["status"] == "downloaded"
    assert row["file_path"] == str(stub_file)
