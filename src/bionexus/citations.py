"""Citation verification — enforce the "never invent" rule.

A hypothesis may cite a PMID or DOI to ground its rationale. This module
checks that the citation EXISTS (PMID resolvable / DOI indexed) via PubMed
E-utilities, with a local content-addressed cache so repeat runs are free
and offline runs degrade to "check-failed" — never to a false "invalid".

Statuses:
  verified        citation resolves to a real publication
  invalid         checked online, no such publication (hallucination)
  check-failed    offline/timeout — unknown, treated as unverified (no bonus)
  unverified      never checked
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(".data/citations.json")
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

PMID_RE = re.compile(r"(?:pmid[:\s]*)?(\d{5,8})\b", re.I)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"')>]+)\b")


def parse(citation: str) -> tuple[str, str] | None:
    """('pmid', '35377565') or ('doi', '10.1021/...') or None."""
    citation = citation.strip()
    m = DOI_RE.search(citation)
    if m:
        return ("doi", m.group(1).rstrip(".,;"))
    m = PMID_RE.search(citation)
    if m and re.search(r"pmid", citation, re.I):
        return ("pmid", m.group(1))
    if citation.isdigit():
        return ("pmid", citation)
    return None


def _default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        return r.read()


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except Exception:
        return {}


def _save_cache(c: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(c, indent=1))


def verify(citation: str, fetch: callable = _default_fetch) -> dict:
    """Resolve one citation. Returns {status, kind, detail}."""
    parsed = parse(citation)
    if not parsed:
        return {"status": "invalid", "kind": "unparseable",
                "detail": "not a PMID or DOI"}
    kind, value = parsed
    cache = _load_cache()
    key = f"{kind}:{value}"
    if key in cache:
        return cache[key]
    try:
        if kind == "pmid":
            url = (f"{EUTILS}/esummary.fcgi?version=2.0&id={value}"
                   "&db=pubmed&retmode=json")
            data = json.loads(fetch(url))
            rec = data.get("result", {}).get(value)
            if rec and rec.get("title"):
                out = {"status": "verified", "kind": kind,
                       "detail": f"{rec.get('pubdate', '')[:4]} · "
                                 f"{(rec.get('source') or '')[:40]}"}
            else:
                out = {"status": "invalid", "kind": kind,
                       "detail": "PMID not found"}
        else:
            term = urllib.parse.quote(f"{value}[DOI]")
            url = f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&term={term}"
            data = json.loads(fetch(url))
            ids = data.get("esearchresult", {}).get("idlist", [])
            out = ({"status": "verified", "kind": kind,
                    "detail": f"PMID {ids[0]}"} if ids else
                   {"status": "invalid", "kind": kind,
                    "detail": "DOI not indexed"})
    except Exception as exc:
        # network failure is NOT evidence of a fake citation
        return {"status": "check-failed", "kind": kind,
                "detail": str(exc)[:80]}
    if out["status"] != "check-failed":
        cache[key] = out
        _save_cache(cache)
    return out


def verify_many(citations: list[str], fetch=_default_fetch) -> dict[str, dict]:
    return {c: verify(c, fetch) for c in citations if c}
