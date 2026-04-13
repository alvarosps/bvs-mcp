"""BVS MCP Server — remote MCP over Streamable HTTP for searching the
Biblioteca Virtual em Saúde (iAHx) public API."""
from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import bvs_client
from bvs_client import BVSError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("bvs-mcp")

mcp = FastMCP(
    name="bvs-mcp",
    instructions=(
        "Search the Biblioteca Virtual em Saúde (BVS) scientific literature databases "
        "(LILACS, MEDLINE, IBECS, BDENF) via the public iAHx API."
    ),
)


def _format_results(results: list[dict], header: str) -> str:
    if not results:
        return f"**{header}**\n\nNo results found. Try broader terms or a different database."
    lines = [f"# {header}", f"_{len(results)} result(s)_\n"]
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
            snippet = r["abstract"]
            if len(snippet) > 350:
                snippet = snippet[:350].rstrip() + "…"
            lines.append(f"- **Abstract:** {snippet}")
        if r.get("url"):
            lines.append(f"- **Link:** {r['url']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def search_bvs(
    query: str,
    database: str = "LILACS",
    lang: str = "pt",
    limit: int = 10,
    search_field: str = "tw",
) -> str:
    """Search the BVS (Biblioteca Virtual em Saúde) scientific literature.

    Args:
        query: Search term(s).
        database: "LILACS", "MEDLINE", "LILACS,MEDLINE", "IBECS", or "BDENF".
        lang: Interface language ("pt", "en", "es").
        limit: Max number of results (1-100).
        search_field: "tw" (all fields), "ti" (title), "au" (author), "mh" (MeSH/subject).
    """
    try:
        results = await bvs_client.search(query, database, lang, limit, search_field)
    except BVSError as exc:
        return f"**Error contacting BVS:** {exc}"
    return _format_results(results, f"BVS search: {query!r} in {database}")


@mcp.tool()
async def get_article_details(article_url: str) -> str:
    """Fetch full metadata for a single BVS article by its URL."""
    try:
        data = await bvs_client.fetch_article(article_url)
    except BVSError as exc:
        return f"**Error fetching article:** {exc}"
    if not data or not any(data.values()):
        return f"No metadata could be extracted from {article_url}"

    lines = ["# Article Details"]
    labels = {
        "title": "Title", "authors": "Authors", "journal": "Journal",
        "pub_date": "Publication Date", "database": "Database", "language": "Language",
        "pages": "Pages", "mesh": "MeSH/DeCS", "type": "Type", "id": "ID",
        "url": "URL", "abstract": "Abstract",
    }
    for key, label in labels.items():
        value = data.get(key)
        if value:
            lines.append(f"**{label}:** {value}\n")
    return "\n".join(lines)


@mcp.tool()
async def search_by_author(
    author_name: str, database: str = "LILACS", limit: int = 10
) -> str:
    """Search BVS articles by author name (index=au)."""
    try:
        results = await bvs_client.search(author_name, database, "pt", limit, "au")
    except BVSError as exc:
        return f"**Error contacting BVS:** {exc}"
    return _format_results(results, f"BVS articles by author: {author_name!r}")


@mcp.tool()
async def search_by_subject(
    subject: str, database: str = "LILACS", limit: int = 10
) -> str:
    """Search BVS using MeSH/DeCS controlled vocabulary (index=mh)."""
    try:
        results = await bvs_client.search(subject, database, "pt", limit, "mh")
    except BVSError as exc:
        return f"**Error contacting BVS:** {exc}"
    return _format_results(results, f"BVS articles on subject: {subject!r}")


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app()
app.router.routes.append(Route("/health", health, methods=["GET"]))


TOOLS = ["search_bvs", "get_article_details", "search_by_author", "search_by_subject"]
PORT = int(os.environ.get("PORT", "8080"))
log.info("BVS MCP server starting on 0.0.0.0:%s", PORT)
log.info("MCP endpoint: /mcp (Streamable HTTP)  |  Health: /health")
log.info("Tools: %s", ", ".join(TOOLS))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
