"""Main scraper CLI and orchestration."""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import time

from .browser import create_browser
from .database import Database
from .parser import parse_listing_page, parse_detail_page, parse_total_count
from .proxy_pool import ProxyPool
from .utils import load_config, setup_logging

CHECKPOINT_FILE = "checkpoint.json"
MAX_PAGES = 50
EMPTY_PAGE_THRESHOLD = 3
RESTAURANTS_PER_PAGE = 48


async def fetch_with_retry(browser, url: str, config: dict, logger,
                          proxy_pool: ProxyPool = None) -> Optional[str]:
    """Fetch URL with exponential backoff retry and optional proxy rotation."""
    retry_cfg = config.get("retry", {})
    max_attempts = retry_cfg.get("max_attempts", 3)
    base_delay = retry_cfg.get("base_delay_seconds", 5)

    proxy = proxy_pool.get_proxy() if proxy_pool else None

    for attempt in range(max_attempts):
        try:
            html = await browser.fetch(url, proxy=proxy)
            # Check for 403 in response (Playwright doesn't raise on 403)
            if "Access Denied" in html or "403 Forbidden" in html:
                raise Exception("403 Forbidden detected")
            return html
        except Exception as e:
            # On any failure with proxy pool: blacklist and rotate
            if proxy_pool and proxy:
                logger.warning(f"Failed with proxy {proxy['server']}: {e}")
                proxy_pool.blacklist(proxy["server"])
                proxy = proxy_pool.get_proxy()
                if proxy:
                    logger.debug(f"Rotated proxy, {proxy_pool.size()} remaining")
                    continue  # Retry immediately with new proxy

            delay = (2 ** attempt) * base_delay
            logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed for {url}: {e}")
            if attempt < max_attempts - 1:
                logger.info(f"Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_attempts} attempts failed for {url}")
                return None


def load_checkpoint() -> dict:
    """Load checkpoint if exists."""
    if Path(CHECKPOINT_FILE).exists():
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {}


def save_checkpoint(data: dict):
    """Save checkpoint to file."""
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f)


def clear_checkpoint():
    """Remove checkpoint file."""
    if Path(CHECKPOINT_FILE).exists():
        Path(CHECKPOINT_FILE).unlink()


def write_change_log(changes: list[dict], log_file: str = "additions.txt"):
    """Append changes to log file."""
    with open(log_file, "a") as f:
        for c in changes:
            f.write(f"[{c['timestamp']}] {c['action'].upper()}: {c['name']} ({c['michelin_id']})\n")


def _build_listing_url(config: dict, page_num: int) -> str:
    """Build listing page URL with query string."""
    scraping = config.get("scraping", {})
    base_url = scraping.get("base_url", "https://guide.michelin.com/es/es/restaurantes")
    query = scraping.get("base_url_query", "")
    qs = f"?{query}" if query else ""
    if page_num > 1:
        return f"{base_url}/page/{page_num}{qs}"
    return f"{base_url}{qs}"


async def scrape_listing_page(browser, page_num: int, config: dict, logger,
                              proxy_pool: ProxyPool = None,
                              return_html: bool = False):
    """Scrape single listing page. Returns (restaurants, html) if return_html else restaurants."""
    url = _build_listing_url(config, page_num)

    logger.info(f"Fetching listing page {page_num}")
    html = await fetch_with_retry(browser, url, config, logger, proxy_pool)
    if not html:
        return ([], None) if return_html else []

    restaurants = parse_listing_page(html)
    logger.info(f"Found {len(restaurants)} restaurants on page {page_num}")
    return (restaurants, html) if return_html else restaurants


async def scrape_restaurant_details(browser, restaurants: list[dict], db: Database,
                                    config: dict, logger, existing_hashes: dict = None,
                                    proxy_pool: ProxyPool = None) -> tuple[dict, list[dict]]:
    """Scrape detail pages for restaurants. Returns (stats, changes)."""
    stats = {"added": 0, "modified": 0, "unchanged": 0, "failed": 0}
    changes = []
    batch_size = config.get("scraping", {}).get("batch_size", 25)
    batch_delay = config.get("scraping", {}).get("batch_delay_seconds", 10)

    for i, rest in enumerate(restaurants):
        url = rest["url"]
        michelin_id = url.rstrip("/").split("/")[-1]

        # Skip if hash unchanged (update mode)
        if existing_hashes and michelin_id in existing_hashes:
            # Still need to fetch to compare hash
            pass

        logger.debug(f"Fetching detail: {rest.get('name', michelin_id)}")
        html = await fetch_with_retry(browser, url, config, logger, proxy_pool)

        if not html:
            stats["failed"] += 1
            continue

        data = parse_detail_page(html, url)
        if not data:
            stats["failed"] += 1
            continue

        # Check if we can skip (update mode with matching hash)
        if existing_hashes and michelin_id in existing_hashes:
            if existing_hashes[michelin_id] == data.get("content_hash"):
                stats["unchanged"] += 1
                continue

        _, action = db.upsert_restaurant(data)
        stats[action] += 1

        # Track changes for log
        if action in ("added", "modified"):
            changes.append({
                "timestamp": datetime.utcnow().isoformat(),
                "action": action,
                "name": data.get("name", "Unknown"),
                "michelin_id": michelin_id,
            })

        # Batch delay
        if (i + 1) % batch_size == 0 and i < len(restaurants) - 1:
            logger.info(f"Batch complete ({i + 1}/{len(restaurants)}), waiting {batch_delay}s...")
            await asyncio.sleep(batch_delay)

    return stats, changes


async def run_full_scrape(config: dict, logger, resume: bool = True, use_proxies: bool = False):
    """Run full scrape — two-pass: scan all listing pages, then scrape details."""
    db = Database()
    checkpoint = load_checkpoint() if resume else {}
    page_delay = config.get("scraping", {}).get("page_delay_seconds", 3)

    proxy_pool = None
    if use_proxies:
        proxy_pool = ProxyPool()
        proxy_pool.refresh()
        logger.info(f"Proxy pool initialized with {proxy_pool.size()} proxies")

    total_stats = {"added": 0, "modified": 0, "unchanged": 0, "failed": 0}
    all_changes = []

    # Determine pass state from checkpoint
    pass_phase = checkpoint.get("pass_phase", "scan")
    collected_urls = checkpoint.get("collected_urls", [])
    processed_urls = set(checkpoint.get("processed_urls", []))

    async with create_browser(config) as browser:
        # --- Pass 1: Scan listing pages, collect restaurant URLs ---
        if pass_phase == "scan":
            start_page = checkpoint.get("last_page", 0) + 1
            logger.info(f"Pass 1 (scan): collecting URLs from page {start_page}")
            seen = set(collected_urls)
            page_num = start_page
            consecutive_empty = 0

            while page_num <= MAX_PAGES and consecutive_empty < EMPTY_PAGE_THRESHOLD:
                if page_num == start_page and start_page == 1:
                    restaurants, raw_html = await scrape_listing_page(
                        browser, page_num, config, logger, proxy_pool, return_html=True
                    )
                    if raw_html:
                        total = parse_total_count(raw_html)
                        if total:
                            logger.info(f"Total restaurants on site: {total}")
                else:
                    restaurants = await scrape_listing_page(browser, page_num, config, logger, proxy_pool)

                if not restaurants:
                    consecutive_empty += 1
                    logger.info(f"Empty page {page_num} ({consecutive_empty}/{EMPTY_PAGE_THRESHOLD} consecutive)")
                else:
                    consecutive_empty = 0
                    for r in restaurants:
                        if r["url"] not in seen:
                            seen.add(r["url"])
                            collected_urls.append(r["url"])

                save_checkpoint({
                    "pass_phase": "scan",
                    "last_page": page_num,
                    "collected_urls": collected_urls,
                    "processed_urls": list(processed_urls),
                    "started_at": checkpoint.get("started_at", datetime.utcnow().isoformat()),
                })

                logger.info(f"Page {page_num} scanned. {len(collected_urls)} URLs collected so far.")

                if proxy_pool and page_num % 5 == 0:
                    proxy_pool.rotate_ip()

                page_num += 1
                time.sleep(page_delay)

            if consecutive_empty >= EMPTY_PAGE_THRESHOLD:
                logger.info(f"Scan done: {EMPTY_PAGE_THRESHOLD} consecutive empty pages at page {page_num - 1}")

            logger.info(f"Pass 1 complete. {len(collected_urls)} restaurant URLs collected.")

            # Save scan checkpoint, advance to scrape phase
            save_checkpoint({
                "pass_phase": "scrape",
                "collected_urls": collected_urls,
                "processed_urls": list(processed_urls),
                "started_at": checkpoint.get("started_at", datetime.utcnow().isoformat()),
            })

        # --- Pass 2: Fetch detail pages ---
        logger.info(f"Pass 2 (scrape): {len(collected_urls)} total, {len(processed_urls)} already done")
        remaining = [u for u in collected_urls if u not in processed_urls]
        batch_size = config.get("scraping", {}).get("batch_size", 25)
        batch_delay = config.get("scraping", {}).get("batch_delay_seconds", 10)

        for i, url in enumerate(remaining):
            michelin_id = url.rstrip("/").split("/")[-1]
            logger.debug(f"Fetching detail {i + 1}/{len(remaining)}: {michelin_id}")

            html = await fetch_with_retry(browser, url, config, logger, proxy_pool)
            if not html:
                total_stats["failed"] += 1
                processed_urls.add(url)
                continue

            data = parse_detail_page(html, url)
            if not data:
                total_stats["failed"] += 1
                processed_urls.add(url)
                continue

            _, action = db.upsert_restaurant(data)
            total_stats[action] += 1

            if action in ("added", "modified"):
                all_changes.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": action,
                    "name": data.get("name", "Unknown"),
                    "michelin_id": michelin_id,
                })

            processed_urls.add(url)

            # Batch delay + checkpoint
            if (i + 1) % batch_size == 0:
                logger.info(f"Batch {(i + 1) // batch_size}: {i + 1}/{len(remaining)} done. "
                           f"+{total_stats['added']} ~{total_stats['modified']} !{total_stats['failed']}")
                save_checkpoint({
                    "pass_phase": "scrape",
                    "collected_urls": collected_urls,
                    "processed_urls": list(processed_urls),
                    "started_at": checkpoint.get("started_at", datetime.utcnow().isoformat()),
                })
                if proxy_pool:
                    proxy_pool.rotate_ip()
                await asyncio.sleep(batch_delay)

    clear_checkpoint()
    db.close()

    if all_changes:
        write_change_log(all_changes)
        logger.info(f"Wrote {len(all_changes)} changes to additions.txt")

    logger.info("Full scrape complete!")
    logger.info(f"Final stats: {total_stats}")
    logger.info(f"Total restaurants in DB: {Database().count()}")
    return total_stats


async def run_update_scrape(config: dict, logger, use_proxies: bool = False):
    """Run incremental update — two-pass: scan listings, then scrape only changed details."""
    db = Database()
    existing_hashes = db.get_all_hashes()
    page_delay = config.get("scraping", {}).get("page_delay_seconds", 3)

    proxy_pool = None
    if use_proxies:
        proxy_pool = ProxyPool()
        proxy_pool.refresh()
        logger.info(f"Proxy pool initialized with {proxy_pool.size()} proxies")

    total_stats = {"added": 0, "modified": 0, "unchanged": 0, "failed": 0}
    all_changes = []

    logger.info(f"Starting update scrape. {len(existing_hashes)} existing restaurants.")

    async with create_browser(config) as browser:
        # --- Pass 1: Scan listing pages, collect URLs ---
        collected_urls = []
        seen = set()
        page_num = 1
        consecutive_empty = 0

        while page_num <= MAX_PAGES and consecutive_empty < EMPTY_PAGE_THRESHOLD:
            restaurants = await scrape_listing_page(browser, page_num, config, logger, proxy_pool)

            if not restaurants:
                consecutive_empty += 1
                logger.info(f"Empty page {page_num} ({consecutive_empty}/{EMPTY_PAGE_THRESHOLD} consecutive)")
            else:
                consecutive_empty = 0
                for r in restaurants:
                    if r["url"] not in seen:
                        seen.add(r["url"])
                        collected_urls.append(r["url"])

            if proxy_pool and page_num % 5 == 0:
                proxy_pool.rotate_ip()

            page_num += 1
            time.sleep(page_delay)

        if consecutive_empty >= EMPTY_PAGE_THRESHOLD:
            logger.info(f"Scan done: {EMPTY_PAGE_THRESHOLD} consecutive empty pages at page {page_num - 1}")

        logger.info(f"Pass 1 complete. {len(collected_urls)} URLs collected.")

        # --- Pass 2: Fetch details, skip unchanged ---
        batch_size = config.get("scraping", {}).get("batch_size", 25)
        batch_delay = config.get("scraping", {}).get("batch_delay_seconds", 10)

        for i, url in enumerate(collected_urls):
            michelin_id = url.rstrip("/").split("/")[-1]
            logger.debug(f"Fetching detail {i + 1}/{len(collected_urls)}: {michelin_id}")

            html = await fetch_with_retry(browser, url, config, logger, proxy_pool)
            if not html:
                total_stats["failed"] += 1
                continue

            data = parse_detail_page(html, url)
            if not data:
                total_stats["failed"] += 1
                continue

            # Skip if hash unchanged
            if michelin_id in existing_hashes and existing_hashes[michelin_id] == data.get("content_hash"):
                total_stats["unchanged"] += 1
                continue

            _, action = db.upsert_restaurant(data)
            total_stats[action] += 1

            if action in ("added", "modified"):
                all_changes.append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": action,
                    "name": data.get("name", "Unknown"),
                    "michelin_id": michelin_id,
                })

            if (i + 1) % batch_size == 0:
                logger.info(f"Batch {(i + 1) // batch_size}: {i + 1}/{len(collected_urls)} done. "
                           f"+{total_stats['added']} ~{total_stats['modified']} ={total_stats['unchanged']}")
                if proxy_pool:
                    proxy_pool.rotate_ip()
                await asyncio.sleep(batch_delay)

    db.close()

    if all_changes:
        write_change_log(all_changes)
        logger.info(f"Wrote {len(all_changes)} changes to additions.txt")

    logger.info("Update scrape complete!")
    logger.info(f"Final stats: {total_stats}")
    return total_stats


def main():
    parser = argparse.ArgumentParser(description="Michelin Guide Restaurant Scraper")
    parser.add_argument("--full", action="store_true", help="Run full scrape of all restaurants")
    parser.add_argument("--update", action="store_true", help="Run incremental update")
    parser.add_argument("--no-resume", action="store_true", help="Start fresh, ignore checkpoint")
    parser.add_argument("--use-proxies", action="store_true", help="Enable proxy rotation for 403 bypass")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--test", action="store_true", help="Test browser connection")

    args = parser.parse_args()

    config = load_config(args.config)
    logger = setup_logging(config)

    if args.test:
        from .browser import Browser
        b = Browser(config)
        asyncio.run(b.test_connection())
        return

    if not args.full and not args.update:
        parser.print_help()
        sys.exit(1)

    if args.full:
        asyncio.run(run_full_scrape(config, logger, resume=not args.no_resume, use_proxies=args.use_proxies))
    elif args.update:
        asyncio.run(run_update_scrape(config, logger, use_proxies=args.use_proxies))


if __name__ == "__main__":
    main()
