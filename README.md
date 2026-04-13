# BVS MCP Server

A remote [Model Context Protocol](https://modelcontextprotocol.io) server that lets any MCP-compatible AI client (Claude Desktop, claude.ai, Cursor, etc.) search the **Biblioteca Virtual em Saúde** (BVS) — the largest Latin American / Iberoamerican scientific health literature hub — via its public **iAHx** API.

Exposes Streamable HTTP (the current MCP transport; SSE is deprecated) and is ready to deploy on Railway's free tier.

## Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `search_bvs` | `query`, `database="LILACS"`, `lang="pt"`, `limit=10`, `search_field="tw"` | General search. `database` accepts `LILACS`, `MEDLINE`, `LILACS,MEDLINE`, `IBECS`, `BDENF`. `search_field`: `tw` (all), `ti` (title), `au` (author), `mh` (MeSH). |
| `get_article_details` | `article_url` | Full metadata for an article given its BVS URL. |
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

## Deploy on Railway (free tier)

1. Push this directory to a GitHub repo.
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → pick the repo.
3. Railway auto-detects the `Dockerfile` and `railway.toml`. No env vars are required — Railway injects `PORT`.
4. When the build finishes, open the service → **Settings** → **Networking** → **Generate Domain**. You'll get something like `https://bvs-mcp-production.up.railway.app`.
5. Your MCP endpoint is `https://<your-domain>/mcp`.

Optional CLI deploy:

```bash
npm i -g @railway/cli
railway login
railway init
railway up
```

## Connect from Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "bvs": {
      "type": "http",
      "url": "https://<your-domain>.up.railway.app/mcp"
    }
  }
}
```

Restart Claude Desktop. The `bvs` server should appear with 4 tools.

## Connect from claude.ai (browser)

1. Open **Settings → Integrations** (or **Connectors**) → **Add custom integration**.
2. Name: `BVS`
3. Remote MCP server URL: `https://<your-domain>.up.railway.app/mcp`
4. Authentication: **None**
5. Save and enable the connector in a new chat.

## Example prompts

- *"Search BVS for recent LILACS articles about `dengue` published in Brazil."*
- *"Use the BVS tool to find articles by author `Paulo Buss` in LILACS."*
- *"Find MeSH-indexed articles on `hipertensão arterial` in both LILACS and MEDLINE."*
- *"Show me the full metadata for this BVS article: https://pesquisa.bvsalud.org/portal/resource/pt/biblio-XXXXX"*

## Notes

- No authentication is configured. If you deploy publicly, consider adding a reverse proxy with a token, or switch to Railway's private networking.
- All upstream calls add a 10 s timeout and a desktop `User-Agent` to avoid bot blocking.
- BVS iAHx base: `https://pesquisa.bvsalud.org/portal/`.
