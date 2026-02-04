import re
from typing import Optional
from urllib.parse import urljoin

from .utils import compute_content_hash

BASE_URL = "https://guide.michelin.com"


def parse_total_count(html: str) -> Optional[int]:
    """Extract total restaurant count from listing page header."""
    # Spanish: "1.274 restaurantes" (dot as thousands separator)
    match = re.search(r'([\d.]+)\s+restaurantes?', html, re.IGNORECASE)
    if not match:
        # English fallback: "1,274 restaurants"
        match = re.search(r'([\d,]+)\s+restaurants?', html, re.IGNORECASE)
    if match:
        try:
            raw = match.group(1).replace(".", "").replace(",", "")
            return int(raw)
        except ValueError:
            return None
    return None


def parse_listing_page(html: str) -> list[dict]:
    """
    Extract restaurant cards from listing page.
    Returns list of {name, url, city, cuisine, distinction}.
    """
    restaurants = []

    # Primary: Spanish locale links /es/.../restaurante/...
    link_pattern = re.compile(
        r'href="(/es/[^"]+/restaurante/[^"]+)"',
        re.IGNORECASE
    )

    seen_urls = set()
    for match in link_pattern.finditer(html):
        url = match.group(1)
        if url in seen_urls:
            continue
        seen_urls.add(url)

    # Fallback: English locale links /en/.../restaurant/...
    if not seen_urls:
        en_pattern = re.compile(
            r'href="(/en/[^"]+/restaurant/[^"]+)"',
            re.IGNORECASE
        )
        for match in en_pattern.finditer(html):
            url = match.group(1)
            if url in seen_urls:
                continue
            seen_urls.add(url)

    for url in seen_urls:

        # Extract name from URL slug
        slug = url.rstrip("/").split("/")[-1]
        name = slug.replace("-", " ").title()

        restaurants.append({
            "name": name,
            "url": urljoin(BASE_URL, url),
            "michelin_url": urljoin(BASE_URL, url),
        })

    return restaurants


def parse_detail_page(html: str, url: str) -> Optional[dict]:
    """
    Extract full restaurant data from detail page.
    Returns dict with all fields + content_hash.
    """
    data = {
        "michelin_url": url,
        "michelin_id": _extract_michelin_id(url),
    }

    # Name - usually in h1
    name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    data["name"] = name_match.group(1).strip() if name_match else ""

    # Stars - English "X MICHELIN Star" or Spanish "X Estrella MICHELIN"
    stars = 0
    lower = html.lower()
    if "3 michelin star" in lower or "three michelin star" in lower or "3 estrella michelin" in lower or "tres estrella" in lower:
        stars = 3
    elif "2 michelin star" in lower or "two michelin star" in lower or "2 estrella michelin" in lower or "dos estrella" in lower:
        stars = 2
    elif "1 michelin star" in lower or "one michelin star" in lower or "1 estrella michelin" in lower or "una estrella" in lower:
        stars = 1
    data["stars"] = stars

    # Bib Gourmand
    data["bib_gourmand"] = 1 if "Bib Gourmand" in html else 0

    # Address - look for address schema or common patterns
    addr_match = re.search(
        r'<div[^>]*class="[^"]*address[^"]*"[^>]*>([^<]+)</div>',
        html, re.IGNORECASE
    )
    if not addr_match:
        addr_match = re.search(r'"streetAddress"\s*:\s*"([^"]+)"', html)
    data["address"] = addr_match.group(1).strip() if addr_match else ""

    # City
    city_match = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', html)
    data["city"] = city_match.group(1).strip() if city_match else ""

    # Region
    region_match = re.search(r'"addressRegion"\s*:\s*"([^"]+)"', html)
    data["region"] = region_match.group(1).strip() if region_match else ""

    # Price range - look for $, $$, $$$, $$$$
    price_match = re.search(r'(\${1,4})', html)
    data["price_range"] = price_match.group(1) if price_match else ""

    # Cuisine types - often in a specific div or meta
    cuisine_match = re.search(
        r'<span[^>]*class="[^"]*cuisine[^"]*"[^>]*>([^<]+)</span>',
        html, re.IGNORECASE
    )
    if not cuisine_match:
        cuisine_match = re.search(r'"servesCuisine"\s*:\s*"([^"]+)"', html)
    data["cuisine_types"] = cuisine_match.group(1).strip() if cuisine_match else ""

    # Description
    desc_match = re.search(
        r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>',
        html, re.IGNORECASE | re.DOTALL
    )
    if desc_match:
        # Strip HTML tags from description
        desc = re.sub(r'<[^>]+>', '', desc_match.group(1))
        data["description"] = desc.strip()
    else:
        data["description"] = ""

    # Coordinates
    lat_match = re.search(r'"latitude"\s*:\s*([0-9.-]+)', html)
    lon_match = re.search(r'"longitude"\s*:\s*([0-9.-]+)', html)
    data["latitude"] = float(lat_match.group(1)) if lat_match else None
    data["longitude"] = float(lon_match.group(1)) if lon_match else None

    # Phone
    phone_match = re.search(r'"telephone"\s*:\s*"([^"]+)"', html)
    data["phone"] = phone_match.group(1).strip() if phone_match else ""

    # Website
    web_match = re.search(r'"url"\s*:\s*"(https?://(?!guide\.michelin)[^"]+)"', html)
    data["website"] = web_match.group(1) if web_match else ""

    # Image URL
    img_match = re.search(r'"image"\s*:\s*"([^"]+)"', html)
    if not img_match:
        img_match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
    data["image_url"] = img_match.group(1) if img_match else ""

    # Compute content hash for change detection (exclude timestamps)
    hash_data = {k: v for k, v in data.items() if k not in ("created_at", "updated_at")}
    data["content_hash"] = compute_content_hash(hash_data)

    return data


def _extract_michelin_id(url: str) -> str:
    """Extract unique ID from Michelin URL."""
    # URL format: .../restaurant/restaurant-name-123456
    # Use the full slug as ID
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else ""
