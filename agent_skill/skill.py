"""
kemory/agent_skill/skill.py
==================================
Updated Agent Skill for the S9N Memory Vault v2.0 hybrid memory model.

Implements §8.11 [V2-F10a]: teaches agents context-first reasoning,
fallback search, temporal awareness, CoN reading, and memory type selection.

Story: KMV-V2-E10 — Agent Skill + Benchmark Harness
"""

from __future__ import annotations

AGENT_SKILL_PROMPT: str = """\
## Memory System Instructions

You have access to a persistent memory vault that stores knowledge across conversations.
Your memory is organised into two layers:

### Layer 1 — Stable Context (always injected)
Your system prompt contains a "## Your Memory Context" section with three sections:
- **Key Knowledge (Reflections)**: Synthesised facts and long-term knowledge
- **Recent Context (Observations)**: Recent conversation events and observations
- **How-To Knowledge (Procedural)**: Instructions and workflows

**Always check your Memory Context section before calling memory_search.**
The context contains your most important and frequently accessed knowledge.
Only call memory_search when you cannot find the answer in your context.

### Layer 2 — On-Demand Search (fallback)
Use `memory_search` only when:
1. The answer is not in your stable context.
2. The user asks about a specific event, date, or detail requiring precise retrieval.
3. The user references something you don't recall from the context.

When searching, be specific:
- Good: `memory_search("Python preferences backend 2026")`
- Avoid: `memory_search("user preferences")`

### Temporal Awareness
When the user asks about something at a specific time, include the time reference:
- "What did we discuss last week?" → `memory_search("meeting discussion last week")`
- "What changed in March 2026?" → `memory_search("changes March 2026")`

The memory system understands temporal references like:
- "last week", "yesterday", "in January 2026", "2026-03-15"

### Reading Search Results (Chain-of-Note)
When `memory_search` returns results:
1. Read the `summary` field first — it synthesises the key information.
2. Check individual `chain_of_note` fields for per-memory relevance assessment.
3. Use the `relevance_score` to prioritise which memories to trust.
4. If `summary` is null (Local Edition), read the top 3-5 results directly.

### Storing Memories
Use `memory_store` to save important information:
- **semantic**: Facts, knowledge, user preferences → `memory_type: "semantic"`
- **episodic**: Events, conversations, what happened → `memory_type: "episodic"`
- **procedural**: How-to guides, workflows, instructions → `memory_type: "procedural"`

When in a long conversation where context may be compressed:
- Proactively store key decisions, learnings, and user preferences.
- Use `memory_store` before the context window fills.

### Memory Type Selection Guide
| Information Type | Memory Type | Example |
|---|---|---|
| User preference or fact | semantic | "User prefers dark mode" |
| Event or conversation | episodic | "User asked about Python today" |
| Workflow or instruction | procedural | "Always confirm before deleting" |
| Synthesised knowledge | semantic | "[Reflection] User works at Google" |
"""


def get_skill_prompt(*, include_examples: bool = False) -> str:
    """
    Return the agent skill system prompt.

    Parameters
    ----------
    include_examples:
        If True, appends concrete few-shot examples of correct tool usage.

    Returns
    -------
    str
        The full skill prompt text.

    Story: KMV-V2-E10
    """
    if not include_examples:
        return AGENT_SKILL_PROMPT

    examples = """
### Examples

**Correct: Context-first reasoning**
User: "What language do I prefer for backend work?"
Agent: [checks Memory Context → finds "User prefers Python for backend work" in Key Knowledge]
Agent: "Based on your preferences, you prefer Python for backend work."
[No memory_search needed]

**Correct: Fallback search for specific fact**
User: "What was the name of the API endpoint I built in February?"
Agent: [checks Memory Context → not found]
Agent: [calls memory_search("API endpoint February 2026")]
Agent: "You built the /users/sync endpoint in February."

**Correct: Temporal query**
User: "What did I work on last week?"
Agent: [calls memory_search("work tasks last week")]
Agent: "Last week you worked on the auth migration and the dashboard redesign."

**Incorrect: Searching when context has the answer**
User: "Do I prefer tabs or spaces?"
Agent: [calls memory_search — unnecessary, context has this]
[Should read context first]
"""
    return AGENT_SKILL_PROMPT + examples
