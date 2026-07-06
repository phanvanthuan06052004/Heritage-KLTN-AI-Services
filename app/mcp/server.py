"""
Heritage AI Services MCP Server — exposes Knowledge Base tools to Claude.

This module creates a FastMCP server that can be mounted into the
main FastAPI app. Claude Desktop connects to /mcp and receives
tools to search the Heritage knowledge base, retrieve wiki pages,
list categories, etc.

Architecture:
    Claude Desktop -> MCP (HTTPS) -> /mcp endpoint -> Heritage KB tools
                                                     -> PostgreSQL (pgvector)
                                                     -> MinIO (files)

Connection:
    Add to claude_desktop_config.json:
    {
        "mcpServers": {
            "heritage-ai": {
                "url": "https://your-server/mcp",
                "headers": {"Authorization": "Bearer <token>"}
            }
        }
    }
"""

from fastmcp import FastMCP

from app.mcp.resources import register_resources
from app.mcp.tools import register_tools


def create_mcp_server() -> FastMCP:
    """
    Create and configure the Heritage AI MCP server.
    Call this once during app startup.
    """
    mcp = FastMCP(
        "Heritage AI Services",
        instructions=(
            "You are connected to the Heritage AI Knowledge Base — a semantic wiki "
            "for Vietnamese cultural heritage. "
            "Knowledge is organized as interlinked markdown wiki pages compiled from "
            "source documents (PDFs, articles, reports). "
            "Start with `search_wiki` or `read_wiki_index` for most questions; "
            "the wiki already synthesizes information across many sources, "
            "so a single page often answers cross-document questions. "
            "Drill into raw sources via `get_source_outline` and `get_source_pages` "
            "only when you need exact citations or details the wiki has paraphrased. "
            "Cite slugs (wiki) and source IDs (raw) when answering."
        ),
    )

    # Register all tools and resources
    register_tools(mcp)
    register_resources(mcp)

    return mcp
