"""Isolated Tor proxy pool module — counter-based IP rotation via stem.

Copy this whole folder into your project and install the dependencies
listed in requirements.txt (stem, pyyaml). See README.md for usage.
"""

from .proxy_pool import ProxyPool
from .utils import load_config

__all__ = ["ProxyPool", "load_config"]
