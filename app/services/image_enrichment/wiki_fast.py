"""
Fast Wikipedia image fetcher using REST API.
Batch-fetches main page images for heritage sites.
"""

import json, urllib.request, urllib.parse, time, os
from typing import Dict, Optional

WIKI_REST = "https://en.wikipedia.org/api/rest_v1/page/summary/"
CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "wiki_images.json")

def fetch_summary(title: str, timeout: int = 8) -> Optional[dict]:
    """Fetch Wikipedia page summary including thumbnail."""
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    url = WIKI_REST + encoded
    req = urllib.request.Request(url, headers={"User-Agent": "HeritagePlanner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            thumb = data.get("thumbnail", {})
            original = data.get("originalimage", {})
            return {
                "title": data.get("title", title),
                "thumb_url": thumb.get("source", ""),
                "image_url": original.get("source", thumb.get("source", "")),
                "description": data.get("description", ""),
                "extract": data.get("extract", "")[:200],
                "page_url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }
    except Exception:
        return None


def batch_fetch(sites: list, callback=None) -> Dict[str, dict]:
    """Fetch Wikipedia images for a list of sites. Returns {site_id: image_data}."""
    results = {}
    total = len(sites)
    
    for i, site in enumerate(sites):
        sid = site.get("id", "")
        name = site.get("name", "")
        province = site.get("province", "")
        
        # Try exact name first
        data = fetch_summary(name, timeout=5)
        
        # If not found, try with Vietnam suffix
        if not data:
            data = fetch_summary(f"{name} Vietnam", timeout=5)
        
        # Try Vietnamese name with diacritics removed
        if not data:
            data = fetch_summary(f"{name} {province}", timeout=5)
        
        if data and data.get("thumb_url"):
            results[sid] = data
        
        if callback and i % 20 == 0:
            callback(i, total)
        
        time.sleep(0.1)  # Rate limit
    
    # Save cache
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    return results


def load_cache() -> Dict[str, dict]:
    """Load cached image data."""
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


if __name__ == "__main__":
    # Test with a few sites
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    
    # Load sites
    with open(os.path.join(os.path.dirname(CACHE_PATH), "deepseek_clean.json")) as f:
        sites = json.load(f)
    
    # Try first 10
    test = sites[:10]
    results = batch_fetch(test)
    print(f"Found images for {len(results)}/{len(test)} sites")
    for sid, data in list(results.items())[:3]:
        s = next((x for x in test if x["id"] == sid), None)
        name = s["name"] if s else sid
        print(f"  {name}: {data.get('thumb_url','')[:60]}...")
