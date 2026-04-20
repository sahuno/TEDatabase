# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: Build all static site artifacts (TSV, BED, JSON stats) from master loci.json

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Column definitions for the TSV output
# ---------------------------------------------------------------------------

TSV_COLUMNS: list[str] = [
    "locus_id",
    "chrom",
    "start",
    "end",
    "strand",
    "l1_family",
    "l1_subtype",
    "insertion_type",
    "tissue_type",
    "cancer_type",
    "gene_name",
    "gene_region",
    "validation_level",
    "validation_method",
    "detection_method",
    "n_samples_detected",
    "paper_year",
    "paper_journal",
    "source_pmid",
    "source_doi",
    "coordinate_confidence",
    "notes",
]


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
# Formatting helpers
# ---------------------------------------------------------------------------

def _list_to_str(value: object) -> str:
    """Render a list as a semicolon-joined string; return '' for None."""
    if isinstance(value, list):
        return ";".join(str(v) for v in value if v is not None)
    if value is None:
        return ""
    return str(value)


def _safe_str(value: object) -> str:
    """Return empty string for None, else str(value)."""
    return "" if value is None else str(value)


def locus_to_tsv_row(locus: dict) -> list[str]:
    """
    Convert a locus dict to a list of TSV column values in ``TSV_COLUMNS``
    order.

    Parameters
    ----------
    locus : dict
        Locus record.

    Returns
    -------
    list[str]
        One string per column.
    """
    row: list[str] = []
    for col in TSV_COLUMNS:
        val = locus.get(col)
        if col in ("tissue_type", "cancer_type", "validation_method",
                   "detection_method", "source_pmid"):
            row.append(_list_to_str(val))
        else:
            row.append(_safe_str(val))
    return row


def locus_to_bed_row(locus: dict) -> list[str] | None:
    """
    Convert a locus dict to a 6-column BED row (strings).

    Returns ``None`` if the locus lacks chrom/start/end.

    Parameters
    ----------
    locus : dict
        Locus record.

    Returns
    -------
    list[str] or None
        [chrom, start, end, name, score, strand] or ``None``.
    """
    chrom = locus.get("chrom")
    start = locus.get("start")
    end = locus.get("end")
    if chrom is None or start is None or end is None:
        return None

    locus_id = locus.get("locus_id") or "."
    vaf = locus.get("vaf")
    try:
        score = str(int(float(vaf) * 1000)) if vaf is not None else "0"
    except (TypeError, ValueError):
        score = "0"
    strand = locus.get("strand") or "."

    return [str(chrom), str(start), str(end), locus_id, score, strand]


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def compute_stats(loci: list[dict], papers_master: dict) -> dict:
    """
    Compute summary statistics for the site stats.json.

    Parameters
    ----------
    loci : list[dict]
        Full master loci list.
    papers_master : dict
        Master papers dict (keyed by PMID).

    Returns
    -------
    dict
        Stats dict with keys: total_loci, literature_loci, l1base2_loci,
        validated_loci, papers_processed, last_updated.
    """
    total_loci = len(loci)
    literature_loci = sum(
        1 for locus in loci if locus.get("source_type") != "l1base2"
    )
    l1base2_loci = sum(
        1 for locus in loci if locus.get("source_type") == "l1base2"
    )
    validated_loci = sum(
        1 for locus in loci if locus.get("validation_level") == "experimental"
    )

    # Count unique PMIDs across all loci
    all_pmids: set[str] = set()
    for locus in loci:
        for pmid in (locus.get("source_pmid") or []):
            if pmid:
                all_pmids.add(str(pmid))
    # Also count keys from papers_master
    all_pmids.update(papers_master.keys())
    papers_processed = len(all_pmids)

    return {
        "total_loci": total_loci,
        "literature_loci": literature_loci,
        "l1base2_loci": l1base2_loci,
        "validated_loci": validated_loci,
        "papers_processed": papers_processed,
        "last_updated": str(date.today()),
    }


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build static site data artifacts from master loci.json."
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
        "--site_data_dir",
        type=Path,
        default=Path("site/data"),
        help="Output directory for site data files (default: site/data).",
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
    logger.info("Date/time       : %s", datetime.now().isoformat())
    logger.info("Python          : %s", sys.version.split()[0])
    logger.info("Working dir     : %s", Path.cwd())
    logger.info("Log dir         : %s", args.log_dir.resolve())
    logger.info("Master loci     : %s", args.master.resolve())
    logger.info("Papers master   : %s", args.papers_master.resolve())
    logger.info("Site data dir   : %s", args.site_data_dir.resolve())

    # ------------------------------------------------------------------ load
    logger.info("=== Loading master data ===")

    if not args.master.exists():
        logger.error("Master loci file not found: %s", args.master.resolve())
        sys.exit(1)

    raw = args.master.read_text(encoding="utf-8").strip()
    loci: list[dict] = json.loads(raw) if raw and raw != "{}" else []
    logger.info("Loaded %d loci from %s", len(loci), args.master.resolve())

    # Load papers master (best-effort)
    papers_master: dict = {}
    if args.papers_master.exists():
        raw_papers = args.papers_master.read_text(encoding="utf-8").strip()
        if raw_papers and raw_papers != "{}":
            try:
                papers_master = json.loads(raw_papers)
            except json.JSONDecodeError as exc:
                logger.warning("Could not parse papers.json: %s", exc)
    logger.info("Loaded %d paper records", len(papers_master))

    # Create output dir
    args.site_data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ TSV
    logger.info("=== Building loci.tsv ===")
    processed_tsv_path = args.master.parent / "loci.tsv"
    header_line = "#" + "\t".join(TSV_COLUMNS)
    tsv_lines: list[str] = [header_line]
    n_tsv_ok = 0
    n_tsv_skip = 0

    for locus in loci:
        try:
            row = locus_to_tsv_row(locus)
            tsv_lines.append("\t".join(row))
            n_tsv_ok += 1
        except Exception as exc:
            logger.warning("Skipping locus in TSV (error): %s — %s", locus.get("locus_id"), exc)
            n_tsv_skip += 1

    processed_tsv_path.write_text("\n".join(tsv_lines) + "\n", encoding="utf-8")
    logger.info(
        "Wrote loci.tsv: %s (%d rows, %d skipped, %.1f KB)",
        processed_tsv_path.resolve(),
        n_tsv_ok,
        n_tsv_skip,
        processed_tsv_path.stat().st_size / 1024,
    )

    # ----------------------------------------------------------------- BED
    logger.info("=== Building loci_hg38.bed ===")
    processed_bed_path = args.master.parent / "loci_hg38.bed"
    bed_lines: list[str] = []
    n_bed_ok = 0
    n_bed_skip = 0

    for locus in loci:
        row = locus_to_bed_row(locus)
        if row is None:
            n_bed_skip += 1
            continue
        bed_lines.append("\t".join(row))
        n_bed_ok += 1

    processed_bed_path.write_text("\n".join(bed_lines) + "\n", encoding="utf-8")
    logger.info(
        "Wrote loci_hg38.bed: %s (%d records, %d skipped, %.1f KB)",
        processed_bed_path.resolve(),
        n_bed_ok,
        n_bed_skip,
        processed_bed_path.stat().st_size / 1024,
    )

    # ---------------------------------------------- copy to site/data/
    logger.info("=== Copying files to site/data/ ===")

    copies: list[tuple[Path, Path]] = [
        (args.master, args.site_data_dir / "loci.json"),
        (processed_tsv_path, args.site_data_dir / "loci.tsv"),
        (processed_bed_path, args.site_data_dir / "loci_hg38.bed"),
    ]

    for src, dst in copies:
        shutil.copy2(src, dst)
        logger.info(
            "Copied %s -> %s (%.1f KB)",
            src.resolve(),
            dst.resolve(),
            dst.stat().st_size / 1024,
        )

    # --------------------------------------------------------------- stats
    logger.info("=== Computing stats.json ===")
    stats = compute_stats(loci, papers_master)
    stats_path = args.site_data_dir / "stats.json"
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote stats.json: %s — %s", stats_path.resolve(), stats)

    # Final summary
    logger.info("=== Build summary ===")
    logger.info("Total loci      : %d", len(loci))
    logger.info("TSV rows        : %d", n_tsv_ok)
    logger.info("BED records     : %d", n_bed_ok)
    logger.info("Literature loci : %d", stats["literature_loci"])
    logger.info("L1Base2 loci    : %d", stats["l1base2_loci"])
    logger.info("Validated loci  : %d", stats["validated_loci"])
    logger.info("Papers total    : %d", stats["papers_processed"])
    logger.info("Last updated    : %s", stats["last_updated"])

    logger.info("=== DONE: %s completed successfully ===", script_name)


if __name__ == "__main__":
    main()
