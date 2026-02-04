import logging
import re

from playwright.async_api import Page
from twocaptcha import TwoCaptcha
from twocaptcha import (
    ApiException,
    NetworkException,
    TimeoutException,
    ValidationException,
)

from .utils import load_config, setup_logging


class CaptchaSolver:
    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self.logger: logging.Logger = setup_logging(self.config)
        api_key = str(self.config.get("captcha", {}).get("api_key", ""))
        if not api_key:
            raise ValueError("2Captcha API key not set in config.yaml")
        self.solver = TwoCaptcha(apiKey=api_key)

    async def detect_sitekey(self, page: Page) -> str | None:
        """Extract reCAPTCHA sitekey from page HTML."""
        html = await page.content()
        # Look for data-sitekey attribute
        match = re.search(r'data-sitekey=["\']([^"\']+)["\']', html)
        if match:
            return match.group(1)
        # Look for sitekey in grecaptcha.render call
        match = re.search(r"grecaptcha\.render\([^,]+,\s*\{[^}]*sitekey['\"]?\s*:\s*['\"]([^'\"]+)['\"]", html)
        if match:
            return match.group(1)
        self.logger.error("Could not detect reCAPTCHA sitekey on page")
        return None

    def solve(self, sitekey: str, page_url: str) -> str | None:
        """Send solve request to 2Captcha and return token."""
        try:
            self.logger.info("Sending captcha to 2Captcha...")
            result = self.solver.recaptcha(sitekey=sitekey, url=page_url)
            if result is None:
                self.logger.error("2Captcha returned empty result")
                return None
            token: str = result["code"]
            self.logger.info("Captcha solved successfully")
            return token
        except ValidationException as e:
            self.logger.error("2Captcha validation error: %s", e)
        except NetworkException as e:
            self.logger.error("2Captcha network error: %s", e)
        except ApiException as e:
            self.logger.error("2Captcha API error: %s", e)
        except TimeoutException as e:
            self.logger.error("2Captcha timeout: %s", e)
        return None

    async def inject_token(self, page: Page, token: str) -> None:
        """Set g-recaptcha-response in the page."""
        await page.evaluate(
            """(token) => {
                const el = document.getElementById('g-recaptcha-response');
                if (el) {
                    el.style.display = '';
                    el.value = token;
                }
                // Also try setting via textarea name
                const ta = document.querySelector('textarea[name="g-recaptcha-response"]');
                if (ta) {
                    ta.style.display = '';
                    ta.value = token;
                }
                // Trigger callback if registered
                if (typeof window.captchaCallback === 'function') {
                    window.captchaCallback(token);
                }
                if (typeof ___grecaptcha_cfg !== 'undefined') {
                    const clients = ___grecaptcha_cfg.clients;
                    if (clients) {
                        Object.keys(clients).forEach(key => {
                            const client = clients[key];
                            // Walk nested objects looking for callback
                            const findCallback = (obj) => {
                                if (!obj || typeof obj !== 'object') return;
                                Object.keys(obj).forEach(k => {
                                    if (typeof obj[k] === 'function' && k === 'callback') {
                                        obj[k](token);
                                    } else if (typeof obj[k] === 'object') {
                                        findCallback(obj[k]);
                                    }
                                });
                            };
                            findCallback(client);
                        });
                    }
                }
            }""",
            token,
        )
        self.logger.info("Captcha token injected into page")
