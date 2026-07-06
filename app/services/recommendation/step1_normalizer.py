"""
Step 1 — Normalize input: Converts free-text or form input into TripRequest.
Uses rule-based parsing for structured forms; LLM function-calling for free text.
"""

from typing import Optional
from app.services.recommendation.models import TripRequest, TripInput


INTEREST_KEYWORDS = {
    "lịch sử": "history",
    "history": "history",
    "kiến trúc": "architecture",
    "architecture": "architecture",
    "kiến truc": "architecture",
    "tâm linh": "spiritual",
    "spiritual": "spiritual",
    "chùa": "spiritual",
    "đền": "spiritual",
    "nhà thờ": "spiritual",
    "làng nghề": "craft_village",
    "craft": "craft_village",
    "bảo tàng": "museum",
    "museum": "museum",
    "bảo tang": "museum",
    "ẩm thực": "local_food",
    "food": "local_food",
    "ăn": "local_food",
    "local_food": "local_food",
    "thiên nhiên": "nature",
    "nature": "nature",
    "núi": "nature",
    "biển": "nature",
    "chụp ảnh": "photography",
    "photography": "photography",
    "sống ảo": "photography",
}

PACE_KEYWORDS = {
    "thư giãn": "relaxed",
    "relaxed": "relaxed",
    "nhẹ nhàng": "relaxed",
    "thoải mái": "relaxed",
    "vừa phải": "moderate",
    "moderate": "moderate",
    "bình thường": "moderate",
    "dày đặc": "packed",
    "packed": "packed",
    "nhiều": "packed",
    "tối đa": "packed",
}

BUDGET_KEYWORDS = {
    "tiết kiệm": "low",
    "low": "low",
    "rẻ": "low",
    "bình dân": "low",
    "vừa": "medium",
    "medium": "medium",
    "trung bình": "medium",
    "cao cấp": "high",
    "high": "high",
    "sang": "high",
    "xa xỉ": "high",
}

CONSTRAINT_KEYWORDS = {
    "người già": "elderly_friendly",
    "elderly": "elderly_friendly",
    "trẻ em": "child_friendly",
    "children": "child_friendly",
    "child": "child_friendly",
    "tránh đi bộ": "avoid_long_walking",
    "avoid walking": "avoid_long_walking",
    "tránh nắng": "avoid_sun",
    "avoid sun": "avoid_sun",
    "prefer indoor": "prefer_indoor",
    "trong nhà": "prefer_indoor",
    "ngoài trời": "prefer_outdoor",
    "outdoor": "prefer_outdoor",
}

PROVINCE_KEYWORDS = {
    "hà nội": "Hà Nội",
    "ha noi": "Hà Nội",
    "hanoi": "Hà Nội",
    "hồ chí minh": "TP. Hồ Chí Minh",
    "sài gòn": "TP. Hồ Chí Minh",
    "saigon": "TP. Hồ Chí Minh",
    "hcm": "TP. Hồ Chí Minh",
    "huế": "Thừa Thiên Huế",
    "hue": "Thừa Thiên Huế",
    "đà nẵng": "Đà Nẵng",
    "da nang": "Đà Nẵng",
    "hội an": "Quảng Nam",
    "hoi an": "Quảng Nam",
    "ninh bình": "Ninh Bình",
    "ninh binh": "Ninh Bình",
    "hạ long": "Quảng Ninh",
    "ha long": "Quảng Ninh",
    "sapa": "Lào Cai",
    "sa pa": "Lào Cai",
    "hà giang": "Hà Giang",
    "ha giang": "Hà Giang",
    "cần thơ": "Cần Thơ",
    "can tho": "Cần Thơ",
}

PROVINCE_COORDS = {
    "Hà Nội": (21.0285, 105.8542),
    "TP. Hồ Chí Minh": (10.8231, 106.6297),
    "Thừa Thiên Huế": (16.4637, 107.5909),
    "Đà Nẵng": (16.0544, 108.2022),
    "Quảng Nam": (15.8801, 108.338),
    "Quảng Ninh": (20.9101, 107.1839),
    "Ninh Bình": (20.2506, 105.9745),
    "Lào Cai": (22.3356, 103.8436),
    "Hà Giang": (23.2785, 105.359),
    "Cần Thơ": (10.0328, 105.7705),
    "Hải Phòng": (20.8550, 106.6830),
    "Nghệ An": (18.6796, 105.6813),
    "Khánh Hòa": (12.2388, 109.1967),
    "Lâm Đồng": (11.9404, 108.4580),
}


def extract_interests(text: str) -> list[str]:
    text_lower = text.lower()
    interests = set()
    for kw, interest in INTEREST_KEYWORDS.items():
        if kw in text_lower:
            interests.add(interest)
    if not interests:
        interests.add("history")
        interests.add("architecture")
    return list(interests)


def extract_pace(text: str) -> str:
    text_lower = text.lower()
    for kw, pace in PACE_KEYWORDS.items():
        if kw in text_lower:
            return pace
    return "moderate"


def extract_budget(text: str) -> str:
    text_lower = text.lower()
    for kw, budget in BUDGET_KEYWORDS.items():
        if kw in text_lower:
            return budget
    return "medium"


def extract_constraints(text: str) -> list[str]:
    text_lower = text.lower()
    constraints = set()
    for kw, constraint in CONSTRAINT_KEYWORDS.items():
        if kw in text_lower:
            constraints.add(constraint)
    return list(constraints)


def extract_province(text: str) -> str:
    text_lower = text.lower()
    for kw, province in PROVINCE_KEYWORDS.items():
        if kw in text_lower:
            return province
    return "Hà Nội"


def extract_duration(text: str) -> int:
    import re
    patterns = [
        r"(\d+)\s*ngày",
        r"(\d+)\s*days?",
        r"(\d+)\s*ngay",
        r"(\d+)\s*day",
    ]
    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return int(match.group(1))
    match = re.search(r"(\d+)\s*d", text.lower())
    if match:
        return int(match.group(1))
    return 2


def parse_trip_request(raw_input: TripInput) -> TripRequest:
    """
    Convert structured or free-text input into a normalized TripRequest.
    Uses rule-based keyword matching for free-text.
    """
    if raw_input.raw_text:
        text = raw_input.raw_text
        destination = extract_province(text)
        interests = extract_interests(text)
        pace = extract_pace(text)
        budget = extract_budget(text)
        constraints = extract_constraints(text)
        duration = extract_duration(text)
        if raw_input.start_lat is not None and raw_input.start_lng is not None:
            coords = (raw_input.start_lat, raw_input.start_lng)
        else:
            coords = PROVINCE_COORDS.get(destination, (21.0285, 105.8542))
        provinces = raw_input.destination_provinces or [destination]
        end_loc = {"lat": raw_input.end_lat, "lng": raw_input.end_lng} if raw_input.end_lat and raw_input.end_lng else None

        return TripRequest(
            destination_area=destination,
            destination_provinces=provinces,
            start_date=raw_input.start_date,
            end_date=raw_input.end_date,
            duration_days=duration,
            number_of_people=raw_input.number_of_people or 2,
            interests=interests,
            pace=pace,
            travel_mode=raw_input.travel_mode or "mixed",
            budget_level=budget,
            constraints=constraints,
            must_visit_site_ids=raw_input.must_visit_site_ids,
            start_location={"lat": coords[0], "lng": coords[1]},
            end_location=end_loc,
        )

    provinces = raw_input.destination_provinces or [raw_input.destination_area or "Hà Nội"]
    end_loc = {"lat": raw_input.end_lat, "lng": raw_input.end_lng} if raw_input.end_lat and raw_input.end_lng else None
    dest_area = raw_input.destination_area or ", ".join(provinces)

    return TripRequest(
        destination_area=dest_area,
        destination_provinces=provinces,
        start_date=raw_input.start_date or "",
        end_date=raw_input.end_date or "",
        duration_days=raw_input.duration_days or 2,
        number_of_people=raw_input.number_of_people or 1,
        interests=raw_input.interests or ["history", "local_food"],
        pace=raw_input.pace or "moderate",
        travel_mode=raw_input.travel_mode or "mixed",
        budget_level=raw_input.budget_level or "medium",
        constraints=raw_input.constraints or [],
        must_visit_site_ids=raw_input.must_visit_site_ids or [],
        start_location={"lat": raw_input.start_lat or 21.0285, "lng": raw_input.start_lng or 105.8542},
        end_location=end_loc,
    )
