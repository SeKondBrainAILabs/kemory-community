"""Community-edition settings and portable JSON backup routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.models.memory import Memory
from backend.services.memory_service import MemoryCreate, create_memory

router = APIRouter(prefix="/api/v1/community", tags=["Community"])


class ImportMemory(BaseModel):
    namespace: str
    content: str
    content_type: str = "text"
    metadata: dict[str, Any] | None = None
    ttl_seconds: int | None = None


class ImportBundle(BaseModel):
    memories: list[ImportMemory] = Field(default_factory=list)


@router.get("/settings")
async def community_settings(auth: AuthContext = Depends(require_auth)):
    return {
        "edition": "community",
        "version": settings.app_version,
        "user_id": str(auth.user_id),
        "org_id": auth.org_id,
        "identity": settings.kmv_identity,
        "vector_backend": settings.kmv_vector_backend,
        "blob_backend": settings.kmv_blob_backend,
        "telemetry": settings.kmv_telemetry,
        "tenant_enforcement": settings.tenant_enforcement,
    }


@router.get("/export")
async def export_bundle(
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Memory)
        .where(Memory.user_id == auth.user_id)
        .where(Memory.invalid_at.is_(None))
        .order_by(Memory.updated_at.desc())
    )
    memories = [
        {
            "namespace": item.namespace,
            "content": item.content,
            "content_type": item.content_type,
            "metadata": item.meta or {},
            "ttl_seconds": item.ttl_seconds,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in result.scalars().all()
    ]
    return {
        "schema_version": 1,
        "edition": "community",
        "exported_at": datetime.now(UTC).isoformat(),
        "memories": memories,
    }


@router.post("/import")
async def import_bundle(
    bundle: ImportBundle,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    imported = 0
    for item in bundle.memories:
        await create_memory(
            auth.user_id,
            auth.agent_id,
            MemoryCreate(
                namespace=item.namespace,
                content=item.content,
                content_type=item.content_type,
                metadata=item.metadata,
                ttl_seconds=item.ttl_seconds,
                allow_duplicate=True,
            ),
            db,
            skip_gatekeeper=True,
            org_id=auth.org_id,
        )
        imported += 1
    return {"imported": imported}
