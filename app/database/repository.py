"""
Generic async CRUD repository for SQLAlchemy models.
"""

import uuid
from typing import Any, Optional, Sequence, Type, TypeVar

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Base

T = TypeVar("T", bound=Base)


class Repository:
    """Generic async CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, model: Type[T], id: uuid.UUID) -> Optional[T]:
        return await self.session.get(model, id)

    async def get_all(
        self,
        model: Type[T],
        *,
        order_by: Any = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Sequence[T]:
        stmt = select(model)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        if limit:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, obj: T) -> T:
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update_fields(
        self, model: Type[T], id: uuid.UUID, **fields: Any
    ) -> Optional[T]:
        stmt = (
            update(model)
            .where(model.id == id)  # type: ignore[attr-defined]
            .values(**fields)
            .returning(model)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            await self.session.flush()
        return row

    async def delete_by_id(self, model: Type[T], id: uuid.UUID) -> bool:
        stmt = delete(model).where(model.id == id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.rowcount > 0  # type: ignore[union-attr]

    async def count(self, model: Type[T]) -> int:
        stmt = select(func.count()).select_from(model)
        result = await self.session.execute(stmt)
        return result.scalar_one()
