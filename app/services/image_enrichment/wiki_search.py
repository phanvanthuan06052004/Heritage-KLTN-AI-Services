"""
Wikimedia Commons Image Search Service
Finds images for heritage sites using free Wikimedia API.
Caches results to avoid repeated API calls.
"""

import hashlib
import json
import urllib.request
import urllib.parse
import time
from typing import List, Dict, Optional


WIKI_API = "https://commons.wikimedia.org/w/api.php"
CACHE = {}
CACHE_FILE = None


def _cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()


def _wiki_request(params: dict) -> dict:
    """Make a Wikimedia API request."""
    params["format"] = "json"
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "HeritageTravelPlanner/1.0 (research project)"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


def search_images(name: str, province: str = "", limit: int = 5) -> List[Dict[str, str]]:
    """
    Search Wikimedia Commons for images of a heritage site.
    Returns list of {url, thumb_url, title, description, width, height}
    """
    cache_k = _cache_key(f"{name}|{province}")
    if cache_k in CACHE:
        return CACHE[cache_k]

    # Build search query
    query = f'"{name}" Vietnam'
    if province:
        query += f" {province}"

    # Step 1: Search for files
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",  # File namespace
        "srlimit": str(limit * 2),
        "srprop": "",
    }
    result = _wiki_request(search_params)
    search_results = result.get("query", {}).get("search", [])

    if not search_results:
        # Try broader search without quotes
        search_params["srsearch"] = f"{name} Vietnam"
        result = _wiki_request(search_params)
        search_results = result.get("query", {}).get("search", [])

    if not search_results:
        # Try just the name
        search_params["srsearch"] = name
        result = _wiki_request(search_params)
        search_results = result.get("query", {}).get("search", [])

    if not search_results:
        CACHE[cache_k] = []
        return []

    # Step 2: Get image URLs for found files
    titles = "|".join(r["title"] for r in search_results[:limit * 2])
    img_params = {
        "action": "query",
        "titles": titles,
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "iiurlwidth": "400",
        "iiurlheight": "300",
    }
    result = _wiki_request(img_params)

    images = []
    pages = result.get("query", {}).get("pages", {})
    for page_id, page in pages.items():
        if page_id == "-1":
            continue
        image_info = page.get("imageinfo", [])
        if not image_info:
            continue
        info = image_info[0]
        mime = info.get("mime", "")
        if "image" not in mime:
            continue

        images.append({
            "url": info.get("url", ""),
            "thumb_url": info.get("thumburl", info.get("url", "")),
            "title": page.get("title", "").replace("File:", "").replace("_", " "),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
        })

        if len(images) >= limit:
            break

    CACHE[cache_k] = images
    return images


def get_images_for_site(name: str, province: str = "") -> List[Dict[str, str]]:
    """Public API: get images for a heritage site."""
    return search_images(name, province)


def preload_cache(sites: list):
    """Preload images for a batch of sites."""
    for site in sites:
        name = site.get("name", "")
        province = site.get("province", "")
        if name:
            images = search_images(name, province)
            if images:
                pass  # Already cached
            time.sleep(0.3)  # Rate limit
