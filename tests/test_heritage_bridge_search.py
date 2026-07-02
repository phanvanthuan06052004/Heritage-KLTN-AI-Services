from app.database.models import WikiPage
from app.routers.heritage_bridge import _extract_search_terms, _score_full_text_page


def test_extract_search_terms_keeps_domain_terms_from_natural_question():
    assert _extract_search_terms("Claude AI là gì?") == ["claude", "ai"]


def test_score_full_text_page_prioritizes_title_matches():
    title_page = WikiPage(
        title="Claude AI",
        summary="General assistant",
        content_md="Short content.",
    )
    content_page = WikiPage(
        title="Research report",
        summary="General assistant",
        content_md="This document mentions Claude AI many times.",
    )
    terms = ["claude", "ai"]

    assert _score_full_text_page(title_page, terms, "claude ai") > _score_full_text_page(
        content_page,
        terms,
        "claude ai",
    )
