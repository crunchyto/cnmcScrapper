"""Fetch free proxies from public APIs and save to proxies.txt."""
import argparse
import json
import urllib.request
import urllib.error
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROXY_SOURCES = [
    {
        "name": "proxyscan",
        "url": "https://proxylist.geonode.com/api/proxy-list?limit=200&page=1&sort_by=lastChecked&sort_type=desc&protocols=http",
        "parser": "geonode",
    },
    {
        "name": "fate0",
        "url": "https://raw.githubusercontent.com/fate0/proxylist/master/proxy.list",
        "parser": "jsonlines",
    },
    {
        "name": "clarketm",
        "url": "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
        "parser": "plaintext",
    },
    {
        "name": "TheSpeedX",
        "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        "parser": "plaintext",
    },
    {
        "name": "ShiftyTR",
        "url": "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "parser": "plaintext",
    },
]


def fetch_url(url: str, timeout: int = 10) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  Failed: {e}", file=sys.stderr)
        return None


def parse_geonode(text: str) -> list[str]:
    try:
        data = json.loads(text)
        return [f"{p['ip']}:{p['port']}" for p in data.get("data", [])]
    except (json.JSONDecodeError, KeyError):
        return []


def parse_jsonlines(text: str) -> list[str]:
    proxies = []
    for line in text.strip().splitlines():
        try:
            obj = json.loads(line)
            if obj.get("type") == "http":
                proxies.append(f"{obj['host']}:{obj['port']}")
        except (json.JSONDecodeError, KeyError):
            continue
    return proxies


def parse_plaintext(text: str) -> list[str]:
    proxies = []
    for line in text.strip().splitlines():
        line = line.strip()
        if ":" in line and line[0].isdigit():
            # Take only ip:port portion
            proxy = line.split()[0]
            if proxy.count(":") == 1:
                proxies.append(proxy)
    return proxies


PARSERS = {
    "geonode": parse_geonode,
    "jsonlines": parse_jsonlines,
    "plaintext": parse_plaintext,
}


def test_proxy(proxy: str, test_url: str = "http://httpbin.org/ip", timeout: int = 5) -> bool:
    """Quick connectivity test on a proxy."""
    try:
        handler = urllib.request.ProxyHandler({"http": f"http://{proxy}", "https": f"http://{proxy}"})
        opener = urllib.request.build_opener(handler)
        opener.open(test_url, timeout=timeout)
        return True
    except Exception:
        return False


def fetch_all_proxies() -> list[str]:
    all_proxies = set()
    for source in PROXY_SOURCES:
        print(f"Fetching from {source['name']}...")
        text = fetch_url(source["url"])
        if not text:
            continue
        parser = PARSERS[source["parser"]]
        proxies = parser(text)
        print(f"  Got {len(proxies)} proxies")
        all_proxies.update(proxies)
    return sorted(all_proxies)


def main():
    parser = argparse.ArgumentParser(description="Fetch and optionally test free HTTP proxies")
    parser.add_argument("-o", "--output", default="proxies.txt", help="Output file (default: proxies.txt)")
    parser.add_argument("--test", action="store_true", help="Test each proxy before saving (slow)")
    parser.add_argument("--test-workers", type=int, default=50, help="Parallel workers for testing")
    args = parser.parse_args()

    proxies = fetch_all_proxies()
    print(f"\nTotal unique proxies: {len(proxies)}")

    if args.test and proxies:
        print(f"Testing proxies with {args.test_workers} workers...")
        working = []
        with ThreadPoolExecutor(max_workers=args.test_workers) as pool:
            futures = {pool.submit(test_proxy, p): p for p in proxies}
            done = 0
            for future in as_completed(futures):
                done += 1
                proxy = futures[future]
                if future.result():
                    working.append(proxy)
                if done % 50 == 0:
                    print(f"  Tested {done}/{len(proxies)}, {len(working)} working")
        proxies = sorted(working)
        print(f"Working proxies: {len(proxies)}")

    if proxies:
        Path(args.output).write_text("\n".join(proxies) + "\n")
        print(f"Saved to {args.output}")
    else:
        print("No proxies found!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
