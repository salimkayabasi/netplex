import pytest
from unittest.mock import MagicMock, patch
from src.database import init_db, set_setting, set_monitored_country, upsert_media_item, insert_ranking
from src.plex.sync import (
    connect_to_plex,
    match_library_item,
    sync_plex_collection,
    sync_plex_playlist,
    run_plex_sync
)


class MockPlexItem:
    def __init__(self, title: str, year: int | None = None, item_type: str = "movie"):
        self.title = title
        self.year = year
        self.type = item_type
        
    def __repr__(self):
        return f"<MockPlexItem {self.title} ({self.year})>"


class MockLibrarySection:
    def __init__(self, title: str, section_type: str, items: list[MockPlexItem]):
        self.title = title
        self.type = section_type
        self._items = items
        self._collections = []

    def all(self):
        return self._items

    def collections(self, title: str = None):
        if title:
            return [c for c in self._collections if c.title == title]
        return self._collections

    def createCollection(self, title: str, items: list):
        collection = MockCollection(title, items)
        self._collections.append(collection)
        return collection


class MockCollection:
    def __init__(self, title: str, items: list):
        self.title = title
        self._items = list(items)
        self.mode = "default"

    def items(self):
        return list(self._items)

    def removeItems(self, items: list):
        for item in items:
            if item in self._items:
                self._items.remove(item)

    def addItems(self, items: list):
        for item in items:
            if item not in self._items:
                self._items.append(item)


class MockPlaylist:
    def __init__(self, title: str, items: list):
        self.title = title
        self._items = list(items)
        self.deleted = False

    def delete(self):
        self.deleted = True


class MockPlexServer:
    def __init__(self, sections: list[MockLibrarySection] = None):
        self._sections = sections or []
        self._playlists = []

    @property
    def library(self):
        class LibraryWrapper:
            def __init__(srv_self):
                pass
            def sections(srv_self):
                return self._sections
            def section(srv_self, title):
                for sec in self._sections:
                    if sec.title == title:
                        return sec
                raise Exception(f"Section {title} not found")
        return LibraryWrapper()

    def playlists(self, title: str = None):
        if title:
            return [p for p in self._playlists if p.title == title and not p.deleted]
        return [p for p in self._playlists if not p.deleted]

    def createPlaylist(self, title: str, items: list):
        playlist = MockPlaylist(title, items)
        self._playlists.append(playlist)
        return playlist


def test_connect_to_plex():
    with patch("src.plex.sync.PlexServer") as mock_plex_cls:
        mock_instance = MagicMock()
        mock_plex_cls.return_value = mock_instance
        
        server = connect_to_plex("http://localhost:32400", "fake_token", timeout=15)
        mock_plex_cls.assert_called_once_with("http://localhost:32400", "fake_token", timeout=15)
        assert server == mock_instance


def test_match_library_item_exact():
    item1 = MockPlexItem("Inside Out 2", 2024)
    item2 = MockPlexItem("Stranger Things", 2016)
    section = MockLibrarySection("Movies", "movie", [item1, item2])

    matched = match_library_item(section, "Inside Out 2", year=2024)
    assert matched == item1


def test_match_library_item_fuzzy():
    item1 = MockPlexItem("Inside Out 2 (2024)", 2024)
    item2 = MockPlexItem("Beverly Hills Cop Axel F", 2024)
    section = MockLibrarySection("Movies", "movie", [item1, item2])

    # Slight variation in search title vs library title
    matched = match_library_item(section, "Inside Out 2", year=2024, threshold=80.0)
    assert matched == item1


def test_match_library_item_year_filter():
    item_old = MockPlexItem("Dune", 1984)
    item_new = MockPlexItem("Dune", 2021)
    section = MockLibrarySection("Movies", "movie", [item_old, item_new])

    # Search for Dune (2021) with year restriction ±1
    matched = match_library_item(section, "Dune", year=2021)
    assert matched == item_new


def test_match_library_item_threshold_rejection():
    item1 = MockPlexItem("The Matrix", 1999)
    section = MockLibrarySection("Movies", "movie", [item1])

    # Low similarity search title should return None under default threshold 85
    matched = match_library_item(section, "Avatar", year=2009)
    assert matched is None


def test_sync_plex_collection_create_and_update():
    item1 = MockPlexItem("Inside Out 2", 2024)
    item2 = MockPlexItem("Beverly Hills Cop: Axel F", 2024)
    item3 = MockPlexItem("Old Movie", 2010)
    section = MockLibrarySection("Movies", "movie", [item1, item2, item3])
    plex_server = MockPlexServer([section])

    ranked_items = [
        {"title": "Inside Out 2", "release_year": 2024, "rank": 1, "type": "movie"},
        {"title": "Beverly Hills Cop: Axel F", "release_year": 2024, "rank": 2, "type": "movie"}
    ]

    collection = sync_plex_collection(plex_server, "Netflix Top 10 - US Films", ranked_items)
    assert collection is not None
    assert collection.title == "Netflix Top 10 - US Films"
    assert collection.items() == [item1, item2]

    # Update collection: item2 leaves top 10, item3 enters top 10
    updated_ranked_items = [
        {"title": "Inside Out 2", "release_year": 2024, "rank": 1, "type": "movie"},
        {"title": "Old Movie", "release_year": 2010, "rank": 2, "type": "movie"}
    ]

    collection_updated = sync_plex_collection(plex_server, "Netflix Top 10 - US Films", updated_ranked_items)
    assert collection_updated.items() == [item1, item3]


def test_sync_plex_playlist():
    item1 = MockPlexItem("Stranger Things", 2016, "show")
    section = MockLibrarySection("TV Shows", "show", [item1])
    plex_server = MockPlexServer([section])

    ranked_items = [
        {"title": "Stranger Things", "release_year": 2016, "rank": 1, "type": "tv"}
    ]

    playlist = sync_plex_playlist(plex_server, "Netflix Top 10 - US TV Playlist", ranked_items)
    assert playlist is not None
    assert playlist.title == "Netflix Top 10 - US TV Playlist"
    assert playlist._items == [item1]

    # Rebuilding playlist deletes previous instance
    playlist2 = sync_plex_playlist(plex_server, "Netflix Top 10 - US TV Playlist", ranked_items)
    assert playlist.deleted is True
    assert playlist2 is not None


def test_run_plex_sync_success(tmp_path):
    db_file = str(tmp_path / "test_netplex.db")
    init_db(db_file)
    
    set_setting(db_file, "plex_url", "http://localhost:32400")
    set_setting(db_file, "plex_token", "valid_token")
    set_monitored_country(db_file, "US", "movies")
    
    item_id = upsert_media_item(db_file, "Inside Out 2", "movie", 2024, None, "Inside Out 2 (2024)")
    insert_ranking(db_file, "US", "Movies", 1, "2026-W32", item_id)

    item1 = MockPlexItem("Inside Out 2", 2024)
    section = MockLibrarySection("Movies", "movie", [item1])
    mock_server = MockPlexServer([section])

    with patch("src.plex.sync.connect_to_plex", return_value=mock_server):
        result = run_plex_sync(db_file, "2026-W32")
        assert result is True
        assert len(section.collections()) == 1
        assert section.collections()[0].title == "Netflix Top 10 - US Movies"


def test_run_plex_sync_missing_settings(tmp_path):
    db_file = str(tmp_path / "test_netplex.db")
    init_db(db_file)
    
    # Missing plex_url & token
    result = run_plex_sync(db_file, "2026-W32")
    assert result is False


def test_run_plex_sync_offline_resilience(tmp_path):
    db_file = str(tmp_path / "test_netplex.db")
    init_db(db_file)
    
    set_setting(db_file, "plex_url", "http://unreachable-plex:32400")
    set_setting(db_file, "plex_token", "token")

    with patch("src.plex.sync.connect_to_plex", side_effect=Exception("Connection timed out")):
        # Should gracefully return False without throwing uncaught Exception
        result = run_plex_sync(db_file, "2026-W32")
        assert result is False
