"""
S9N Memory Vault — Enrichment API Routes

Endpoints for triggering and monitoring the enrichment pipeline:
- POST /api/v1/memories/{memory_id}/enrich  — Enrich a single memory
- POST /api/v1/enrichment/batch             — Enrich all pending memories
- GET  /api/v1/memories/{memory_id}/enrichment — Get enrichment results

Spec reference: Section 7.5 (Enrichment Pipeline)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.auth import require_auth, AuthContext
from backend.services.enrichment_service import (
    enrich_memory,
    enrich_pending_memories,
    EnrichmentResult,
)

router = APIRouter(prefix="/api/v1", tags=["Enrichment"])


@router.post(
    "/memories/{memory_id}/enrich",
    summary="Enrich a single memory",
)
async def enrich_memory_endpoint(
    memory_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger enrichment for a single memory.

    Runs entity extraction, concept tagging, quality scoring,
    and graph relationship building.
    """
    try:
        result = await enrich_memory(memory_id, auth.user_id, db)
        return {
            "memory_id": result.memory_id,
            "entity_count": len(result.entities),
            "tag_count": len(result.concept_tags),
            "quality_score": result.quality_score.overall,
            "relationship_count": len(result.graph_relationships),
            "processing_time_ms": result.processing_time_ms,
            "status": "completed",
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Enrichment failed: {str(e)}",
        )


@router.post(
    "/enrichment/batch",
    summary="Enrich all pending memories",
)
async def batch_enrich_endpoint(
    batch_size: int = 10,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger batch enrichment for all pending memories.

    Processes up to batch_size memories in a single call.
    """
    results = await enrich_pending_memories(auth.user_id, db, batch_size)
    return {
        "processed": len(results),
        "results": [
            {
                "memory_id": r.memory_id,
                "entity_count": len(r.entities),
                "quality_score": r.quality_score.overall,
                "status": "completed",
            }
            for r in results
        ],
    }


@router.get(
    "/memories/{memory_id}/enrichment",
    summary="Get enrichment results for a memory",
)
async def get_enrichment_endpoint(
    memory_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get the enrichment results stored in a memory's metadata."""
    from sqlalchemy import select
    from backend.models.memory import Memory

    result = await db.execute(
        select(Memory).where(
            Memory.memory_id == memory_id,
            Memory.user_id == auth.user_id,
            Memory.invalid_at == None,
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")

    enrichment_data = (memory.meta or {}).get("enrichment")
    if not enrichment_data:
        return {
            "memory_id": str(memory_id),
            "enrichment_status": memory.enrichment_status,
            "message": "No enrichment data available",
        }

    return {
        "memory_id": str(memory_id),
        "enrichment_status": memory.enrichment_status,
        "quality_score": memory.quality_score,
        "data": enrichment_data,
    }
