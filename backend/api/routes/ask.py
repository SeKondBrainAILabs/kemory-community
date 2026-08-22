"""Community Ask HTTP endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.services.ask_service import AskRequest, AskResponse, ask

router = APIRouter(prefix="/api/v1", tags=["Ask"])


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Answer a question from local Kemory evidence",
)
async def ask_endpoint(
    request: AskRequest,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> AskResponse:
    """Return retrieval items even when synthesis is disabled or unavailable."""
    return await ask(db, user_id=auth.user_id, agent_id=auth.agent_id, request=request)
