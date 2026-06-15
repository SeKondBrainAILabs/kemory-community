"""
S9N Memory Vault — MCP (Model Context Protocol) Server

Provides 6 core tools for agent interaction with the Memory Vault:
1. s9nmem_store_memory   — Write a memory to the vault
2. s9nmem_recall_memory  — Read/search memories from the vault
3. s9nmem_delete_memory  — Soft-delete a memory
4. s9nmem_check_access   — Check if an agent has permission for an action
5. s9nmem_list_namespaces — List available namespaces
6. s9nmem_get_context    — Get contextual memories for a conversation

All tools are permission-aware through Gatekeeper integration.

Spec reference: Section 11 (MCP Tools), Appendix C (MCP Tool Schemas)
"""
