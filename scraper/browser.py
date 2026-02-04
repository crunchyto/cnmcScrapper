import logging
import random
from typing import Optional

from playwright.async_api import async_playwright, Browser as PWBrowser, BrowserContext, Page, Playwright, ProxySettings

from .utils import load_config, setup_logging

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

WEBDRIVER_MASK_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => false});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
    Object.defineProperty(navigator, 'languages', {get: () => ['es-ES', 'es', 'en']});
    window.chrome = {runtime: {}};
"""


class Browser:
    """Playwright browser wrapper for CNMC form interaction via Tor SOCKS proxy."""

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self.logger: logging.Logger = setup_logging(self.config)
        self._playwright: Playwright | None = None
        self._browser: Optional[PWBrowser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def _build_tor_proxy(self) -> "ProxySettings":
        """Build Tor SOCKS5 proxy dict from config."""
        proxy_cfg = self.config.get("proxy", {})
        host = str(proxy_cfg.get("tor_host", "127.0.0.1"))
        port = int(proxy_cfg.get("tor_port", 9050))
        proxy: "ProxySettings" = {"server": f"socks5://{host}:{port}"}
        return proxy

    async def start(self) -> None:
        """Launch Chromium with Tor SOCKS proxy and webdriver masking."""
        pw = await async_playwright().start()
        self._playwright = pw
        proxy = self._build_tor_proxy()
        self._browser = await pw.chromium.launch(
            headless=True,
            proxy=proxy,
        )
        user_agent = random.choice(USER_AGENTS)
        timeout_ms = int(self.config.get("scraping", {}).get("page_load_timeout_ms", 60000))
        self._context = await self._browser.new_context(user_agent=user_agent)
        self._context.set_default_timeout(timeout_ms)
        page = await self._context.new_page()
        await page.add_init_script(WEBDRIVER_MASK_SCRIPT)
        self._page = page
        self.logger.info("Browser started with Tor proxy and UA: %s", user_agent[:40])

    async def stop(self) -> None:
        """Close browser and playwright."""
        if self._context:
            await self._context.close()
            self._context = None
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self.logger.info("Browser stopped")

    @property
    def page(self) -> Page:
        """Return current page; raises if browser not started."""
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    async def navigate_to_form(self) -> None:
        """Load the CNMC portability checker page and dismiss cookie consent."""
        base_url = str(self.config.get("scraping", {}).get(
            "base_url", "https://numeracionyoperadores.cnmc.es/portabilidad/movil"
        ))
        self.logger.info("Navigating to %s", base_url)
        await self.page.goto(base_url, wait_until="networkidle")
        # Dismiss cookie consent dialog if present
        try:
            acepto = self.page.locator('button:has-text("Acepto")')
            await acepto.click(timeout=3000)
            await self.page.wait_for_timeout(500)
            self.logger.info("Cookie consent dismissed")
        except Exception:
            pass
        self.logger.info("CNMC form page loaded")

    async def fill_phone(self, phone: str) -> None:
        """Enter phone number into the CNMC Vuetify form input field."""
        input_selector = "input.v-field__input"
        await self.page.wait_for_selector(input_selector)
        await self.page.locator(input_selector).first.fill(phone)
        self.logger.info("Filled phone: %s", phone)

    async def submit_form(self) -> None:
        """Click the Buscar button on the CNMC form."""
        submit_selector = 'button.v-btn.bg-warning:has-text("Buscar")'
        await self.page.locator(submit_selector).click()
        self.logger.info("Form submitted")

    async def get_response_html(self) -> str:
        """Wait for result card and return the result column HTML."""
        try:
            await self.page.wait_for_selector(
                ".v-col-lg-8 .v-card",
                timeout=30000,
            )
        except Exception:
            self.logger.warning("Result card not found; returning full page HTML")
        return await self.page.locator(".v-col-lg-8").inner_html()

    async def rotate_user_agent(self) -> None:
        """Create a new context+page with a fresh user agent (call after IP rotation)."""
        old_page = self._page
        old_ctx = self._context
        user_agent = random.choice(USER_AGENTS)
        if self._browser is None:
            raise RuntimeError("Browser not started")
        timeout_ms = int(self.config.get("scraping", {}).get("page_load_timeout_ms", 60000))
        self._context = await self._browser.new_context(user_agent=user_agent)
        self._context.set_default_timeout(timeout_ms)
        page = await self._context.new_page()
        await page.add_init_script(WEBDRIVER_MASK_SCRIPT)
        self._page = page
        if old_ctx:
            await old_ctx.close()
        self.logger.info("Rotated user agent: %s", user_agent[:40])
