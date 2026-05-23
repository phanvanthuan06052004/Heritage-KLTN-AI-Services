import uuid

from app.database.models import Source
from app.services.source_chunk_service import (
    EvidenceHit,
    _build_chunks,
    evidence_to_citations,
)
from app.services.source_outline import assemble_full_text


def test_build_chunks_preserves_page_numbers():
    pages = [
        {"content": "Page one about Ha Long Bay and limestone islands.", "page_number": 1},
        {"content": "Page two about Hoi An Ancient Town and trade ports.", "page_number": 2},
    ]
    full_text, offsets = assemble_full_text(pages)
    source_id = uuid.uuid4()
    source = Source(
        id=source_id,
        title="Vietnam heritage",
        full_text=full_text,
        page_offsets=offsets,
        source_type="file",
    )

    chunks = _build_chunks(source)

    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert all(chunk.source_id == source_id for chunk in chunks)
    assert all(len(chunk.content_hash) == 64 for chunk in chunks)


def test_evidence_to_citations_uses_public_wire_shape():
    source_id = uuid.uuid4()
    hit = EvidenceHit(
        source_id=source_id,
        title="Source A",
        source_type="file",
        file_name="source.pdf",
        url=None,
        page=3,
        snippet="A short source excerpt.",
        evidence_type="raw_page",
        score=2.0,
    )

    citations = evidence_to_citations([hit])

    assert citations == [
        {
            "sourceId": str(source_id),
            "title": "Source A",
            "page": 3,
            "snippet": "A short source excerpt.",
            "evidenceType": "raw_page",
            "score": 2.0,
        }
    ]
