"""Wiki image resolver — turn `image://<uuid>` references in wiki content_md
into short-lived presigned MinIO URLs that the browser can fetch directly.

Auth: portal JWT (Depends(get_current_user)). Each requested id is checked
against the user's source-level scope via permission_engine.can_access_document.
Denied ids are returned in `denied[]` so the frontend can render a placeholder.
Unknown ids are silently dropped (broken-image placeholder client-side).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.database.models import Employee, Source, SourceImage
from app.services.auth_service import get_current_user
from app.services.permission_engine import can_access_document
from app.services.storage_service import storage_service

router = APIRouter()


MAX_IDS_PER_REQUEST = 100
PRESIGN_EXPIRY_HOURS = 1


class ResolveRequest(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list)


class ResolveResponse(BaseModel):
    resolved: dict[str, str]   # uuid -> presigned URL
    denied: list[str]          # uuids the user can't see
    # Unknown / non-existent ids are simply absent from both lists.


@router.post("/wiki/images/resolve", response_model=ResolveResponse)
async def resolve_wiki_images(
    body: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
) -> ResolveResponse:
    if not body.ids:
        return ResolveResponse(resolved={}, denied=[])
    if len(body.ids) > MAX_IDS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Too many ids (max {MAX_IDS_PER_REQUEST} per request)",
        )

    # Dedupe
    unique_ids = list({i for i in body.ids})

    rows = (await db.execute(
        select(SourceImage)
        .options(selectinload(SourceImage.source).selectinload(Source.departments))
        .where(SourceImage.id.in_(unique_ids))
    )).scalars().all()

    resolved: dict[str, str] = {}
    denied: list[str] = []

    # Cache per-source access decisions (one image often shares a source with others).
    access_cache: dict[uuid.UUID, bool] = {}

    for img in rows:
        source = img.source
        if source is None:
            continue
        if source.id not in access_cache:
            access_cache[source.id] = await can_access_document(db, user, source, "read")
        if not access_cache[source.id]:
            denied.append(str(img.id))
            continue
        try:
            url = storage_service.get_presigned_url(img.minio_key, expiry_hours=PRESIGN_EXPIRY_HOURS)
            resolved[str(img.id)] = url
        except Exception as e:
            logger.warning(f"Failed to presign image {img.id} ({img.minio_key}): {e}")
            # Fall through — frontend treats it as unknown/broken.

    return ResolveResponse(resolved=resolved, denied=denied)
