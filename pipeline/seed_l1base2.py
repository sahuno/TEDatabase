# Author: Samuel Ahuno
# Date: 2026-04-20
# Purpose: One-time seed import of L1Base2 putative somatic LINE-1 insertions into master loci.json

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# L1Base2 BED file sources
# ---------------------------------------------------------------------------

L1BASE2_SOURCES: dict[str, dict] = {
    "FLI": {
        "url": "https://l1base.charite.de/BED/hsflil1_8438.bed",
        "filename": "hsflil1_8438.bed",
        "import": True,
        "description": "Full-length insertions (FLI)",
    },
    "ORF2": {
        "url": "https://l1base.charite.de/BED/hsorf2l1_8438.bed",
        "filename": "hsorf2l1_8438.bed",
        "import": True,
        "description": "ORF2-containing insertions",
    },
    "FLnI": {
        "url": "https://l1base.charite.de/BED/hsflnil1_8438_rm.bed",
        "filename": "hsflnil1_8438_rm.bed",
        "import": False,  # stored but NOT imported
        "description": "Full-length non-insertions (FLnI) — reference set, not imported",
    },
}


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
# Download helper
# ---------------------------------------------------------------------------

def download_file(url: str, dest: Path, logger: logging.Logger) -> None:
    """
    Download a file from *url* to *dest* using urllib.

    Parameters
    ----------
    url : str
        Source URL.
    dest : Path
        Local destination path.
    logger : logging.Logger
        Logger instance.

    Raises
    ------
    Exception
        Propagates any network/IO error after logging.
    """
    logger.info("Downloading: %s -> %s", url, dest)
    try:
        with urllib.request.urlopen(url) as response, dest.open("wb") as out_f:
            shutil.copyfileobj(response, out_f)
        logger.info(
            "Downloaded: %s (%.2f MB)", dest, dest.stat().st_size / 1e6
        )
    except Exception as exc:
        logger.error("Failed to download %s: %s", url, exc)
        raise


def ensure_seed_files(
    seed_dir: Path,
    force: bool,
    logger: logging.Logger,
) -> dict[str, Path]:
    """
    Ensure all L1Base2 BED files are present in *seed_dir*.

    Parameters
    ----------
    seed_dir : Path
        Directory where seed files are cached.
    force : bool
        If ``True``, re-download even if files exist.
    logger : logging.Logger
        Logger instance.

    Returns
    -------
    dict[str, Path]
        Mapping of category name -> local file path.
    """
    seed_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    for category, info in L1BASE2_SOURCES.items():
        local_path = seed_dir / info["filename"]
        paths[category] = local_path

        if local_path.exists() and not force:
            logger.info(
                "Seed file already present (use --force to re-download): %s", local_path
            )
        else:
            download_file(info["url"], local_path, logger)

    return paths


# ---------------------------------------------------------------------------
# BED parsing
# ---------------------------------------------------------------------------

def parse_bed_records(bed_path: Path, logger: logging.Logger) -> Iterator[dict]:
    """
    Parse a 9-column L1Base2 BED file, yielding one dict per record.

    Expected columns (0-indexed):
    0: chrom, 1: start, 2: end, 3: uid, 4: score,
    5: strand, 6: thickStart, 7: thickEnd, 8: itemRgb

    Skips header/comment lines and lines with fewer than 6 columns.

    Parameters
    ----------
    bed_path : Path
        Path to the BED file.
    logger : logging.Logger
        Logger instance.

    Yields
    ------
    dict
        Dict with keys: chrom, start, end, uid, score, strand, thick_start,
        thick_end, item_rgb.
    """
    n_parsed = 0
    n_skipped = 0

    with bed_path.open(encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("track") or line.startswith("browser"):
                continue

            cols = line.split("\t")
            if len(cols) < 6:
                logger.debug("Line %d: fewer than 6 columns, skipping: %r", lineno, line[:80])
                n_skipped += 1
                continue

            chrom = cols[0].strip()
            try:
                start = int(cols[1])
                end = int(cols[2])
            except ValueError:
                logger.debug("Line %d: non-integer start/end, skipping: %r", lineno, line[:80])
                n_skipped += 1
                continue

            uid = cols[3].strip() if len(cols) > 3 else None
            try:
                score = int(cols[4]) if len(cols) > 4 and cols[4].strip() else 0
            except ValueError:
                score = 0
            strand = cols[5].strip() if len(cols) > 5 else "."
            thick_start = int(cols[6]) if len(cols) > 6 and cols[6].strip().lstrip("-").isdigit() else None
            thick_end = int(cols[7]) if len(cols) > 7 and cols[7].strip().lstrip("-").isdigit() else None
            item_rgb = cols[8].strip() if len(cols) > 8 else None

            n_parsed += 1
            yield {
                "chrom": chrom,
                "start": start,
                "end": end,
                "uid": uid,
                "score": score,
                "strand": strand,
                "thick_start": thick_start,
                "thick_end": thick_end,
                "item_rgb": item_rgb,
            }

    logger.info(
        "%s: parsed %d records, skipped %d lines", bed_path.name, n_parsed, n_skipped
    )


# ---------------------------------------------------------------------------
# Build locus dict from a BED record
# ---------------------------------------------------------------------------

def build_locus_from_bed(
    record: dict,
    category: str,
    today: str,
) -> dict | None:
    """
    Build a master-format locus dict from a parsed L1Base2 BED record.

    Parameters
    ----------
    record : dict
        Parsed BED record from :func:`parse_bed_records`.
    category : str
        ``"FLI"`` or ``"ORF2"``.
    today : str
        ISO date string for ``date_added`` / ``date_updated``.

    Returns
    -------
    dict or None
        Locus dict, or ``None`` if the chromosome cannot be normalised.
    """
    from pipeline.utils.coordinates import make_locus_id, parse_chrom

    chrom = parse_chrom(record["chrom"])
    if chrom is None:
        return None

    start = record["start"]
    end = record["end"]
    strand = record["strand"] if record["strand"] in ("+", "-") else "."
    uid = record.get("uid") or None

    locus_id = make_locus_id(chrom, start, end, strand)

    is_full_length = category == "FLI"

    return {
        "locus_id": locus_id,
        "chrom": chrom,
        "start": start,
        "end": end,
        "strand": strand,
        "genome_build": "hg38",
        "l1_family": "L1HS",
        "l1_subtype": "Ta-1",
        "insertion_type": "putative_somatic",
        "tissue_type": [],
        "cancer_type": [],
        "gene_name": None,
        "gene_region": None,
        "validation_level": "computational",
        "validation_method": [],
        "detection_method": [],
        "n_samples_detected": None,
        "vaf": None,
        "source_pmid": [],
        "source_doi": None,
        "source_type": "l1base2",
        "coordinate_confidence": "high",
        "coordinate_source": "l1base2",
        "liftover_performed": False,
        "original_build": None,
        "l1base2_uid": uid,
        "l1base2_category": category,
        "is_full_length": is_full_length,
        "has_orf1": is_full_length,
        "has_orf2": True,
        "paper_year": None,
        "paper_journal": None,
        "date_added": today,
        "date_updated": today,
        "version": 1,
        "notes": None,
    }


# ---------------------------------------------------------------------------
# Master I/O helpers
# ---------------------------------------------------------------------------

def load_master(path: Path, logger: logging.Logger) -> list[dict]:
    """Load master loci.json, returning empty list on missing/empty file."""
    if not path.exists():
        logger.info("Master not found, starting fresh: %s", path)
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw or raw == "{}":
        logger.info("Master is empty, starting fresh.")
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        logger.warning("Master is not a list (%s), starting fresh.", type(data).__name__)
        return []
    except json.JSONDecodeError as exc:
        logger.error("Cannot parse master JSON (%s), starting fresh: %s", path, exc)
        return []


def atomic_write_json(path: Path, data: object, logger: logging.Logger) -> None:
    """Write JSON atomically via .tmp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)
    logger.info("Wrote (atomic): %s (%.1f KB)", path.resolve(), path.stat().st_size / 1024)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-time seed import of L1Base2 putative somatic LINE-1 insertions."
    )
    parser.add_argument(
        "--seed_dir",
        type=Path,
        default=Path("data/seed"),
        help="Directory for downloaded BED files (default: data/seed).",
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("data/processed/loci.json"),
        help="Master loci JSON (default: data/processed/loci.json).",
    )
    parser.add_argument(
        "--log_dir",
        type=Path,
        default=Path("logs"),
        help="Directory for log files (default: logs).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-download BED files even if they already exist in seed_dir.",
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
    logger.info("Date/time   : %s", datetime.now().isoformat())
    logger.info("Python      : %s", sys.version.split()[0])
    logger.info("Working dir : %s", Path.cwd())
    logger.info("Log dir     : %s", args.log_dir.resolve())
    logger.info("Seed dir    : %s", args.seed_dir.resolve())
    logger.info("Master      : %s", args.master.resolve())
    logger.info("Force       : %s", args.force)

    today = str(date.today())

    # ---------------------------------------------------------------- download
    logger.info("=== Ensuring seed files ===")
    seed_paths = ensure_seed_files(args.seed_dir, args.force, logger)

    # ------------------------------------------------------------------ parse
    logger.info("=== Parsing BED files ===")

    # Collect loci from each importable category; FLI takes precedence over ORF2
    # (dedup by locus_id: FLI overwrites ORF2 if they share a locus_id)
    seed_loci_by_id: dict[str, dict] = {}
    category_counts: dict[str, int] = {}
    n_invalid_chrom = 0

    for category in ("ORF2", "FLI"):  # FLI processed second so it overwrites ORF2
        info = L1BASE2_SOURCES[category]
        if not info["import"]:
            logger.info("Skipping (not imported): %s", category)
            continue

        bed_path = seed_paths[category]
        if not bed_path.exists():
            logger.error("Seed BED file missing: %s", bed_path)
            sys.exit(1)

        n_category = 0
        for record in parse_bed_records(bed_path, logger):
            locus = build_locus_from_bed(record, category, today)
            if locus is None:
                n_invalid_chrom += 1
                continue
            seed_loci_by_id[locus["locus_id"]] = locus
            n_category += 1

        category_counts[category] = n_category
        logger.info("Category %s: %d valid loci parsed", category, n_category)

    logger.info("Invalid chrom (skipped): %d", n_invalid_chrom)

    n_fli = category_counts.get("FLI", 0)
    n_orf2 = category_counts.get("ORF2", 0)
    n_deduped = n_fli + n_orf2 - len(seed_loci_by_id)
    logger.info("FLI count          : %d", n_fli)
    logger.info("ORF2 count         : %d", n_orf2)
    logger.info("Deduped (FLI wins) : %d", n_deduped)
    logger.info("Unique seed loci   : %d", len(seed_loci_by_id))

    if not seed_loci_by_id:
        logger.warning("No valid loci produced from L1Base2 BED files. Exiting without modifying master.")
        logger.info("=== DONE: %s completed successfully ===", script_name)
        return

    # ----------------------------------------------------------- merge master
    logger.info("=== Merging into master loci.json ===")
    from pipeline.utils.dedup import merge_loci

    master_loci = load_master(args.master, logger)
    logger.info("Existing master loci: %d", len(master_loci))

    master_index: dict[str, int] = {
        locus["locus_id"]: idx
        for idx, locus in enumerate(master_loci)
        if locus.get("locus_id")
    }

    n_added = 0
    n_merged_existing = 0

    for locus_id, seed_locus in seed_loci_by_id.items():
        if locus_id in master_index:
            idx = master_index[locus_id]
            master_loci[idx] = merge_loci(master_loci[idx], seed_locus)
            n_merged_existing += 1
        else:
            master_loci.append(seed_locus)
            master_index[locus_id] = len(master_loci) - 1
            n_added += 1

    logger.info("New loci added to master  : %d", n_added)
    logger.info("Existing loci merged      : %d", n_merged_existing)
    logger.info("Master total after merge  : %d", len(master_loci))

    # ----------------------------------------------------------- write master
    atomic_write_json(args.master, master_loci, logger)

    logger.info("=== DONE: %s completed successfully ===", script_name)


if __name__ == "__main__":
    main()
