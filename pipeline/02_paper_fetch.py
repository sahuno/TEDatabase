# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: Download PDFs for LINE-1 papers via PMC OA API and Unpaywall, build extraction manifest

import argparse
import io
import json
import logging
import sys
import tarfile
import time
import urllib.request
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

PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
UNPAYWALL_EMAIL = "ekwame001@gmail.com"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}?email={email}"

# PMC OA API allows ~3 req/s; Unpaywall allows ~100k/day, keep polite
PMC_INTERVAL = 0.4
UNPAYWALL_INTERVAL = 0.5
DOWNLOAD_CHUNK_SIZE = 65536  # 64 KB

# Supplementary file extensions worth extracting for LLM parsing
SUPPLEMENT_EXTS = {".xlsx", ".xls", ".csv", ".tsv", ".txt"}
# Skip these even if extension matches — they're not data tables
SUPPLEMENT_SKIP_PATTERNS = {"readme", "license", "manifest", "checksums"}


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
# Rate-limited session
# ---------------------------------------------------------------------------

class RateLimitedSession:
    """Wraps requests.Session with per-instance minimum inter-request delay."""

    def __init__(self, min_interval: float):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "TEDatabase/1.0 (ekwame001@gmail.com)"})
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
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def get(self, url: str, stream: bool = False, **kwargs) -> requests.Response:
        self._throttle()
        resp = self._session.get(url, timeout=60, stream=stream, **kwargs)
        resp.raise_for_status()
        return resp


# ---------------------------------------------------------------------------
# PDF acquisition helpers
# ---------------------------------------------------------------------------

def try_pmc_pdf(pmcid: str, papers_dir: Path,
                session: RateLimitedSession, logger: logging.Logger) -> Path | None:
    """
    Try to download a PDF from the PMC Open Access API.

    Parameters
    ----------
    pmcid : str
        PubMed Central ID (e.g. 'PMC1234567').
    papers_dir : Path
        Directory to save downloaded PDFs.
    session : RateLimitedSession
        Shared HTTP session.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    Path or None
        Saved PDF path, or None on failure.

    Example
    -------
    >>> path = try_pmc_pdf("PMC1234567", Path("data/raw/papers"), session, logger)
    """
    try:
        resp = session.get(PMC_OA_URL, params={"id": pmcid, "format": "pdf"})
        root = ET.fromstring(resp.text)

        # Check for error element
        error_el = root.find(".//error")
        if error_el is not None:
            logger.debug("PMC OA API error for %s: %s", pmcid, error_el.text)
            return None

        # Find <link format="pdf"> href
        pdf_url: str | None = None
        for link in root.findall(".//link"):
            if link.get("format") == "pdf":
                pdf_url = link.get("href")
                break

        if not pdf_url:
            logger.debug("No PDF link in PMC OA response for %s", pmcid)
            return None

        out_path = papers_dir / f"{pmcid}.pdf"
        # PMC may return ftp:// URLs — use urllib which handles both ftp and http
        if pdf_url.startswith("ftp://"):
            _download_url_urllib(pdf_url, out_path, logger)
        else:
            _download_pdf(pdf_url, out_path, session, logger)
        return out_path

    except ET.ParseError as exc:
        logger.warning("PMC OA XML parse error for %s: %s", pmcid, exc)
        return None
    except requests.HTTPError as exc:
        logger.warning("PMC OA HTTP error for %s: %s", pmcid, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("PMC OA unexpected error for %s: %s", pmcid, exc)
        return None


def try_unpaywall_pdf(doi: str, pmid: str, papers_dir: Path,
                      session: RateLimitedSession, logger: logging.Logger) -> Path | None:
    """
    Try to download a PDF via the Unpaywall API.

    Parameters
    ----------
    doi : str
        Digital Object Identifier.
    pmid : str
        PubMed ID used as filename fallback.
    papers_dir : Path
        Directory to save downloaded PDFs.
    session : RateLimitedSession
        Shared HTTP session.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    Path or None
        Saved PDF path, or None on failure.
    """
    try:
        url = UNPAYWALL_URL.format(doi=doi, email=UNPAYWALL_EMAIL)
        resp = session.get(url)
        data = resp.json()

        best = data.get("best_oa_location") or {}
        pdf_url = best.get("url_for_pdf")

        if not pdf_url:
            logger.debug("No OA PDF URL from Unpaywall for DOI %s", doi)
            return None

        out_path = papers_dir / f"{pmid}.pdf"
        _download_pdf(pdf_url, out_path, session, logger)
        return out_path

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        if status == 404:
            logger.debug("Unpaywall 404 for DOI %s (not indexed)", doi)
        else:
            logger.warning("Unpaywall HTTP %s for DOI %s: %s", status, doi, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unpaywall unexpected error for DOI %s: %s", doi, exc)
        return None


def _download_url_urllib(url: str, out_path: Path, logger: logging.Logger) -> None:
    """Download any URL (including ftp://) using urllib."""
    logger.debug("Downloading via urllib: %s -> %s", url, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as resp:
        out_path.write_bytes(resp.read())
    logger.debug("Saved: %s (%.1f KB)", out_path, out_path.stat().st_size / 1024)


def _download_pdf(url: str, out_path: Path,
                  session: RateLimitedSession, logger: logging.Logger) -> None:
    """
    Stream-download a PDF to out_path.

    Parameters
    ----------
    url : str
        Direct URL of the PDF.
    out_path : Path
        Destination file path.
    session : RateLimitedSession
        Shared HTTP session.
    logger : logging.Logger
        Logger instance.

    Raises
    ------
    requests.HTTPError
        Propagated on non-2xx responses.
    """
    logger.debug("Downloading PDF: %s -> %s", url, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resp = session.get(url, stream=True)

    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
        logger.warning(
            "Unexpected Content-Type '%s' when downloading %s; saving anyway.",
            content_type,
            url,
        )

    with out_path.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            if chunk:
                fh.write(chunk)

    size_kb = out_path.stat().st_size / 1024
    logger.debug("Saved PDF: %s (%.1f KB)", out_path, size_kb)


# ---------------------------------------------------------------------------
# Supplementary file acquisition
# ---------------------------------------------------------------------------

def try_pmc_supplements(
    pmcid: str,
    supplements_dir: Path,
    session: RateLimitedSession,
    logger: logging.Logger,
) -> list[Path]:
    """
    Download and extract supplementary data files from PMC OA tgz bundle.

    Parameters
    ----------
    pmcid : str
        PubMed Central ID (e.g. 'PMC1234567').
    supplements_dir : Path
        Root directory; files are saved under supplements_dir/{pmcid}/.
    session : RateLimitedSession
        Shared HTTP session.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    list[Path]
        Paths to extracted supplement files (xlsx, csv, tsv, txt only).
    """
    try:
        resp = session.get(PMC_OA_URL, params={"id": pmcid, "format": "tgz"})
        root = ET.fromstring(resp.text)

        error_el = root.find(".//error")
        if error_el is not None:
            logger.debug("PMC OA tgz not available for %s: %s", pmcid, error_el.text)
            return []

        tgz_url: str | None = None
        for link in root.findall(".//link"):
            if link.get("format") == "tgz":
                tgz_url = link.get("href")
                break

        if not tgz_url:
            logger.debug("No tgz link in PMC OA response for %s", pmcid)
            return []

        # Download tgz into memory — PMC returns ftp:// URLs, use urllib (handles both ftp+http)
        logger.debug("Downloading tgz for %s from %s", pmcid, tgz_url)
        buf = io.BytesIO()
        with urllib.request.urlopen(tgz_url, timeout=120) as resp:
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                buf.write(chunk)
        buf.seek(0)

        out_dir = supplements_dir / pmcid
        out_dir.mkdir(parents=True, exist_ok=True)

        saved: list[Path] = []
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                p = Path(member.name)
                ext = p.suffix.lower()
                if ext not in SUPPLEMENT_EXTS:
                    continue
                stem_lower = p.stem.lower()
                if any(skip in stem_lower for skip in SUPPLEMENT_SKIP_PATTERNS):
                    continue
                out_path = out_dir / p.name
                fobj = tar.extractfile(member)
                if fobj is None:
                    continue
                out_path.write_bytes(fobj.read())
                saved.append(out_path)
                logger.debug("Extracted supplement: %s (%.1f KB)", out_path.name, out_path.stat().st_size / 1024)

        if saved:
            logger.info(
                "PMC tgz %s: extracted %d supplement file(s): %s",
                pmcid, len(saved), [p.name for p in saved],
            )
        else:
            logger.debug("PMC tgz %s: no tabular supplements found in archive", pmcid)

        return saved

    except ET.ParseError as exc:
        logger.warning("PMC OA tgz XML parse error for %s: %s", pmcid, exc)
        return []
    except tarfile.TarError as exc:
        logger.warning("PMC tgz extraction error for %s: %s", pmcid, exc)
        return []
    except requests.HTTPError as exc:
        logger.warning("PMC OA tgz HTTP error for %s: %s", pmcid, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("PMC tgz unexpected error for %s: %s", pmcid, exc)
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download PDFs for LINE-1 papers and build extraction manifest."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/papers_pending.json"),
        help="Input papers_pending.json path (default: data/raw/papers_pending.json).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/papers_to_extract.json"),
        help="Output manifest JSON path (default: data/raw/papers_to_extract.json).",
    )
    parser.add_argument(
        "--papers_dir",
        type=Path,
        default=Path("data/raw/papers"),
        help="Directory to store downloaded PDFs (default: data/raw/papers).",
    )
    parser.add_argument(
        "--supplements_dir",
        type=Path,
        default=Path("data/raw/supplements"),
        help="Directory to store extracted supplement files (default: data/raw/supplements).",
    )
    parser.add_argument(
        "--max_papers",
        type=int,
        default=None,
        help="Cap number of papers to download (useful for test runs, e.g. --max_papers 5).",
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
    logger.info("Input        : %s", args.input.resolve())
    logger.info("Output       : %s", args.output.resolve())
    logger.info("Papers dir   : %s", args.papers_dir.resolve())
    logger.info("Supplements  : %s", args.supplements_dir.resolve())

    # Load input
    if not args.input.exists():
        logger.error("Input file not found: %s", args.input.resolve())
        sys.exit(1)

    raw = args.input.read_text(encoding="utf-8")
    papers: list[dict] = json.loads(raw) if raw.strip() else []
    logger.info("Loaded %d papers from %s", len(papers), args.input.resolve())

    if args.max_papers and len(papers) > args.max_papers:
        logger.info("--max_papers %d: capping from %d papers", args.max_papers, len(papers))
        papers = papers[: args.max_papers]

    if not papers:
        logger.info("No papers to process. Writing empty manifest.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps([], indent=2))
        logger.info("=== DONE: %s completed successfully ===", script_name)
        return

    args.papers_dir.mkdir(parents=True, exist_ok=True)
    args.supplements_dir.mkdir(parents=True, exist_ok=True)

    # Two sessions with different rate limits
    pmc_session = RateLimitedSession(PMC_INTERVAL)
    unp_session = RateLimitedSession(UNPAYWALL_INTERVAL)

    manifest: list[dict] = []
    n_pdf_downloaded = 0
    n_abstract_only = 0
    n_supplements_found = 0

    for idx, paper in enumerate(papers, start=1):
        pmid = paper.get("pmid", "")
        pmcid = paper.get("pmcid")
        doi = paper.get("doi")

        logger.debug(
            "Processing %d/%d  PMID=%s  PMCID=%s  DOI=%s",
            idx, len(papers), pmid, pmcid, doi,
        )

        pdf_path: Path | None = None

        # Strategy 1: PMC OA PDF
        if pmcid:
            pdf_path = try_pmc_pdf(pmcid, args.papers_dir, pmc_session, logger)
            if pdf_path:
                logger.info("[%d/%d] PDF via PMC OA: %s", idx, len(papers), pdf_path.name)

        # Strategy 2: Unpaywall PDF
        if pdf_path is None and doi:
            pdf_path = try_unpaywall_pdf(doi, pmid, args.papers_dir, unp_session, logger)
            if pdf_path:
                logger.info("[%d/%d] PDF via Unpaywall: %s", idx, len(papers), pdf_path.name)

        if pdf_path is not None:
            n_pdf_downloaded += 1
        else:
            n_abstract_only += 1
            logger.info(
                "[%d/%d] No PDF available for PMID=%s — abstract only", idx, len(papers), pmid
            )

        # Strategy 3: PMC tgz supplementary files (always attempted if PMCID present)
        supplement_paths: list[str] = []
        if pmcid:
            supp_files = try_pmc_supplements(pmcid, args.supplements_dir, pmc_session, logger)
            supplement_paths = [str(p.resolve()) for p in supp_files]
            if supp_files:
                n_supplements_found += 1
                logger.info(
                    "[%d/%d] Supplements for PMID=%s: %d file(s)",
                    idx, len(papers), pmid, len(supp_files),
                )

        manifest.append(
            {
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "title": paper.get("title", ""),
                "authors": paper.get("authors", []),
                "journal": paper.get("journal", ""),
                "year": paper.get("year"),
                "abstract": paper.get("abstract", ""),
                "pdf_path": str(pdf_path.resolve()) if pdf_path else None,
                "pdf_available": pdf_path is not None,
                "supplement_paths": supplement_paths,
            }
        )

    # Summary
    logger.info("=== PDF Download Summary ===")
    logger.info("Total papers         : %d", len(papers))
    logger.info("PDFs downloaded      : %d", n_pdf_downloaded)
    logger.info("Abstract-only        : %d", n_abstract_only)
    logger.info("Papers w/ supplements: %d", n_supplements_found)

    # Save manifest
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    logger.info(
        "Saved manifest: %s (%d entries, %.1f KB)",
        args.output.resolve(),
        len(manifest),
        args.output.stat().st_size / 1024,
    )

    logger.info("=== DONE: %s completed successfully ===", script_name)


if __name__ == "__main__":
    main()
