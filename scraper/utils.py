import hashlib
import json
import logging
import sys
from pathlib import Path

import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> logging.Logger:
    """Configure logging based on config."""
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO").upper())
    log_file = log_config.get("file")

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )
    return logging.getLogger("michelin_scraper")


def compute_content_hash(data: dict) -> str:
    """Compute SHA256 hash of restaurant data for change detection."""
    # Sort keys for consistent hashing
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
