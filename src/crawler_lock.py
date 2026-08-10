import threading

_IS_CRAWLING = False
_crawl_lock = threading.Lock()

def try_acquire_crawl_lock() -> bool:
    """Attempts to acquire the crawling lock atomically. Returns True if acquired, False if already crawling."""
    global _IS_CRAWLING
    with _crawl_lock:
        if _IS_CRAWLING:
            return False
        _IS_CRAWLING = True
        return True

def release_crawl_lock():
    """Releases the crawling lock."""
    global _IS_CRAWLING
    with _crawl_lock:
        _IS_CRAWLING = False

def is_crawl_in_progress() -> bool:
    """Checks whether a crawl job is currently running."""
    global _IS_CRAWLING
    with _crawl_lock:
        return _IS_CRAWLING
