"""
Heritage Bridge Router — Simplified API endpoints for Heritage-LastDance-BE (NestJS).

Provides:
  POST /api/heritage/import    - Upload a document (file or URL), enqueue ingestion
  GET  /api/heritage/search    - Semantic search over wiki pages
  GET  /api/heritage/wiki      - List wiki pages (summary)
  GET  /api/heritage/wiki/{slug} - Get a specific wiki page (full detail)
  GET  /api/heritage/sources/{id}/progress - Check ingestion job progress

Authentication:
  Uses a shared service token (HERITAGE_SERVICE_TOKEN env var).
  Heritage-LastDance-BE sends the token in Authorization: Bearer <token> header.
  No Employee account is required — this is a service-to-service API.

Design Notes:
  - This router is intentionally separate from the main Heritage AI auth flow.
  - It uses a simpler token mechanism: env var shared secret.
  - For production, consider rotating the token via the admin portal.
"""

import uuid
from typing import Optional

from arq.connections import ArqRedis, create_pool
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.database.models import Source, ScopeType, SourceDepartment, WikiPage
from app.database.repository import Repository

router = APIRouter(prefix="/heritage")


# ---------------------------------------------------------------------------
# Token-based auth (service-to-service)
# ---------------------------------------------------------------------------

def get_service_token(authorization: Optional[str] = Header(None)) -> str:
    """Extract and validate the Heritage service token from the Authorization header."""
    expected = settings.heritage_service_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="HERITAGE_SERVICE_TOKEN is not configured on the AI service. Contact admin.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid service token")
    return token


# ---------------------------------------------------------------------------
# ARQ pool (shared with sources router)
# ---------------------------------------------------------------------------

_arq_pool: Optional[ArqRedis] = None


async def _get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        from app.worker import _get_redis_settings
        _arq_pool = await create_pool(_get_redis_settings())
    return _arq_pool


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

class ImportResponse(BaseModel):
    source_id: str
    title: str
    status: str
    job_id: Optional[str] = None
    message: str


class SearchResultItem(BaseModel):
    slug: str
    title: str
    summary: str
    page_type: str
    knowledge_type_slugs: list[str]
    updated_at: str
    similarity: Optional[float] = None
    retrieval_mode: str = "full_text"


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResultItem]
    retrieval_mode: str = "full_text"


class WikiPageSummaryOut(BaseModel):
    slug: str
    title: str
    summary: str
    page_type: str
    knowledge_type_slugs: list[str]
    source_count: int
    updated_at: str


class WikiPageDetailOut(WikiPageSummaryOut):
    content_md: str
    backlinks: list[str]
    outlinks: list[str]


class ProgressResponse(BaseModel):
    source_id: str
    status: str
    progress: int
    progress_message: Optional[str] = None
    page_count: int
    wiki_page_count: int


class QueryRequest(BaseModel):
    question: str
    topK: int = 5
    heritageId: Optional[str] = None
    heritageContext: Optional[str] = None


class QuerySource(BaseModel):
    slug: str
    title: str
    summary: str
    pageType: str
    similarity: Optional[float] = None


class WikiLink(BaseModel):
    slug: str
    title: str


class QueryResponse(BaseModel):
    answer: str
    mode: str
    sources: list[QuerySource]
    wikiLinks: list[WikiLink]


# ---------------------------------------------------------------------------
# Retrieval + generation helpers
# ---------------------------------------------------------------------------

async def _search_wiki_pages(
    db: AsyncSession,
    query: str,
    limit: int,
    page_type: Optional[str] = None,
) -> tuple[list[SearchResultItem], str]:
    semantic_results = await _search_wiki_pages_semantic(db, query, limit, page_type)
    if semantic_results:
        return semantic_results, "semantic"
    return await _search_wiki_pages_full_text(db, query, limit, page_type), "full_text"


async def _search_wiki_pages_semantic(
    db: AsyncSession,
    query: str,
    limit: int,
    page_type: Optional[str] = None,
) -> list[SearchResultItem]:
    try:
        from app.ai.registry import ProviderRegistry
        from app.services import wiki_service

        registry = ProviderRegistry(db)
        embedding_provider = await registry.get_embedding(task="search_query")
        query_embedding = await embedding_provider.embed(query)
        hits = await wiki_service.search_pages_semantic(
            db,
            query_embedding=query_embedding,
            top_k=limit,
        )
    except Exception as exc:
        logger.warning(f"[Heritage] Semantic search unavailable, falling back: {exc}")
        return []

    items: list[SearchResultItem] = []
    for page, similarity in hits:
        if page_type and page.page_type != page_type:
            continue
        items.append(_page_to_search_item(page, similarity=similarity, retrieval_mode="semantic"))
    return items[:limit]


async def _search_wiki_pages_full_text(
    db: AsyncSession,
    query: str,
    limit: int,
    page_type: Optional[str] = None,
) -> list[SearchResultItem]:
    from app.services import wiki_service

    like = f"%{query}%"
    stmt = (
        select(WikiPage)
        .where(
            WikiPage.slug.notin_([wiki_service.INDEX_SLUG, wiki_service.LOG_SLUG]),
            WikiPage.scope_type == "global",
            or_(
                WikiPage.title.ilike(like),
                WikiPage.summary.ilike(like),
            ),
        )
        .order_by(WikiPage.updated_at.desc())
        .limit(limit)
    )
    if page_type:
        stmt = stmt.where(WikiPage.page_type == page_type)

    pages = (await db.execute(stmt)).scalars().all()
    return [_page_to_search_item(page, retrieval_mode="full_text") for page in pages]


def _page_to_search_item(
    page: WikiPage,
    similarity: Optional[float] = None,
    retrieval_mode: str = "full_text",
) -> SearchResultItem:
    return SearchResultItem(
        slug=page.slug,
        title=page.title,
        summary=page.summary or "",
        page_type=page.page_type,
        knowledge_type_slugs=page.knowledge_type_slugs or [],
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
        similarity=similarity,
        retrieval_mode=retrieval_mode,
    )


def _to_query_sources(items: list[SearchResultItem]) -> list[QuerySource]:
    return [
        QuerySource(
            slug=item.slug,
            title=item.title,
            summary=item.summary,
            pageType=item.page_type,
            similarity=item.similarity,
        )
        for item in items
    ]


async def _generate_grounded_answer(
    db: AsyncSession,
    question: str,
    pages: list[WikiPage],
    heritage_context: Optional[str] = None,
) -> str:
    from app.ai.registry import ProviderRegistry

    context_blocks = []
    for index, page in enumerate(pages, start=1):
        content = _truncate_text(page.content_md or page.summary or "", 3500)
        context_blocks.append(
            f"[{index}] {page.title}\n"
            f"Slug: {page.slug}\n"
            f"Summary: {page.summary or ''}\n"
            f"Content:\n{content}"
        )

    system = (
        "Bạn là Heritage Assistant. Trả lời bằng ngôn ngữ tự nhiên cùng ngôn ngữ với câu hỏi của người dùng. "
        "Chỉ dùng thông tin trong CONTEXT. Nếu context không đủ, nói rõ là kho tri thức chưa đủ dữ liệu. "
        "Không bịa nguồn, không nhắc đến prompt nội bộ, không chép nguyên văn dài. "
        "Ưu tiên câu trả lời gọn, rõ, có cấu trúc nhẹ khi cần."
    )
    prompt_parts = [
        f"Câu hỏi của người dùng:\n{question}",
        f"CONTEXT:\n\n{chr(10).join(context_blocks)}",
    ]
    if heritage_context:
        prompt_parts.insert(1, f"Ngữ cảnh di tích/trang hiện tại:\n{heritage_context}")

    registry = ProviderRegistry(db)
    llm = await registry.get_llm()
    answer = await llm.generate(
        "\n\n".join(prompt_parts),
        system=system,
        max_tokens=900,
        temperature=0.2,
    )
    return answer.strip() or (
        "Em chưa thể tổng hợp câu trả lời từ các nguồn hiện có. Anh thử hỏi cụ thể hơn hoặc import thêm tài liệu nhé."
    )


def _truncate_text(text: str, max_length: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length].rstrip()}..."


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/import", response_model=ImportResponse, summary="Import a document into the Heritage knowledge base")
async def heritage_import(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    knowledge_type: Optional[str] = Form(None, description="Optional knowledge type slug (e.g. 'heritage-site')"),
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(get_service_token),
):
    """
    Import a document into the Heritage knowledge base.

    Accepts either:
    - A file upload (multipart/form-data) — PDF, DOCX, TXT, HTML supported
    - A URL to crawl and ingest

    The document is stored in MinIO and queued for AI ingestion (chunking + embedding).
    Poll GET /api/heritage/sources/{id}/progress to track progress.

    Called by Heritage-LastDance-BE NestJS service.
    """
    if not file and not url:
        raise HTTPException(status_code=400, detail="Provide either 'file' (multipart) or 'url' (form field)")

    # Resolve knowledge_type_id from slug if provided
    knowledge_type_id: Optional[uuid.UUID] = None
    if knowledge_type:
        from app.database.models import KnowledgeType
        kt_row = (await db.execute(
            select(KnowledgeType).where(KnowledgeType.slug == knowledge_type)
        )).scalar_one_or_none()
        if kt_row:
            knowledge_type_id = kt_row.id
        else:
            logger.warning(f"Heritage import: knowledge_type slug '{knowledge_type}' not found, ignoring")

    repo = Repository(db)

    if file:
        # --- File upload path ---
        file_data = await file.read()
        file_name = file.filename or "unknown"

        source = Source(
            title=title or file_name,
            source_type="file",
            file_name=file_name,
            file_size=len(file_data),
            status="pending",
            progress=0,
            progress_message="Queued for ingestion...",
            knowledge_type_id=knowledge_type_id,
            scope_type=ScopeType.GLOBAL.value,
        )
        source = await repo.create(source)
        await db.flush()
        await db.commit()
        await db.refresh(source)

        # Upload to MinIO
        from app.services.kb_service import _guess_content_type
        from app.services.storage_service import storage_service
        minio_key = f"sources/{source.id}/original/{file_name}"
        storage_service.upload_file(
            object_name=minio_key,
            data=file_data,
            content_type=_guess_content_type(file_name),
        )
        source.minio_key = minio_key
        await db.commit()

        # Enqueue ingestion job
        pool = await _get_arq_pool()
        job = await pool.enqueue_job("ingest_file_task", str(source.id))
        if job:
            source.job_id = job.job_id
            await db.commit()

        logger.info(f"[Heritage] Enqueued file ingestion: source={source.id}, file={file_name}")
        return ImportResponse(
            source_id=str(source.id),
            title=source.title,
            status="pending",
            job_id=source.job_id,
            message=f"File '{file_name}' queued for ingestion. Poll /api/heritage/sources/{source.id}/progress for status.",
        )

    else:
        # --- URL ingestion path ---
        source = Source(
            title=title or url,
            source_type="url",
            url=url,
            status="pending",
            progress=0,
            progress_message="Queued for ingestion...",
            knowledge_type_id=knowledge_type_id,
            scope_type=ScopeType.GLOBAL.value,
        )
        source = await repo.create(source)
        await db.flush()
        await db.commit()
        await db.refresh(source)

        pool = await _get_arq_pool()
        job = await pool.enqueue_job("ingest_url_task", str(source.id))
        if job:
            source.job_id = job.job_id
            await db.commit()

        logger.info(f"[Heritage] Enqueued URL ingestion: source={source.id}, url={url}")
        return ImportResponse(
            source_id=str(source.id),
            title=source.title,
            status="pending",
            job_id=source.job_id,
            message=f"URL '{url}' queued for ingestion. Poll /api/heritage/sources/{source.id}/progress for status.",
        )


@router.get("/search", response_model=SearchResponse, summary="Semantic search over Heritage knowledge base")
async def heritage_search(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    page_type: Optional[str] = Query(None, description="Filter by page_type (e.g. 'concept', 'how-to')"),
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(get_service_token),
):
    """
    Search the Heritage knowledge base for relevant wiki pages.

    Attempts semantic/vector retrieval first. If embedding config or vectors are
    not ready yet, falls back to the previous title/summary full-text search.
    """
    results, retrieval_mode = await _search_wiki_pages(db, q, limit, page_type)
    logger.info(f"[Heritage] Search '{q}' ({retrieval_mode}) -> {len(results)} results")
    return SearchResponse(
        query=q,
        total=len(results),
        results=results,
        retrieval_mode=retrieval_mode,
    )


@router.post("/query", response_model=QueryResponse, summary="Answer a Heritage question with RAG + LLM")
async def heritage_query(
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(get_service_token),
):
    """
    Retrieve relevant wiki pages, then ask the configured LLM to synthesize a
    natural-language answer grounded in those pages.
    """
    question = body.question.strip()
    if len(question) < 2:
        raise HTTPException(status_code=400, detail="question must be at least 2 characters")

    top_k = min(max(body.topK or 5, 1), 10)
    search_query = question
    if body.heritageContext:
        search_query = f"{body.heritageContext}\n\n{question}"

    search_results, retrieval_mode = await _search_wiki_pages(db, search_query, top_k, None)
    if not search_results:
        return QueryResponse(
            answer=(
                "Hiện tại kho tri thức chưa có dữ liệu đủ liên quan để trả lời câu hỏi này. "
                "Anh có thể import thêm tài liệu phù hợp rồi thử lại."
            ),
            mode=f"llm_9router:{retrieval_mode}:no_sources",
            sources=[],
            wikiLinks=[],
        )

    from app.services import wiki_service

    detail_pages: list[WikiPage] = []
    for item in search_results[: min(4, top_k)]:
        page = await wiki_service.get_page_by_slug(db, item.slug, scope_type="global", scope_id=None)
        if not page:
            page = await wiki_service.get_page_by_slug_any_scope(db, item.slug)
        if page:
            detail_pages.append(page)

    if not detail_pages:
        return QueryResponse(
            answer=(
                "Em tìm thấy trang liên quan trong kho tri thức, nhưng chưa đọc được nội dung chi tiết "
                "để tổng hợp câu trả lời."
            ),
            mode=f"llm_9router:{retrieval_mode}:missing_details",
            sources=_to_query_sources(search_results),
            wikiLinks=[WikiLink(slug=s.slug, title=s.title) for s in search_results],
        )

    answer = await _generate_grounded_answer(
        db=db,
        question=question,
        pages=detail_pages,
        heritage_context=body.heritageContext,
    )

    return QueryResponse(
        answer=answer,
        mode=f"llm_9router:{retrieval_mode}",
        sources=_to_query_sources(search_results),
        wikiLinks=[WikiLink(slug=s.slug, title=s.title) for s in search_results],
    )


@router.get("/wiki", response_model=list[WikiPageSummaryOut], summary="List Heritage wiki pages")
async def heritage_wiki_list(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    page_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(get_service_token),
):
    """
    List all global wiki pages in the Heritage knowledge base.

    Called by Heritage-LastDance-BE to display the knowledge base index to users.
    """
    from app.services import wiki_service

    stmt = (
        select(WikiPage)
        .where(
            WikiPage.slug.notin_([wiki_service.INDEX_SLUG, wiki_service.LOG_SLUG]),
            WikiPage.scope_type == "global",
        )
        .order_by(WikiPage.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if page_type:
        stmt = stmt.where(WikiPage.page_type == page_type)

    pages = (await db.execute(stmt)).scalars().all()
    return [
        WikiPageSummaryOut(
            slug=p.slug,
            title=p.title,
            summary=p.summary or "",
            page_type=p.page_type,
            knowledge_type_slugs=p.knowledge_type_slugs or [],
            source_count=len(p.source_ids or []),
            updated_at=p.updated_at.isoformat() if p.updated_at else "",
        )
        for p in pages
    ]


@router.get("/wiki/{slug:path}", response_model=WikiPageDetailOut, summary="Get a Heritage wiki page by slug")
async def heritage_wiki_detail(
    slug: str,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(get_service_token),
):
    """
    Retrieve a specific wiki page by its slug.

    Called by Heritage-LastDance-BE to display document details to users.
    """
    from app.services import wiki_service

    page = await wiki_service.get_page_by_slug(db, slug, scope_type="global", scope_id=None)
    if not page:
        page = await wiki_service.get_page_by_slug_any_scope(db, slug)
    if not page:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {slug}")

    backlinks = await wiki_service.get_backlinks(db, slug)
    outlinks = await wiki_service.get_outlinks(db, slug)

    return WikiPageDetailOut(
        slug=page.slug,
        title=page.title,
        summary=page.summary or "",
        page_type=page.page_type,
        knowledge_type_slugs=page.knowledge_type_slugs or [],
        source_count=len(page.source_ids or []),
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
        content_md=page.content_md or "",
        backlinks=sorted(backlinks),
        outlinks=sorted(outlinks),
    )


@router.get("/sources/{source_id}/progress", response_model=ProgressResponse, summary="Check ingestion job progress")
async def heritage_source_progress(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(get_service_token),
):
    """
    Poll the progress of a document ingestion job.

    After calling POST /api/heritage/import, poll this endpoint until
    status is 'done' or 'error'.

    Called by Heritage-LastDance-BE to track ingestion status.
    """
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Count wiki pages generated from this source
    from sqlalchemy import func as sqlfunc
    wiki_count = (await db.execute(
        select(sqlfunc.count()).select_from(WikiPage).where(WikiPage.source_ids.any(source_id))  # type: ignore[arg-type]
    )).scalar_one()

    return ProgressResponse(
        source_id=str(source.id),
        status=source.status,
        progress=source.progress,
        progress_message=source.progress_message,
        page_count=len(source.page_offsets or []),
        wiki_page_count=wiki_count,
    )
