"""
Batch image fetcher — searches Wikipedia for each site and gets the page image.
Uses Wikipedia opensearch + pageimages APIs with ThreadPoolExecutor.
"""

import json, urllib.request, urllib.parse, time, os, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict

WIKI_EN = "https://en.wikipedia.org/w/api.php"
WIKI_VI = "https://vi.wikipedia.org/w/api.php"
CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "wiki_images.json")
_lock = threading.Lock()

def _api(url, params, timeout=8):
    params["format"] = "json"
    u = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(u, headers={"User-Agent": "Heritage/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except: return {}

def fetch_image(site_id, name, province):
    """Try to get Wikipedia page image for a site. Returns (site_id, data) or None."""
    
    # Strategy 1: Try exact name on enwiki pageimages
    r = _api(WIKI_EN, {"action":"query","titles":name,"prop":"pageimages","pithumbsize":"400"})
    for pid, page in r.get("query",{}).get("pages",{}).items():
        if pid != "-1" and page.get("thumbnail"):
            return (site_id, {"thumb_url": page["thumbnail"]["source"], "title": page.get("title",name)})
    
    # Strategy 2: Try name on viwiki
    r = _api(WIKI_VI, {"action":"query","titles":name,"prop":"pageimages","pithumbsize":"400"})
    for pid, page in r.get("query",{}).get("pages",{}).items():
        if pid != "-1" and page.get("thumbnail"):
            return (site_id, {"thumb_url": page["thumbnail"]["source"], "title": page.get("title",name)})
    
    # Strategy 3: Search enwiki + get first result's image
    r = _api(WIKI_EN, {"action":"opensearch","search":f"{name} {province} Vietnam","limit":"1"})
    if len(r) >= 2 and r[1]:
        title = r[1][0]
        r2 = _api(WIKI_EN, {"action":"query","titles":title,"prop":"pageimages","pithumbsize":"400"})
        for pid, page in r2.get("query",{}).get("pages",{}).items():
            if pid != "-1" and page.get("thumbnail"):
                return (site_id, {"thumb_url": page["thumbnail"]["source"], "title": title})
    
    # Strategy 4: Search viwiki
    r = _api(WIKI_VI, {"action":"opensearch","search":f"{name}","limit":"1"})
    if len(r) >= 2 and r[1]:
        title = r[1][0]
        r2 = _api(WIKI_VI, {"action":"query","titles":title,"prop":"pageimages","pithumbsize":"400"})
        for pid, page in r2.get("query",{}).get("pages",{}).items():
            if pid != "-1" and page.get("thumbnail"):
                return (site_id, {"thumb_url": page["thumbnail"]["source"], "title": title})
    
    return None


def batch_fetch(sites, max_workers=8, callback=None):
    """Fetch images for all sites in parallel."""
    results = {}
    total = len(sites)
    done = 0
    
    def worker(s):
        nonlocal done
        result = fetch_image(s["id"], s["name"], s.get("province",""))
        with _lock:
            done += 1
            if callback and done % 20 == 0:
                callback(done, total, len(results))
        return result
    
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, s): s for s in sites}
        for f in as_completed(futures):
            result = f.result()
            if result:
                sid, data = result
                results[sid] = data
    
    return results


def load_cache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    
    with open(os.path.join(os.path.dirname(CACHE_PATH), "deepseek_clean.json")) as f:
        sites = json.load(f)
    
    cache = load_cache()
    missing = [s for s in sites if s["id"] not in cache]
    
    print(f"Cache: {len(cache)}, Missing: {len(missing)}")
    
    if missing:
        print(f"Fetching {len(missing)} sites via Wikipedia (8 parallel workers)...")
        
        def progress(done, total, found):
            print(f"  {done}/{total} | found: {found}")
        
        new = batch_fetch(missing, max_workers=8, callback=progress)
        cache.update(new)
        save_cache(cache)
        print(f"Added {len(new)} images, total: {len(cache)}/{len(sites)}")
