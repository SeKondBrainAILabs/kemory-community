"""
S9N Memory Vault — Gatekeeper Service (Permission Engine)

Implements the L1-L2 Gatekeeper from the spec:
- L1: Rule-based evaluation (priority-ordered, first-match wins)
- L2: JIT consent for rules with action='jit'
- Default-deny posture: if no rule matches, access is DENIED

Spec reference: Section 7.1 (Gatekeeper), Appendix D (Evaluation Examples)

Stories: F02-US-001 (scope declaration), F02-US-002 (default-deny),
         F03-US-001 (permission CRUD), F03-US-002 (rule evaluation)
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.permission import PermissionRule
from backend.models.consent import ConsentRequest
from backend.models.audit import AuditLog
from backend.models.agent import AgentRegistry


# ─── Request/Response Schemas ─────────────────────────────────────

class PermissionRuleCreate(BaseModel):
    """Request body for creating a permission rule."""
    agent_id: Optional[str] = Field(None, description="Agent UUID. NULL = applies to all agents.")
    scope: str = Field(..., min_length=1, max_length=100, description="Scope: memory:read, memory:write, etc.")
    action: str = Field(..., description="Action: allow, deny, jit")
    priority: int = Field(default=100, ge=1, le=10000, description="Priority (lower = evaluated first)")
    namespace_filter: Optional[str] = Field(None, max_length=255, description="Glob pattern for namespace")
    conditions: Optional[dict] = Field(None, description="Optional conditions: time_window, rate_limit, etc.")


class PermissionRuleUpdate(BaseModel):
    """Request body for updating a permission rule."""
    scope: Optional[str] = Field(None, min_length=1, max_length=100)
    action: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=10000)
    namespace_filter: Optional[str] = Field(None, max_length=255)
    conditions: Optional[dict] = None
    is_active: Optional[bool] = None


class PermissionRuleResponse(BaseModel):
    """Response body for a permission rule."""
    rule_id: str
    user_id: str
    agent_id: Optional[str]
    scope: str
    action: str
    priority: int
    namespace_filter: Optional[str]
    conditions: Optional[dict]
    is_active: bool
    created_at: str
    updated_at: str


class GatekeeperDecision(BaseModel):
    """Result of a Gatekeeper evaluation."""
    allowed: bool
    outcome: str  # "allowed", "denied", "jit_pending", "jit_approved", "jit_denied", "jit_timeout"
    matched_rule_id: Optional[str] = None
    reason: str
    evaluation_time_ms: Optional[int] = None
    consent_id: Optional[str] = None  # If JIT consent was triggered


class EvaluationRequest(BaseModel):
    """Request to evaluate a permission."""
    agent_id: str
    scope: str
    resource: Optional[str] = None  # namespace or memory ID
    namespace: Optional[str] = None


# ─── Validation ───────────────────────────────────────────────────

VALID_SCOPES = {
    "memory:read", "memory:write", "memory:delete",
    "namespace:read", "namespace:write", "namespace:create",
    "graph:read", "graph:write",
    "admin:*",
}

VALID_ACTIONS = {"allow", "deny", "jit"}


def validate_scope(scope: str) -> bool:
    """Validate that a scope string is recognized."""
    # Allow exact matches and wildcard patterns
    if scope in VALID_SCOPES:
        return True
    # Allow namespace-specific scopes like "memory:read:shared"
    base_scope = ":".join(scope.split(":")[:2])
    return base_scope in VALID_SCOPES


def validate_action(action: str) -> bool:
    """Validate that an action string is recognized."""
    return action in VALID_ACTIONS


# ─── Rule CRUD ────────────────────────────────────────────────────

async def create_rule(
    user_id: uuid.UUID,
    request: PermissionRuleCreate,
    db: AsyncSession,
) -> PermissionRuleResponse:
    """
    Create a new permission rule.

    Business rules:
    - Scope must be a valid scope string
    - Action must be one of: allow, deny, jit
    - Priority must be between 1 and 10000
    - Agent ID is optional (NULL = applies to all agents)
    """
    if not validate_scope(request.scope):
        raise ValueError(f"Invalid scope: '{request.scope}'. Valid scopes: {sorted(VALID_SCOPES)}")
    if not validate_action(request.action):
        raise ValueError(f"Invalid action: '{request.action}'. Valid actions: {sorted(VALID_ACTIONS)}")

    rule = PermissionRule(
        user_id=user_id,
        agent_id=uuid.UUID(request.agent_id) if request.agent_id else None,
        scope=request.scope,
        action=request.action,
        priority=request.priority,
        namespace_filter=request.namespace_filter,
        conditions=request.conditions,
        is_active=True,
    )
    db.add(rule)
    await db.flush()
    return _to_response(rule)


async def update_rule(
    rule_id: uuid.UUID,
    user_id: uuid.UUID,
    request: PermissionRuleUpdate,
    db: AsyncSession,
) -> PermissionRuleResponse:
    """Update an existing permission rule."""
    rule = await _get_rule_for_user(rule_id, user_id, db)

    if request.scope is not None:
        if not validate_scope(request.scope):
            raise ValueError(f"Invalid scope: '{request.scope}'")
        rule.scope = request.scope

    if request.action is not None:
        if not validate_action(request.action):
            raise ValueError(f"Invalid action: '{request.action}'")
        rule.action = request.action

    if request.priority is not None:
        rule.priority = request.priority

    if request.namespace_filter is not None:
        rule.namespace_filter = request.namespace_filter

    if request.conditions is not None:
        rule.conditions = request.conditions

    if request.is_active is not None:
        rule.is_active = request.is_active

    rule.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _to_response(rule)


async def delete_rule(
    rule_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Delete a permission rule."""
    rule = await _get_rule_for_user(rule_id, user_id, db)
    await db.delete(rule)
    await db.flush()


async def get_rule(
    rule_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> PermissionRuleResponse:
    """Get a single permission rule."""
    rule = await _get_rule_for_user(rule_id, user_id, db)
    return _to_response(rule)


async def list_rules(
    user_id: uuid.UUID,
    db: AsyncSession,
    agent_id: Optional[uuid.UUID] = None,
    scope: Optional[str] = None,
    admin_view: bool = False,
) -> list[PermissionRuleResponse]:
    """
    List permission rules.

    Fix KMV-QA-005: When ``admin_view`` is True (Memory Vault admin role)
    the user_id filter is omitted so the admin can see all rules across
    every user's vault.
    """
    if admin_view:
        query = select(PermissionRule)
    else:
        query = select(PermissionRule).where(PermissionRule.user_id == user_id)
    if agent_id:
        query = query.where(PermissionRule.agent_id == agent_id)
    if scope:
        query = query.where(PermissionRule.scope == scope)
    query = query.order_by(PermissionRule.priority.asc())

    result = await db.execute(query)
    rules = result.scalars().all()
    return [_to_response(r) for r in rules]


# ─── Gatekeeper Evaluation Engine ─────────────────────────────────


async def _increment_agent_stats(
    agent_id: uuid.UUID,
    scope: str,
    allowed: bool,
    db: AsyncSession,
) -> None:
    """Increment agent usage counters after a gatekeeper decision.

    BUG-004 fix: total_reads / total_writes / denied_requests were never
    incremented because evaluate() returned early without updating the
    AgentRegistry row.  This helper is called at every exit point.

    Concurrency note: under bulk ingest (e.g. the LongMemEval harness
    running 16 worker threads against the same agent), doing a
    SELECT...read-modify-flush on this row inline would pin a
    row-level lock for the entire request lifetime — until the
    enclosing transaction commits at request end, which can be many
    seconds after the embedding/L2/L3 background hooks fire. With many
    concurrent writers, every connection ends up waiting on the same
    row → SQLAlchemy connection pool exhaustion → all writes hang.

    Fix: do an atomic UPDATE on a short-lived session of our own,
    committed immediately. The row lock is held for microseconds, not
    for the duration of create_memory(). Same pattern as F14's
    _bg_embed / _bg_enrich.
    """
    from backend.core.database import _get_session_factory
    from sqlalchemy import update

    if not allowed:
        column = AgentRegistry.denied_requests
    elif "write" in scope:
        column = AgentRegistry.total_writes
    else:
        column = AgentRegistry.total_reads

    async with _get_session_factory()() as own_db:
        async with own_db.begin():
            await own_db.execute(
                update(AgentRegistry)
                .where(AgentRegistry.agent_id == agent_id)
                .values({column: column + 1})
            )


async def evaluate(
    user_id: uuid.UUID,
    request: EvaluationRequest,
    db: AsyncSession,
) -> GatekeeperDecision:
    """
    Evaluate a permission request through the Gatekeeper.

    L1 Evaluation (Rule-Based):
    1. Fetch all active rules for this user, ordered by priority (ascending)
    2. Filter rules that match the agent_id (or are wildcard rules with agent_id=NULL)
    3. Filter rules that match the requested scope
    4. Filter rules that match the namespace (if namespace_filter is set)
    5. Return the first matching rule's action

    L2 Evaluation (JIT Consent):
    - If the matched rule has action='jit', create a ConsentRequest
    - Return 'jit_pending' — the caller must poll for resolution

    Default-Deny:
    - If no rule matches, return DENIED
    """
    import time
    start = time.monotonic()

    agent_id = uuid.UUID(request.agent_id)

    # Fetch all active rules for this user, ordered by priority
    query = (
        select(PermissionRule)
        .where(
            PermissionRule.user_id == user_id,
            PermissionRule.is_active == True,
        )
        .order_by(PermissionRule.priority.asc())
    )
    result = await db.execute(query)
    rules = result.scalars().all()

    # Evaluate rules in priority order
    for rule in rules:
        if not _matches_agent(rule, agent_id):
            continue
        if not _matches_scope(rule, request.scope):
            continue
        if not _matches_namespace(rule, request.namespace):
            continue
        if not _matches_conditions(rule):
            continue

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Rule matched — execute action
        if rule.action == "allow":
            await _increment_agent_stats(agent_id, request.scope, True, db)
            return GatekeeperDecision(
                allowed=True,
                outcome="allowed",
                matched_rule_id=str(rule.rule_id),
                reason=f"Allowed by rule {rule.rule_id} (priority {rule.priority})",
                evaluation_time_ms=elapsed_ms,
            )
        elif rule.action == "deny":
            await _increment_agent_stats(agent_id, request.scope, False, db)
            return GatekeeperDecision(
                allowed=False,
                outcome="denied",
                matched_rule_id=str(rule.rule_id),
                reason=f"Denied by rule {rule.rule_id} (priority {rule.priority})",
                evaluation_time_ms=elapsed_ms,
            )
        elif rule.action == "jit":
            # Create a JIT consent request
            consent = ConsentRequest(
                user_id=user_id,
                agent_id=agent_id,
                requested_scope=request.scope,
                requested_resource=request.resource or request.namespace,
                context={
                    "rule_id": str(rule.rule_id),
                    "priority": rule.priority,
                },
                status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            )
            db.add(consent)
            await db.flush()

            return GatekeeperDecision(
                allowed=False,
                outcome="jit_pending",
                matched_rule_id=str(rule.rule_id),
                reason=f"JIT consent required by rule {rule.rule_id}",
                evaluation_time_ms=elapsed_ms,
                consent_id=str(consent.consent_id),
            )

    # No rule matched — DEFAULT DENY
    elapsed_ms = int((time.monotonic() - start) * 1000)
    await _increment_agent_stats(agent_id, request.scope, False, db)
    return GatekeeperDecision(
        allowed=False,
        outcome="denied",
        matched_rule_id=None,
        reason="No matching rule found. Default-deny posture applied.",
        evaluation_time_ms=elapsed_ms,
    )


# ─── JIT Consent Resolution ──────────────────────────────────────

class ConsentRequestResponse(BaseModel):
    """Response body for a consent request."""
    consent_id: str
    user_id: str
    agent_id: str
    requested_scope: str
    requested_resource: Optional[str]
    context: Optional[dict]
    status: str
    created_at: str
    expires_at: str
    resolved_at: Optional[str]


async def list_consent_requests(
    user_id: uuid.UUID,
    db: AsyncSession,
    status: Optional[str] = None,
    admin_view: bool = False,
) -> list[ConsentRequestResponse]:
    """
    List JIT consent requests.

    Fix KMV-QA-006: The Consent Queue page previously filtered audit logs
    for consent_id which returned nothing because audit logs were empty.
    This function queries the ConsentRequest table directly.

    Admin users see all consent requests across every user's vault.
    Regular users only see their own requests.
    """
    if admin_view:
        query = select(ConsentRequest)
    else:
        query = select(ConsentRequest).where(ConsentRequest.user_id == user_id)
    if status:
        query = query.where(ConsentRequest.status == status)
    query = query.order_by(ConsentRequest.created_at.desc())
    result = await db.execute(query)
    consents = result.scalars().all()
    return [
        ConsentRequestResponse(
            consent_id=str(c.consent_id),
            user_id=str(c.user_id),
            agent_id=str(c.agent_id),
            requested_scope=c.requested_scope,
            requested_resource=c.requested_resource,
            context=c.context,
            status=c.status,
            created_at=c.created_at.isoformat() if c.created_at else "",
            expires_at=c.expires_at.isoformat() if c.expires_at else "",
            resolved_at=c.resolved_at.isoformat() if c.resolved_at else None,
        )
        for c in consents
    ]


async def resolve_consent(
    consent_id: uuid.UUID,
    user_id: uuid.UUID,
    approved: bool,
    db: AsyncSession,
) -> GatekeeperDecision:
    """
    Resolve a JIT consent request.

    The user approves or denies the request. If the request has expired,
    it is automatically denied.
    """
    result = await db.execute(
        select(ConsentRequest).where(
            ConsentRequest.consent_id == consent_id,
            ConsentRequest.user_id == user_id,
        )
    )
    consent = result.scalar_one_or_none()
    if not consent:
        raise ValueError("Consent request not found")

    if consent.status != "pending":
        raise ValueError(f"Consent request already resolved: {consent.status}")

    now = datetime.now(timezone.utc)

    # Check if expired — handle both naive and aware datetimes from SQLite
    expires_at = consent.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and now > expires_at:
        consent.status = "timeout"
        consent.resolved_at = now
        await db.flush()
        return GatekeeperDecision(
            allowed=False,
            outcome="jit_timeout",
            matched_rule_id=None,
            reason="JIT consent request expired",
            consent_id=str(consent.consent_id),
        )

    # Resolve
    consent.status = "approved" if approved else "denied"
    consent.resolved_at = now
    await db.flush()

    if approved:
        return GatekeeperDecision(
            allowed=True,
            outcome="jit_approved",
            matched_rule_id=None,
            reason="JIT consent approved by user",
            consent_id=str(consent.consent_id),
        )
    else:
        return GatekeeperDecision(
            allowed=False,
            outcome="jit_denied",
            matched_rule_id=None,
            reason="JIT consent denied by user",
            consent_id=str(consent.consent_id),
        )


# ─── Rule Matching Helpers ────────────────────────────────────────

def _matches_agent(rule: PermissionRule, agent_id: uuid.UUID) -> bool:
    """Check if a rule applies to the given agent."""
    if rule.agent_id is None:
        return True  # Wildcard rule — applies to all agents
    return str(rule.agent_id) == str(agent_id)


def _matches_scope(rule: PermissionRule, requested_scope: str) -> bool:
    """Check if a rule's scope matches the requested scope."""
    if rule.scope == requested_scope:
        return True
    # Wildcard matching: "admin:*" matches everything
    if rule.scope == "admin:*":
        return True
    # Prefix matching: "memory:*" matches "memory:read", "memory:write", etc.
    if rule.scope.endswith(":*"):
        prefix = rule.scope[:-1]  # "memory:"
        return requested_scope.startswith(prefix)
    return False


def _matches_namespace(rule: PermissionRule, namespace: Optional[str]) -> bool:
    """Check if a rule's namespace filter matches the requested namespace."""
    if not rule.namespace_filter:
        return True  # No filter — matches all namespaces
    if not namespace:
        return True  # No namespace in request — skip filter
    # Simple glob matching
    import fnmatch
    return fnmatch.fnmatch(namespace, rule.namespace_filter)


def _matches_conditions(rule: PermissionRule) -> bool:
    """
    Check if a rule's conditions are met.
    Currently supports: time_window.
    """
    if not rule.conditions:
        return True

    # Time window check
    if "time_window" in rule.conditions:
        tw = rule.conditions["time_window"]
        now = datetime.now(timezone.utc)
        start_hour = tw.get("start_hour", 0)
        end_hour = tw.get("end_hour", 24)
        if not (start_hour <= now.hour < end_hour):
            return False

    return True


# ─── Internal Helpers ─────────────────────────────────────────────

async def _get_rule_for_user(
    rule_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> PermissionRule:
    """Fetch a rule ensuring it belongs to the specified user."""
    result = await db.execute(
        select(PermissionRule).where(
            PermissionRule.rule_id == rule_id,
            PermissionRule.user_id == user_id,
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise ValueError("Permission rule not found")
    return rule


def _to_response(rule: PermissionRule) -> PermissionRuleResponse:
    """Convert a PermissionRule ORM object to a response."""
    return PermissionRuleResponse(
        rule_id=str(rule.rule_id),
        user_id=str(rule.user_id),
        agent_id=str(rule.agent_id) if rule.agent_id else None,
        scope=rule.scope,
        action=rule.action,
        priority=rule.priority,
        namespace_filter=rule.namespace_filter,
        conditions=rule.conditions,
        is_active=rule.is_active,
        created_at=rule.created_at.isoformat() if rule.created_at else "",
        updated_at=rule.updated_at.isoformat() if rule.updated_at else "",
    )
