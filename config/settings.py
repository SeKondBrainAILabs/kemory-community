"""
S9N Memory Vault — Application Settings

Centralized configuration using pydantic-settings v2.
All values are loaded from environment variables with sensible defaults for development.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Application ──────────────────────────────────────────────
    app_name: str = "S9N Memory Vault"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # ─── CORS ─────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:3002,http://localhost:3003"
    """Comma-separated list of allowed CORS origins."""

    # ─── PostgreSQL ───────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://kora:kora_secret@localhost:5432/kora_vault"
    database_url_sync: str = "postgresql://kora:kora_secret@localhost:5432/kora_vault"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # ─── Redis ────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ─── Neo4j ────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "kora_neo4j_secret"

    # ─── Weaviate ─────────────────────────────────────────────────
    weaviate_url: str = "http://localhost:8080"

    # ─── JWT Authentication (internal HS256 for agents) ─────────
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 15

    # ─── Multi-tenancy (KEMORY_MULTI_TENANT_AUTH_PLAN.md) ────────
    # Three-stage rollout:
    #   "off"     — legacy single-tenant behaviour, no enforcement (default)
    #   "shadow"  — log cross-org / claim-missing violations but allow request
    #   "enforce" — reject cross-org with 404 and missing-claim with 401
    # Default is "off" so this branch is shippable but inert until each
    # follow-up workstream flips it on.
    tenant_enforcement: str = "off"

    # Keycloak claim name carrying the tenant identifier. Mapped from the
    # user attribute via a Protocol Mapper (WS-2). The legacy tenant name
    # used for backfilled rows; matches the migration sentinel in 009.
    tenant_org_claim: str = "org_id"
    tenant_legacy_sentinel: str = "legacy"

    # ─── Keycloak (RS256 for human users) ─────────────────────────
    keycloak_enabled: bool = False
    keycloak_url: str = "http://host.docker.internal:8888"
    keycloak_public_url: str = "http://localhost:8888"
    keycloak_realm: str = "s9n-mvp"
    keycloak_client_id: str = "kemory-api"
    keycloak_client_ids: str = "vault-dashboard,kemory-api,kemory-frontend,admin-panel"
    keycloak_admin_client_secret: str = "kemory-api-secret-change-in-production"

    @property
    def keycloak_jwks_url(self) -> str:
        """Keycloak JWKS endpoint for RSA public key fetching."""
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"

    @property
    def keycloak_issuer_url(self) -> str:
        """Token issuer URL (must match iss claim — uses public URL)."""
        base = self.keycloak_public_url or self.keycloak_url
        return f"{base}/realms/{self.keycloak_realm}"

    @property
    def keycloak_client_ids_list(self) -> list[str]:
        """Parse comma-separated client IDs into a list."""
        return [c.strip() for c in self.keycloak_client_ids.split(",") if c.strip()]

    # ─── Email ──────────────────────────────────────────────────────
    email_enabled: bool = False
    email_provider: str = "smtp"  # "smtp" (add "sendgrid" / "resend" later)
    email_from: str = "S9N Memory Vault <hello@sekondbrain.ai>"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # ─── Rate Limiting ────────────────────────────────────────────
    rate_limit_default_rpm: int = 60  # requests per minute
    rate_limit_burst_multiplier: float = 1.5

    # ─── Cognition OS Bridge ─────────────────────────────────────
    cognition_os_url: str = ""
    """Cognition OS base URL (e.g. http://localhost:3002). Empty = disabled."""
    cognition_os_auth_token: str = ""
    """SERVICE_AUTH_SECRET for Cognition OS API."""
    cognition_os_org_id: str = ""
    """X-Org-Id header value for Cognition OS tenant isolation."""

    # ─── Deduplication ────────────────────────────────────────────
    dedup_exact_enabled: bool = True
    dedup_semantic_enabled: bool = True
    dedup_semantic_threshold: float = 0.92
    dedup_semantic_max_candidates: int = 50

    # ─── Enrichment ───────────────────────────────────────────────
    openai_api_key: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# Singleton settings instance
settings = Settings()
