"""
Multi-image preloader using Wikipedia pageimages + REST summary.
Returns 3-5 images per site via pageimages API (prop=images on the wiki page).
"""
import json, os, time, threading, urllib.request, urllib.parse, re
from typing import Dict, List

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "wiki_images.json")
IMAGE_CACHE: Dict[str, List[Dict]] = {}

VI_API = "https://vi.wikipedia.org/w/api.php"
EN_API = "https://en.wikipedia.org/w/api.php"
VI_REST = "https://vi.wikipedia.org/api/rest_v1/page/summary/"
EN_REST = "https://en.wikipedia.org/api/rest_v1/page/summary/"


def _wiki_json(api_url: str, params: dict, timeout: int = 10) -> dict:
    params["format"] = "json"
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{api_url}?{qs}", headers={"User-Agent": "HeritagePlanner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def _rest_summary(rest_base: str, title: str, timeout: int = 8) -> dict | None:
    encoded = urllib.parse.quote(title.replace(" ", "_"))
    req = urllib.request.Request(rest_base + encoded, headers={"User-Agent": "HeritagePlanner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _search_wiki_page(api_url: str, query: str, timeout: int = 8) -> str | None:
    """Search Wikipedia for a page title."""
    data = _wiki_json(api_url, {
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": "1", "srprop": "",
    }, timeout)
    for page in data.get("query", {}).get("search", []):
        return page["title"]
    return None


def _get_page_images(api_url: str, page_title: str, limit: int = 8, timeout: int = 10) -> List[Dict]:
    """Get all images from a Wikipedia page."""
    # Step 1: Get image titles
    data = _wiki_json(api_url, {
        "action": "query", "titles": page_title,
        "prop": "images", "imlimit": str(limit * 3),
    }, timeout)

    images = []
    for page in data.get("query", {}).get("pages", {}).values():
        for img in page.get("images", []):
            title = img.get("title", "")
            if title.startswith("File:"):
                images.append(title)

    if not images:
        return []

    # Skip icons, flags, logos, maps
    skip_kw = ['icon', 'flag', 'symbol', 'map of', 'location', 'padlock',
               'shield', 'logo', 'question', 'stub', 'wikiproject',
               'commons-logo', 'disambig', 'merge', 'redirect']
    images = [t for t in images if not any(k in t.lower() for k in skip_kw)]

    # Step 2: Get image URLs (batch of 10)
    image_urls = []
    batch = images[:min(limit * 2, 10)]
    if batch:
        titles_str = "|".join(batch)
        data2 = _wiki_json(api_url, {
            "action": "query", "titles": titles_str,
            "prop": "imageinfo", "iiprop": "url|size|mime",
            "iiurlwidth": "400",
        }, timeout)

        for p in data2.get("query", {}).get("pages", {}).values():
            ii = p.get("imageinfo", [])
            if ii:
                info = ii[0]
                mime = info.get("mime", "")
                if "image" not in mime:
                    continue
                image_urls.append({
                    "thumb_url": info.get("thumburl", info.get("url", "")),
                    "url": info.get("url", ""),
                    "title": p.get("title", "").replace("File:", "").replace("_", " "),
                    "width": info.get("width", 0),
                    "height": info.get("height", 0),
                })

    if len(image_urls) > limit:
        image_urls = image_urls[:limit]

    return image_urls


def _parse_wiki_title(ref_url: str) -> str | None:
    m = re.search(r'wikipedia\.org/wiki/(.+?)(?:[?#]|$)', ref_url)
    if m:
        return urllib.parse.unquote(m.group(1)).replace("_", " ")
    return None


def _fetch_images(name: str, province: str = "", ref_url: str = "") -> List[Dict]:
    """Find multiple images for a heritage site. Returns list of {thumb_url, url, title}."""

    images = []

    # Strategy 1: Use reference URL to find Wikipedia page, get all images
    if ref_url:
        title = _parse_wiki_title(ref_url)
        if title:
            host = "vi" if "vi.wikipedia" in ref_url else "en"
            api_url = VI_API if host == "vi" else EN_API
            images = _get_page_images(api_url, title, limit=5)
            if images:
                return images

    # Strategy 2: REST summary (vi) + get page images
    data = _rest_summary(VI_REST, name)
    if data and data.get("title"):
        images = _get_page_images(VI_API, data["title"], limit=5)
        if images:
            return images

    # Strategy 3: REST summary (en)
    data = _rest_summary(EN_REST, name)
    if data and data.get("title"):
        images = _get_page_images(EN_API, data["title"], limit=5)
        if images:
            return images

    # Strategy 4: Search vi.wikipedia for the page
    vi_title = _search_wiki_page(VI_API, name)
    if vi_title:
        images = _get_page_images(VI_API, vi_title, limit=5)
        if images:
            return images

    # Strategy 5: Search en.wikipedia
    en_title = _search_wiki_page(EN_API, f"{name} {province} Vietnam")
    if en_title:
        images = _get_page_images(EN_API, en_title, limit=5)
        if images:
            return images

    # Strategy 6: Try just the name + Vietnam on en
    en_title = _search_wiki_page(EN_API, f"{name} Vietnam")
    if en_title:
        images = _get_page_images(EN_API, en_title, limit=5)
        if images:
            return images

    return []


def preload_site(name: str, province: str = "", site_id: str = "", ref_url: str = "") -> List[Dict]:
    if site_id in IMAGE_CACHE and IMAGE_CACHE[site_id]:
        return IMAGE_CACHE[site_id]

    images = _fetch_images(name, province, ref_url)
    if images:
        IMAGE_CACHE[site_id] = images
        _save_cache()
        return images

    return []


def preload_all_sites(sites: list, callback=None):
    def _run():
        total = len(sites)
        found = 0
        for i, site in enumerate(sites):
            name = site.get("name", "")
            province = site.get("province", "")
            sid = site.get("id", "")
            ref_url = site.get("reference_url", "")
            if sid not in IMAGE_CACHE or not IMAGE_CACHE[sid]:
                images = preload_site(name, province, sid, ref_url)
                if images:
                    found += 1
            if callback and (i % 50 == 0 or i == total - 1):
                callback(i + 1, total, found)
            time.sleep(0.5)
        if callback:
            callback(total, total, found)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def _save_cache():
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(IMAGE_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_cache():
    global IMAGE_CACHE
    IMAGE_CACHE = {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        for sid, images in cache_data.items():
            if isinstance(images, list) and images:
                IMAGE_CACHE[sid] = images
            elif isinstance(images, dict) and "thumb_url" in images:
                # Backward compat: old format with single image dict
                IMAGE_CACHE[sid] = [images]
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def get_cached_images(site_id: str) -> List[Dict]:
    return IMAGE_CACHE.get(site_id, [])


def get_stats() -> dict:
    return {
        "cached_sites": len(IMAGE_CACHE),
        "sites_with_images": sum(1 for v in IMAGE_CACHE.values() if v),
    }


_load_cache()
