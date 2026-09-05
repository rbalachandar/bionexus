"""PubMed adapter — literature search via NCBI E-utilities.

Lightweight adapter for PubMed article search and abstract retrieval,
using the NCBI E-utilities API (stdlib only, no Biopython dependency).
Set NCBI_API_KEY env for higher rate limits (10 req/s vs 3 req/s).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedAdapter:
    """Adapter for NCBI PubMed search and abstract retrieval."""

    name = "pubmed"

    def __init__(self, api_key: str | None = None, tool: str = "bionexus",
                 email: str = "", delay_secs: float = 0.5):
        self.api_key = api_key or os.environ.get("NCBI_API_KEY", "")
        self.tool = tool
        self.email = email
        self._delay = delay_secs if not self.api_key else max(delay_secs, 0.12)
        self._last_call = 0.0

    def _get(self, endpoint: str, params: dict[str, str]) -> Any:
        elapsed = time.time() - self._last_call
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        params.update({"tool": self.tool, "db": "pubmed"})
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{EUTILS}/{endpoint}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        self._last_call = time.time()
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return resp.read()

    def search(self, query: str, max_results: int = 10,
               sort: str = "relevance") -> list[str]:
        """Search PubMed and return a list of PMID strings."""
        params = {
            "term": query, "retmax": str(max_results),
            "retmode": "json", "sort": sort,
        }
        raw = self._get("esearch.fcgi", params)
        data = json.loads(raw)
        return data.get("esearchresult", {}).get("idlist", [])

    def fetch_abstracts(self, pmids: list[str]) -> list[dict[str, str]]:
        """Fetch titles and abstracts for a list of PMIDs."""
        if not pmids:
            return []
        params = {
            "id": ",".join(pmids), "rettype": "abstract", "retmode": "json",
        }
        raw = self._get("efetch.fcgi", params)
        data = json.loads(raw)
        articles = []
        for pmid, item in data.get("result", {}).items():
            if pmid == "uids":
                continue
            articles.append({
                "pmid": pmid,
                "title": item.get("title", ""),
                "abstract": item.get("abstract", "")[:2000],
                "journal": item.get("source", ""),
                "pub_date": item.get("pubdate", ""),
                "authors": ", ".join(a.get("name", "") for a in item.get("authors", [])[:5]),
            })
        return articles

    def search_and_fetch(self, query: str, max_results: int = 10) -> list[dict[str, str]]:
        """Search + fetch in one call."""
        pmids = self.search(query, max_results)
        if not pmids:
            return []
        return self.fetch_abstracts(pmids)
