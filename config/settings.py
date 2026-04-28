"""
S9N Memory Vault — Application Settings

Centralized configuration using pydantic-settings v2.
All values are loaded from environment variables with sensible defaults for development.
"""

import re

from pydantic_settings import BaseSettings, SettingsConfigDict

# ─── CORS validator (P1 #6) ────────────────────────────────────────────────
# Validates each entry has scheme + host. Runs at model_post_init time so
# misconfigured CORS_ORIGINS fails kemory startup instead of producing
# silent CORS errors at the customer's browser. The cors_origins field
# stays a CSV string (matching env shape) and is parsed via the
# cors_origins_list property; validation guarantees the property never
# returns a malformed entry.
_CORS_ORIGIN_RE = re.compile(r"^https?://[^\s,]+$")


def _parse_cors_origins(raw: str) -> list[str]:
    """Split CSV, strip, dedupe, validate each entry. Empty input → []."""
    if not raw:
        return []
    items = [s.strip() for s in raw.split(",") if s.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for entry in items:
        if not _CORS_ORIGIN_RE.match(entry):
            raise ValueError(
                f"CORS origin {entry!r} is not a valid http(s) URL — "
                "did you forget the scheme? expected e.g. 'https://app.example.com'"
            )
        if entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Application ──────────────────────────────────────────────
    # P1 #9: rebranded "S9N Memory Vault" → "Kemory" in the user-facing
    # default. The DB table prefix `s9nmv_*` and the Python package
    # `memory_vault` remain on legacy names until migration 011 (the
    # follow-up that renames tables; not safe to do without a coordinated
    # deploy + data migration).
    app_name: str = "Kemory"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # ─── CORS ─────────────────────────────────────────────────────
    # P1 #6: stays a CSV string (matches env-var shape) but is validated
    # at model_post_init — invalid entries (missing scheme, etc.) fail
    # kemory startup instead of producing silent CORS errors at the
    # customer's browser. Parsed view via .cors_origins_list.
    cors_origins: str = "http://localhost:3000,http://localhost:3002,http://localhost:3003"

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
    # SECURITY: fail-closed in non-development environments. The previous
    # default ("dev-secret-change-in-production") meant a misconfigured env
    # would silently ship that hard-coded secret to prod. See codebase review
    # P1 #5. Empty in dev → an ephemeral random key is generated at startup
    # (logged WARN). Empty in staging/prod → kemory refuses to start.
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 15

    # ─── Multi-tenancy (KEMORY_MULTI_TENANT_AUTH_PLAN.md) ────────
    # Three modes:
    #   "off"     — legacy single-tenant behaviour, no enforcement
    #   "shadow"  — log cross-org / claim-missing violations but allow request
    #   "enforce" — reject cross-org with 404 and missing-claim with 401
    # Default is "enforce" — kemory has no production users yet, so we
    # ship multi-tenant from day 1 rather than running through shadow bake.
    # Set TENANT_ENFORCEMENT=off in local dev when working without Keycloak.
    tenant_enforcement: str = "enforce"

    # Keycloak claim name carrying the tenant identifier. Mapped from the
    # user attribute via a Protocol Mapper (WS-2). The legacy tenant name
    # used for backfilled rows; matches the migration sentinel in 009.
    tenant_org_claim: str = "org_id"
    tenant_legacy_sentinel: str = "legacy"

    # Per-tenant rate limits applied by tenant_rate_limit_middleware.
    # Generous defaults — a popular product gets noisy fast and we don't
    # want to throttle real customers. Override per-deployment via env.
    tenant_rps_per_org: int = 200
    tenant_rps_per_user: int = 50
    tenant_rate_limit_window_seconds: int = 1

    # Hard cap on agents per user. Prevents a single user from spamming
    # the agent_registry table after they obtain a Keycloak token.
    max_agents_per_user: int = 50

    # P4 #22: hard cap on request body size. Default 1 MiB is generous
    # for typical memories (a long conversation summary is ~5 KB) and
    # tight enough to prevent a malicious 10 GB body from OOMing the
    # worker. Override per env if a real ingest endpoint needs more.
    max_request_body_bytes: int = 1_048_576

    # P4 #21: defense-in-depth cap on list/search page size. The Pydantic
    # MemorySearchRequest already enforces limit ≤ 100; this is the
    # ceiling for any other handler that takes a raw `limit` parameter.
    max_page_size: int = 100

    # P4 #21: query-safety mode for the un-LIMITed-SELECT detector.
    #   "off"   — no checks (production default)
    #   "warn"  — log a structured warning, request continues
    #   "raise" — raise RuntimeError so CI / dev catches the regression
    # See backend/core/query_safety.py.
    query_safety_mode: str = "off"

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
    """DEPRECATED (P3 #19) — fallback X-Org-Id only for background tasks
    that run outside a request scope (e.g. periodic consolidation worker).
    The primary source is the active TenantScope's org_id, derived from
    the caller's auth at request time. Will be removed in v0.3."""

    # ─── Deduplication ────────────────────────────────────────────
    dedup_exact_enabled: bool = True
    dedup_semantic_enabled: bool = True
    dedup_semantic_threshold: float = 0.92
    dedup_semantic_max_candidates: int = 50

    # ─── Enrichment ───────────────────────────────────────────────
    openai_api_key: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        """Validated, deduplicated list of CORS origins.
        Validated at startup by model_post_init — this just returns the
        already-known-good split.
        """
        return _parse_cors_origins(self.cors_origins)

    def model_post_init(self, __context) -> None:
        """Apply security policies that depend on multiple fields.

        P1 #5 — JWT secret fail-closed:
          * non-dev with empty/placeholder secret → refuse to start.
          * dev with empty secret → generate ephemeral random key, log WARN.

        P1 #6 — CORS origins format validation:
          Misformatted CORS_ORIGINS (missing scheme, etc.) makes kemory
          refuse to start. Better than silent CORS errors in the customer's
          browser console.
        """
        # P1 #6: CORS validation. Re-parse to surface format errors at
        # startup; the validator raises ValueError on malformed entries.
        try:
            _parse_cors_origins(self.cors_origins)
        except ValueError as exc:
            raise ValueError(f"CORS_ORIGINS is malformed: {exc}. Refusing to start.") from exc

        legacy_placeholders = {"", "dev-secret-change-in-production", "change-me"}
        if self.jwt_secret_key in legacy_placeholders:
            if self.environment in {"staging", "production", "prod"}:
                raise ValueError(
                    "JWT_SECRET_KEY is empty or a placeholder in a non-dev "
                    "environment. Refusing to start. Set a real secret in "
                    "the deployment env (32+ random bytes)."
                )
            # Dev: generate an ephemeral key. Use object.__setattr__ because
            # pydantic v2 freezes fields after validation by default.
            import secrets
            import sys as _sys

            ephemeral = secrets.token_urlsafe(48)
            object.__setattr__(self, "jwt_secret_key", ephemeral)
            # Log to stderr explicitly. structlog's default goes to stdout,
            # which is wrong for a startup-warn line — and pollutes anything
            # else that pipes the process's stdout (gen_env.py, scripts that
            # render the model).
            print(
                f"[WARN] jwt.ephemeral_secret_generated environment={self.environment} "
                "hint='Set JWT_SECRET_KEY to keep tokens valid across restarts'",
                file=_sys.stderr,
            )


# Singleton settings instance
settings = Settings()
