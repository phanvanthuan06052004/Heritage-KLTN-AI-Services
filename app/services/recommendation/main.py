"""
AI Service — FastAPI application.
Implements the core recommendation engine REST API.
"""

from contextlib import asynccontextmanager
from typing import List
import asyncio
import urllib.parse
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.services.recommendation.models import (
    HeritageSite, TripInput, TripRequest, Itinerary, Review,
    RoutePlanRequest, RoutePlanResponse,
)
from app.services.recommendation.pipeline import pipeline
from app.services.recommendation.route_planner import plan_route


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load curated data
    from app.services.recommendation.data_loader import load_all_data
    sites, _ = load_all_data()
    pipeline.load_data(sites)
    print(f"Loaded {len(sites)} heritage sites")

    # Start background image populator (fetches + stores in DB)
    from app.services.image_enrichment.batch_populator import populate_all
    import threading
    def progress(done, total, found):
        if done % 50 == 0 or done == total:
            print(f"  Image populate: {done}/{total} ({found} with images)")

    def run_populator():
        populate_all(progress_callback=progress)

    t = threading.Thread(target=run_populator, daemon=True)
    t.start()
    print("Background image populator started")
    yield


app = FastAPI(
    title="Vietnam Heritage Travel AI Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-service"}


@app.post("/api/v1/recommend", response_model=Itinerary)
async def recommend(input_data: TripInput):
    """Recommend a heritage travel itinerary based on user input."""
    try:
        itinerary = await pipeline.run(input_data)
        return itinerary
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/routes/plan", response_model=RoutePlanResponse)
async def route_plan(input_data: RoutePlanRequest):
    """Plan a fixed start/end route using the alth.md contract."""
    try:
        return await asyncio.to_thread(plan_route, input_data)
    except Exception as e:
        return RoutePlanResponse(status="error", warnings=[str(e)])


@app.get("/api/v1/heritage-sites", response_model=List[HeritageSite])
async def list_sites():
    """List all available heritage sites."""
    return pipeline._sites_cache


@app.get("/api/v1/heritage-sites/{site_id}", response_model=HeritageSite)
async def get_site(site_id: str):
    for site in pipeline._sites_cache:
        if site.id == site_id:
            return site
    raise HTTPException(status_code=404, detail="Site not found")


@app.get("/api/v1/heritage-sites/{site_id}/images")
async def get_site_images(site_id: str):
    """Get images for a heritage site from persistent store. Guarantees images via SVG fallback."""
    from app.services.image_enrichment.image_store import get_images, store_images
    from app.services.image_enrichment.batch_populator import fetch_images_for_site

    site = None
    for s in pipeline._sites_cache:
        if s.id == site_id:
            site = s
            break
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Check store first
    images = get_images(site_id)
    if images:
        return {"site_id": site_id, "name": site.name, "images": images, "source": "store"}

    # Try live fetch
    try:
        images = fetch_images_for_site(site.name, site.province, site.reference_url or "")
    except Exception:
        images = []
    if images:
        store_images(site_id, images)
        return {"site_id": site_id, "name": site.name, "images": images, "source": "live"}

    # Generate SVG placeholders (3 per site) so frontend always shows images
    cat_icons = {
        'spiritual': '🕌', 'history': '🏛️', 'architecture': '🏗️',
        'nature': '🏔️', 'museum': '🏛️', 'craft_village': '🎨',
        'unesco': '🌐', 'entertainment': '🎡'
    }
    icon = cat_icons.get(site.categories[0] if site.categories else 'history', '📍')
    colors = ['#e94560', '#f0a500', '#4a90d9']
    
    placeholders = []
    for i, color in enumerate(colors):
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="400" height="250" viewBox="0 0 400 250">
  <rect width="400" height="250" fill="#12121f"/>
  <rect x="10" y="10" width="380" height="230" rx="12" fill="none" stroke="{color}" stroke-width="2" opacity="0.4"/>
  <circle cx="200" cy="80" r="35" fill="{color}" opacity="0.15"/>
  <text x="200" y="95" text-anchor="middle" font-size="36">{icon}</text>
  <text x="200" y="150" text-anchor="middle" font-size="16" fill="#ddd" font-family="sans-serif">{site.name}</text>
  <text x="200" y="175" text-anchor="middle" font-size="12" fill="#888" font-family="sans-serif">📍 {site.province}</text>
  <text x="200" y="205" text-anchor="middle" font-size="10" fill="{color}" font-family="sans-serif">Đang tải ảnh từ Wikipedia...</text>
</svg>'''
        data_uri = f"data:image/svg+xml,{urllib.parse.quote(svg)}"
        placeholders.append({
            "thumb_url": data_uri,
            "url": data_uri,
            "title": f"{site.name} - {site.province}",
        })
    
    return {"site_id": site_id, "name": site.name, "images": placeholders, "source": "placeholder"}


@app.get("/api/v1/images/stats")
async def image_stats():
    """Get image storage statistics."""
    from app.services.image_enrichment.image_store import get_stats
    return get_stats()


@app.get("/api/v1/heritage-sites/{site_id}/reviews", response_model=List[Review])
async def get_reviews(site_id: str):
    """Get reviews for a heritage site. Persisted in file store."""
    from app.services.image_enrichment.persistent_store import get_reviews, save_reviews
    from app.services.image_enrichment.enricher import generate_reviews
    
    site = None
    for s in pipeline._sites_cache:
        if s.id == site_id:
            site = s
            break
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    # Check persistent cache first
    cached = get_reviews(site_id)
    if cached:
        return cached
    
    # Fetch from API and persist
    reviews = generate_reviews(site.name, site.province, site.popularity_score)
    save_reviews(site_id, reviews)
    return reviews


@app.get("/api/v1/heritage-sites/{site_id}/enrich")
async def enrich_site_info(site_id: str):
    """Get enriched description. Persisted in file store."""
    from app.services.image_enrichment.persistent_store import get_enriched, save_enriched
    from app.services.image_enrichment.enricher import enrich_site
    
    site = None
    for s in pipeline._sites_cache:
        if s.id == site_id:
            site = s
            break
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    # Check persistent cache first, but refresh old one-line fallback entries.
    cached = get_enriched(site_id)
    if cached and len(cached.get("long_description", "")) >= 220:
        return {"site_id": site_id, "name": site.name, **cached}
    
    # Fetch from API and persist
    data = enrich_site(site.name, site.province, site.reference_url or "")
    save_enriched(site_id, data)
    return {"site_id": site_id, "name": site.name, **data}


@app.get("/api/v1/heritage-sites/{site_id}/narrate")
async def get_site_narration(site_id: str):
    """Get narration text for a heritage site, using its description and wikipedia info."""
    site = None
    for s in pipeline._sites_cache:
        if s.id == site_id:
            site = s
            break
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
        
    # Attempt to fetch summary from Wikipedia API
    import urllib.request
    import json
    import urllib.parse
    
    summary = ""
    try:
        query = urllib.parse.quote(site.name)
        url = f"https://vi.wikipedia.org/w/api.php?format=json&action=query&prop=extracts&exintro&explaintext&redirects=1&titles={query}"
        req = urllib.request.Request(url, headers={'User-Agent': 'HeritageTravelApp/1.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            pages = data['query']['pages']
            page = list(pages.values())[0]
            if 'extract' in page:
                summary = page['extract'][:500] + "..." if len(page['extract']) > 500 else page['extract']
    except Exception:
        pass
        
    fallback = site.long_description or site.description or "Hiện chưa có thông tin chi tiết về địa điểm này."
    final_text = summary if summary and len(summary) > 50 else fallback
    
    return {"site_id": site_id, "name": site.name, "narration": final_text}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
