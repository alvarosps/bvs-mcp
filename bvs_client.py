"""Async client for the BVS (Biblioteca Virtual em Saúde) iAHx public API."""
from __future__ import annotations

from typing import Any

import httpx
import xmltodict

BVS_BASE_URL = "https://pesquisa.bvsalud.org/portal/"
DEFAULT_TIMEOUT = 10.0
USER_AGENT = "Mozilla/5.0 BVS-MCP-Server/1.0"


class BVSError(Exception):
    """Raised when the BVS API cannot be reached or returns invalid data."""


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _flatten_text(value: Any) -> str:
    """xmltodict turns <tag>text</tag> into str and <tag attr="x">text</tag> into dict."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        text = value.get("#text", "")
        return text.strip() if isinstance(text, str) else ""
    if isinstance(value, list):
        return " | ".join(filter(None, (_flatten_text(v) for v in value)))
    return str(value)


async def _fetch_xml(params: dict[str, str]) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/xml, text/xml"}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers) as client:
            response = await client.get(BVS_BASE_URL, params=params)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise BVSError(f"BVS API request timed out after {DEFAULT_TIMEOUT}s") from exc
    except httpx.HTTPStatusError as exc:
        raise BVSError(
            f"BVS API returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise BVSError(f"BVS API unreachable: {exc}") from exc

    try:
        return xmltodict.parse(response.text)
    except Exception as exc:  # xmltodict raises ExpatError
        raise BVSError(f"Failed to parse BVS XML response: {exc}") from exc


def _hits_from_parsed(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    root = parsed.get("result") or parsed.get("results") or {}
    if not isinstance(root, dict):
        return []
    hits = root.get("hit") or root.get("hits") or root.get("doc")
    return [h for h in _ensure_list(hits) if isinstance(h, dict)]


def _extract_fields(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _flatten_text(hit.get("ti")),
        "authors": _flatten_text(hit.get("au")),
        "abstract": _flatten_text(hit.get("ab")),
        "pub_date": _flatten_text(hit.get("dp")),
        "database": _flatten_text(hit.get("db")),
        "mesh": _flatten_text(hit.get("mh")),
        "url": _flatten_text(hit.get("ur")),
        "pages": _flatten_text(hit.get("pg")),
        "journal": _flatten_text(hit.get("ta")),
        "language": _flatten_text(hit.get("la")),
        "id": _flatten_text(hit.get("id")),
        "type": _flatten_text(hit.get("type")),
    }


async def search(
    query: str,
    database: str = "LILACS",
    lang: str = "pt",
    limit: int = 10,
    search_field: str = "tw",
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    params = {
        "q": query,
        "filter": f"db:{database}",
        "lang": lang,
        "index": search_field,
        "output": "xml",
        "count": str(limit),
    }
    parsed = await _fetch_xml(params)
    return [_extract_fields(h) for h in _hits_from_parsed(parsed)]


async def fetch_article(article_url: str) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True) as client:
            response = await client.get(article_url, params={"output": "xml"})
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise BVSError(f"BVS article request timed out after {DEFAULT_TIMEOUT}s") from exc
    except httpx.HTTPError as exc:
        raise BVSError(f"Could not fetch article: {exc}") from exc

    try:
        parsed = xmltodict.parse(response.text)
    except Exception as exc:
        raise BVSError(f"Failed to parse article XML: {exc}") from exc

    hits = _hits_from_parsed(parsed)
    if hits:
        return _extract_fields(hits[0])
    # fallback: flatten root
    root = parsed.get("result") or parsed
    if isinstance(root, dict):
        return _extract_fields(root)
    return {}
