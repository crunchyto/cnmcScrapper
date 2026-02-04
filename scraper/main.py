"""CNMC mobile portability scraper — main orchestration with resume."""

import argparse
import asyncio
import logging
import signal

from .browser import Browser
from .captcha import CaptchaSolver
from .csv_reader import read_phones
from .database import Database
from .parser import parse_result
from .proxy_pool import ProxyPool
from .utils import load_config, setup_logging

logger = logging.getLogger("cnmc_scraper")

MAX_RETRIES = 3


class GracefulExit(Exception):
    """Raised on SIGINT to trigger graceful shutdown."""


def _setup_signal_handler() -> None:
    """Install SIGINT handler that raises GracefulExit."""
    def handler(_sig: int, _frame: object) -> None:
        logger.info("SIGINT received, shutting down gracefully...")
        raise GracefulExit()
    signal.signal(signal.SIGINT, handler)


async def _process_phone(
    phone: str,
    browser: Browser,
    captcha_solver: CaptchaSolver,
    config: dict,
) -> dict[str, str] | None:
    """Navigate form, solve captcha, submit, parse result for one phone.

    Returns parsed dict or None on failure.
    """
    base_url = str(config.get("scraping", {}).get(
        "base_url", "https://numeracionyoperadores.cnmc.es/portabilidad/movil"
    ))

    await browser.navigate_to_form()
    await browser.fill_phone(phone)

    # Detect and solve captcha
    sitekey = await captcha_solver.detect_sitekey(browser.page)
    if sitekey:
        token = captcha_solver.solve(sitekey, base_url)
        if token is None:
            raise RuntimeError("Captcha solve failed")
        await captcha_solver.inject_token(browser.page, token)

    await browser.submit_form()
    html = await browser.get_response_html()
    return parse_result(html)


async def run(config: dict, input_path: str | None, reset: bool) -> None:
    """Main async orchestration loop."""
    _setup_signal_handler()

    db = Database()
    phones = read_phones(input_path)
    if not phones:
        logger.error("No valid phones to process")
        db.close()
        return

    csv_file = input_path or str(config.get("input_csv", "phones.csv"))
    start_line = 0
    if reset:
        db.update_progress(csv_file, 0)
        logger.info("Progress reset for %s", csv_file)
    else:
        start_line = db.get_progress(csv_file)
        if start_line > 0:
            logger.info("Resuming from line %d for %s", start_line, csv_file)

    proxy_pool = ProxyPool(config)
    proxy_pool.connect()

    captcha_solver = CaptchaSolver(config)
    browser = Browser(config)
    await browser.start()

    delay = float(config.get("scraping", {}).get("delay_seconds", 2))
    retry_cfg = config.get("retry", {})
    max_retries = int(retry_cfg.get("max_attempts", MAX_RETRIES))
    base_delay = float(retry_cfg.get("base_delay_seconds", 5))

    success_count = 0
    fail_count = 0
    skip_count = start_line
    last_idx = start_line

    try:
        for idx, phone in enumerate(phones):
            if idx < start_line:
                continue
            last_idx = idx

            retries = 0
            succeeded = False

            while retries < max_retries and not succeeded:
                try:
                    result = await _process_phone(phone, browser, captcha_solver, config)
                    if result:
                        db.upsert_result(result["phone"] or phone, result["operator"], result["query_date"])
                        logger.info("[%d/%d] %s -> %s", idx + 1, len(phones), phone, result["operator"])
                        succeeded = True
                        success_count += 1
                    else:
                        raise RuntimeError("Parse returned None")
                except GracefulExit:
                    raise
                except Exception as e:
                    retries += 1
                    is_captcha_or_block = "captcha" in str(e).lower() or "block" in str(e).lower()
                    if is_captcha_or_block:
                        logger.warning("Captcha/block failure for %s, rotating IP: %s", phone, e)
                        proxy_pool.force_rotate()
                        await browser.rotate_user_agent()
                    elif retries < max_retries:
                        wait = base_delay * (2 ** (retries - 1))
                        logger.warning("Retry %d/%d for %s: %s (wait %.0fs)", retries, max_retries, phone, e, wait)
                        await asyncio.sleep(wait)
                    else:
                        logger.error("All %d retries failed for %s: %s", max_retries, phone, e)

            if not succeeded:
                fail_count += 1

            # Update progress after each phone
            db.update_progress(csv_file, idx + 1)

            # Rotate IP every N successful queries
            if succeeded:
                rotated = proxy_pool.rotate_if_needed(success_count)
                if rotated:
                    await browser.rotate_user_agent()

            # Delay between queries
            if idx < len(phones) - 1:
                await asyncio.sleep(delay)

    except GracefulExit:
        logger.info("Graceful shutdown: saving progress at line %d", last_idx + 1)
        db.update_progress(csv_file, last_idx)
    finally:
        await browser.stop()
        db.close()

    logger.info("Done. success=%d fail=%d skipped=%d total=%d", success_count, fail_count, skip_count, len(phones))


def main() -> None:
    parser = argparse.ArgumentParser(description="CNMC Mobile Portability Scraper")
    parser.add_argument("--input", type=str, default=None, help="Path to phone CSV")
    parser.add_argument("--reset", action="store_true", help="Clear progress and start from line 0")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config)

    asyncio.run(run(config, args.input, args.reset))


if __name__ == "__main__":
    main()
