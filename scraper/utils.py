"""Utility functions: config loading and logging setup."""

import logging
import sys
from logging.handlers import RotatingFileHandler

import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def setup_logging(config: dict) -> logging.Logger:
    """Configure logging with rotating file handler and console output.

    File handler: 10 MB max, 5 backups (configurable via config.yaml).
    Console handler: stdout.
    """
    log_config = config.get("logging", {})
    level_name = str(log_config.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    log_file = log_config.get("file")
    max_bytes = int(log_config.get("max_bytes", 10_485_760))
    backup_count = int(log_config.get("backup_count", 5))

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    # Clear existing handlers to avoid duplicates on re-init
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file:
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    return logging.getLogger("cnmc_scraper")
