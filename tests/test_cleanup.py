import os
import shutil
import tempfile
import pytest
import logging
from src.database import (
    init_db,
    upsert_media_item,
    insert_ranking,
    _get_connection
)
from src.cleanup import (
    find_orphaned_media,
    delete_media_folder,
    prune_orphaned_records,
    run_cleanup_cycle
)

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)

@pytest.fixture
def temp_data_dir():
    temp_dir = tempfile.mkdtemp()
    movies_dir = os.path.join(temp_dir, "movies")
    tv_dir = os.path.join(temp_dir, "tv")
    os.makedirs(movies_dir, exist_ok=True)
    os.makedirs(tv_dir, exist_ok=True)
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

def test_find_orphaned_media(temp_db):
    # Setup media items
    id1 = upsert_media_item(temp_db, "Movie One", "movie", 2021, None, "Movie One (2021)")
    id2 = upsert_media_item(temp_db, "Movie Two", "movie", 2022, None, "Movie Two (2022)")
    id3 = upsert_media_item(temp_db, "Show Three", "tv", 2023, "Season 1", "Show Three (2023)")

    # Insert rankings for week "2026-W32" (only id1 and id3 active)
    insert_ranking(temp_db, "US", "Movies", 1, "2026-W32", id1)
    insert_ranking(temp_db, "US", "TV", 1, "2026-W32", id3)

    # id2 is active in an older week "2026-W31"
    insert_ranking(temp_db, "US", "Movies", 2, "2026-W31", id2)

    # find_orphaned_media for week "2026-W32" should return id2
    orphans = find_orphaned_media(temp_db, "2026-W32")
    orphan_ids = [m["id"] for m in orphans]

    assert id2 in orphan_ids
    assert id1 not in orphan_ids
    assert id3 not in orphan_ids

def test_delete_media_folder_success(temp_data_dir):
    # Create movie folder with trailer, subtitle, and nfo
    movie_folder = os.path.join(temp_data_dir, "movies", "Movie One (2021)")
    os.makedirs(movie_folder, exist_ok=True)
    
    video_path = os.path.join(movie_folder, "Movie One (2021).mp4")
    sub_path = os.path.join(movie_folder, "Movie One (2021).en.srt")
    nfo_path = os.path.join(movie_folder, "movie.nfo")

    with open(video_path, "w") as f: f.write("video content")
    with open(sub_path, "w") as f: f.write("sub content")
    with open(nfo_path, "w") as f: f.write("nfo content")

    assert os.path.exists(movie_folder)

    success = delete_media_folder(movie_folder, base_data_dir=temp_data_dir)
    assert success is True
    assert not os.path.exists(movie_folder)

def test_delete_tv_media_folder_success(temp_data_dir):
    # Create TV show folder structure
    tv_folder = os.path.join(temp_data_dir, "tv", "Show One (2023)")
    season_folder = os.path.join(tv_folder, "Season 01")
    os.makedirs(season_folder, exist_ok=True)

    nfo_path = os.path.join(tv_folder, "tvshow.nfo")
    video_path = os.path.join(season_folder, "S01E00 - Trailer.mp4")
    sub_path = os.path.join(season_folder, "S01E00 - Trailer.en.srt")

    with open(nfo_path, "w") as f: f.write("nfo content")
    with open(video_path, "w") as f: f.write("video content")
    with open(sub_path, "w") as f: f.write("sub content")

    success = delete_media_folder(tv_folder, base_data_dir=temp_data_dir)
    assert success is True
    assert not os.path.exists(tv_folder)

def test_delete_media_folder_safety_unrelated_file(temp_data_dir, caplog):
    # Create movie folder with NetPlex files AND an unrelated file
    movie_folder = os.path.join(temp_data_dir, "movies", "Movie Two (2022)")
    os.makedirs(movie_folder, exist_ok=True)

    video_path = os.path.join(movie_folder, "Movie Two (2022).mp4")
    unrelated_path = os.path.join(movie_folder, "my_movie.mkv")

    with open(video_path, "w") as f: f.write("video content")
    with open(unrelated_path, "w") as f: f.write("user file content")

    with caplog.at_level(logging.ERROR):
        success = delete_media_folder(movie_folder, base_data_dir=temp_data_dir)

    assert success is False
    assert os.path.exists(movie_folder)
    assert os.path.exists(unrelated_path)
    assert "Unrelated file(s) found" in caplog.text

def test_delete_media_folder_traversal_prevention(temp_data_dir, caplog):
    # Attempt directory traversal outside allowed dirs
    invalid_path = os.path.join(temp_data_dir, "movies", "..", "..", "etc")
    
    with caplog.at_level(logging.ERROR):
        success = delete_media_folder(invalid_path, base_data_dir=temp_data_dir)

    assert success is False
    assert "Security error" in caplog.text

def test_prune_orphaned_records(temp_db):
    id1 = upsert_media_item(temp_db, "Movie One", "movie", 2021, None, "Movie One (2021)")
    id2 = upsert_media_item(temp_db, "Movie Two", "movie", 2022, None, "Movie Two (2022)")
    insert_ranking(temp_db, "US", "Movies", 1, "2026-W30", id1)

    pruned = prune_orphaned_records(temp_db, [id1, id2])
    assert pruned == 2

    conn = _get_connection(temp_db)
    cursor = conn.execute("SELECT COUNT(*) FROM media_items WHERE id IN (?, ?)", (id1, id2))
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 0

def test_run_cleanup_cycle(temp_db, temp_data_dir):
    # Setup 1 active item, 1 orphaned item
    active_id = upsert_media_item(temp_db, "Active Movie", "movie", 2024, None, "Active Movie (2024)")
    orphan_id = upsert_media_item(temp_db, "Orphan Movie", "movie", 2020, None, "Orphan Movie (2020)")

    insert_ranking(temp_db, "US", "Movies", 1, "2026-W32", active_id)
    insert_ranking(temp_db, "US", "Movies", 2, "2026-W31", orphan_id)

    orphan_folder = os.path.join(temp_data_dir, "movies", "Orphan Movie (2020)")
    os.makedirs(orphan_folder, exist_ok=True)
    with open(os.path.join(orphan_folder, "movie.nfo"), "w") as f: f.write("nfo")

    result = run_cleanup_cycle(temp_db, "2026-W32", media_dir=temp_data_dir)

    assert result["orphans_found"] == 1
    assert result["folders_deleted"] == 1
    assert result["records_pruned"] == 1
    assert not os.path.exists(orphan_folder)
