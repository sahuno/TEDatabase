# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: Search PubMed for new LINE-1 somatic insertion papers and save pending metadata

import argparse
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"

QUERIES = [
    (
        '("LINE-1" OR "L1 retrotransposon" OR "L1HS") AND '
        '("somatic insertion" OR "somatic retrotransposition") AND "human"[organism]'
    ),
    (
        '("retrotransposon" OR "transposable element") AND "somatic" AND '
        '("cancer" OR "tumor") AND ("LINE-1" OR "L1")'
    ),
    '"de novo L1 insertion" AND human',
    '"L1 mobilization" AND somatic AND human',
    (
        '("ATLAS-seq" OR "RC-seq" OR "mTRAP" OR "L1-seq" OR "LEAP-seq") '
        'AND "somatic" AND "human"'
    ),
]

PREFILTER_TERMS = {"l1", "line-1", "retrotranspos"}
BATCH_SIZE = 200


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(log_dir: Path, script_name: str) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{script_name}_{timestamp}.log"

    logger = logging.getLogger(script_name)
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------------
# Rate-limited HTTP session
# ---------------------------------------------------------------------------

class RateLimitedSession:
    """Wraps requests.Session with a minimum inter-request delay."""

    def __init__(self, min_interval: float):
        self._session = requests.Session()
        self._min_interval = min_interval
        self._last_call: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    @retry(
        retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def get(self, url: str, **kwargs) -> requests.Response:
        self._throttle()
        resp = self._session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp


# ---------------------------------------------------------------------------
# NCBI helpers
# ---------------------------------------------------------------------------

def esearch(session: RateLimitedSession, query: str, api_key: str | None,
            lookback_days: int, logger: logging.Logger) -> list[str]:
    """Run a single esearch query and return a list of PMIDs."""
    params: dict = {
        "db": "pubmed",
        "term": query,
        "retmax": 500,
        "retmode": "xml",
        "datetype": "edat",
        "reldate": lookback_days,
        "usehistory": "n",
    }
    if api_key:
        params["api_key"] = api_key

    resp = session.get(ESEARCH_URL, params=params)
    root = ET.fromstring(resp.text)
    pmids = [el.text for el in root.findall(".//Id") if el.text]
    logger.debug("Query returned %d PMIDs: %.80s...", len(pmids), query)
    return pmids


def efetch_batch(session: RateLimitedSession, pmids: list[str],
                 api_key: str | None, logger: logging.Logger) -> list[dict]:
    """Fetch PubMed metadata for a list of PMIDs (one batch)."""
    params: dict = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "xml",
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key

    resp = session.get(EFETCH_URL, params=params)
    return parse_pubmed_xml(resp.text, logger)


def parse_pubmed_xml(xml_text: str, logger: logging.Logger) -> list[dict]:
    """Parse PubMed XML and return list of metadata dicts."""
    records: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("XML parse error: %s", exc)
        return records

    for article in root.findall(".//PubmedArticle"):
        rec = _parse_article(article, logger)
        if rec:
            records.append(rec)
    return records


def _parse_article(article: ET.Element, logger: logging.Logger) -> dict | None:
    """Extract metadata from a single PubmedArticle element."""
    try:
        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else None
        if not pmid:
            return None

        # Title
        title_el = article.find(".//ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        # Abstract
        abstract_parts = article.findall(".//AbstractText")
        abstract = " ".join(
            "".join(p.itertext()).strip() for p in abstract_parts if p is not None
        ).strip()

        # Authors
        authors: list[str] = []
        for author in article.findall(".//Author"):
            last = author.findtext("LastName", "")
            fore = author.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {fore}".strip())

        # Journal
        journal = article.findtext(".//Journal/Title", "") or article.findtext(
            ".//Journal/ISOAbbreviation", ""
        )

        # Year
        year_el = article.find(".//PubDate/Year")
        if year_el is None:
            year_el = article.find(".//PubDate/MedlineDate")
        year = year_el.text[:4] if year_el is not None and year_el.text else None

        # DOI
        doi = None
        for id_el in article.findall(".//ArticleId"):
            if id_el.get("IdType") == "doi":
                doi = id_el.text.strip() if id_el.text else None
                break

        # PMCID
        pmcid = None
        for id_el in article.findall(".//ArticleId"):
            if id_el.get("IdType") == "pmc":
                pmcid = id_el.text.strip() if id_el.text else None
                break

        is_oa = pmcid is not None  # Conservative proxy; Unpaywall refines this

        return {
            "pmid": pmid,
            "pmcid": pmcid,
            "doi": doi,
            "title": title,
            "authors": authors,
            "journal": journal,
            "year": year,
            "abstract": abstract,
            "is_oa": is_oa,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse article element: %s", exc)
        return None


def prefilter(records: list[dict], logger: logging.Logger) -> list[dict]:
    """Discard records whose abstract contains none of the prefilter terms."""
    kept: list[dict] = []
    dropped = 0
    for rec in records:
        text = (rec.get("abstract") or "").lower()
        if any(term in text for term in PREFILTER_TERMS):
            kept.append(rec)
        else:
            dropped += 1
    logger.info(
        "Pre-filter: kept %d / %d records (%d dropped — no L1/LINE-1/retrotranspos in abstract)",
        len(kept),
        len(records),
        dropped,
    )
    return kept


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search PubMed for new LINE-1 somatic insertion papers."
    )
    parser.add_argument(
        "--ncbi_api_key",
        default=os.environ.get("NCBI_API_KEY"),
        help="NCBI API key (or set NCBI_API_KEY env var).",
    )
    parser.add_argument(
        "--lookback_days",
        type=int,
        default=14,
        help="Number of days to look back for new papers (default: 14).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/papers_pending.json"),
        help="Output JSON path (default: data/raw/papers_pending.json).",
    )
    parser.add_argument(
        "--max_papers",
        type=int,
        default=None,
        help="Cap number of new papers to process (useful for test runs, e.g. --max_papers 5).",
    )
    parser.add_argument(
        "--log_dir",
        type=Path,
        default=Path("logs"),
        help="Directory for log files (default: logs).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_name = Path(__file__).stem
    logger = setup_logging(args.log_dir, script_name)

    # Session header
    logger.info("=== SESSION START: %s ===", script_name)
    logger.info("Date/time    : %s", datetime.now().isoformat())
    logger.info("Python       : %s", sys.version.split()[0])
    logger.info("Working dir  : %s", Path.cwd())
    logger.info("Log dir      : %s", args.log_dir.resolve())
    logger.info("NCBI API key : %s", "present" if args.ncbi_api_key else "absent (2 req/s)")
    logger.info("Lookback days: %d", args.lookback_days)
    logger.info("Output path  : %s", args.output.resolve())

    # Rate limit: 8 req/s with key, 2 req/s without
    min_interval = 1 / 8 if args.ncbi_api_key else 1 / 2
    session = RateLimitedSession(min_interval)

    # Load seen PMIDs
    seen_path = Path("data/raw/pmids_seen.txt")
    if seen_path.exists():
        seen_pmids: set[str] = {
            line.strip() for line in seen_path.read_text().splitlines() if line.strip()
        }
    else:
        seen_pmids = set()
    logger.info("Loaded %d previously seen PMIDs from %s", len(seen_pmids), seen_path)

    # Run esearch across all queries
    all_pmids: set[str] = set()
    for idx, query in enumerate(QUERIES, start=1):
        logger.info("Running query %d/%d: %.100s...", idx, len(QUERIES), query)
        try:
            pmids = esearch(session, query, args.ncbi_api_key, args.lookback_days, logger)
            logger.info("  -> %d PMIDs returned", len(pmids))
            all_pmids.update(pmids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Query %d failed: %s", idx, exc)

    logger.info("Total unique PMIDs across all queries: %d", len(all_pmids))

    # Filter to new PMIDs only
    new_pmids = sorted(all_pmids - seen_pmids)
    logger.info(
        "New PMIDs (not in pmids_seen.txt): %d (out of %d total)",
        len(new_pmids),
        len(all_pmids),
    )

    if args.max_papers and len(new_pmids) > args.max_papers:
        logger.info("--max_papers %d: capping from %d PMIDs", args.max_papers, len(new_pmids))
        new_pmids = new_pmids[: args.max_papers]

    if not new_pmids:
        logger.info("No new PMIDs found. Nothing to fetch.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps([], indent=2))
        logger.info("Saved empty list to %s", args.output)
        logger.info("=== DONE: %s completed successfully ===", script_name)
        return

    # Fetch metadata in batches
    all_records: list[dict] = []
    n_batches = (len(new_pmids) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_idx in range(n_batches):
        batch = new_pmids[batch_idx * BATCH_SIZE: (batch_idx + 1) * BATCH_SIZE]
        logger.info(
            "Fetching metadata batch %d/%d (%d PMIDs)...",
            batch_idx + 1,
            n_batches,
            len(batch),
        )
        try:
            records = efetch_batch(session, batch, args.ncbi_api_key, logger)
            logger.info("  -> Parsed %d records from batch", len(records))
            all_records.extend(records)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Batch %d efetch failed: %s", batch_idx + 1, exc)

    logger.info(
        "Fetched metadata: %d records (from %d new PMIDs; %d failed to parse)",
        len(all_records),
        len(new_pmids),
        len(new_pmids) - len(all_records),
    )

    # Pre-filter by abstract content
    filtered_records = prefilter(all_records, logger)

    # Save output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(filtered_records, indent=2, ensure_ascii=False))
    logger.info(
        "Saved %d records to %s (%.1f KB)",
        len(filtered_records),
        args.output.resolve(),
        args.output.stat().st_size / 1024,
    )

    logger.info("=== DONE: %s completed successfully ===", script_name)


if __name__ == "__main__":
    main()
