"""Utility functions: config loading (isolated copy for tor_proxy module)."""

import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]
