"""Tor-based proxy with IP rotation via stem."""
import logging
import time
from typing import Optional

from stem import Signal
from stem.control import Controller

logger = logging.getLogger(__name__)

TOR_PROXY = {"server": "http://127.0.0.1:8118"}
CONTROL_PORT = 9051
CONTROL_PASSWORD = "scraper"
MIN_ROTATION_INTERVAL = 10  # Tor needs ~10s between NEWNYM signals


class ProxyPool:
    def __init__(self):
        self._last_rotation = 0.0

    def refresh(self):
        """Verify Tor connectivity."""
        try:
            with Controller.from_port(port=CONTROL_PORT) as ctrl:
                ctrl.authenticate(password=CONTROL_PASSWORD)
                logger.info("Tor control port connected")
        except Exception as e:
            logger.error(f"Cannot connect to Tor control port: {e}")

    def get_proxy(self) -> Optional[dict]:
        return TOR_PROXY

    def rotate_ip(self):
        """Request new Tor circuit (new exit IP)."""
        elapsed = time.time() - self._last_rotation
        if elapsed < MIN_ROTATION_INTERVAL:
            wait = MIN_ROTATION_INTERVAL - elapsed
            logger.debug(f"Waiting {wait:.0f}s before rotating Tor IP")
            time.sleep(wait)
        try:
            with Controller.from_port(port=CONTROL_PORT) as ctrl:
                ctrl.authenticate(password=CONTROL_PASSWORD)
                ctrl.signal(Signal.NEWNYM)
                self._last_rotation = time.time()
                logger.info("Tor IP rotated (NEWNYM)")
        except Exception as e:
            logger.warning(f"Failed to rotate Tor IP: {e}")

    def blacklist(self, proxy_server: str):
        """For Tor, blacklist means rotate to new circuit."""
        self.rotate_ip()

    def size(self) -> int:
        return 1  # Single Tor proxy, infinite IPs
