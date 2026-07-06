"""
Data Loader — Loads heritage sites from DeepSeek-curated data.
"""
from typing import List, Tuple
from app.services.recommendation.models import HeritageSite

def load_all_data() -> Tuple[List[HeritageSite], List]:
    from app.services.recommendation.curated_data import CURATED_HERITAGE
    return list(CURATED_HERITAGE), []
