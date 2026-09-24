"""Example: how to use the isolated tor_proxy module from another project.

Prerequisites: a local Tor daemon with control port enabled (see README.md).

Run from the parent directory of tor_proxy/:
    python -m tor_proxy.example_usage
or:
    python tor_proxy/example_usage.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tor_proxy import ProxyPool, load_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> None:
    # 1. Load config (defaults to ./config.yaml; pass a path to override)
    config = load_config(str(Path(__file__).resolve().parent / "config.yaml"))

    # 2. Create pool and verify Tor control port connectivity
    pool = ProxyPool(config)
    pool.connect()

    # 3. Use the SOCKS5 proxy URL in your HTTP client or browser
    socks_url = pool.get_socks_proxy()
    print(f"Point your client at: {socks_url}")
    # e.g. Playwright:  browser = await p.chromium.launch(proxy={"server": socks_url})
    # e.g. requests:    requests.get(url, proxies={"http": socks_url, "https": socks_url})

    # 4. Counter-based rotation: call after each successful unit of work.
    #    Rotates automatically every `scraping.rotation_count` successes (default 9).
    for success_count in range(1, 21):
        if pool.rotate_if_needed(success_count):
            print(f"IP rotated after {success_count} successful queries")

    # 5. Forced rotation: call immediately on block/captcha/rate-limit.
    pool.force_rotate()


if __name__ == "__main__":
    main()
