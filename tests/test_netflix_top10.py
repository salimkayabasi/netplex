import os
import shutil
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from src.database import init_db, set_monitored_country, get_active_rankings, _get_connection
from src.scraper.netflix_top10 import (
    fetch_top10_tsv,
    get_latest_available_week,
    parse_title_and_year,
    parse_top10_data,
    crawl_netflix_top10
)

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")

@pytest.fixture
def initialized_db(db_path):
    init_db(db_path)
    return db_path

@patch('urllib.request.urlopen')
def test_fetch_top10_tsv(mock_urlopen, tmp_path):
    mock_response = MagicMock()
    mock_response.read.side_effect = [b"mock row 1\tmock row 2\n", b""]
    mock_urlopen.return_value.__enter__.return_value = mock_response

    cache_file = str(tmp_path / "test.tsv")
    
    # 1. First fetch (downloads data)
    res = fetch_top10_tsv("https://example.com/all-weeks-global.tsv", cache_file)
    assert res == cache_file
    assert os.path.exists(cache_file)
    with open(cache_file, "r") as f:
        content = f.read()
        assert content == "mock row 1\tmock row 2\n"
    assert mock_urlopen.call_count == 1

    # 2. Second fetch (reuses cached file)
    res2 = fetch_top10_tsv("https://example.com/all-weeks-global.tsv", cache_file)
    assert res2 == cache_file
    assert mock_urlopen.call_count == 1

def test_get_latest_available_week():
    week = get_latest_available_week("tests/fixtures/all-weeks-global.tsv")
    assert week == "2026-08-02"

def test_parse_title_and_year():
    # Title with year
    t1, y1 = parse_title_and_year("Inside Out 2 (2024)")
    assert t1 == "Inside Out 2"
    assert y1 == 2024

    # Title without year
    t2, y2 = parse_title_and_year("Stranger Things")
    assert t2 == "Stranger Things"
    # y2 should be the current year
    import datetime
    assert y2 == datetime.datetime.now().year

    # Title with year but extra spaces
    t3, y3 = parse_title_and_year("  Glass Onion (2022)   ")
    assert t3 == "Glass Onion"
    assert y3 == 2022

def test_parse_top10_data_country():
    # Monitor US (both movies and TV) and AR (only TV)
    countries_config = [
        {"country_code": "US", "formats": "both"},
        {"country_code": "AR", "formats": "tv"}
    ]
    target_week = "2026-08-02"
    
    results = parse_top10_data(
        "tests/fixtures/all-weeks-countries.tsv",
        countries_config,
        target_week
    )
    
    assert len(results) > 0
    # Every parsed item should match requirements
    for item in results:
        assert item['country_code'] in ["US", "AR"]
        if item['country_code'] == "AR":
            assert item['type'] == "tv"
        assert item['category'] in ["Movies", "TV"]
        assert 1 <= item['rank'] <= 10
        assert item['title'] != ""
        assert item['folder_name'] == f"{item['title']} ({item['release_year']})"

    # Verify TV title splitting logic e.g. "Series Title: Season Name"
    # Let's inspect if any TV items exist in AR or US
    tv_items = [i for i in results if i['type'] == 'tv' and i['season_name'] is not None]
    if tv_items:
        # Season name should not contain the show title prefix if split correctly
        for tv in tv_items:
            assert ":" not in tv['season_name']

def test_parse_top10_data_global():
    # Monitor GLOBAL (both)
    countries_config = [
        {"country_code": "GLOBAL", "formats": "both"}
    ]
    target_week = "2026-08-02"
    
    results = parse_top10_data(
        "tests/fixtures/all-weeks-global.tsv",
        countries_config,
        target_week
    )
    
    assert len(results) > 0
    movies = [i for i in results if i['category'] == 'Movies']
    tv = [i for i in results if i['category'] == 'TV']
    assert len(movies) == 10
    assert len(tv) == 10
    assert [i['rank'] for i in movies] == list(range(1, 11))
    assert [i['rank'] for i in tv] == list(range(1, 11))
    for item in results:
        assert item['country_code'] == "GLOBAL"
        assert item['category'] in ["Movies", "TV"]
        assert 1 <= item['rank'] <= 10
        assert item['title'] != ""

@patch('src.scraper.netflix_top10.fetch_local_title', return_value=None)
@patch('src.scraper.netflix_top10.fetch_top10_tsv')
def test_crawl_netflix_top10(mock_fetch, mock_local_title, initialized_db):
    # Set monitored countries in the database
    set_monitored_country(initialized_db, "GLOBAL", "both")
    set_monitored_country(initialized_db, "AR", "tv")

    # Side-effect to copy local fixtures to the temporary cache path
    def copy_fixture(url, cache_path, *args, **kwargs):
        if "global" in url:
            shutil.copy("tests/fixtures/all-weeks-global.tsv", cache_path)
        else:
            shutil.copy("tests/fixtures/all-weeks-countries.tsv", cache_path)
        return cache_path
    
    mock_fetch.side_effect = copy_fixture

    # Execute crawl
    crawl_netflix_top10(initialized_db)

    # Verify rankings populated for the latest week "2026-08-02"
    global_rankings = get_active_rankings(initialized_db, "GLOBAL", "Movies", "2026-08-02")
    assert len(global_rankings) > 0
    assert global_rankings[0]['rank'] == 1
    # Check that media item joins correctly
    assert global_rankings[0]['title'] == "72 HOURS"
    assert global_rankings[0]['release_year'] == 2026 # defaults to current year as year is not in title
    assert global_rankings[0]['type'] == "movie"
    assert global_rankings[0]['weekly_hours_viewed'] == 44000000
    assert global_rankings[0]['weekly_views'] == 25100000
    assert global_rankings[0]['cumulative_weeks_in_top_10'] == 2
    assert global_rankings[0]['country_name'] == "Global"

    ar_tv_rankings = get_active_rankings(initialized_db, "AR", "TV", "2026-08-02")
    assert len(ar_tv_rankings) > 0
    assert ar_tv_rankings[0]['country_name'] == "Argentina"
    assert ar_tv_rankings[0]['cumulative_weeks_in_top_10'] is not None

    # Ensure rankings for AR Movies are empty since we only monitored 'tv'
    ar_movie_rankings = get_active_rankings(initialized_db, "AR", "Movies", "2026-08-02")
    assert len(ar_movie_rankings) == 0

@patch('src.scraper.netflix_top10.fetch_local_title', return_value=None)
@patch('src.scraper.netflix_top10.fetch_top10_tsv')
def test_crawl_logging(mock_fetch, mock_local_title, initialized_db, caplog):
    set_monitored_country(initialized_db, "GLOBAL", "both")
    set_monitored_country(initialized_db, "AR", "tv")

    def copy_fixture(url, cache_path, *args, **kwargs):
        if "global" in url:
            shutil.copy("tests/fixtures/all-weeks-global.tsv", cache_path)
        else:
            shutil.copy("tests/fixtures/all-weeks-countries.tsv", cache_path)
        return cache_path
    
    mock_fetch.side_effect = copy_fixture

    import logging
    with caplog.at_level(logging.INFO, logger="netplex.crawler"):
        crawl_netflix_top10(initialized_db)

    log_messages = [rec.message for rec in caplog.records]
    
    assert any("Fetching regions & found 2 regions" in msg for msg in log_messages)
    assert any("fetching GLOBAL" in msg for msg in log_messages)
    assert any("Content types of GLOBAL: Movies, TV Shows" in msg for msg in log_messages)
    assert any("Fetching Movies" in msg for msg in log_messages)
    assert any("Fetching 72 HOURS" in msg for msg in log_messages)
    assert any("Fetching TV Shows" in msg for msg in log_messages)
    assert any("fetching AR" in msg for msg in log_messages)
    assert any("Content types of AR: TV Shows" in msg for msg in log_messages)
    assert any("Summary of Crawling:" in msg for msg in log_messages)


@patch('urllib.request.urlopen')
def test_fetch_local_title_dynamic_locale(mock_urlopen):
    from src.scraper.netflix_top10 import fetch_local_title

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'<html><body><h1>El Conjuro</h1></body></html>'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    title = fetch_local_title(12345, "ES")
    assert title == "El Conjuro"
    
    # Check that request URL used country code ES
    req = mock_urlopen.call_args[0][0]
    assert "netflix.com/es/title/12345" in req.full_url

    # Check GLOBAL maps to us
    fetch_local_title(12345, "GLOBAL")
    req_global = mock_urlopen.call_args[0][0]
    assert "netflix.com/us/title/12345" in req_global.full_url


