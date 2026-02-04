import asyncio
import random
from contextlib import asynccontextmanager
from typing import Optional

from playwright.async_api import async_playwright, Browser as PWBrowser, Page

from .utils import load_config, setup_logging

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


class Browser:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.logger = setup_logging(self.config)
        self._playwright = None
        self._browser: Optional[PWBrowser] = None

    def _get_proxy_config(self) -> Optional[dict]:
        """Build proxy config if enabled."""
        proxy_cfg = self.config.get("proxy", {})
        if not proxy_cfg.get("enabled"):
            return None
        proxy = {"server": proxy_cfg["server"]}
        if proxy_cfg.get("username"):
            proxy["username"] = proxy_cfg["username"]
            proxy["password"] = proxy_cfg.get("password", "")
        return proxy

    async def start(self):
        """Start browser instance."""
        self._playwright = await async_playwright().start()
        proxy = self._get_proxy_config()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            proxy=proxy,
            channel="chrome",
        )
        self.logger.info("Browser started")

    async def stop(self):
        """Stop browser instance."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self.logger.info("Browser stopped")

    @asynccontextmanager
    async def new_page(self, proxy: dict = None):
        """Create new page with random user agent and optional proxy."""
        user_agent = random.choice(USER_AGENTS)
        ctx_options = {"user_agent": user_agent}
        if proxy:
            ctx_options["proxy"] = proxy
        context = await self._browser.new_context(**ctx_options)
        page = await context.new_page()
        # Mask automation signals
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = {runtime: {}};
        """)
        timeout = self.config.get("scraping", {}).get("page_load_timeout_ms", 30000)
        page.set_default_timeout(timeout)
        try:
            yield page
        finally:
            await context.close()

    async def fetch(self, url: str, proxy: dict = None,
                    wait_for_selector: str = None) -> str:
        """Fetch page HTML."""
        async with self.new_page(proxy=proxy) as page:
            await page.goto(url, wait_until="networkidle")
            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=10000)
                except Exception:
                    pass  # proceed with whatever loaded
            return await page.content()

    async def test_connection(self):
        """Test browser can connect to Michelin."""
        base_url = self.config.get("scraping", {}).get(
            "base_url", "https://guide.michelin.com/en/restaurants"
        )
        await self.start()
        try:
            async with self.new_page() as page:
                await page.goto(base_url, wait_until="domcontentloaded")
                title = await page.title()
                self.logger.info(f"Connection OK: {title}")
                return True
        finally:
            await self.stop()


@asynccontextmanager
async def create_browser(config: Optional[dict] = None):
    """Async context manager for browser lifecycle."""
    browser = Browser(config)
    await browser.start()
    try:
        yield browser
    finally:
        await browser.stop()
