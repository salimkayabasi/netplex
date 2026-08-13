import threading

_IS_CRAWLING = False
_CURRENT_TASK = 0
_TOTAL_TASKS = 0
_TASK_MESSAGE = ""
_crawl_lock = threading.Lock()

def try_acquire_crawl_lock() -> bool:
    """Attempts to acquire the crawling lock atomically. Returns True if acquired, False if already crawling."""
    global _IS_CRAWLING, _CURRENT_TASK, _TOTAL_TASKS, _TASK_MESSAGE
    with _crawl_lock:
        if _IS_CRAWLING:
            return False
        _IS_CRAWLING = True
        _CURRENT_TASK = 0
        _TOTAL_TASKS = 0
        _TASK_MESSAGE = "Initiating crawl..."
        return True

def release_crawl_lock():
    """Releases the crawling lock and resets progress state."""
    global _IS_CRAWLING, _CURRENT_TASK, _TOTAL_TASKS, _TASK_MESSAGE
    with _crawl_lock:
        _IS_CRAWLING = False
        _CURRENT_TASK = 0
        _TOTAL_TASKS = 0
        _TASK_MESSAGE = ""

def is_crawl_in_progress() -> bool:
    """Checks whether a crawl job is currently running."""
    with _crawl_lock:
        return _IS_CRAWLING

def set_crawl_progress(current_task: int, total_tasks: int, message: str = ""):
    """Updates the current crawl task progress and message thread-safely."""
    global _CURRENT_TASK, _TOTAL_TASKS, _TASK_MESSAGE
    with _crawl_lock:
        _CURRENT_TASK = current_task
        _TOTAL_TASKS = total_tasks
        if message:
            _TASK_MESSAGE = message

def get_crawl_status_info() -> dict:
    """Returns detailed dictionary of crawl progress status for API responses."""
    with _crawl_lock:
        if not _IS_CRAWLING:
            return {
                "is_crawling": False,
                "current_task": 0,
                "total_tasks": 0,
                "task_display": "",
                "message": "Idle"
            }
        
        if _TOTAL_TASKS > 0:
            display = f"Crawling ({_CURRENT_TASK}/{_TOTAL_TASKS})"
        else:
            display = "Crawling..."

        return {
            "is_crawling": True,
            "current_task": _CURRENT_TASK,
            "total_tasks": _TOTAL_TASKS,
            "task_display": display,
            "message": _TASK_MESSAGE or display
        }

