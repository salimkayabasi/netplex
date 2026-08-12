import os
import sys
import logging
from logging.handlers import RotatingFileHandler

_initialized = False

class LoggerFilter(logging.Filter):
    """
    Filter that only allows log records matching specified logger names or prefixes.
    e.g. log_filter="netplex.crawler" matches "netplex.crawler" or "netplex.crawler.foo".
    Multiple loggers can be comma-separated: "netplex.crawler,netplex.scheduler".
    """
    def __init__(self, allowed_loggers: str):
        super().__init__()
        self.allowed_loggers = [name.strip() for name in allowed_loggers.split(",") if name.strip()]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.allowed_loggers:
            return True
        return any(
            record.name == allowed or record.name.startswith(allowed + ".")
            for allowed in self.allowed_loggers
        )

def setup_logger(log_level: str = None, log_file: str = None, log_filter: str = None) -> logging.Logger:
    """
    Configures and returns the application logger with both standard output (stdout)
    and rotating file handlers. Supports log filtering.
    """
    global _initialized
    if log_level is None:
        log_level = os.environ.get("NETPLEX_LOG_LEVEL", "INFO")
        
    if log_filter is None:
        log_filter = os.environ.get("NETPLEX_LOG_FILTER", None)

    if log_file is None:
        config_dir = os.environ.get("NETPLEX_CONFIG_DIR", "/config")
        log_file = os.path.join(config_dir, "netplex.log")

    numeric_level = getattr(logging, str(log_level).upper(), logging.INFO)

    # Configure root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Configure netplex parent logger
    logger = logging.getLogger("netplex")
    logger.setLevel(numeric_level)

    # Clear existing handlers to prevent duplicated logs on re-initialization
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Console Handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    if log_filter:
        filter_obj = LoggerFilter(log_filter)
        console_handler.addFilter(filter_obj)
        for uvicorn_logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            logging.getLogger(uvicorn_logger_name).addFilter(filter_obj)
    logger.addHandler(console_handler)

    # Rotating File Handler
    if log_file:
        try:
            abs_log_path = os.path.abspath(log_file)
            log_dir = os.path.dirname(abs_log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
                
            file_handler = RotatingFileHandler(
                abs_log_path,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=3,
                encoding="utf-8"
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to setup file logger at {log_file}: {e}\n")

    _initialized = True
    return logger

def get_logger(name: str = "netplex") -> logging.Logger:
    """
    Helper function to retrieve logger instance. Automatically initializes setup_logger if not yet configured.
    """
    global _initialized
    if not _initialized and not logging.getLogger("netplex").hasHandlers():
        setup_logger()

    if name != "netplex" and not name.startswith("netplex."):
        name = f"netplex.{name}"

    return logging.getLogger(name)

