import os
import sys
import logging
from logging.handlers import RotatingFileHandler

def setup_logger(log_level: str = "INFO", log_file: str = "/config/netplex.log") -> logging.Logger:
    """
    Configures and returns the application logger with both standard output (stdout)
    and rotating file handlers.
    """
    numeric_level = getattr(logging, str(log_level).upper(), logging.INFO)
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
    logger.addHandler(console_handler)

    # Rotating File Handler
    if log_file:
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

    return logger

def get_logger(name: str = "netplex") -> logging.Logger:
    """
    Helper function to retrieve logger instance.
    """
    return logging.getLogger(name)
