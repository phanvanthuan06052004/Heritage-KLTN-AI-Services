"""
Heritage Trips Router — AI-powered trip recommendation endpoints.
Integrated from Map-Heritage recommendation engine.

Endpoints:
  POST /api/heritage/trips/recommend          — Generate heritage travel itinerary
  POST /api/heritage/trips/route-plan         — Plan fixed start/end route
  GET  /api/heritage/trips/heritage-sites      — List all heritage sites
  GET  /api/heritage/trips/heritage-sites/{id}       — Get site by ID
  GET  /api/heritage/trips/heritage-sites/{id}/images  — Get site images
  GET  /api/heritage/trips/heritage-sites/{id}/reviews — Get site reviews
  GET  /api/heritage/trips/heritage-sites/{id}/enrich  — Get enriched description
  GET  /api/heritage/trips/heritage-sites/{id}/narrate — Get site narration
"""

import asyncio
import json
import threading
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/heritage/trips")

_REC_READY = False
_LOCK = threading.Lock()

from app.config import settings


def _warm_up():
    global _REC_READY
    if _REC_READY:
        return
    with _LOCK:
        if _REC_READY:
            return

        from app.services.recommendation.data_loader import load_all_data
        from app.services.recommendation.pipeline import pipeline
        from app.services.image_enrichment.image_store import init_db
        from app.services.image_enrichment.batch_populator import populate_all

        sites, _ = load_all_data()
        pipeline.load_data(sites)
        print(f"[Trips] Loaded {len(sites)} heritage sites")

        init_db()

        def _progress(done, total, found):
            if done % 50 == 0 or done == total:
                print(f"[Trips] Images: {done}/{total} ({found} found)")

        t = threading.Thread(
            target=lambda: populate_all(progress_callback=_progress), daemon=True
        )
        t.start()
        print("[Trips] Image populator started in background")

        _REC_READY = True


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.post("/recommend")
async def recommend(payload: dict):
    from app.services.recommendation.models import TripRequest
    from app.services.recommendation.pipeline import pipeline

    _warm_up()
    req = TripRequest(**payload)
    try:
        itinerary = await pipeline.run(req)
        return itinerary.model_dump()
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/route-plan")
async def route_plan(payload: dict):
    from app.services.recommendation.models import RoutePlanRequest
    from app.services.recommendation.route_planner import plan_route

    _warm_up()
    req = RoutePlanRequest(**payload)
    try:
        result = await asyncio.to_thread(plan_route, req)
        return result.model_dump()
    except Exception as e:
        return {"status": "error", "warnings": [str(e)]}


@router.get("/heritage-sites")
async def list_heritage_sites():
    from app.services.recommendation.pipeline import pipeline

    _warm_up()
    return [s.model_dump() for s in pipeline._sites_cache]


@router.get("/heritage-sites/{site_id}")
async def get_heritage_site(site_id: str):
    from app.services.recommendation.pipeline import pipeline

    _warm_up()
    for s in pipeline._sites_cache:
        if s.id == site_id:
            return s.model_dump()
    raise HTTPException(status_code=404, detail="Site not found")


@router.get("/heritage-sites/{site_id}/images")
async def get_site_images(site_id: str):
    from app.services.recommendation.pipeline import pipeline
    from app.services.image_enrichment.image_store import get_images, store_images
    from app.services.image_enrichment.batch_populator import fetch_images_for_site

    _warm_up()
    site = next((s for s in pipeline._sites_cache if s.id == site_id), None)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    imgs = get_images(site_id)
    if imgs:
        return {"site_id": site_id, "name": site.name, "images": imgs, "source": "store"}

    try:
        imgs = fetch_images_for_site(site.name, site.province, site.reference_url or "")
    except Exception:
        imgs = []
    if imgs:
        store_images(site_id, imgs)
        return {"site_id": site_id, "name": site.name, "images": imgs, "source": "live"}

    cat_icons = {
        "spiritual": "\U0001f54c", "history": "\U0001f3db\ufe0f",
        "architecture": "\U0001f3d7\ufe0f", "nature": "\U0001f3d4\ufe0f",
        "museum": "\U0001f3db\ufe0f", "craft_village": "\U0001f3a8",
        "unesco": "\U0001f310", "entertainment": "\U0001f3a1",
    }
    icon = cat_icons.get(site.categories[0] if site.categories else "history", "\U0001f4cd")
    colors = ["#e94560", "#f0a500", "#4a90d9"]
    placeholders = []
    for i, color in enumerate(colors):
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="250" viewBox="0 0 400 250">'
            f'<rect width="400" height="250" fill="#12121f"/>'
            f'<rect x="10" y="10" width="380" height="230" rx="12" fill="none"'
            f' stroke="{color}" stroke-width="2" opacity="0.4"/>'
            f'<circle cx="200" cy="80" r="35" fill="{color}" opacity="0.15"/>'
            f'<text x="200" y="95" text-anchor="middle" font-size="36">{icon}</text>'
            f'<text x="200" y="150" text-anchor="middle" font-size="16" fill="#ddd"'
            f' font-family="sans-serif">{site.name}</text>'
            f'<text x="200" y="175" text-anchor="middle" font-size="12" fill="#888"'
            f' font-family="sans-serif">\U0001f4cd {site.province}</text>'
            f'<text x="200" y="205" text-anchor="middle" font-size="10" fill="{color}"'
            f' font-family="sans-serif">Loading images...</text>'
            f'</svg>'
        )
        data_uri = f"data:image/svg+xml,{urllib.parse.quote(svg)}"
        placeholders.append(
            {"thumb_url": data_uri, "url": data_uri, "title": f"{site.name} - {site.province}"}
        )
    return {"site_id": site_id, "name": site.name, "images": placeholders, "source": "placeholder"}


@router.get("/heritage-sites/{site_id}/reviews")
async def get_site_reviews(site_id: str):
    from app.services.recommendation.pipeline import pipeline
    from app.services.image_enrichment.persistent_store import get_reviews, save_reviews
    from app.services.image_enrichment.enricher import generate_reviews

    _warm_up()
    site = next((s for s in pipeline._sites_cache if s.id == site_id), None)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    cached = get_reviews(site_id)
    if cached:
        return cached

    reviews = generate_reviews(site.name, site.province, site.popularity_score)
    save_reviews(site_id, reviews)
    return reviews


@router.get("/heritage-sites/{site_id}/enrich")
async def get_site_enrich(site_id: str):
    from app.services.recommendation.pipeline import pipeline
    from app.services.image_enrichment.persistent_store import get_enriched, save_enriched
    from app.services.image_enrichment.enricher import enrich_site

    _warm_up()
    site = next((s for s in pipeline._sites_cache if s.id == site_id), None)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    cached = get_enriched(site_id)
    if cached and len(cached.get("long_description", "")) >= 220:
        return {"site_id": site_id, "name": site.name, **cached}

    data = enrich_site(site.name, site.province, site.reference_url or "")
    save_enriched(site_id, data)
    return {"site_id": site_id, "name": site.name, **data}


@router.get("/heritage-sites/{site_id}/narrate")
async def get_site_narration(site_id: str):
    from app.services.recommendation.pipeline import pipeline

    _warm_up()
    site = next((s for s in pipeline._sites_cache if s.id == site_id), None)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    summary = ""
    try:
        q = urllib.parse.quote(site.name)
        url = (
            "https://vi.wikipedia.org/w/api.php?format=json"
            "&action=query&prop=extracts&exintro&explaintext&redirects=1"
            f"&titles={q}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "HeritageAI/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            pages = data["query"]["pages"]
            page = list(pages.values())[0]
            if "extract" in page:
                extract = page["extract"]
                summary = extract[:500] + "..." if len(extract) > 500 else extract
    except Exception:
        pass

    fallback = site.long_description or site.description or "Chua co thong tin chi tiet."
    final = summary if summary and len(summary) > 50 else fallback
    return {"site_id": site_id, "name": site.name, "narration": final}
