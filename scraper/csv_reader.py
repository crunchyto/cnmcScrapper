"""CSV reader with phone number validation for Spanish mobile numbers."""
import logging
import re
from pathlib import Path

from .utils import load_config

logger = logging.getLogger("cnmc_scraper")

SPANISH_MOBILE_RE = re.compile(r"^[67]\d{8}$")


def read_phones(input_path: str | None = None) -> list[str]:
    """Read and validate phone numbers from a single-column CSV.

    Args:
        input_path: Path to CSV file. Falls back to config.yaml input_csv.

    Returns:
        Deduplicated list of valid 9-digit Spanish mobile numbers.
    """
    if input_path is None:
        config = load_config()
        input_path = str(config.get("input_csv", "phones.csv"))

    path = Path(input_path)
    if not path.exists():
        logger.error(f"Input CSV not found: {input_path}")
        return []

    seen: set[str] = set()
    phones: list[str] = []

    with open(path, "r") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            if not SPANISH_MOBILE_RE.match(raw):
                logger.warning(f"Skipping invalid phone: {raw}")
                continue
            if raw in seen:
                continue
            seen.add(raw)
            phones.append(raw)

    logger.info(f"Loaded {len(phones)} valid phone numbers from {input_path}")
    return phones
