"""Raw source chunking, embedding, and evidence retrieval for hybrid RAG."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_catalog import EmbeddingModelSpec, get_spec
from app.ai.registry import ProviderRegistry
from app.database.models import (
    Source,
    SourceChunk,
    get_source_chunk_embedding_model_for_dim,
)
from app.services.source_outline import slice_pages_by_range

CHUNK_MAX_CHARS = 1600
CHUNK_OVERLAP_CHARS = 180
EMBED_INPUT_CHARS = 2200


@dataclass
class EvidenceHit:
    source_id: uuid.UUID
    title: str
    source_type: str
    file_name: Optional[str]
    url: Optional[str]
    page: Optional[int]
    snippet: str
    evidence_type: str
    score: Optional[float] = None


def compute_chunk_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def chunk_embedding_input(chunk: SourceChunk) -> str:
    page_label = f"Page {chunk.page_number}" if chunk.page_number else "Source excerpt"
    return f"{page_label}\n\n{chunk.content}"[:EMBED_INPUT_CHARS]


async def rebuild_source_chunks(
    session: AsyncSession,
    source: Source,
    embed: bool = True,
) -> list[SourceChunk]:
    """Recreate chunks for a source and optionally embed them."""
    await session.execute(delete(SourceChunk).where(SourceChunk.source_id == source.id))
    await session.flush()

    chunks = _build_chunks(source)
    for chunk in chunks:
        session.add(chunk)
    await session.flush()

    if embed and chunks:
        await embed_chunks(session, chunks)

    return chunks


def _build_chunks(source: Source) -> list[SourceChunk]:
    full_text = source.full_text or ""
    if not full_text.strip():
        return []

    offsets = source.page_offsets or []
    if offsets:
        page_numbers = list(range(1, len(offsets) + 1))
        page_slices = slice_pages_by_range(full_text, offsets, page_numbers)
    else:
        page_slices = [{"page": None, "content": full_text}]

    chunks: list[SourceChunk] = []
    chunk_index = 0
    for page in page_slices:
        content = _normalize_text(page.get("content") or "")
        if not content:
            continue
        for piece in _split_text(content):
            if not piece:
                continue
            chunks.append(
                SourceChunk(
                    source_id=source.id,
                    page_number=page.get("page"),
                    chunk_index=chunk_index,
                    content=piece,
                    content_hash=compute_chunk_hash(piece),
                    metadata_={"strategy": "page_sliding_window"},
                )
            )
            chunk_index += 1
    return chunks


def _split_text(text: str) -> list[str]:
    if len(text) <= CHUNK_MAX_CHARS:
        return [text]

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_MAX_CHARS, len(text))
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind("\n", start, end))
            if boundary > start + CHUNK_MAX_CHARS // 2:
                end = boundary + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return pieces


async def embed_chunks(session: AsyncSession, chunks: list[SourceChunk]) -> None:
    registry = ProviderRegistry(session)
    try:
        spec_id = await registry.get_active_embedding_spec_id()
        if not spec_id:
            logger.info("No active embedding model — skipping source chunk embeddings.")
            return
        spec = get_spec(spec_id)
        provider = await registry.get_embedding(task="document", spec_id=spec.id)
        vectors = await provider.embed_batch([chunk_embedding_input(c) for c in chunks])
    except Exception as exc:
        logger.warning(f"Source chunk embedding skipped/failed: {exc}")
        return

    for chunk, vector in zip(chunks, vectors):
        await upsert_chunk_embedding(
            session,
            chunk_id=chunk.id,
            spec=spec,
            vector=list(vector),
            content_hash=chunk.content_hash,
        )
    await session.flush()


async def upsert_chunk_embedding(
    session: AsyncSession,
    chunk_id: uuid.UUID,
    spec: EmbeddingModelSpec,
    vector: list[float],
    content_hash: str,
) -> None:
    Model = get_source_chunk_embedding_model_for_dim(spec.dimension)
    stmt = pg_insert(Model).values(
        chunk_id=chunk_id,
        model_spec_id=spec.id,
        content_hash=content_hash,
        embedding=vector,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["chunk_id", "model_spec_id"],
        set_={
            "embedding": stmt.excluded.embedding,
            "content_hash": stmt.excluded.content_hash,
            "embedded_at": stmt.excluded.embedded_at,
        },
    )
    await session.execute(stmt)


async def cleanup_stale_chunk_embeddings(
    session: AsyncSession,
    keep_spec_id: str,
) -> int:
    from app.database.models import (
        SourceChunkEmbedding768,
        SourceChunkEmbedding1024,
        SourceChunkEmbedding1536,
        SourceChunkEmbedding3072,
    )

    total = 0
    for Model in (
        SourceChunkEmbedding768,
        SourceChunkEmbedding1024,
        SourceChunkEmbedding1536,
        SourceChunkEmbedding3072,
    ):
        result = await session.execute(
            delete(Model).where(Model.model_spec_id != keep_spec_id)
        )
        total += result.rowcount or 0  # type: ignore[union-attr]
    return total


async def find_evidence(
    session: AsyncSession,
    query: str,
    source_ids: list[uuid.UUID],
    limit: int = 5,
) -> list[EvidenceHit]:
    unique_source_ids = list(dict.fromkeys(source_ids))
    if not unique_source_ids:
        return []

    hits = await _find_semantic_chunk_evidence(session, query, unique_source_ids, limit)
    if hits:
        return hits
    return await _find_lexical_page_evidence(session, query, unique_source_ids, limit)


async def _find_semantic_chunk_evidence(
    session: AsyncSession,
    query: str,
    source_ids: list[uuid.UUID],
    limit: int,
) -> list[EvidenceHit]:
    try:
        registry = ProviderRegistry(session)
        spec_id = await registry.get_active_embedding_spec_id()
        if not spec_id:
            return []
        spec = get_spec(spec_id)
        provider = await registry.get_embedding(task="search_query", spec_id=spec.id)
        query_embedding = await provider.embed(query)
        Emb = get_source_chunk_embedding_model_for_dim(spec.dimension)
    except Exception as exc:
        logger.warning(f"Source chunk semantic evidence unavailable: {exc}")
        return []

    stmt = (
        select(
            SourceChunk,
            Source,
            (1 - Emb.embedding.cosine_distance(query_embedding)).label("similarity"),
        )
        .join(Emb, Emb.chunk_id == SourceChunk.id)
        .join(Source, Source.id == SourceChunk.source_id)
        .where(
            SourceChunk.source_id.in_(source_ids),
            Emb.model_spec_id == spec.id,
        )
        .order_by(Emb.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    terms = _query_terms(query)
    return [
        _chunk_to_hit(chunk, source, evidence_type="raw_chunk", score=float(score), terms=terms)
        for chunk, source, score in rows
    ]


async def _find_lexical_page_evidence(
    session: AsyncSession,
    query: str,
    source_ids: list[uuid.UUID],
    limit: int,
) -> list[EvidenceHit]:
    sources = (
        await session.execute(select(Source).where(Source.id.in_(source_ids)))
    ).scalars().all()
    terms = _query_terms(query)
    scored: list[tuple[float, EvidenceHit]] = []
    for source in sources:
        full_text = source.full_text or ""
        offsets = source.page_offsets or []
        if not full_text.strip():
            continue
        if offsets:
            page_slices = slice_pages_by_range(full_text, offsets, list(range(1, len(offsets) + 1)))
        else:
            page_slices = [{"page": None, "content": full_text}]

        for page in page_slices:
            content = _normalize_text(page.get("content") or "")
            if not content:
                continue
            score = _lexical_score(content, terms)
            if score <= 0:
                continue
            scored.append((
                score,
                EvidenceHit(
                    source_id=source.id,
                    title=source.title or source.file_name or source.url or "Untitled source",
                    source_type=source.source_type or "file",
                    file_name=source.file_name,
                    url=source.url,
                    page=page.get("page"),
                    snippet=clean_public_snippet(_best_snippet(content, terms)),
                    evidence_type="raw_page",
                    score=score,
                ),
            ))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [hit for _, hit in scored[:limit]]


async def list_raw_sources(
    session: AsyncSession,
    source_ids: list[uuid.UUID],
) -> list[dict]:
    unique_source_ids = list(dict.fromkeys(source_ids))
    if not unique_source_ids:
        return []
    sources = (
        await session.execute(select(Source).where(Source.id.in_(unique_source_ids)))
    ).scalars().all()
    return [
        {
            "sourceId": str(source.id),
            "title": source.title or source.file_name or source.url or "Untitled source",
            "sourceType": source.source_type or "file",
            "fileName": source.file_name,
            "url": source.url,
        }
        for source in sources
    ]


def evidence_to_context(hits: list[EvidenceHit]) -> str:
    blocks = []
    for index, hit in enumerate(hits, start=1):
        page_label = f", page {hit.page}" if hit.page else ""
        blocks.append(
            f"[E{index}] {hit.title}{page_label}\n"
            f"Source ID: {hit.source_id}\n"
            f"Evidence type: {hit.evidence_type}\n"
            f"Excerpt:\n{hit.snippet}"
        )
    return "\n\n".join(blocks)


def evidence_to_citations(hits: list[EvidenceHit]) -> list[dict]:
    return [
        {
            "sourceId": str(hit.source_id),
            "title": hit.title,
            "page": hit.page,
            "snippet": clean_public_snippet(hit.snippet),
            "evidenceType": hit.evidence_type,
            "score": hit.score,
        }
        for hit in hits
    ]


def _chunk_to_hit(
    chunk: SourceChunk,
    source: Source,
    evidence_type: str,
    score: Optional[float],
    terms: Optional[list[str]] = None,
) -> EvidenceHit:
    snippet = _best_snippet(chunk.content, terms or [], max_chars=900)
    return EvidenceHit(
        source_id=source.id,
        title=source.title or source.file_name or source.url or "Untitled source",
        source_type=source.source_type or "file",
        file_name=source.file_name,
        url=source.url,
        page=chunk.page_number,
        snippet=clean_public_snippet(snippet),
        evidence_type=evidence_type,
        score=score,
    )


def _query_terms(query: str) -> list[str]:
    normalized = query.lower()
    terms = re.findall(r"[\wÀ-ỹ]+", normalized, flags=re.UNICODE)
    return [term for term in terms if len(term) >= 3][:20]


def _lexical_score(content: str, terms: list[str]) -> float:
    lower = content.lower()
    return float(sum(lower.count(term) for term in terms))


def _best_snippet(content: str, terms: list[str], max_chars: int = 900) -> str:
    lower = content.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    if not positions:
        return _truncate(content, max_chars)
    center = min(positions)
    start = max(0, center - min(140, max_chars // 4))
    end = min(len(content), start + max_chars)
    snippet = content[start:end].strip()
    if start > 0:
        sentence_start = re.search(r"[.!?…]\s+", snippet[:260])
        if sentence_start and sentence_start.end() < len(snippet):
            snippet = snippet[sentence_start.end() :]
    return _truncate(snippet, max_chars)


def clean_public_snippet(text: str, max_chars: int = 700) -> str:
    """Remove crawler/markdown noise before exposing raw evidence to users."""
    cleaned = _normalize_text(text)
    cleaned = re.sub(r"URL Source:\s*https?://\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"Published Time:\s+.*?(?=Markdown Content:|$)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"Markdown Content:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"!\[[^\]]*]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[\[([^\]|]+)\|([^\]]+)]]", r"\2", cleaned)
    cleaned = re.sub(r"\[\[([^\]]+)]]", r"\1", cleaned)
    cleaned = re.sub(r"[*_`>#]+", "", cleaned)
    cleaned = _normalize_text(cleaned)
    if cleaned and cleaned[0].islower():
        sentence_start = re.search(r"[.!?…]\s+", cleaned[:260])
        if sentence_start and sentence_start.end() < len(cleaned):
            cleaned = cleaned[sentence_start.end() :]
    return _truncate(cleaned, max_chars)


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _truncate(text: str, max_chars: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars].rstrip()}..."
