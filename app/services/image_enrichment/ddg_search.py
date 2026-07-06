"""
DuckDuckGo Image Search — free, no API key.
Returns up to 10 real image URLs per search query.
"""
import json, urllib.request, urllib.parse, re, time, threading
from typing import Dict, List


def _get_vqd(query: str, timeout: int = 8) -> str | None:
    """Extract vqd token from DuckDuckGo image search page."""
    url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "vi-VN,vi;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode('utf-8', errors='ignore')
            m = re.search(r'vqd=([0-9-]+)', html)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def search_images(query: str, limit: int = 10, timeout: int = 10) -> List[Dict]:
    """
    Search DuckDuckGo for images.
    Returns list of {thumb_url, url, title, source, width, height}
    """
    token = _get_vqd(query, timeout)
    if not token:
        return []

    api_url = f"https://duckduckgo.com/i.js?l=us-en&o=json&q={urllib.parse.quote(query)}&vqd={token}"
    req = urllib.request.Request(api_url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    })

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return []

    results = data.get("results", [])
    images = []
    for item in results[:limit]:
        img_url = item.get("image", "")
        thumb_url = item.get("thumbnail", "")
        if not img_url:
            continue
        # Skip SVG and data URIs
        if img_url.startswith("data:"):
            continue
        images.append({
            "thumb_url": thumb_url or img_url,
            "url": img_url,
            "title": item.get("title", "")[:100],
            "width": item.get("width", 0),
            "height": item.get("height", 0),
            "source": "duckduckgo",
        })

    return images
