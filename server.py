"""BVS MCP Server — remote MCP over Streamable HTTP for searching the
Biblioteca Virtual em Saúde (iAHx) public API.

Exposes:
  POST /mcp     — MCP Streamable HTTP endpoint (session-based)
  GET  /health  — liveness probe
"""
from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import bvs_client
from bvs_client import BVSError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("bvs-mcp")

mcp = FastMCP(
    name="bvs-mcp",
    instructions=(
        "Search the Biblioteca Virtual em Saúde (BVS) scientific literature "
        "databases — LILACS, MEDLINE, IBECS, BDENF — via the public iAHx API. "
        "Results include title, authors, journal, abstract and a stable BVS link."
    ),
)


def _truncate(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _format_results(results: list[dict], num_found: int, header: str) -> str:
    if not results:
        return (
            f"**{header}**\n\nNo results found. "
            "Try broader terms, a different database, or search_field='tw'."
        )
    lines = [
        f"# {header}",
        f"_Showing {len(results)} of {num_found} match(es)._\n",
    ]
    for i, r in enumerate(results, 1):
        title = r.get("title") or "(untitled)"
        lines.append(f"## {i}. {title}")
        if r.get("authors"):
            lines.append(f"- **Authors:** {r['authors']}")
        if r.get("journal"):
            lines.append(f"- **Journal:** {r['journal']}")
        if r.get("pub_date"):
            lines.append(f"- **Date:** {r['pub_date']}")
        if r.get("database"):
            lines.append(f"- **DB:** {r['database']}")
        if r.get("language"):
            lines.append(f"- **Lang:** {r['language']}")
        if r.get("abstract"):
            lines.append(f"- **Abstract:** {_truncate(r['abstract'], 400)}")
        if r.get("resource_url"):
            lines.append(f"- **BVS:** {r['resource_url']}")
        if r.get("url") and r.get("url") != r.get("resource_url"):
            lines.append(f"- **Fulltext:** {r['url']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def search_bvs(
    query: str,
    database: str = "LILACS",
    lang: str = "pt",
    limit: int = 10,
    search_field: str = "tw",
    offset: int = 0,
) -> str:
    """Search the BVS (Biblioteca Virtual em Saúde) scientific literature.

    Supports boolean operators (AND, OR, AND NOT), phrase quotes ("..."),
    parentheses for grouping, and per-field syntax like `ti:(cancer) AND au:(Souza)`
    when `search_field='tw'`. For multi-database queries pass a comma list, e.g.
    `database='LILACS,MEDLINE'`.

    Args:
        query: Search expression.
        database: Comma-separated list, any of 'LILACS', 'MEDLINE', 'IBECS', 'BDENF'.
        lang: Interface language — 'pt', 'en', or 'es'.
        limit: Max results per page (1-100).
        search_field: 'tw' (all fields), 'ti' (title), 'au' (author), 'mh' (MeSH/DeCS).
        offset: Pagination offset (number of results to skip).
    """
    try:
        num_found, results = await bvs_client.search(
            query, database, lang, limit, search_field, offset
        )
    except BVSError as exc:
        return f"**Error contacting BVS:** {exc}"
    return _format_results(
        results, num_found, f"BVS search: {query!r} in {database}"
    )


@mcp.tool()
async def get_article_details(article_url: str) -> str:
    """Fetch full metadata for a single BVS article.

    Args:
        article_url: Either a BVS resource URL (…/resource/pt/biblio-XXXXX)
                     or a raw id such as 'biblio-1649387'.
    """
    try:
        data = await bvs_client.fetch_article(article_url)
    except BVSError as exc:
        return f"**Error fetching article:** {exc}"
    if not data:
        return f"No article found for {article_url!r}."

    labels = [
        ("title", "Title"), ("authors", "Authors"), ("journal", "Journal"),
        ("pub_date", "Publication Date"), ("year", "Year"),
        ("database", "Database"), ("language", "Language"),
        ("pages", "Pages"), ("mesh", "MeSH/DeCS"), ("type", "Type"),
        ("id", "ID"), ("resource_url", "BVS Link"), ("url", "Full Text"),
        ("abstract", "Abstract"),
    ]
    lines = ["# Article Details\n"]
    for key, label in labels:
        value = data.get(key)
        if value:
            lines.append(f"**{label}:** {value}\n")
    return "\n".join(lines)


@mcp.tool()
async def search_by_author(
    author_name: str, database: str = "LILACS", limit: int = 10
) -> str:
    """Search BVS articles by author name (Solr field `au`)."""
    try:
        num_found, results = await bvs_client.search(
            author_name, database, "pt", limit, "au"
        )
    except BVSError as exc:
        return f"**Error contacting BVS:** {exc}"
    return _format_results(
        results, num_found, f"BVS articles by author: {author_name!r}"
    )


@mcp.tool()
async def search_by_subject(
    subject: str, database: str = "LILACS", limit: int = 10
) -> str:
    """Search BVS using MeSH/DeCS controlled-vocabulary subjects (Solr field `mh`)."""
    try:
        num_found, results = await bvs_client.search(
            subject, database, "pt", limit, "mh"
        )
    except BVSError as exc:
        return f"**Error contacting BVS:** {exc}"
    return _format_results(
        results, num_found, f"BVS articles on subject: {subject!r}"
    )


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# FastMCP builds a Starlette app whose lifespan already runs the MCP session
# manager. We just append the /health route before uvicorn picks it up.
app = mcp.streamable_http_app()
app.router.routes.append(Route("/health", health, methods=["GET"]))


TOOLS = ["search_bvs", "get_article_details", "search_by_author", "search_by_subject"]
PORT = int(os.environ.get("PORT", "8080"))
log.info("BVS MCP server ready — binding to 0.0.0.0:%s", PORT)
log.info("MCP endpoint: POST /mcp  (Streamable HTTP)")
log.info("Health:       GET  /health")
log.info("Tools:        %s", ", ".join(TOOLS))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
