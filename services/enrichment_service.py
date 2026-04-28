"""
S9N Memory Vault — Enrichment Pipeline Service

Implements the async enrichment pipeline that processes memories after creation:
1. Entity Extraction: Extract named entities (people, places, orgs, concepts)
2. Concept Tagging: Tag memories with concept categories
3. Quality Scoring: Score memory quality (0.0-1.0) based on specificity, clarity, utility
4. Graph Integration: Prepare entity/relationship data for Neo4j knowledge graph

The pipeline is designed to be invoked asynchronously after memory creation.
It communicates with the AI backend via the feature bus pattern.

AI Model Routing:
- Entity extraction: llama.cpp / Groq (local-first, per AI model preference)
- Quality scoring: rule-based + LLM fallback
- Graph integration: direct Neo4j write (when available)

Spec reference: Section 7.5 (Enrichment Pipeline), Appendix E (Enrichment Technical Detail)

Stories: F06-US-001 (entity extraction), F06-US-002 (concept tagging),
         F06-US-003 (quality scoring), F06-US-004 (graph integration)
"""

import hashlib
import re
import uuid
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.memory import Memory

# ─── Enrichment Schemas ───────────────────────────────────────────


class EntityType(str, Enum):
    """Types of entities that can be extracted from memory content."""

    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    CONCEPT = "concept"
    TECHNOLOGY = "technology"
    EVENT = "event"
    DATE = "date"
    PRODUCT = "product"


class ExtractedEntity(BaseModel):
    """An entity extracted from memory content."""

    entity_id: str = Field(default="", description="Deterministic hash-based ID")
    name: str
    entity_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0)
    start_pos: int | None = None
    end_pos: int | None = None
    context: str | None = None  # Surrounding text for disambiguation


class ConceptTag(BaseModel):
    """A concept tag applied to a memory."""

    tag: str
    category: str  # e.g., "domain", "topic", "skill", "preference"
    confidence: float = Field(ge=0.0, le=1.0)


class QualityScore(BaseModel):
    """Quality assessment of a memory."""

    overall: float = Field(ge=0.0, le=1.0)
    specificity: float = Field(ge=0.0, le=1.0, description="How specific/detailed is the content")
    clarity: float = Field(ge=0.0, le=1.0, description="How clear and unambiguous is the content")
    utility: float = Field(ge=0.0, le=1.0, description="How useful is this for future recall")
    actionability: float = Field(ge=0.0, le=1.0, description="Can this be acted upon")


class GraphRelationship(BaseModel):
    """A relationship to be added to the knowledge graph."""

    source_entity: str
    relationship_type: str  # e.g., "KNOWS", "USES", "PREFERS", "LOCATED_IN"
    target_entity: str
    properties: dict = Field(default_factory=dict)


class EnrichmentResult(BaseModel):
    """Complete enrichment result for a memory."""

    memory_id: str
    entities: list[ExtractedEntity]
    concept_tags: list[ConceptTag]
    quality_score: QualityScore
    graph_relationships: list[GraphRelationship]
    enrichment_version: str = "1.0"
    processing_time_ms: float | None = None


# ─── Entity Extraction (Rule-Based + Pattern Matching) ────────────
# In production, this would route through the AI backend via feature bus
# to llama.cpp or Groq for LLM-based extraction.
# This implementation provides a deterministic rule-based baseline.

# Common technology terms for pattern matching
TECHNOLOGY_PATTERNS = {
    "python",
    "javascript",
    "typescript",
    "react",
    "vue",
    "angular",
    "node.js",
    "fastapi",
    "django",
    "flask",
    "postgresql",
    "mysql",
    "redis",
    "docker",
    "kubernetes",
    "aws",
    "gcp",
    "azure",
    "machine learning",
    "deep learning",
    "neural network",
    "llm",
    "scikit-learn",
    "tensorflow",
    "pytorch",
    "neo4j",
    "graphql",
    "rest api",
    "microservices",
    "ci/cd",
    "git",
    "linux",
}

# Concept category patterns
CONCEPT_CATEGORIES = {
    "programming": {
        "python",
        "javascript",
        "typescript",
        "code",
        "coding",
        "programming",
        "developer",
        "software",
    },
    "data_science": {
        "data",
        "analysis",
        "machine learning",
        "deep learning",
        "statistics",
        "model",
        "training",
    },
    "infrastructure": {"docker", "kubernetes", "aws", "cloud", "server", "deploy", "ci/cd"},
    "preference": {"prefer", "like", "enjoy", "favorite", "love", "hate", "dislike"},
    "skill": {"learn", "study", "practice", "expert", "beginner", "proficient"},
    "work": {"project", "task", "deadline", "meeting", "team", "client", "sprint"},
    "personal": {"hobby", "family", "health", "exercise", "travel", "food", "music"},
}


def _generate_entity_id(name: str, entity_type: str) -> str:
    """Generate a deterministic entity ID based on name and type."""
    raw = f"{entity_type}:{name.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def extract_entities(content: str) -> list[ExtractedEntity]:
    """
    Extract named entities from memory content.

    Uses rule-based pattern matching as a baseline.
    In production, this would be augmented by LLM-based extraction
    via the AI backend (feature bus → llama.cpp/Groq).

    Returns a list of ExtractedEntity objects with confidence scores.
    """
    entities = []
    content_lower = content.lower()

    # Technology extraction
    for tech in TECHNOLOGY_PATTERNS:
        if tech in content_lower:
            idx = content_lower.index(tech)
            entity = ExtractedEntity(
                name=tech.title() if len(tech) > 3 else tech.upper(),
                entity_type=EntityType.TECHNOLOGY,
                confidence=0.85,
                start_pos=idx,
                end_pos=idx + len(tech),
                context=content[max(0, idx - 30) : idx + len(tech) + 30],
            )
            entity.entity_id = _generate_entity_id(entity.name, entity.entity_type)
            entities.append(entity)

    # Capitalized word extraction (potential proper nouns — people, orgs, places)
    # Pattern: sequences of capitalized words not at sentence start
    cap_pattern = r"(?<=[.!?] )([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)"
    for match in re.finditer(cap_pattern, content):
        name = match.group(1)
        if len(name) > 2 and name.lower() not in {"the", "this", "that", "these", "those"}:
            entity = ExtractedEntity(
                name=name,
                entity_type=EntityType.CONCEPT,  # Default; LLM would classify more precisely
                confidence=0.6,
                start_pos=match.start(),
                end_pos=match.end(),
                context=content[max(0, match.start() - 20) : match.end() + 20],
            )
            entity.entity_id = _generate_entity_id(entity.name, entity.entity_type)
            entities.append(entity)

    # Deduplicate by normalized name (case-insensitive)
    seen = set()
    unique_entities = []
    for e in entities:
        key = e.name.lower().strip()
        if key not in seen:
            seen.add(key)
            unique_entities.append(e)

    return unique_entities


async def tag_concepts(content: str, entities: list[ExtractedEntity]) -> list[ConceptTag]:
    """
    Tag a memory with concept categories based on content and extracted entities.

    Uses keyword matching against concept category patterns.
    In production, augmented by LLM classification.
    """
    tags = []
    content_lower = content.lower()

    for category, keywords in CONCEPT_CATEGORIES.items():
        matching_keywords = [kw for kw in keywords if kw in content_lower]
        if matching_keywords:
            # Confidence based on number of matching keywords
            confidence = min(0.5 + 0.1 * len(matching_keywords), 0.95)
            tags.append(
                ConceptTag(
                    tag=category,
                    category="domain",
                    confidence=confidence,
                )
            )

    # Add tags from entity types
    entity_type_tags = set()
    for entity in entities:
        if entity.entity_type == EntityType.TECHNOLOGY:
            entity_type_tags.add("technology")
        elif entity.entity_type == EntityType.PERSON:
            entity_type_tags.add("people")

    for tag in entity_type_tags:
        tags.append(
            ConceptTag(
                tag=tag,
                category="entity_type",
                confidence=0.8,
            )
        )

    return tags


async def score_quality(
    content: str, entities: list[ExtractedEntity], tags: list[ConceptTag]
) -> QualityScore:
    """
    Score the quality of a memory based on multiple dimensions.

    Scoring rubric:
    - Specificity: longer, more detailed content scores higher
    - Clarity: well-structured content with fewer ambiguous terms scores higher
    - Utility: content with extractable entities and tags scores higher
    - Actionability: content with action verbs or preferences scores higher
    """
    # Specificity: based on content length and detail
    word_count = len(content.split())
    if word_count >= 50:
        specificity = 0.9
    elif word_count >= 20:
        specificity = 0.7
    elif word_count >= 10:
        specificity = 0.5
    else:
        specificity = 0.3

    # Clarity: based on sentence structure
    sentences = re.split(r"[.!?]+", content)
    avg_sentence_len = sum(len(s.split()) for s in sentences if s.strip()) / max(len(sentences), 1)
    if 5 <= avg_sentence_len <= 25:
        clarity = 0.8
    elif avg_sentence_len < 5:
        clarity = 0.5
    else:
        clarity = 0.6

    # Utility: based on entity and tag richness
    entity_score = min(len(entities) * 0.15, 0.6) + 0.3
    tag_score = min(len(tags) * 0.1, 0.4) + 0.3
    utility = (entity_score + tag_score) / 2

    # Actionability: based on action verbs and preference indicators
    action_words = {"should", "must", "need", "want", "prefer", "like", "use", "build", "create", "learn"}
    action_count = sum(1 for word in content.lower().split() if word in action_words)
    actionability = min(0.3 + action_count * 0.1, 0.9)

    # Overall: weighted average
    overall = specificity * 0.25 + clarity * 0.25 + utility * 0.30 + actionability * 0.20

    return QualityScore(
        overall=round(overall, 3),
        specificity=round(specificity, 3),
        clarity=round(clarity, 3),
        utility=round(utility, 3),
        actionability=round(actionability, 3),
    )


async def build_graph_relationships(
    memory_id: str,
    entities: list[ExtractedEntity],
    tags: list[ConceptTag],
) -> list[GraphRelationship]:
    """
    Build knowledge graph relationships from extracted entities and tags.

    Creates relationships between:
    - Memory → Entity (HAS_ENTITY)
    - Entity → Entity (co-occurrence based RELATED_TO)
    - Memory → Concept (TAGGED_WITH)
    """
    relationships = []

    # Memory → Entity relationships
    for entity in entities:
        relationships.append(
            GraphRelationship(
                source_entity=f"memory:{memory_id}",
                relationship_type="HAS_ENTITY",
                target_entity=f"{entity.entity_type.value}:{entity.entity_id}",
                properties={
                    "entity_name": entity.name,
                    "confidence": entity.confidence,
                },
            )
        )

    # Entity → Entity co-occurrence relationships
    for i, e1 in enumerate(entities):
        for e2 in entities[i + 1 :]:
            relationships.append(
                GraphRelationship(
                    source_entity=f"{e1.entity_type.value}:{e1.entity_id}",
                    relationship_type="CO_OCCURS_WITH",
                    target_entity=f"{e2.entity_type.value}:{e2.entity_id}",
                    properties={
                        "memory_id": memory_id,
                        "confidence": min(e1.confidence, e2.confidence),
                    },
                )
            )

    # Memory → Concept tag relationships
    for tag in tags:
        relationships.append(
            GraphRelationship(
                source_entity=f"memory:{memory_id}",
                relationship_type="TAGGED_WITH",
                target_entity=f"concept:{tag.tag}",
                properties={
                    "category": tag.category,
                    "confidence": tag.confidence,
                },
            )
        )

    return relationships


# ─── Main Enrichment Pipeline ─────────────────────────────────────


async def enrich_memory(
    memory_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> EnrichmentResult:
    """
    Run the full enrichment pipeline on a memory.

    Pipeline stages:
    1. Fetch memory content
    2. Extract entities
    3. Tag concepts
    4. Score quality
    5. Build graph relationships
    6. Update memory record with enrichment results

    This is designed to be called asynchronously after memory creation/update.
    """
    import time

    start_time = time.monotonic()

    # Fetch the memory
    result = await db.execute(
        select(Memory).where(
            Memory.memory_id == memory_id,
            Memory.user_id == user_id,
            Memory.invalid_at == None,
        )
    )
    memory = result.scalar_one_or_none()
    if not memory:
        raise ValueError(f"Memory not found: {memory_id}")

    # Stage 1: Entity extraction
    entities = await extract_entities(memory.content)

    # Stage 2: Concept tagging
    tags = await tag_concepts(memory.content, entities)

    # Stage 3: Quality scoring
    quality = await score_quality(memory.content, entities, tags)

    # Stage 4: Graph relationship building
    graph_rels = await build_graph_relationships(str(memory_id), entities, tags)

    # Stage 5: Update memory record
    memory.quality_score = quality.overall
    memory.enrichment_status = "completed"

    # Store enrichment data in metadata
    enrichment_meta = memory.meta or {}
    enrichment_meta["enrichment"] = {
        "entities": [e.model_dump() for e in entities],
        "concept_tags": [t.model_dump() for t in tags],
        "quality_score": quality.model_dump(),
        "entity_count": len(entities),
        "tag_count": len(tags),
        "relationship_count": len(graph_rels),
    }
    memory.meta = enrichment_meta
    await db.flush()

    # KMV-E8 S8.2: Upsert entities to Cognition OS concept graph
    try:
        from backend.services.cognition_bridge import get_cognition_bridge

        bridge = get_cognition_bridge()
        if bridge.enabled and (entities or graph_rels):
            await bridge.upsert_entities(
                memory_id=str(memory_id),
                entities=[e.model_dump() for e in entities],
                relationships=[r.model_dump() for r in graph_rels],
            )
    except Exception as exc:
        logger.debug("cognition_bridge.enrichment_hook_skipped", error=str(exc))

    processing_time = (time.monotonic() - start_time) * 1000

    return EnrichmentResult(
        memory_id=str(memory_id),
        entities=entities,
        concept_tags=tags,
        quality_score=quality,
        graph_relationships=graph_rels,
        processing_time_ms=round(processing_time, 2),
    )


async def enrich_pending_memories(
    user_id: uuid.UUID,
    db: AsyncSession,
    batch_size: int = 10,
) -> list[EnrichmentResult]:
    """
    Process all pending memories for a user.

    This is the batch enrichment entry point, designed to be called
    by a background worker or scheduled task.
    """
    result = await db.execute(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.enrichment_status == "pending",
            Memory.invalid_at == None,
        )
        .limit(batch_size)
    )
    memories = result.scalars().all()

    results = []
    for memory in memories:
        try:
            enrichment = await enrich_memory(memory.memory_id, user_id, db)
            results.append(enrichment)
        except Exception as e:
            # Mark as failed but continue processing
            memory.enrichment_status = "failed"
            memory.meta = {**(memory.meta or {}), "enrichment_error": str(e)}
            await db.flush()

    return results
