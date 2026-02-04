"""Tor-based proxy pool with counter-based IP rotation via stem."""

import logging
import time

from stem import Signal
from stem.control import Controller

from .utils import load_config

logger = logging.getLogger(__name__)

MIN_ROTATION_WAIT = 10  # Tor needs ~10s for new circuit after NEWNYM


class ProxyPool:
    def __init__(self, config: dict | None = None):
        if config is None:
            config = load_config()
        proxy_cfg = config.get("proxy", {})
        scraping_cfg = config.get("scraping", {})

        self.tor_host: str = str(proxy_cfg.get("tor_host", "127.0.0.1"))
        self.tor_port: int = int(proxy_cfg.get("tor_port", 9050))
        self.control_port: int = int(proxy_cfg.get("control_port", 9051))
        self.control_password: str = str(proxy_cfg.get("control_password", "scraper"))
        self.rotation_count: int = int(scraping_cfg.get("rotation_count", 9))

        self._last_rotation: float = 0.0
        self._query_counter: int = 0

    def connect(self) -> None:
        """Verify Tor control port connectivity."""
        try:
            with Controller.from_port(port=self.control_port) as ctrl:
                ctrl.authenticate(password=self.control_password)
                logger.info("Tor control port connected")
        except Exception as e:
            logger.error(f"Cannot connect to Tor control port: {e}")

    def get_socks_proxy(self) -> str:
        """Return Tor SOCKS5 proxy URL for Playwright."""
        return f"socks5://{self.tor_host}:{self.tor_port}"

    def rotate_if_needed(self, query_count: int) -> bool:
        """Rotate IP if query_count is a multiple of rotation_count.

        Returns True if rotation happened.
        """
        if query_count > 0 and query_count % self.rotation_count == 0:
            self._rotate()
            return True
        return False

    def force_rotate(self) -> None:
        """Force immediate IP rotation (e.g. on block/captcha failure)."""
        self._rotate()

    def reset_counter(self) -> None:
        """Reset the internal query counter."""
        self._query_counter = 0
        logger.debug("Proxy pool query counter reset")

    def _rotate(self) -> None:
        """Send NEWNYM signal to Tor, respecting minimum wait interval."""
        elapsed = time.time() - self._last_rotation
        if elapsed < MIN_ROTATION_WAIT:
            wait = MIN_ROTATION_WAIT - elapsed
            logger.debug(f"Waiting {wait:.0f}s before Tor IP rotation")
            time.sleep(wait)
        try:
            with Controller.from_port(port=self.control_port) as ctrl:
                ctrl.authenticate(password=self.control_password)
                ctrl.signal(Signal.NEWNYM)  # pyright: ignore[reportAttributeAccessIssue]
                self._last_rotation = time.time()
                logger.info("Tor IP rotated (NEWNYM signal sent)")
        except Exception as e:
            logger.warning(f"Failed to rotate Tor IP: {e}")
