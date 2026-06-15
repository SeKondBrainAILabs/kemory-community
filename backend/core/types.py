"""
S9N Memory Vault — Cross-Dialect Column Types

Provides column types that work across both PostgreSQL (production) and
SQLite (unit tests). Uses TypeDecorator to adapt PG-specific types.

Usage in models:
    from backend.core.types import GUID, JSONType, IPAddress

    class MyModel(Base):
        id = Column(GUID(), primary_key=True, default=uuid.uuid4)
        data = Column(JSONType(), nullable=True)
        ip = Column(IPAddress(), nullable=True)
"""

import json
import uuid

from sqlalchemy import LargeBinary, String, Text, TypeDecorator
from sqlalchemy.types import CHAR


class GUID(TypeDecorator):
    """
    Platform-independent UUID type.
    Uses PostgreSQL's UUID type when available, otherwise CHAR(36).
    """

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID

            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONType(TypeDecorator):
    """
    Platform-independent JSON type.
    Uses PostgreSQL's JSONB when available, otherwise stores as JSON text.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB

            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)


class IPAddress(TypeDecorator):
    """
    Platform-independent IP address type.
    Uses PostgreSQL's INET when available, otherwise String(45).
    """

    impl = String(45)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import INET

            return dialect.type_descriptor(INET())
        else:
            return dialect.type_descriptor(String(45))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return str(value)


class VectorEmbedding(TypeDecorator):
    """
    Platform-independent vector column.

    PostgreSQL uses pgvector's native Vector type. SQLite/PGlite-friendly
    local paths use a BLOB column; adapter code serialises values explicitly.
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, dimension: int = 384, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dimension = dimension

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector(self.dimension))
            except ImportError:
                return dialect.type_descriptor(Text())
        return dialect.type_descriptor(LargeBinary())
