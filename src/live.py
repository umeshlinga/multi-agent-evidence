"""Live retrieval from NCBI E-utilities (ClinVar + PubMed).

Used by the Retriever when a variant is outside Build 1's local
universe — the same live-evidence situation as Build 1's app. Live
records are context from after the 2024-01 freeze; they never count
toward Build 1's gate.

Failures are returned as (None, error_string) so the caller logs them;
this module never fabricates a record.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UA = {"User-Agent": "multi-agent-evidence/1.0 (research; multi-agent evaluation)"}
_PAUSE = 0.4  # NCBI asks for <=3 requests/second without an API key


def _get(path: str, params: dict) -> dict:
    url = f"{EUTILS}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def clinvar_live(name: str, gene: str) -> tuple[str | None, str | None]:
    """Current ClinVar record for a variant name. Returns (detail, error)."""
    try:
        time.sleep(_PAUSE)
        s = _get("esearch.fcgi", {"db": "clinvar", "term": name, "retmode": "json", "retmax": 3})
        ids = s.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return None, None  # genuinely no live record — not an error
        time.sleep(_PAUSE)
        summ = _get("esummary.fcgi", {"db": "clinvar", "id": ",".join(ids), "retmode": "json"})
        result = summ.get("result", {})
        for uid in result.get("uids", []):
            doc = result[uid]
            # Current ClinVar esummary carries the germline classification;
            # older shapes used clinical_significance. Read both.
            cls = doc.get("germline_classification") or doc.get("clinical_significance") or {}
            sig = cls.get("description") or "not stated"
            detail = (f"Live ClinVar record for {doc.get('title', name)}: current clinical "
                      f"significance: {sig}; review status: {cls.get('review_status') or 'not stated'}; "
                      f"last evaluated: {cls.get('last_evaluated') or 'not stated'}")
            return detail, None
        return None, None
    except Exception as e:  # network/parse failure — reported, not hidden
        return None, f"{type(e).__name__}: {e}"


def pubmed_live(gene: str, variant_token: str) -> tuple[str | None, str | None]:
    """Literature count for gene + variant. Returns (detail, error)."""
    try:
        term = f"{gene} AND {variant_token}"
        time.sleep(_PAUSE)
        s = _get("esearch.fcgi", {"db": "pubmed", "term": term, "retmode": "json", "retmax": 0})
        count = int(s.get("esearchresult", {}).get("count", 0))
        return (f"Live PubMed search '{term}': {count} article(s) indexed", None)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
