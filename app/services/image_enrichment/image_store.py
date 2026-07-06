"""
Persistent image store using SQLite + in-memory LRU cache.
Guarantees every site has at least 1 image (placeholder if none found).
"""
import json, os, time, threading, sqlite3, hashlib, logging
from typing import Dict, List, Optional
from collections import OrderedDict

logger = logging.getLogger(__name__)

from app.config import settings
DB_PATH = os.path.join(settings.data_dir, "images.db")
MAX_CACHE_ENTRIES = 2000
CACHE_TTL = 300  # 5 min in-memory

# In-memory LRU cache
_mem_cache: OrderedDict = OrderedDict()
_cache_times: Dict[str, float] = {}
_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if not exists."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_db()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS site_images (
                    site_id TEXT NOT NULL,
                    thumb_url TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    title TEXT DEFAULT '',
                    width INTEGER DEFAULT 0,
                    height INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'wikipedia',
                    idx INTEGER DEFAULT 0,
                    created_at REAL DEFAULT (strftime('%s','now')),
                    PRIMARY KEY (site_id, idx)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_site_images_site ON site_images(site_id)")
    finally:
        conn.close()


def get_images(site_id: str) -> List[Dict]:
    """Get images for a site. Checks in-memory cache first, then DB."""
    with _lock:
        # Check memory cache
        if site_id in _mem_cache:
            age = time.time() - _cache_times.get(site_id, 0)
            if age < CACHE_TTL:
                # Move to end (LRU)
                val = _mem_cache.pop(site_id)
                _mem_cache[site_id] = val
                return val
            else:
                del _mem_cache[site_id]
                _cache_times.pop(site_id, None)

    # Check DB
    try:
        conn = _get_db()
        try:
            with conn:
                rows = conn.execute(
                    "SELECT site_id, thumb_url, url, title, width, height, source FROM site_images WHERE site_id = ? ORDER BY idx",
                    (site_id,)
                ).fetchall()
        finally:
            conn.close()

        images = []
        for row in rows:
            images.append({
                "thumb_url": row["thumb_url"],
                "url": row["url"] or row["thumb_url"],
                "title": row["title"] or "",
                "width": row["width"],
                "height": row["height"],
                "source": row["source"],
            })

        # Update memory cache
        with _lock:
            _mem_cache[site_id] = images
            _cache_times[site_id] = time.time()
            # Evict oldest if over limit
            while len(_mem_cache) > MAX_CACHE_ENTRIES:
                _mem_cache.popitem(last=False)

        return images
    except Exception:
        return []


def store_images(site_id: str, images: List[Dict], source: str = "wikipedia"):
    """Store images for a site in DB and memory cache."""
    if not images:
        return

    try:
        conn = _get_db()
        try:
            with conn:
                # Delete existing
                conn.execute("DELETE FROM site_images WHERE site_id = ?", (site_id,))
                # Insert new
                for idx, img in enumerate(images):
                    conn.execute(
                        "INSERT INTO site_images (site_id, thumb_url, url, title, width, height, source, idx) VALUES (?,?,?,?,?,?,?,?)",
                        (site_id, img.get("thumb_url", ""), img.get("url", img.get("thumb_url", "")),
                         img.get("title", ""), img.get("width", 0), img.get("height", 0), source, idx)
                    )
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"store_images failed for {site_id}: {e}")
        return

    # Update memory cache
    with _lock:
        _mem_cache[site_id] = images
        _cache_times[site_id] = time.time()
        while len(_mem_cache) > MAX_CACHE_ENTRIES:
            _mem_cache.popitem(last=False)


def has_images(site_id: str) -> bool:
    """Check if site has images in store."""
    with _lock:
        if site_id in _mem_cache:
            return True
    try:
        conn = _get_db()
        try:
            with conn:
                row = conn.execute("SELECT 1 FROM site_images WHERE site_id = ? LIMIT 1", (site_id,)).fetchone()
                return row is not None
        finally:
            conn.close()
    except Exception:
        return False


def get_stats() -> dict:
    """Get store statistics."""
    try:
        conn = _get_db()
        try:
            with conn:
                total_sites = conn.execute("SELECT COUNT(DISTINCT site_id) FROM site_images").fetchone()[0]
                total_imgs = conn.execute("SELECT COUNT(*) FROM site_images").fetchone()[0]
                return {"sites_with_images": total_sites, "total_images": total_imgs}
        finally:
            conn.close()
    except Exception:
        return {"sites_with_images": 0, "total_images": 0}


# Initialize on import
init_db()
