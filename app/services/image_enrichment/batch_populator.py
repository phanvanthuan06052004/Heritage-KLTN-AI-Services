"""
Batch image populator: fetches 3-5 images for every curated site.
Uses Wikipedia pageimages API + Wikimedia Commons fallback.
Stores results in SQLite image_store.
"""
import json, urllib.request, urllib.parse, time, re, sys, os
from urllib.error import HTTPError
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from app.services.image_enrichment import image_store

EN_API = "https://en.wikipedia.org/w/api.php"
VI_API = "https://vi.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
TARGET_IMAGES = 5
MIN_IMAGES = 3

# Known English Wikipedia page titles for major Vietnamese sites
KNOWN_EN_PAGES = {
    "chùa một cột": "One Pillar Pagoda",
    "chùa trấn quốc": "Trấn Quốc Pagoda",
    "văn miếu quốc tử giám": "Temple of Literature, Hanoi",
    "hồ hoàn kiếm": "Hoàn Kiếm Lake",
    "hoàng thành thăng long": "Imperial Citadel of Thăng Long",
    "nhà thờ lớn hà nội": "St. Joseph's Cathedral, Hanoi",
    "nhà hát lớn hà nội": "Hanoi Opera House",
    "lăng chủ tịch hồ chí minh": "Ho Chi Minh Mausoleum",
    "đại nội huế": "Imperial City of Huế",
    "lăng tự đức": "Tomb of Tự Đức",
    "lăng khải định": "Tomb of Khải Định",
    "chùa thiên mụ": "Thiên Mụ Pagoda",
    "phố cổ hội an": "Hội An",
    "thánh địa mỹ sơn": "Mỹ Sơn",
    "vịnh hạ long": "Hạ Long Bay",
    "chùa bái đính": "Bái Đính Temple",
    "tràng an": "Tràng An Scenic Landscape Complex",
    "tam cốc": "Tam Cốc-Bích Động",
    "bà nà hills": "Bà Nà Hills",
    "ngũ hành sơn": "Marble Mountains (Vietnam)",
    "tháp bà ponagar": "Po Nagar",
    "thác bản giốc": "Ban Giốc Waterfalls",
    "động phong nha": "Phong Nha-Kẻ Bàng National Park",
    "đèo mã pí lèng": "Mã Pí Lèng Pass",
    "cột cờ lũng cú": "Lũng Cú Flag Tower",
    "yên tử": "Yên Tử",
    "phố cổ hà nội": "Old Quarter, Hanoi",
    "hồ tây": "West Lake (Hanoi)",
    "chùa hương": "Hương Temple",
    "sa pa": "Sa Pa",
    "chợ bến thành": "Bến Thành Market",
    "địa đạo củ chi": "Củ Chi tunnels",
    "nhà thờ đức bà sài gòn": "Notre-Dame Cathedral Basilica of Saigon",
    "dinh độc lập": "Independence Palace",
    "bưu điện thành phố hồ chí minh": "Saigon Central Post Office",
    "hồ xuân hương": "Xuân Hương Lake",
    "thung lũng tình yêu": "Valley of Love",
    "biển mỹ khê": "Mỹ Khê Beach",
    "cầu rồng": "Dragon Bridge (Da Nang)",
    "núi bà đen": "Black Virgin Mountain",
    "núi cấm": "Cấm Mountains",
}


def _wiki_json(api_url: str, params: dict, timeout: int = 10) -> dict:
    params["format"] = "json"
    qs = urllib.parse.urlencode(params)
    url = f"{api_url}?{qs}"
    for attempt in range(3):
        req = urllib.request.Request(url, headers={"User-Agent": "HeritagePlanner/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(1 + attempt)
                continue
            return {}
        except Exception:
            if attempt < 2:
                time.sleep(0.5)
                continue
            return {}
    return {}


def _search_page(api_url: str, query: str, timeout: int = 8) -> str | None:
    data = _wiki_json(api_url, {
        "action": "query", "list": "search", "srsearch": query,
        "srlimit": "1", "srprop": "",
    }, timeout)
    for page in data.get("query", {}).get("search", []):
        return page["title"]
    return None


def _get_page_images(api_url: str, page_title: str, limit: int = 8, timeout: int = 10) -> List[Dict]:
    """Get images from a Wikipedia page."""
    data = _wiki_json(api_url, {
        "action": "query", "titles": page_title,
        "prop": "images", "imlimit": str(limit * 3),
    }, timeout)

    all_titles = []
    for page in data.get("query", {}).get("pages", {}).values():
        for img in page.get("images", []):
            t = img.get("title", "")
            if t.startswith("File:") and t.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                all_titles.append(t)

    skip_kw = ['icon', 'flag', 'symbol', 'map of', 'location', 'padlock',
               'shield', 'logo', 'question', 'stub', 'wikiproject',
               'commons-logo', 'disambig', 'merge', 'redirect', 'edit', 'lock']
    all_titles = [t for t in all_titles if not any(k in t.lower() for k in skip_kw)]

    if not all_titles:
        return []

    results = []
    batch = all_titles[:min(limit * 2, 10)]
    titles_str = "|".join(batch)

    data2 = _wiki_json(api_url, {
        "action": "query", "titles": titles_str,
        "prop": "imageinfo", "iiprop": "url|size|mime",
        "iiurlwidth": "400",
    }, timeout)

    for p in data2.get("query", {}).get("pages", {}).values():
        ii = p.get("imageinfo", [])
        if ii and "image" in ii[0].get("mime", ""):
            results.append({
                "thumb_url": ii[0].get("thumburl", ii[0].get("url", "")),
                "url": ii[0].get("url", ""),
                "title": p.get("title", "").replace("File:", "").replace("_", " ").rsplit('.', 1)[0],
                "width": ii[0].get("width", 0),
                "height": ii[0].get("height", 0),
            })

    return results[:limit]


def _commons_search(query: str, limit: int = 5, timeout: int = 10) -> List[Dict]:
    """Search Wikimedia Commons for images."""
    data = _wiki_json(COMMONS_API, {
        "action": "query", "list": "search", "srsearch": query,
        "srnamespace": "6", "srlimit": str(limit * 2),
    }, timeout)

    titles = []
    for r in data.get("query", {}).get("search", []):
        titles.append(r["title"])

    if not titles:
        return []

    titles_str = "|".join(titles[:limit * 2])
    data2 = _wiki_json(COMMONS_API, {
        "action": "query", "titles": titles_str,
        "prop": "imageinfo", "iiprop": "url|size|mime",
        "iiurlwidth": "400",
    }, timeout)

    results = []
    for p in data2.get("query", {}).get("pages", {}).values():
        ii = p.get("imageinfo", [])
        if ii and "image" in ii[0].get("mime", ""):
            results.append({
                "thumb_url": ii[0].get("thumburl", ii[0].get("url", "")),
                "url": ii[0].get("url", ""),
                "title": p.get("title", "").replace("File:", "").replace("_", " ").rsplit('.', 1)[0],
                "width": ii[0].get("width", 0),
                "height": ii[0].get("height", 0),
            })

    return results[:limit]


def fetch_images_for_site(name: str, province: str = "", ref_url: str = "") -> List[Dict]:
    """Fetch 3-5 images for a heritage site."""
    all_images = []

    # Strategy 0: Known English page title mapping (most reliable)
    en_title = KNOWN_EN_PAGES.get(name.lower().strip())
    if en_title:
        imgs = _get_page_images(EN_API, en_title, limit=5)
        all_images.extend(imgs)

    # Strategy 1: Parse reference URL for vi.wikipedia page, get images
    if len(all_images) < TARGET_IMAGES and ref_url and "vi.wikipedia.org" in ref_url:
        m = re.search(r'wikipedia\.org/wiki/(.+?)(?:[?#]|$)', ref_url)
        if m:
            title = urllib.parse.unquote(m.group(1)).replace("_", " ")
            imgs = _get_page_images(VI_API, title, limit=5)
            if imgs:
                all_images.extend(imgs)

    # Strategy 2: Search vi.wikipedia
    if len(all_images) < TARGET_IMAGES:
        vi_title = _search_page(VI_API, name)
        if vi_title:
            imgs = _get_page_images(VI_API, vi_title, limit=5)
            for img in imgs:
                if img["thumb_url"] not in {i["thumb_url"] for i in all_images}:
                    all_images.append(img)

    # Strategy 3: Search en.wikipedia with name + province + Vietnam
    if len(all_images) < TARGET_IMAGES:
        en_title = _search_page(EN_API, f"{name} {province} Vietnam")
        if en_title:
            imgs = _get_page_images(EN_API, en_title, limit=5)
            for img in imgs:
                if img["thumb_url"] not in {i["thumb_url"] for i in all_images}:
                    all_images.append(img)

    # Strategy 4: Search en.wikipedia with just name + Vietnam
    if len(all_images) < TARGET_IMAGES:
        en_title = _search_page(EN_API, f"{name} Vietnam")
        if en_title:
            imgs = _get_page_images(EN_API, en_title, limit=5)
            for img in imgs:
                if img["thumb_url"] not in {i["thumb_url"] for i in all_images}:
                    all_images.append(img)

    # Strategy 5: Wikimedia Commons search
    if len(all_images) < MIN_IMAGES:
        imgs = _commons_search(f"{name} {province} Vietnam", limit=5)
        for img in imgs:
            if img["thumb_url"] not in {i["thumb_url"] for i in all_images}:
                all_images.append(img)

    # Strategy 6: Commons with just name
    if len(all_images) < MIN_IMAGES:
        imgs = _commons_search(name, limit=5)
        for img in imgs:
            if img["thumb_url"] not in {i["thumb_url"] for i in all_images}:
                all_images.append(img)

    # Strategy 7: DuckDuckGo Image Search (always try for real photos)
    if len(all_images) < TARGET_IMAGES:
        from app.services.image_enrichment.ddg_search import search_images
        try:
            ddg_imgs = search_images(f"{name} {province} Vietnam", limit=8)
            for img in ddg_imgs:
                if img["thumb_url"] not in {i["thumb_url"] for i in all_images}:
                    all_images.append(img)
                    if len(all_images) >= TARGET_IMAGES:
                        break
        except Exception:
            pass

    return all_images[:TARGET_IMAGES]


def populate_all(progress_callback=None):
    """Populate image store for ALL curated sites. Multi-threaded for speed."""
    from app.services.recommendation.data_loader import load_all_data
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock

    sites, _ = load_all_data()
    total = len(sites)
    done = [0]
    with_images = [0]
    lock = Lock()
    running = True

    def populate_one(site):
        if not running:
            return False
        if image_store.has_images(site.id):
            with lock:
                done[0] += 1
                with_images[0] += 1
            return True
        try:
            images = fetch_images_for_site(site.name, site.province, site.reference_url or "")
            if images:
                image_store.store_images(site.id, images)
                with lock:
                    with_images[0] += 1
                return True
        except Exception:
            pass
        return False

    # Process with 10 concurrent workers
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(populate_one, site): site for site in sites}
        for future in as_completed(futures):
            with lock:
                done[0] += 1
                d = done[0]
                w = with_images[0]
            if progress_callback and (d % 50 == 0 or d == total):
                progress_callback(d, total, w)
            time.sleep(0.1)  # Small delay between completions

    if progress_callback:
        progress_callback(total, total, with_images[0])

    return with_images[0]
