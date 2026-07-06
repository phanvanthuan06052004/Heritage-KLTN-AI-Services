"""Repair wrong heritage-site coordinates using geocoding.

The data file is generated Python, so this module parses HeritageSite calls,
updates only lat/lng for confident matches, and rewrites the same canonical
shape used by curated_data.py.
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import math
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "services" / "ai_service" / "curated_data.py"
CACHE_FILE = ROOT / "data" / "geocode_cache.json"
USER_AGENT = "heritage-coordinate-repair/1.0"

SITE_FIELDS = [
    "id", "name", "province", "lat", "lng", "categories", "description",
    "long_description", "visit_tips", "reference_url", "opening_hours",
    "estimated_visit_minutes", "indoor_score", "outdoor_score",
    "suitable_for_children", "suitable_for_elderly", "ticket_price",
    "popularity_score", "historical_importance_score",
]

SITE_DEFAULTS = {
    "categories": [],
    "description": "",
    "long_description": "",
    "visit_tips": "",
    "reference_url": "",
    "opening_hours": "08:00-17:00",
    "estimated_visit_minutes": 60,
    "indoor_score": 0.5,
    "outdoor_score": 0.5,
    "suitable_for_children": True,
    "suitable_for_elderly": True,
    "ticket_price": 0,
    "popularity_score": 0.5,
    "historical_importance_score": 0.5,
}

def normalize(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    return " ".join(value.strip().lower().split())


MANUAL_OVERRIDES = {
    (normalize("Chợ đêm Đồng Xuân"), normalize("Hà Nội")): {
        "lat": 21.0380961,
        "lng": 105.8494029,
        "display_name": "Chợ Đồng Xuân, Phố Cầu Đông, Hoàn Kiếm, Hà Nội, Việt Nam",
    },
}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def literal(node: ast.AST) -> Any:
    return ast.literal_eval(node)


def load_sites(path: Path = DATA_FILE) -> list[dict[str, Any]]:
    module = ast.parse(path.read_text())
    sites: list[dict[str, Any]] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HeritageSite":
            site = {kw.arg: literal(kw.value) for kw in node.keywords if kw.arg}
            for field, default in SITE_DEFAULTS.items():
                site.setdefault(field, default)
            sites.append(site)
    return sites


def write_sites(sites: list[dict[str, Any]], path: Path = DATA_FILE) -> None:
    lines = [
        '"""\n',
        f"CURATED VIETNAM SITES - {len(sites)} heritage sites after coordinate repair\n",
        "Generated data; edit via services.ai_service.coordinate_repair.\n",
        '"""\n\n',
        "from app.services.recommendation.models import HeritageSite\n\n",
        "CURATED_HERITAGE = [\n",
    ]
    for site in sites:
        lines.append("    HeritageSite(\n")
        for field in SITE_FIELDS:
            lines.append(f"        {field}={site.get(field, SITE_DEFAULTS.get(field))!r},\n")
        lines.append("    ),\n")
    lines.append("]\n")
    path.write_text("".join(lines))


def province_centers(sites: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    for site in sites:
        grouped.setdefault(site["province"], []).append((float(site["lat"]), float(site["lng"])))
    centers = {}
    for province, coords in grouped.items():
        lats = [lat for lat, _ in coords]
        lngs = [lng for _, lng in coords]
        centers[province] = (median(lats), median(lngs))
    return centers


def load_cache() -> dict[str, Any]:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))


def query_variants(name: str, province: str) -> list[str]:
    variants = [
        f"{name}, {province}, Việt Nam",
        f"{name}, {province}, Vietnam",
    ]
    if normalize(name) == normalize("Chợ đêm Đồng Xuân") and normalize(province) == normalize("Hà Nội"):
        variants.extend([
            "Chợ Đồng Xuân, Hoàn Kiếm, Hà Nội, Việt Nam",
            "Dong Xuan Market, Hoan Kiem, Hanoi, Vietnam",
            "Dong Xuan Night Market, Hoan Kiem, Hanoi, Vietnam",
        ])
    simplified = name
    for token in ("Chợ đêm ", "Khu du lịch ", "Khu di tích ", "Di tích "):
        simplified = simplified.replace(token, "")
    if simplified != name:
        variants.extend([
            f"{simplified}, {province}, Việt Nam",
            f"{simplified}, {province}, Vietnam",
        ])
    variants.extend([
        f"{name} market, {province}, Vietnam",
        f"{simplified} market, {province}, Vietnam",
    ])
    return list(dict.fromkeys(variants))


def result_matches_name(name: str, result: dict[str, Any]) -> bool:
    display = normalize(result.get("display_name", ""))
    raw_name = normalize(name)
    simplified = raw_name.replace("chợ đêm ", "").replace("chợ ", "")
    if raw_name in display or simplified in display:
        return True
    aliases = {
        normalize("Chợ đêm Đồng Xuân"): ["dong xuan market", "dong xuan night market", normalize("Chợ Đồng Xuân")],
    }
    return any(alias in display for alias in aliases.get(raw_name, []))


def geocode(name: str, province: str, cache: dict[str, Any], delay: float, center: tuple[float, float] | None = None) -> dict[str, Any] | None:
    key = f"{name}|{province}"
    if key in cache:
        return cache[key]
    best = None
    for query in query_variants(name, province):
        params = urllib.parse.urlencode({
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "countrycodes": "vn",
            "addressdetails": 1,
            "accept-language": "vi",
        })
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/search?{params}",
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            results = json.loads(response.read().decode())
        time.sleep(delay)
        results = [item for item in results if result_matches_name(name, item)]
        if not results:
            continue
        if center:
            results.sort(key=lambda item: haversine_km(float(item["lat"]), float(item["lon"]), center[0], center[1]))
        best = results[0]
        break
    cache[key] = best
    save_cache(cache)
    return cache[key]


def suspicious_sites(sites: list[dict[str, Any]], threshold_km: float, only_names: set[str]) -> list[dict[str, Any]]:
    centers = province_centers(sites)
    suspects = []
    for site in sites:
        if only_names and normalize(site["name"]) not in only_names:
            continue
        center = centers.get(site["province"])
        if not center:
            continue
        distance = haversine_km(float(site["lat"]), float(site["lng"]), center[0], center[1])
        if only_names or distance >= threshold_km:
            item = dict(site)
            item["_distance_from_province_center_km"] = round(distance, 1)
            suspects.append(item)
    return suspects


def repair(threshold_km: float, limit: int | None, only_name: str | None, apply: bool, delay: float) -> None:
    sites = load_sites()
    cache = load_cache()
    only_names = {normalize(only_name)} if only_name else set()
    suspects = suspicious_sites(sites, threshold_km, only_names)
    if limit is not None:
        suspects = suspects[:limit]

    by_id = {site["id"]: site for site in sites}
    updates = []
    centers = province_centers(sites)
    for site in suspects:
        override = MANUAL_OVERRIDES.get((normalize(site["name"]), normalize(site["province"])))
        if override:
            updates.append((site, override, "update"))
            if apply:
                by_id[site["id"]]["lat"] = override["lat"]
                by_id[site["id"]]["lng"] = override["lng"]
            continue
        center = centers[site["province"]]
        result = geocode(site["name"], site["province"], cache, delay, center)
        if not result:
            updates.append((site, None, "not_found"))
            continue
        lat, lng = float(result["lat"]), float(result["lon"])
        new_distance = haversine_km(lat, lng, center[0], center[1])
        old_distance = site["_distance_from_province_center_km"]
        if new_distance < old_distance and new_distance < max(threshold_km, 80):
            updates.append((site, {"lat": lat, "lng": lng, "display_name": result.get("display_name", "")}, "update"))
            if apply:
                by_id[site["id"]]["lat"] = lat
                by_id[site["id"]]["lng"] = lng
        else:
            updates.append((site, {"lat": lat, "lng": lng, "display_name": result.get("display_name", "")}, "low_confidence"))

    for site, result, status in updates:
        print(f"{status}: {site['province']} | {site['name']} | old=({site['lat']}, {site['lng']})", end="")
        if result:
            print(f" -> new=({result['lat']}, {result['lng']}) | {result['display_name']}")
        else:
            print()
    if apply:
        write_sites(sites)
        print(f"applied_updates={sum(1 for _, _, status in updates if status == 'update')}")
    else:
        print("dry_run=true")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold-km", type=float, default=160.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-name")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    repair(args.threshold_km, args.limit, args.only_name, args.apply, args.delay)


if __name__ == "__main__":
    main()
