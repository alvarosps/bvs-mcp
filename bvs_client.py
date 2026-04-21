"""Async client for the BVS (Biblioteca Virtual em Saúde) iAHx public search.

The portal at pesquisa.bvsalud.org is Solr-backed and emits Solr XML
(<response><result><doc><str name='...'>…</str><arr name='…'>…</arr></doc>…).
We parse by the `name` attribute rather than tag name.

The endpoint sits behind a Bunny Shield anti-bot that fingerprints the TLS
handshake (JA3). Plain `httpx`/`requests` are blocked with HTTP 403 from
datacenter IPs, so we use `curl_cffi` which impersonates Chrome's TLS stack.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException as CurlRequestException
from curl_cffi.requests.exceptions import Timeout as CurlTimeout
from lxml import etree as LET

BVS_BASE_URL = "https://pesquisa.bvsalud.org/portal/"
DEFAULT_TIMEOUT = 20.0
IMPERSONATE = "chrome131"

BROWSER_HEADERS = {
    "Accept": "application/xml,text/xml,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8,es;q=0.7",
    "Referer": "https://pesquisa.bvsalud.org/portal/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

SEARCH_FIELDS = {"tw", "ti", "au", "mh"}
KNOWN_DATABASES = {"LILACS", "MEDLINE", "IBECS", "BDENF"}

log = logging.getLogger(__name__)

# Shared session for cookie persistence — Bunny Shield issues a bypass cookie
# after the first clean TLS/header pass; keeping it across requests avoids
# re-challenging on every call.
_session: AsyncSession | None = None


class BVSError(Exception):
    """Raised when the BVS API is unreachable or returns invalid data."""


def _is_challenge(body: str) -> bool:
    head = body.lstrip()[:400].lower()
    return "bunny-shield" in head or "establishing a secure connection" in head


def _get_session() -> AsyncSession:
    global _session
    if _session is None:
        _session = AsyncSession(
            impersonate=IMPERSONATE,
            headers=BROWSER_HEADERS,
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=True,
        )
    return _session


async def _fetch_xml_text(params: dict[str, str]) -> str:
    session = _get_session()
    try:
        response = await session.get(BVS_BASE_URL, params=params)
    except CurlTimeout as exc:
        raise BVSError(f"BVS API request timed out after {DEFAULT_TIMEOUT}s") from exc
    except CurlRequestException as exc:
        raise BVSError(f"BVS API unreachable: {exc}") from exc

    if response.status_code >= 400:
        raise BVSError(f"BVS API returned HTTP {response.status_code}")

    text = response.text
    if _is_challenge(text):
        raise BVSError(
            "BVS returned an anti-bot challenge page (Bunny Shield). "
            "The server IP may be blocked; retry later or contact BIREME for API access."
        )
    return text


_XML_ILLEGAL_CHARS = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F]"
)
_BARE_AMP = re.compile(r"&(?!#?\w{1,10};)")


def _parse_doc(doc: LET._Element) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for child in doc:
        if not isinstance(child.tag, str):
            continue  # skip comments / processing instructions
        name = child.get("name")
        if not name:
            continue
        tag = child.tag
        if tag == "arr":
            out[name] = [c.text for c in child if c.text is not None]
        elif tag == "bool":
            out[name] = (child.text or "").lower() == "true"
        elif tag in {"int", "long"}:
            try:
                out[name] = int(child.text) if child.text else None
            except ValueError:
                out[name] = child.text
        else:
            out[name] = child.text
    return out


def _parse_response(xml_text: str) -> tuple[int, list[dict[str, Any]]]:
    sanitized = _XML_ILLEGAL_CHARS.sub("", xml_text)
    sanitized = _BARE_AMP.sub("&amp;", sanitized)
    parser = LET.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    try:
        root = LET.fromstring(sanitized.encode("utf-8"), parser=parser)
    except LET.XMLSyntaxError as exc:  # pragma: no cover — recover=True rarely raises
        raise BVSError(f"Failed to parse BVS XML: {exc}") from exc
    if root is None:
        raise BVSError("BVS returned an empty or unparseable response")

    result_el = root.find("./result[@name='response']")
    if result_el is None:
        result_el = root.find("./result")
    if result_el is None:
        return 0, []
    try:
        num_found = int(result_el.get("numFound", "0"))
    except ValueError:
        num_found = 0
    docs = [_parse_doc(d) for d in result_el.findall("./doc")]
    return num_found, docs


def _friendly(doc: dict[str, Any]) -> dict[str, Any]:
    def first(val: Any) -> str:
        if isinstance(val, list):
            return val[0] if val else ""
        return val or ""

    def join(val: Any, sep: str = "; ") -> str:
        if isinstance(val, list):
            return sep.join(v for v in val if v)
        return val or ""

    article_id = first(doc.get("id"))
    url = first(doc.get("ur"))
    # prefer a stable resource URL when we have the id
    resource_url = (
        f"https://pesquisa.bvsalud.org/portal/resource/pt/{article_id}"
        if article_id else url
    )
    return {
        "id": article_id,
        "title": first(doc.get("ti")),
        "authors": join(doc.get("au")),
        "abstract": first(doc.get("ab")),
        "pub_date": first(doc.get("da")) or first(doc.get("dp")),
        "year": first(doc.get("publication_year")) or first(doc.get("da"))[:4],
        "database": join(doc.get("db")),
        "mesh": join(doc.get("mh")),
        "url": url,
        "resource_url": resource_url,
        "pages": first(doc.get("pg")),
        "journal": first(doc.get("ta")) or first(doc.get("fo")),
        "language": join(doc.get("la"), sep=", "),
        "type": join(doc.get("type"), sep=", "),
    }


SCOPES = {"advanced", "simple"}


def _db_params(database: str, scope: str = "advanced") -> dict[str, str]:
    """Build the DB filter query for BVS.

    Two scopes map to two different portal query modes:

    * `scope="advanced"` (default) — uses `fq=db:X` (Solr native). Matches the
      portal's advanced-search URL (`where=X → fq=db:X`). Returns all instances
      (regional, harvest, etc.). Required for multi-DB OR. Example:
      `autism nursing` in LILACS → 87 matches.

    * `scope="simple"` — uses `filter=db:X`. Reproduces the portal's simple
      search box, which silently adds `instance:lilacsplus` (curated subset).
      Only supports a single database. Example: `autism nursing` in LILACS
      → 63 matches.
    """
    if scope not in SCOPES:
        raise BVSError(
            f"scope must be one of {sorted(SCOPES)}, got {scope!r}"
        )
    parts = [p.strip() for p in database.split(",") if p.strip()]
    if not parts:
        raise BVSError("database must not be empty")
    if scope == "simple":
        if len(parts) > 1:
            raise BVSError(
                "scope='simple' only supports a single database. "
                "Use scope='advanced' for multi-database searches."
            )
        return {"filter": f"db:{parts[0]}"}
    if len(parts) == 1:
        return {"fq": f"db:{parts[0]}"}
    return {"fq": "db:(" + " OR ".join(parts) + ")"}


def build_params(
    query: str,
    database: str = "LILACS",
    lang: str = "pt",
    limit: int = 10,
    search_field: str = "tw",
    offset: int = 0,
    scope: str = "advanced",
) -> dict[str, str]:
    """Pure builder for the BVS request params. No network. Raises BVSError on
    invalid input so preview and search share the same validation."""
    if not query or not query.strip():
        raise BVSError("query must not be empty")
    if search_field not in SEARCH_FIELDS:
        raise BVSError(
            f"search_field must be one of {sorted(SEARCH_FIELDS)}, got {search_field!r}"
        )
    if lang not in {"pt", "en", "es"}:
        raise BVSError(f"lang must be 'pt', 'en', or 'es'; got {lang!r}")
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    q = query if search_field == "tw" else f"{search_field}:({query})"
    params: dict[str, str] = {
        "q": q,
        "lang": lang,
        "output": "xml",
        "count": str(limit),
        **_db_params(database, scope),
    }
    if offset:
        params["start"] = str(offset)
    return params


def preview_url(params: dict[str, str]) -> str:
    """Assemble the human-readable URL that `search` would hit."""
    import urllib.parse
    return f"{BVS_BASE_URL}?{urllib.parse.urlencode(params)}"


async def search(
    query: str,
    database: str = "LILACS",
    lang: str = "pt",
    limit: int = 10,
    search_field: str = "tw",
    offset: int = 0,
    scope: str = "advanced",
) -> tuple[int, list[dict[str, Any]]]:
    params = build_params(
        query, database, lang, limit, search_field, offset, scope
    )
    xml_text = await _fetch_xml_text(params)
    num_found, docs = _parse_response(xml_text)
    return num_found, [_friendly(d) for d in docs]


async def fetch_article(article_url_or_id: str) -> dict[str, Any]:
    """Look up a single article by BVS id (e.g. 'biblio-1234567') or resource URL."""
    raw = (article_url_or_id or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")
    identifier = raw.rsplit("/", 1)[-1]
    if not identifier:
        raise BVSError("Could not extract an id from the URL")
    params = {
        "q": f"id:{identifier}",
        "output": "xml",
        "count": "1",
        "lang": "pt",
    }
    xml_text = await _fetch_xml_text(params)
    _, docs = _parse_response(xml_text)
    if not docs:
        return {}
    return _friendly(docs[0])
