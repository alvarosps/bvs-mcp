# BVS MCP Server

A remote [Model Context Protocol](https://modelcontextprotocol.io) server that lets any MCP-compatible AI client (Claude Desktop, claude.ai, Cursor, etc.) search the **Biblioteca Virtual em Saúde** (BVS) — the largest Latin American / Iberoamerican scientific health literature hub — via its public **iAHx** API.

Exposes Streamable HTTP (the current MCP transport; SSE is deprecated).

## Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `search_bvs` | `query`, `database="LILACS"`, `lang="pt"`, `limit=10`, `search_field="tw"`, `offset=0` | General search. `database` accepts comma-separated list of `LILACS`, `MEDLINE`, `IBECS`, `BDENF`. `search_field`: `tw` (all), `ti` (title), `au` (author), `mh` (MeSH). Supports boolean operators `AND`/`OR`/`AND NOT`, phrase quotes and parentheses. |
| `get_article_details` | `article_url` | Full metadata for an article given its BVS URL or id (`biblio-XXXXX`). |
| `search_by_author` | `author_name`, `database="LILACS"`, `limit=10` | Shortcut for author search (`index=au`). |
| `search_by_subject` | `subject`, `database="LILACS"`, `limit=10` | Shortcut for controlled-vocabulary search (MeSH/DeCS, `index=mh`). |

All tools return Markdown-formatted text.

## Endpoints

- `POST /mcp` — Streamable HTTP MCP endpoint
- `GET /health` — liveness probe → `{"status":"ok"}`

## Local development

```bash
pip install -r requirements.txt
python server.py
# server on http://localhost:8080
curl http://localhost:8080/health
```

## Example prompts

- *"Search BVS for recent LILACS articles about `dengue` published in Brazil."*
- *"Use the BVS tool to find articles by author `Paulo Buss` in LILACS."*
- *"Find MeSH-indexed articles on `hipertensão arterial` in both LILACS and MEDLINE."*
- *"Show me the full metadata for this BVS article: https://pesquisa.bvsalud.org/portal/resource/pt/biblio-XXXXX"*

## Notes

- No authentication is configured. If exposed publicly, consider a reverse proxy with a token or private networking.
- All upstream calls use a 10 s timeout and a realistic browser `User-Agent` to get past the Bunny Shield anti-bot challenge on `pesquisa.bvsalud.org`.
- XML from BVS is occasionally malformed; the client parses with `lxml` in recovery mode and sanitizes control characters and bare `&` entities.
- BVS iAHx base: `https://pesquisa.bvsalud.org/portal/`.
