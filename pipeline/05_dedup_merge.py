# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: Merge new loci from loci_lifted.json into the master loci.json database

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Natural chromosome sort key
# ---------------------------------------------------------------------------

_CHROM_ORDER: dict[str, int] = {
    **{f"chr{i}": i for i in range(1, 23)},
    "chrX": 23,
    "chrY": 24,
    "chrM": 25,
}


def _chrom_sort_key(locus: dict) -> tuple[int, int]:
    chrom = locus.get("chrom") or ""
    start = locus.get("start") or 0
    return (_CHROM_ORDER.get(chrom, 99), start)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(log_dir: Path, script_name: str) -> logging.Logger:
    """
    Configure dual-handler logging (file + stdout).

    Parameters
    ----------
    log_dir : Path
        Directory for the log file.
    script_name : str
        Logger name and log file prefix.

    Returns
    -------
    logging.Logger
        Configured logger.
    """
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
# JSON I/O helpers
# ---------------------------------------------------------------------------

def load_json_list(path: Path, logger: logging.Logger) -> list:
    """
    Load a JSON file that should contain a list. Returns empty list on missing
    file, empty file, or a file containing only ``{}``.

    Parameters
    ----------
    path : Path
        File to load.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    list
        Parsed list, or ``[]`` if the file is absent/empty/invalid.
    """
    if not path.exists():
        logger.info("File not found, initialising as empty list: %s", path)
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw or raw == "{}":
        logger.info("File is empty or '{}', initialising as empty list: %s", path)
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        logger.warning("Expected list in %s, got %s — treating as empty.", path, type(data).__name__)
        return []
    except json.JSONDecodeError as exc:
        logger.error("JSON decode error in %s: %s — treating as empty.", path, exc)
        return []


def load_json_dict(path: Path, logger: logging.Logger) -> dict:
    """
    Load a JSON file that should contain a dict. Returns empty dict on missing
    file or empty file.

    Parameters
    ----------
    path : Path
        File to load.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    dict
        Parsed dict, or ``{}`` if the file is absent/empty/invalid.
    """
    if not path.exists():
        logger.info("File not found, initialising as empty dict: %s", path)
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        logger.info("File is empty, initialising as empty dict: %s", path)
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        logger.warning("Expected dict in %s, got %s — treating as empty.", path, type(data).__name__)
        return {}
    except json.JSONDecodeError as exc:
        logger.error("JSON decode error in %s: %s — treating as empty.", path, exc)
        return {}


def atomic_write_json(path: Path, data: object, logger: logging.Logger) -> None:
    """
    Write JSON data to *path* atomically (write to ``.tmp`` then rename).

    Parameters
    ----------
    path : Path
        Destination file.
    data : object
        JSON-serialisable object.
    logger : logging.Logger
        Logger instance.
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)
    logger.info(
        "Wrote (atomic): %s (%.1f KB)",
        path.resolve(),
        path.stat().st_size / 1024,
    )


# ---------------------------------------------------------------------------
# PMIDs collected this run
# ---------------------------------------------------------------------------

def collect_run_pmids(new_loci: list[dict]) -> set[str]:
    """Return the set of PMIDs referenced across all new loci."""
    pmids: set[str] = set()
    for locus in new_loci:
        for pmid in (locus.get("source_pmid") or []):
            if pmid:
                pmids.add(str(pmid))
        # Also capture top-level pmid field from extraction step
        pmid_field = locus.get("pmid")
        if pmid_field:
            pmids.add(str(pmid_field))
    return pmids


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge lifted loci into the master loci.json database."
    )
    parser.add_argument(
        "--loci_input",
        type=Path,
        default=Path("data/raw/loci_lifted.json"),
        help="Lifted loci JSON (default: data/raw/loci_lifted.json).",
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("data/processed/loci.json"),
        help="Master loci JSON (default: data/processed/loci.json).",
    )
    parser.add_argument(
        "--papers_master",
        type=Path,
        default=Path("data/processed/papers.json"),
        help="Master papers JSON (default: data/processed/papers.json).",
    )
    parser.add_argument(
        "--papers_input",
        type=Path,
        default=Path("data/raw/papers_to_extract.json"),
        help="Papers extraction metadata JSON (default: data/raw/papers_to_extract.json).",
    )
    parser.add_argument(
        "--pmids_seen",
        type=Path,
        default=Path("data/raw/pmids_seen.txt"),
        help="Seen PMIDs text file (default: data/raw/pmids_seen.txt).",
    )
    parser.add_argument(
        "--run_log",
        type=Path,
        default=Path("data/processed/run_log.jsonl"),
        help="Run log JSONL (default: data/processed/run_log.jsonl).",
    )
    parser.add_argument(
        "--log_dir",
        type=Path,
        default=Path("logs"),
        help="Directory for log files (default: logs).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    script_name = Path(__file__).stem
    logger = setup_logging(args.log_dir, script_name)

    # Session header
    logger.info("=== SESSION START: %s ===", script_name)
    logger.info("Date/time      : %s", datetime.now().isoformat())
    logger.info("Python         : %s", sys.version.split()[0])
    logger.info("Working dir    : %s", Path.cwd())
    logger.info("Log dir        : %s", args.log_dir.resolve())
    logger.info("Loci input     : %s", args.loci_input.resolve())
    logger.info("Master loci    : %s", args.master.resolve())
    logger.info("Papers master  : %s", args.papers_master.resolve())

    from pipeline.config import DEDUP_WINDOW_BP, VALID_CHROMS
    from pipeline.utils.coordinates import make_locus_id
    from pipeline.utils.dedup import find_duplicates, merge_loci, normalize_locus

    # ------------------------------------------------------------------ load
    logger.info("=== Loading data ===")

    if not args.loci_input.exists():
        logger.error("Loci input not found: %s", args.loci_input.resolve())
        sys.exit(1)

    new_loci: list[dict] = load_json_list(args.loci_input, logger)
    logger.info("New loci (from liftover): %d", len(new_loci))

    master_loci: list[dict] = load_json_list(args.master, logger)
    logger.info("Existing master loci   : %d", len(master_loci))

    papers_master: dict = load_json_dict(args.papers_master, logger)
    logger.info("Existing papers records: %d", len(papers_master))

    # Build index: locus_id -> position in master list
    master_index: dict[str, int] = {
        locus["locus_id"]: idx
        for idx, locus in enumerate(master_loci)
        if locus.get("locus_id")
    }
    logger.info("Master index size: %d unique locus IDs", len(master_index))

    # ---------------------------------------------------------- merge new loci
    logger.info("=== Merging new loci ===")

    today = str(date.today())
    n_new = 0
    n_merged = 0
    n_skipped = 0

    for raw_locus in new_loci:
        norm = normalize_locus(raw_locus)

        # Validate required fields
        chrom = norm.get("chrom")
        start = norm.get("start")
        end = norm.get("end")

        if chrom is None or start is None or end is None:
            logger.warning(
                "Skipping locus — missing chrom/start/end: %s",
                {k: norm.get(k) for k in ("chrom", "start", "end", "source_pmid")},
            )
            n_skipped += 1
            continue

        if chrom not in VALID_CHROMS:
            logger.warning(
                "Skipping locus — chrom not in VALID_CHROMS: %s (chrom=%s)", norm.get("locus_id"), chrom
            )
            n_skipped += 1
            continue

        # Compute canonical locus_id
        strand = norm.get("strand") or "."
        locus_id = make_locus_id(chrom, int(start), int(end), strand)
        norm["locus_id"] = locus_id

        if locus_id in master_index:
            # Merge into existing record
            idx = master_index[locus_id]
            master_loci[idx] = merge_loci(master_loci[idx], norm)
            logger.debug("Merged existing locus: %s", locus_id)
            n_merged += 1
        else:
            # New record
            norm["date_added"] = today
            norm["date_updated"] = today
            norm["version"] = 1
            master_loci.append(norm)
            master_index[locus_id] = len(master_loci) - 1
            logger.debug("Added new locus: %s", locus_id)
            n_new += 1

    logger.info("=== Merge summary ===")
    logger.info("New loci added  : %d", n_new)
    logger.info("Loci merged     : %d", n_merged)
    logger.info("Loci skipped    : %d", n_skipped)
    logger.info("Master total    : %d", len(master_loci))

    # ------------------------------------------------------ duplicate flagging
    logger.info("=== Running duplicate detection (window=%d bp) ===", DEDUP_WINDOW_BP)
    dupe_pairs = find_duplicates(master_loci, window=DEDUP_WINDOW_BP)
    logger.info("Potential duplicate pairs found: %d", len(dupe_pairs))

    for i, j in dupe_pairs:
        lid_j = master_loci[j].get("locus_id", f"index_{j}")
        lid_i = master_loci[i].get("locus_id", f"index_{i}")
        # Flag both sides
        for idx, other_lid in [(i, lid_j), (j, lid_i)]:
            tag = f"potential_duplicate_of: {other_lid}"
            existing_notes = master_loci[idx].get("notes") or ""
            if tag not in existing_notes:
                master_loci[idx]["notes"] = (
                    (existing_notes + "; " + tag).strip("; ") if existing_notes else tag
                )

    # ------------------------------------------------------------------- sort
    master_loci.sort(key=_chrom_sort_key)

    # --------------------------------------------------------------- save loci
    logger.info("=== Writing outputs ===")
    args.master.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.master, master_loci, logger)

    # ---------------------------------------------------------- update papers
    papers_input_path: Path = args.papers_input
    if papers_input_path.exists():
        raw_papers = papers_input_path.read_text(encoding="utf-8").strip()
        incoming_papers: list[dict] = json.loads(raw_papers) if raw_papers else []
        for paper in incoming_papers:
            pmid = str(paper.get("pmid", ""))
            if pmid:
                papers_master[pmid] = paper
        logger.info(
            "Updated papers.json: %d total entries (%d from this run)",
            len(papers_master),
            len(incoming_papers),
        )
    else:
        logger.info("No papers_to_extract.json found at %s, skipping papers update.", papers_input_path)

    args.papers_master.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.papers_master, papers_master, logger)

    # --------------------------------------------------------------- run log
    run_record = {
        "run_id": datetime.now().isoformat(),
        "loci_new": n_new,
        "loci_merged": n_merged,
        "loci_skipped": n_skipped,
        "loci_total": len(master_loci),
        "date": today,
    }
    args.run_log.parent.mkdir(parents=True, exist_ok=True)
    with args.run_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(run_record) + "\n")
    logger.info("Appended run record to %s: %s", args.run_log.resolve(), run_record)

    # ---------------------------------------------------------- update pmids_seen
    run_pmids = collect_run_pmids(new_loci)
    if run_pmids:
        args.pmids_seen.parent.mkdir(parents=True, exist_ok=True)
        with args.pmids_seen.open("a", encoding="utf-8") as fh:
            for pmid in sorted(run_pmids):
                fh.write(pmid + "\n")
        logger.info(
            "Appended %d new PMIDs to %s", len(run_pmids), args.pmids_seen.resolve()
        )

    logger.info("=== DONE: %s completed successfully ===", script_name)


if __name__ == "__main__":
    main()
