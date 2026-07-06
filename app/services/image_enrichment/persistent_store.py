"""
Persistent file-based store for reviews + enriched descriptions.
Saves to data/reviews_store.json and data/enrich_store.json
No external API calls on subsequent requests.
"""

import json
import os
import threading
from typing import Dict, List, Optional

from app.config import settings
DATA_DIR = settings.data_dir
REVIEWS_FILE = os.path.join(DATA_DIR, "reviews_store.json")
ENRICH_FILE = os.path.join(DATA_DIR, "enrich_store.json")

os.makedirs(DATA_DIR, exist_ok=True)

# Locks to ensure thread safety when writing to the store
_reviews_lock = threading.Lock()
_enrich_lock = threading.Lock()

def _load(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return {}


def _save(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_reviews(site_id: str) -> Optional[List[dict]]:
    """Get cached reviews for a site."""
    with _reviews_lock:
        store = _load(REVIEWS_FILE)
        return store.get(site_id)


def save_reviews(site_id: str, reviews: List[dict]):
    """Save reviews for a site."""
    with _reviews_lock:
        store = _load(REVIEWS_FILE)
        store[site_id] = reviews
        _save(REVIEWS_FILE, store)


def get_enriched(site_id: str) -> Optional[dict]:
    """Get cached enriched data for a site."""
    with _enrich_lock:
        store = _load(ENRICH_FILE)
        return store.get(site_id)


def save_enriched(site_id: str, data: dict):
    """Save enriched data for a site."""
    with _enrich_lock:
        store = _load(ENRICH_FILE)
        store[site_id] = data
        _save(ENRICH_FILE, store)


def get_stats() -> dict:
    with _reviews_lock:
        reviews_cached = len(_load(REVIEWS_FILE))
    with _enrich_lock:
        enriched_cached = len(_load(ENRICH_FILE))
    return {
        "reviews_cached": reviews_cached,
        "enriched_cached": enriched_cached,
    }
