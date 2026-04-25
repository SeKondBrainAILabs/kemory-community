"""
S9N Memory Vault — FastAPI Dependencies

Centralized dependency injection for database sessions, Redis, and auth.
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.database import get_db
from backend.core.redis import get_redis


# Re-export for clean imports
__all__ = ["get_db", "get_redis"]
