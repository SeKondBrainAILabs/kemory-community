from backend.mcp.tools import HANDLERS, TOOL_DEFINITIONS


def test_only_canonical_kemory_tools_are_advertised():
    names = [tool.name for tool in TOOL_DEFINITIONS]

    assert names
    assert len(names) == len(set(names))
    assert all(name.startswith("kemory_") for name in names)
    assert "kemory_get_session_context" in names
    assert "kemory_rehydrate_session_sources" in names


def test_tool_descriptions_match_the_community_runtime():
    descriptions = "\n".join(tool.description for tool in TOOL_DEFINITIONS)

    assert "local single-user vault" in descriptions
    assert "Postgres/pgvector" in descriptions
    assert "FalkorDB" not in descriptions
    assert "private/team/org" not in descriptions


def test_legacy_names_remain_dispatch_aliases():
    assert HANDLERS["s9nmem_get_context"] is HANDLERS["kemory_get_context"]
    assert HANDLERS["s9nmem_store_memory"] is HANDLERS["kemory_store_memory"]
    assert "kemory_get_session_context" in HANDLERS
    assert "kemory_rehydrate_session_sources" in HANDLERS
